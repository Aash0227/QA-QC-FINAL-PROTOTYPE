"""Project Manager CRUD: POST /api/projects, GET /api/projects/{slug},
PATCH /api/projects/{slug}, and the metadata that GET /api/projects now returns.

The load-bearing guarantees pinned here:
  - metadata is additive, so workspaces predating the Project Manager still list;
  - PATCH can only write the five editable fields, never pipeline-owned keys;
  - editing metadata never touches artifacts, so a rename cannot move a verdict.

Handlers are called directly (same convention as test_project_delete.py) with
config.PROJECTS_DIR pointed at tmp_path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app import config
from app.routers import projects


@pytest.fixture
def projects_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "projects"
    root.mkdir()
    monkeypatch.setattr(config, "PROJECTS_DIR", root)
    monkeypatch.setattr(config, "MEMORY_DIR", tmp_path / "memory")
    monkeypatch.setattr(config, "active_project", lambda: "keeper")
    (root / "keeper").mkdir()
    # These handlers resolve every path from PROJECTS_DIR explicitly, but the
    # suite as a whole shares one thread: pin the ambient binding so a slug left
    # over by another module cannot reach in here, and hand it back afterwards.
    token = config._PROJECT_SLUG.set(None)
    yield root
    config._PROJECT_SLUG.reset(token)


def _manifest(root: Path, slug: str, **keys) -> Path:
    d = root / slug
    d.mkdir(exist_ok=True)
    p = d / config.ARTIFACT_FILES["project_manifest"]
    p.write_text(json.dumps(keys), encoding="utf-8")
    return p


def _find(slug: str) -> dict:
    return next(p for p in projects.list_projects()["projects"] if p["slug"] == slug)


# --------------------------------------------------------------- create

def test_create_makes_workspace_and_manifest(projects_dir: Path) -> None:
    out = projects.create_project({"name": "Maple Ridge Block C", "client": "Northwind"})
    assert out["slug"] == "maple-ridge-block-c"
    # The typed name is kept verbatim: the slug is a folder name, not a title.
    assert out["display_name"] == "Maple Ridge Block C"
    assert out["client"] == "Northwind"
    assert out["status"] == "active"
    d = projects_dir / "maple-ridge-block-c"
    assert d.is_dir()
    saved = json.loads((d / config.ARTIFACT_FILES["project_manifest"]).read_text(encoding="utf-8"))
    assert saved["display_name"] == "Maple Ridge Block C"
    assert saved["created_at"] and saved["updated_at"]


def test_create_does_not_activate(projects_dir: Path) -> None:
    """Creating a project must not steal the open workspace out from under the
    reviewer — /activate is a separate, explicit action."""
    out = projects.create_project({"name": "Somewhere Else"})
    assert out["active"] is False
    assert _find("keeper")["active"] is True


def test_create_duplicate_409(projects_dir: Path) -> None:
    projects.create_project({"name": "Twice"})
    with pytest.raises(HTTPException) as exc:
        projects.create_project({"name": "Twice"})
    assert exc.value.status_code == 409


@pytest.mark.parametrize("payload", [{}, {"name": ""}, {"name": "   "}, {"name": 7}])
def test_create_requires_a_name_400(projects_dir: Path, payload: dict) -> None:
    with pytest.raises(HTTPException) as exc:
        projects.create_project(payload)
    assert exc.value.status_code == 400


def test_create_rejects_name_with_no_usable_characters(projects_dir: Path) -> None:
    """'---' slugifies to '' — refuse rather than silently creating 'project'."""
    with pytest.raises(HTTPException) as exc:
        projects.create_project({"name": "---"})
    assert exc.value.status_code == 400


def test_create_rejects_unknown_field(projects_dir: Path) -> None:
    with pytest.raises(HTTPException) as exc:
        projects.create_project({"name": "Sneaky", "pdf_path": r"C:\somewhere\else.pdf"})
    assert exc.value.status_code == 400
    assert not (projects_dir / "sneaky").exists()


# --------------------------------------------------------------- read

def test_manifest_without_metadata_still_lists(projects_dir: Path) -> None:
    """Workspaces created before the Project Manager have none of the new keys.
    They must list with a derived name and sane defaults, not blow up."""
    _manifest(projects_dir, "legacy", pdf_original_name="permit set.pdf", page_count=42)
    p = _find("legacy")
    assert p["display_name"] == "permit set.pdf"   # falls back to the PDF name
    assert p["status"] == "active"                  # default, not stored
    assert p["client"] is None and p["revision"] is None
    assert p["page_count"] == 42


def test_workspace_with_no_manifest_at_all_lists(projects_dir: Path) -> None:
    (projects_dir / "bare").mkdir()
    p = _find("bare")
    assert p["display_name"] == "bare"              # last resort: the slug
    assert p["has_pdf"] is False and p["has_revit"] is False


def test_corrupt_manifest_does_not_break_listing(projects_dir: Path) -> None:
    """One torn write must not 500 the whole project list."""
    d = projects_dir / "torn"
    d.mkdir()
    (d / config.ARTIFACT_FILES["project_manifest"]).write_text("{not json", encoding="utf-8")
    assert _find("torn")["display_name"] == "torn"


def test_display_name_wins_over_pdf_name(projects_dir: Path) -> None:
    _manifest(projects_dir, "renamed", display_name="Tower A", pdf_original_name="raw.pdf")
    assert _find("renamed")["display_name"] == "Tower A"


def test_uploaded_at_seeds_timestamps_for_older_workspaces(projects_dir: Path) -> None:
    _manifest(projects_dir, "old", uploaded_at="2026-01-02T03:04:05+00:00")
    p = _find("old")
    assert p["created_at"] == "2026-01-02T03:04:05+00:00"
    assert p["updated_at"] == "2026-01-02T03:04:05+00:00"


def test_get_project_reports_disk_usage(projects_dir: Path) -> None:
    d = projects_dir / "sized"
    (d / "uploads").mkdir(parents=True)
    (d / "uploads" / "input.pdf").write_bytes(b"x" * 1000)
    (d / config.ARTIFACT_FILES["element_list"]).write_text(
        json.dumps({"counts": {"total": 3}, "sheets": ["S1", "S2"]}), encoding="utf-8")
    out = projects.get_project("sized")
    assert out["file_count"] == 2
    assert out["size_bytes"] >= 1000
    assert out["sheet_count"] == 2
    assert out["counts"] == {"total": 3}


def test_get_project_unknown_404(projects_dir: Path) -> None:
    with pytest.raises(HTTPException) as exc:
        projects.get_project("nope")
    assert exc.value.status_code == 404


# --------------------------------------------------------------- update

def test_patch_updates_whitelisted_fields(projects_dir: Path) -> None:
    _manifest(projects_dir, "edit-me", pdf_original_name="raw.pdf")
    out = projects.update_project("edit-me", {
        "display_name": "1311 Countryside Ct",
        "client": "Sarkar Residence",
        "revision": "PC2 2026-05-26",
        "status": "archived",
        "notes": "waiting on structural revision",
    })
    assert out["display_name"] == "1311 Countryside Ct"
    assert out["status"] == "archived"
    assert out["updated_at"] is not None


def test_patch_rejects_unknown_field(projects_dir: Path) -> None:
    """The security-relevant case: pdf_path is pipeline-owned. If a client could
    set it, it could aim the pipeline at any file on disk."""
    _manifest(projects_dir, "guard", pdf_path=r"C:\real\input.pdf")
    with pytest.raises(HTTPException) as exc:
        projects.update_project("guard", {"pdf_path": r"C:\evil\payload.pdf"})
    assert exc.value.status_code == 400
    assert "pdf_path" in exc.value.detail
    saved = json.loads(
        (projects_dir / "guard" / config.ARTIFACT_FILES["project_manifest"]).read_text(encoding="utf-8"))
    assert saved["pdf_path"] == r"C:\real\input.pdf"     # untouched


def test_patch_rejects_bad_status(projects_dir: Path) -> None:
    _manifest(projects_dir, "st")
    with pytest.raises(HTTPException) as exc:
        projects.update_project("st", {"status": "released"})
    assert exc.value.status_code == 400


def test_patch_rejects_overlong_value(projects_dir: Path) -> None:
    _manifest(projects_dir, "long")
    with pytest.raises(HTTPException) as exc:
        projects.update_project("long", {"display_name": "x" * 121})
    assert exc.value.status_code == 400


def test_patch_rejects_non_string(projects_dir: Path) -> None:
    _manifest(projects_dir, "typed")
    with pytest.raises(HTTPException) as exc:
        projects.update_project("typed", {"client": {"nested": "object"}})
    assert exc.value.status_code == 400


def test_patch_empty_payload_400(projects_dir: Path) -> None:
    _manifest(projects_dir, "nada")
    with pytest.raises(HTTPException) as exc:
        projects.update_project("nada", {})
    assert exc.value.status_code == 400


def test_patch_null_clears_a_field(projects_dir: Path) -> None:
    _manifest(projects_dir, "clearme", client="Old Client")
    assert projects.update_project("clearme", {"client": None})["client"] is None


def test_patch_preserves_artifacts_and_counts(projects_dir: Path) -> None:
    """Renaming a project must not disturb a single verdict."""
    d = projects_dir / "keep-results"
    d.mkdir()
    element_list = d / config.ARTIFACT_FILES["element_list"]
    payload = {"counts": {"total": 341, "by_status": {"MATCH": 19}}, "sheets": ["S5", "S6"]}
    element_list.write_text(json.dumps(payload), encoding="utf-8")
    before = element_list.read_bytes()

    out = projects.update_project("keep-results", {"display_name": "Renamed"})

    assert element_list.read_bytes() == before          # byte-identical
    assert out["counts"] == payload["counts"]
    assert out["sheet_count"] == 2


def test_patch_preserves_pipeline_manifest_keys(projects_dir: Path) -> None:
    _manifest(projects_dir, "mixed", pdf_path=r"C:\in.pdf", page_count=108,
              revit_model_title="Tower.rvt")
    projects.update_project("mixed", {"client": "Acme"})
    saved = json.loads(
        (projects_dir / "mixed" / config.ARTIFACT_FILES["project_manifest"]).read_text(encoding="utf-8"))
    assert saved["pdf_path"] == r"C:\in.pdf"
    assert saved["page_count"] == 108
    assert saved["revit_model_title"] == "Tower.rvt"
    assert saved["client"] == "Acme"


# --------------------------------------------------------------- traversal

@pytest.mark.parametrize("handler", [projects.get_project,
                                     lambda s: projects.update_project(s, {"client": "x"}),
                                     projects.delete_project])
@pytest.mark.parametrize("slug", ["..", "../outside", "..\\outside", "a/b"])
def test_traversal_rejected_on_every_slug_route(projects_dir: Path, handler, slug: str) -> None:
    outside = projects_dir.parent / "outside"
    outside.mkdir(exist_ok=True)
    with pytest.raises(HTTPException) as exc:
        handler(slug)
    assert exc.value.status_code == 400
    assert outside.is_dir()
