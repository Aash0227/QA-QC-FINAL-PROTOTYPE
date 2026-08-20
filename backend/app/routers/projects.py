"""Project workspace endpoints: CRUD over artifacts/projects/<slug>/, plus upload.

A "project" is a directory, not a database row. Its metadata lives in that
directory's project_manifest.json alongside the pipeline artifacts, so a
workspace stays self-describing: copy the folder and the name, client and
revision travel with it.

Every metadata key here is OPTIONAL and additive. Workspaces created before the
Project Manager existed have none of them and must keep listing correctly —
that is what the fallback chains below are for, and what
test_projects_crud.py::test_manifest_without_metadata_still_lists pins."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Body, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse

from .. import config, phase_summary, revit_v3_adapter
from .common import make_router, save_artifact
from .workflow import _maybe_auto_advance_export, maybe_auto_benchmark

router = make_router()

# Maximum upload size: 50 MB. Defence-in-depth: check file.size before reading
# and len(content) after reading.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50MB

# The only manifest keys PATCH may write. Everything else in the manifest is
# pipeline-owned (pdf_path, page_count, last_ingested_export…) and must never be
# settable over HTTP: a client that could rewrite pdf_path could point the
# pipeline at any file on disk.
EDITABLE_META = ("display_name", "client", "revision", "status", "notes")
PROJECT_STATUSES = ("active", "archived")

# Free-text metadata caps. Generous for real titles, bounded so the manifest
# cannot be used as arbitrary storage.
_MAX_LEN = {"display_name": 120, "client": 120, "revision": 60, "notes": 2000}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _workspace_dir(slug: str) -> Path:
    """Validated workspace path. Traversal-safe: the target must resolve to a
    direct child of PROJECTS_DIR, which rejects '..', absolute paths, and
    symlinks pointing outside the tree. Raises 400 (malformed) or 404 (absent)
    so callers never branch on path shape themselves."""
    if not slug or ".." in slug or "/" in slug or "\\" in slug:
        raise HTTPException(status_code=400, detail="Invalid project name")
    target = (config.PROJECTS_DIR / slug).resolve()
    if target.parent != config.PROJECTS_DIR.resolve():
        raise HTTPException(status_code=400, detail="Invalid project name")
    if not target.is_dir():
        raise HTTPException(status_code=404, detail=f"No project workspace '{slug}'.")
    return target


def _read_json(path: Path) -> dict[str, Any]:
    """Artifact contents, or {} when absent/corrupt. Listing many projects must
    not 500 because one manifest was torn by a crashed write."""
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _active_slug() -> str | None:
    try:
        return config.active_project()
    except ValueError:
        return None


def _summary(d: Path, active: str | None) -> dict[str, Any]:
    """One project as the UI lists it. Absent metadata is reported as None
    rather than invented: the card shows a dash, not a guess."""
    manifest = _read_json(d / config.ARTIFACT_FILES["project_manifest"])
    element_list = _read_json(d / config.ARTIFACT_FILES["element_list"])

    pdf_path = manifest.get("pdf_path")
    revit_path = manifest.get("revit_path")
    # uploaded_at predates created_at/updated_at; it is the only timestamp older
    # workspaces have, so it seeds both rather than showing nothing.
    uploaded = manifest.get("uploaded_at")
    has_pdf = bool(pdf_path) and Path(pdf_path).is_file()
    has_revit = bool(revit_path) and Path(revit_path).is_file()
    has_results = bool(element_list.get("elements"))

    # Readiness is computed HERE, once, so every surface agrees on whether a
    # project can actually produce an answer. Previously each layer inferred
    # it from missing artifacts and reached a different conclusion: the card
    # said "no Revit export", the pipeline said "completed", the AI agent said
    # "run the pipeline first" -- three truthful components giving a user
    # three different stories about one project.
    if has_results:
        readiness, missing = "ready", []
    else:
        missing = [k for k, present in (("pdf", has_pdf), ("revit", has_revit))
                   if not present]
        readiness = "runnable" if not missing else "incomplete"

    return {
        "slug": d.name,
        # Fallback chain unchanged from before the Project Manager, with the
        # human-set name taking priority when one exists.
        "display_name": manifest.get("display_name") or manifest.get("pdf_original_name") or d.name,
        "active": d.name == active,
        "client": manifest.get("client"),
        "revision": manifest.get("revision"),
        "status": manifest.get("status") or "active",
        "notes": manifest.get("notes"),
        "created_at": manifest.get("created_at") or uploaded,
        "updated_at": manifest.get("updated_at") or uploaded,
        "has_pdf": has_pdf,
        "has_revit": has_revit,
        # ready      — results exist, open it and review
        # runnable   — both inputs present, the pipeline can be run
        # incomplete — `missing_inputs` names exactly what to supply
        "readiness": readiness,
        "missing_inputs": missing,
        "page_count": manifest.get("page_count"),
        "sheet_count": len(element_list.get("sheets") or []) or None,
        "counts": element_list.get("counts"),
    }


def _validate_meta(payload: dict[str, Any]) -> dict[str, Any]:
    """Whitelist + normalise editable metadata. Unknown keys are rejected loudly
    rather than dropped silently — a typo'd field name that appears to save and
    then vanishes is worse than a 400."""
    unknown = sorted(set(payload) - set(EDITABLE_META))
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported field(s): {', '.join(unknown)}. "
                   f"Editable fields are: {', '.join(EDITABLE_META)}.")
    clean: dict[str, Any] = {}
    for key, value in payload.items():
        if value is None:
            clean[key] = None      # explicit clear
            continue
        if not isinstance(value, str):
            raise HTTPException(status_code=400, detail=f"'{key}' must be a string.")
        value = value.strip()
        if key == "status":
            if value not in PROJECT_STATUSES:
                raise HTTPException(
                    status_code=400,
                    detail=f"'status' must be one of: {', '.join(PROJECT_STATUSES)}.")
        elif len(value) > _MAX_LEN[key]:
            raise HTTPException(
                status_code=400,
                detail=f"'{key}' is longer than {_MAX_LEN[key]} characters.")
        clean[key] = value or None
    return clean


@router.get("/api/projects")
def list_projects() -> dict[str, Any]:
    """All project workspaces under artifacts/projects/ + which one is active."""
    active = _active_slug()
    projects = []
    if config.PROJECTS_DIR.exists():
        for d in sorted(config.PROJECTS_DIR.iterdir()):
            if d.is_dir():
                projects.append(_summary(d, active))
    return {"active": active, "projects": projects}


@router.post("/api/projects", status_code=201)
def create_project(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Create an empty workspace from a name, with no files yet.

    Deliberately does NOT activate the new project: creating and switching are
    separate user intents, and silently redirecting the open UI to an empty
    workspace loses the reviewer's place. The client calls /activate when the
    user actually opens it."""
    unknown = sorted(set(payload) - {"name", *EDITABLE_META})
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported field(s): {', '.join(unknown)}. "
                   f"Accepted fields are: name, {', '.join(EDITABLE_META)}.")

    raw_name = payload.get("name")
    if not isinstance(raw_name, str) or not raw_name.strip():
        raise HTTPException(status_code=400, detail="A project name is required.")
    name = raw_name.strip()
    # slugify() falls back to the literal "project" when a name has no
    # alphanumerics, so "---" would otherwise silently create a folder called
    # "project". Check the name itself rather than trusting the slug.
    if sum(c.isalnum() for c in name) < 2:
        raise HTTPException(
            status_code=400,
            detail="That name has too few letters or digits to form a project folder.")
    slug = config.slugify(name)
    if (config.PROJECTS_DIR / slug).exists():
        raise HTTPException(
            status_code=409,
            detail=f"A project folder named '{slug}' already exists. Pick a different name.")

    meta = _validate_meta({k: v for k, v in payload.items() if k != "name"})
    # display_name defaults to what the human typed — the slug is a folder name,
    # not a title, and round-tripping it back through the UI would lose casing.
    meta.setdefault("display_name", name)

    # Written to an explicit path rather than through config.artifact_path():
    # that helper resolves against the *ambient* project binding, and this
    # handler is the one place that already knows exactly which directory it is
    # creating. Going direct also means creating a project neither reads nor
    # writes the request's project context — create and activate stay separate.
    target = config.PROJECTS_DIR / slug
    for sub in config._DERIVED.values():      # uploads / evidence / pages
        (target / sub).mkdir(parents=True, exist_ok=True)
    manifest = {**meta, "project": slug, "created_at": _now(), "updated_at": _now()}
    (target / config.ARTIFACT_FILES["project_manifest"]).write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    return _summary(target, _active_slug())


