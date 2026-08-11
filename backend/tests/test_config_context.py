"""BUG-03 full fix: artifact dirs are request-scoped via a ContextVar, and a
test monkeypatch of config.ARTIFACT_DIR still wins (and drags the derived dirs)."""

from __future__ import annotations

import contextvars
import threading

from app import config


import pytest


@pytest.fixture(autouse=True)
def _clear_dir_shadows():
    """A prior monkeypatch test's undo re-creates ARTIFACT_DIR as a real module
    attr that would shadow __getattr__. Drop those so ContextVar resolution is
    what we're actually testing here (production never has such an attr)."""
    for name in ("ARTIFACT_DIR", "EVIDENCE_DIR", "UPLOAD_DIR", "PAGES_DIR"):
        config.__dict__.pop(name, None)
    yield


def test_bind_project_is_request_scoped(monkeypatch, tmp_path):
    """Two contexts bound to different slugs each see their own ARTIFACT_DIR —
    no cross-context stomp (the whole point of the ContextVar)."""
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path)
    results: dict[str, object] = {}
    both_bound = threading.Barrier(2)

    def worker(slug: str) -> None:
        def run() -> None:
            config.bind_project(slug)
            both_bound.wait()  # force interleave: both bound before either reads
            results[slug] = config.ARTIFACT_DIR

        contextvars.copy_context().run(run)

    threads = [threading.Thread(target=worker, args=(s,)) for s in ("alpha", "beta")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results["alpha"] == tmp_path / "alpha"
    assert results["beta"] == tmp_path / "beta"


def test_monkeypatch_artifact_dir_wins_and_drags_derived(monkeypatch, tmp_path):
    """The 7 legacy tests pin config.ARTIFACT_DIR via monkeypatch; the derived
    dirs must follow it through the module's own attribute lookup."""
    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path)
    assert config.ARTIFACT_DIR == tmp_path
    assert config.EVIDENCE_DIR == tmp_path / "evidence"
    assert config.UPLOAD_DIR == tmp_path / "uploads"
    assert config.PAGES_DIR == tmp_path / "pages"
