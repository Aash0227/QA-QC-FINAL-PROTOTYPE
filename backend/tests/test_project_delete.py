"""DELETE /api/projects/{slug}: removes a workspace tree; refuses the active
project (409); rejects traversal (400) and unknown slugs (404)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from app import config
from app.routers import projects


@pytest.fixture
def projects_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path)
    monkeypatch.setattr(config, "active_project", lambda: "keeper")
    (tmp_path / "keeper").mkdir()
    return tmp_path


def _mk(root: Path, slug: str) -> Path:
    d = root / slug
    (d / "evidence").mkdir(parents=True)
    (d / "element_list.json").write_text("{}", encoding="utf-8")
    return d


def test_delete_removes_workspace(projects_dir: Path) -> None:
    _mk(projects_dir, "old-run")
    assert projects.delete_project("old-run") == {"deleted": "old-run"}
    assert not (projects_dir / "old-run").exists()
    assert (projects_dir / "keeper").is_dir()  # siblings untouched
    slugs = [p["slug"] for p in projects.list_projects()["projects"]]
    assert "old-run" not in slugs


def test_delete_unknown_slug_404(projects_dir: Path) -> None:
    with pytest.raises(HTTPException) as exc:
        projects.delete_project("nope")
    assert exc.value.status_code == 404


def test_delete_active_project_409(projects_dir: Path) -> None:
    with pytest.raises(HTTPException) as exc:
        projects.delete_project("keeper")
    assert exc.value.status_code == 409
    assert (projects_dir / "keeper").is_dir()  # untouched


@pytest.mark.parametrize("slug", ["..", "../outside", "..\\outside"])
def test_delete_traversal_400(projects_dir: Path, slug: str, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(HTTPException) as exc:
        projects.delete_project(slug)
    assert exc.value.status_code == 400
    assert outside.is_dir()  # nothing outside PROJECTS_DIR was touched