@router.get("/api/projects/{slug}")
def get_project(slug: str) -> dict[str, Any]:
    """One project in detail, including how much disk it occupies — so the
    delete confirmation can state what is actually being destroyed instead of
    asking the reviewer to trust an unquantified warning."""
    target = _workspace_dir(slug)
    size = 0
    files = 0
    for p in target.rglob("*"):
        if p.is_file():
            files += 1
            try:
                size += p.stat().st_size
            except OSError:
                pass    # racing GC/antivirus: report what we could measure
    return {**_summary(target, _active_slug()), "size_bytes": size, "file_count": files}


@router.patch("/api/projects/{slug}")
def update_project(slug: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Update project metadata. Touches the manifest only — never uploads,
    artifacts or verdicts, so renaming a project cannot change a single
    comparison result."""
    target = _workspace_dir(slug)
    meta = _validate_meta(payload)
    if not meta:
        raise HTTPException(status_code=400, detail="No fields to update.")

    manifest_path = target / config.ARTIFACT_FILES["project_manifest"]
    manifest = _read_json(manifest_path)
    for key, value in meta.items():
        if value is None:
            manifest.pop(key, None)
        else:
            manifest[key] = value
    manifest.setdefault("project", slug)
    manifest["updated_at"] = _now()
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return _summary(target, _active_slug())


@router.post("/api/projects/activate")
def activate_project(payload: dict[str, Any]) -> dict[str, Any]:
    """UI preference write ONLY (BUG-03): records which workspace the UI shows
    by default. Other endpoints resolve their own project per request (via the
    X-Project header / ?project= query), so this is no longer required for
    their correctness."""
    slug = config.slugify(str(payload.get("slug", "")))
    if not (config.PROJECTS_DIR / slug).is_dir():
        raise HTTPException(status_code=404, detail=f"No project workspace '{slug}'.")
    config.set_active_project(slug)
    return {"active": slug}


@router.delete("/api/projects/{slug}")
def delete_project(slug: str) -> dict[str, Any]:
    """Delete a whole project workspace tree. Refuses the active project (409):
    in-flight requests may still be bound to it. Traversal-safe: the target
    must resolve to a direct child of PROJECTS_DIR."""
    target = _workspace_dir(slug)
    if target.name == _active_slug():
        raise HTTPException(status_code=409,
                            detail="Cannot delete the active project — switch to another project first.")
    shutil.rmtree(target)
    return {"deleted": slug}


def ingest_revit_export(manifest: dict[str, Any], raw: dict[str, Any],
                        original_name: str | None) -> dict[str, Any]:
    """THE Revit-export ingest path — used by both the /api/upload form branch
    and the zero-upload auto-ingest (/api/revit/ingest, Design A2). Mutates
    ``manifest`` in place and returns the adapted raw.

    Design A2's whole claim to zero math risk is that the auto-ingest runs this
    exact code, so the Madera 106-MATCH baseline holds by construction. Do not
    fork it."""
    revit_path = config.UPLOAD_DIR / "input_revit.json"
    revit_path.write_text(json.dumps(raw), encoding="utf-8")
    manifest["revit_path"] = str(revit_path)
    manifest["revit_original_name"] = original_name
    if revit_v3_adapter.is_v3(raw):
        # pyRevit category-scoped export: normalize to the raw_revit
        # shapes existing consumers read (walls/grids/comparison_view),
        # keeping the full element list under v3_elements.
        raw = revit_v3_adapter.adapt_raw(raw)
        manifest["revit_schema"] = "v3"
    save_artifact("raw_revit", raw)
    _maybe_auto_advance_export(raw)
    return raw


@router.post("/api/upload")
async def upload_project(
    pdf: UploadFile | None = File(default=None),
    revit_json: UploadFile | None = File(default=None),
    project: str | None = Query(default=None),
) -> JSONResponse:
    """Upload any project's PDF + Revit export to create/activate a project
    workspace (named from ?project= or the PDF filename) so different projects
    never contaminate each other's artifacts."""
    if pdf is None and revit_json is None:
        raise HTTPException(status_code=400, detail="Provide pdf and/or revit_json files.")
    if project:
        slug = config.slugify(project)
    elif pdf is not None:
        # A PDF starts (or retargets) the workspace, named from its filename.
        slug = config.slugify(Path(pdf.filename).stem)
    else:
        # Revit-only upload: ATTACH to the project already open. Minting a new
        # workspace from the JSON filename here split PDF (uploaded first) from
        # its Revit export across two projects — the "No project PDF" 409 root
        # cause. Only fall back to the filename when there is no active project
        # yet (Revit JSON was the very first file).
        try:
            slug = config.active_project()
        except ValueError:
            slug = config.slugify(Path(revit_json.filename).stem)
    # Validate slug: reject empty, path-traversal, or too-short names.
    if not slug or '..' in slug or len(slug) < 2:
        raise HTTPException(status_code=400, detail="Invalid project name")
    config.set_active_project(slug)
    manifest_path = config.artifact_path("project_manifest")
    manifest: dict[str, Any] = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )
    if pdf is not None:
        if pdf.size and pdf.size > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File too large")
        raw_bytes = await pdf.read()
        if len(raw_bytes) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File too large")
        # Validate PDF magic bytes before writing to disk.
        if not raw_bytes[:4] == b'%PDF':
            raise HTTPException(status_code=400, detail="Not a valid PDF")
        pdf_path = config.UPLOAD_DIR / "input.pdf"
        pdf_path.write_bytes(raw_bytes)
        import fitz

        with fitz.open(pdf_path) as doc:
            manifest["page_count"] = doc.page_count
        manifest["pdf_path"] = str(pdf_path)
        manifest["pdf_original_name"] = pdf.filename
    if revit_json is not None:
        if revit_json.size and revit_json.size > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File too large")
        raw_bytes = await revit_json.read()
        if len(raw_bytes) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File too large")
        try:
            raw = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid Revit JSON: {exc}")
        ingest_revit_export(manifest, raw, revit_json.filename)
    manifest["uploaded_at"] = _now()
    # Keep the Project Manager's timestamps truthful when files land in a
    # workspace that was defined first and uploaded to second.
    manifest.setdefault("created_at", manifest["uploaded_at"])
    manifest["updated_at"] = manifest["uploaded_at"]
    manifest["project"] = config.active_project()
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    phase_summary.record(
        "upload",
        phase_summary.upload(manifest, _optional("element_intelligence"),
                             _optional("pdf_page_intelligence")),
    )
    if pdf is not None:
        # Zero-click benchmark proposal from this PDF's own grids; skips itself
        # (with a log line) whenever its inputs aren't there yet.
        maybe_auto_benchmark()
    return JSONResponse(manifest)


def _optional(key: str) -> dict[str, Any] | None:
    """Artifact if it exists, else None — summaries degrade, never raise."""
    path = config.artifact_path(key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
