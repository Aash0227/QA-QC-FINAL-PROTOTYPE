"""Upload slug fix: a revit_json-ONLY upload with no ?project= attaches to the
active workspace (config.active_project()) instead of slugging the filename."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app  # noqa: F401

REVIT_FILENAME = "revit_export_somewhere_else.json"
REVIT_SLUG = "revit-export-somewhere-else"  # what slugging the filename gives


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Active project 'scratch' with artifacts isolated to tmp_path. Every
    derived dir is pinned as a real attr (not left to __getattr__/ContextVar
    resolution) so a prior test's lingering monkeypatch can never redirect
    this test's writes into another test's tmp dir."""
    ws = tmp_path / "ws"
    monkeypatch.setattr(config, "ARTIFACT_DIR", ws)
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    for name in ("EVIDENCE_DIR", "UPLOAD_DIR", "PAGES_DIR"):
        monkeypatch.setattr(config, name, ws / config._DERIVED[name])
    active = tmp_path / "active_project.json"
    active.write_text(json.dumps({"slug": "scratch"}), encoding="utf-8")
    monkeypatch.setattr(config, "ACTIVE_PROJECT_FILE", active)
    # Reset any ContextVar leaked by earlier tests in this process.
    config._PROJECT_SLUG.set("scratch")
    return tmp_path


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_revit_only_upload_attaches_to_active_workspace(workspace, client):
    """No ?project= and no PDF → the JSON lands in the ACTIVE workspace; no
    new project dir is minted from the filename."""
    resp = client.post(
        "/api/upload",
        files={"revit_json": (REVIT_FILENAME, b'{"walls": []}', "application/json")},
    )
    assert resp.status_code == 200, resp.text
    manifest = resp.json()

    # Bound to the ACTIVE project, not slugified from the filename.
    assert manifest["project"] == "scratch"
    assert manifest["revit_original_name"] == REVIT_FILENAME

    # revit_path points inside the active workspace's upload dir.
    revit_path = Path(manifest["revit_path"])
    assert revit_path.is_file()
    assert revit_path.parent == workspace / "ws" / "uploads"

    # The raw export artifact landed in the active workspace too.
    raw_path = config.artifact_path("raw_revit")
    assert raw_path.exists()
    assert raw_path.parent == workspace / "ws"

    # The persisted preference still names the active project.
    assert json.loads(
        (workspace / "active_project.json").read_text(encoding="utf-8")
    )["slug"] == "scratch"

    # And NO project dir was created from the filename slug.
    assert not (workspace / "projects" / REVIT_SLUG).exists()
    assert not (workspace / "projects" / REVIT_FILENAME).exists()