"""Project workspace endpoints: list, activate (UI preference only), upload."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from fastapi import File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse

from .. import config, phase_summary, revit_v3_adapter
from .common import make_router, save_artifact
from .workflow import _maybe_auto_advance_export, maybe_auto_benchmark

router = make_router()

# Maximum upload size: 50 MB. Defence-in-depth: check file.size before reading
# and len(content) after reading.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50MB


@router.get("/api/projects")
def list_projects() -> dict[str, Any]:
    """All project workspaces under artifacts/projects/ + which one is active."""
    active = config.active_project()
    projects = []
    if config.PROJECTS_DIR.exists():
        for d in sorted(config.PROJECTS_DIR.iterdir()):
            if not d.is_dir():
                continue
            name = d.name
            manifest = d / config.ARTIFACT_FILES["project_manifest"]
            display = name
            if manifest.exists():
                try:
                    display = json.loads(manifest.read_text(encoding="utf-8")).get(
                        "pdf_original_name") or name
                except json.JSONDecodeError:
                    pass
            el = d / config.ARTIFACT_FILES["element_list"]
            counts = None
            if el.exists():
                try:
                    counts = json.loads(el.read_text(encoding="utf-8")).get("counts")
                except json.JSONDecodeError:
                    pass
            projects.append({"slug": name, "display_name": display,
                             "active": name == active, "counts": counts})
    return {"active": active, "projects": projects}


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
    if not slug or ".." in slug or "/" in slug or "\\" in slug:
        raise HTTPException(status_code=400, detail="Invalid project name")
    target = (config.PROJECTS_DIR / slug).resolve()
    if target.parent != config.PROJECTS_DIR.resolve():
        raise HTTPException(status_code=400, detail="Invalid project name")
    if not target.is_dir():
        raise HTTPException(status_code=404, detail=f"No project workspace '{slug}'.")
    try:
        active: str | None = config.active_project()
    except ValueError:
        active = None
    if target.name == active:
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
    slug_source = project or (pdf.filename if pdf else None) or (
        revit_json.filename if revit_json else None) or "project"
    slug = config.slugify(Path(slug_source).stem)
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
    from datetime import datetime, timezone

    manifest["uploaded_at"] = datetime.now(timezone.utc).isoformat()
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
