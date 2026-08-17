"""Concurrent project isolation (BUG-03): two projects, one process.

(a) HTTP level: two uploads bound via ?project= land in separate workspaces
    and GET /api/pipeline/status reports each its own artifacts.
(b) Thread level: the _PROJECT_SLUG ContextVar keeps two threads writing the
    same artifact key in their own workspace dirs.

NOTE: this module deliberately does NOT monkeypatch config.ARTIFACT_DIR — the
per-request ContextVar resolution IS the thing under test. PROJECTS_DIR is
monkeypatched so every workspace lands in tmp_path.
"""

from __future__ import annotations

import contextvars
import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.main import app  # noqa: F401


def _tiny_pdf() -> bytes:
    """One real page of PDF (fitz must open it: upload checks magic + page count)."""
    import fitz

    doc = fitz.open()
    doc.new_page()
    return doc.tobytes()


@pytest.fixture()
def projects_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """All project workspaces resolve under tmp_path."""
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    active = tmp_path / "active_project.json"
    active.write_text(json.dumps({"slug": "proj-a"}), encoding="utf-8")
    monkeypatch.setattr(config, "ACTIVE_PROJECT_FILE", active)
    return tmp_path


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ── (a) HTTP-level isolation ─────────────────────────────────────────────


def test_uploads_land_in_their_own_workspaces(projects_root, client):
    """PDF uploads bound to A and B end up in separate project dirs."""
    pdf = _tiny_pdf()
    for slug in ("proj-a", "proj-b"):
        resp = client.post(
            f"/api/upload?project={slug}",
            files={"pdf": (f"drawing-{slug}.pdf", pdf, "application/pdf")},
        )
        assert resp.status_code == 200, resp.text

    a_manifest = json.loads(
        (projects_root / "projects" / "proj-a" / "project_manifest.json")
        .read_text(encoding="utf-8"))
    b_manifest = json.loads(
        (projects_root / "projects" / "proj-b" / "project_manifest.json")
        .read_text(encoding="utf-8"))

    assert a_manifest["project"] == "proj-a"
    assert b_manifest["project"] == "proj-b"
    a_pdf = Path(a_manifest["pdf_path"])
    b_pdf = Path(b_manifest["pdf_path"])
    assert a_pdf != b_pdf
    assert a_pdf.is_file() and b_pdf.is_file()
    assert a_pdf.parent == projects_root / "projects" / "proj-a" / "uploads"
    assert b_pdf.parent == projects_root / "projects" / "proj-b" / "uploads"


def test_pipeline_status_sees_own_artifacts_per_binding(projects_root, client):
    """GET /api/pipeline/status reports each project's own artifact presence,
    resolved per request via ?project= and X-Project."""
    pdf = _tiny_pdf()
    client.post("/api/upload?project=proj-a",
                files={"pdf": ("a.pdf", pdf, "application/pdf")})
    client.post("/api/upload?project=proj-b",
                files={"pdf": ("b.pdf", pdf, "application/pdf")})

    # ?project= binding
    a = client.get("/api/pipeline/status?project=proj-a").json()
    # X-Project header binding
    b = client.get("/api/pipeline/status", headers={"X-Project": "proj-b"}).json()

    upload_a = next(s for s in a["steps"] if s["key"] == "upload")
    upload_b = next(s for s in b["steps"] if s["key"] == "upload")
    assert upload_a["done"] is True
    assert upload_b["done"] is True

    # Neither workspace sees the other's stage artifacts beyond its own upload:
    # with only a PDF uploaded, all downstream stages are absent in both.
    for s in a["steps"]:
        assert s["done"] == (s["key"] == "upload")
    for s in b["steps"]:
        assert s["done"] == (s["key"] == "upload")


# ── (b) thread-level ContextVar isolation ───────────────────────────────


def test_two_threads_write_same_artifact_key_to_own_workspaces(projects_root):
    """Two threads bound to different slugs writing the same artifact key
    each land in their own workspace dir."""
    results: dict[str, Path] = {}
    both_bound = threading.Barrier(2)

    def worker(slug: str) -> None:
        def run() -> None:
            config.bind_project(slug)
            path = config.artifact_path("raw_revit")
            path.write_text(json.dumps({"slug": slug}), encoding="utf-8")
            results[slug] = path
            both_bound.wait()

        contextvars.copy_context().run(run)

    threads = [threading.Thread(target=worker, args=(s,)) for s in ("alpha", "beta")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert results["alpha"] == projects_root / "projects" / "alpha" / "raw_revit_export.json"
    assert results["beta"] == projects_root / "projects" / "beta" / "raw_revit_export.json"
    assert json.loads(results["alpha"].read_text(encoding="utf-8")) == {"slug": "alpha"}
    assert json.loads(results["beta"].read_text(encoding="utf-8")) == {"slug": "beta"}