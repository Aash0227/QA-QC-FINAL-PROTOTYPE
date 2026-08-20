"""Phase 1 run-engine lifecycle over HTTP: start, poll, 409 duplicate lock,
stale-run recovery, and completion. Background threads run no-op stages
(``run_engine._exec_stage`` monkeypatched) so runs finish near-instantly."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, run_engine
from app.main import app  # noqa: F401 — app import triggers create_app once

SLUG = "scratch"


# ── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Scratch workspace: artifacts + active-project preference land in tmp."""
    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path)
    active = tmp_path / "active_project.json"
    active.write_text(json.dumps({"slug": SLUG}), encoding="utf-8")
    monkeypatch.setattr(config, "ACTIVE_PROJECT_FILE", active)
    return tmp_path


@pytest.fixture()
def quiet_stages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stages succeed instantly, writing their declared output artifact.

    They must actually write it: a stage that returns without producing its
    declared output is now a FAILURE, not a success (run_engine asserts the
    artifact exists before marking a stage done). A no-op fixture would be
    simulating a stage that lies about succeeding, which is precisely the bug
    that assertion exists to catch."""
    from app import stage_graph

    # raw_revit is an UPLOADED input, not any stage's output, so it must be
    # seeded or every Revit-dependent stage skips and the run is blocked.
    seed = config.artifact_path("raw_revit")
    seed.parent.mkdir(parents=True, exist_ok=True)
    seed.write_text("{}", encoding="utf-8")

    def _fake(key: str) -> None:
        out = stage_graph.STAGE_OUTPUT.get(key)
        if out:
            path = config.artifact_path(out)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(run_engine, "_exec_stage", _fake)


@pytest.fixture()
def blocked_stages(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stages succeed EXCEPT anything needing Revit data, which never arrives.

    Reproduces the real `madera` shape: the PDF side runs, every
    Revit-dependent stage skips for a missing prerequisite, and no
    element_list is ever produced."""
    from app import stage_graph

    def _fake(key: str) -> None:
        out = stage_graph.STAGE_OUTPUT.get(key)
        if out and out not in ("ai_revit",):
            path = config.artifact_path(out)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(run_engine, "_exec_stage", _fake)


@pytest.fixture(autouse=True)
def _reap_threads(workspace):
    """Never leak a runner thread into the next test (or past monkeypatch undo,
    where a still-running thread would write into the LIVE workspace).

    Depends on ``workspace`` so this teardown (join) runs BEFORE monkeypatch
    undoes ARTIFACT_DIR — the thread finishes its writes inside tmp_path."""
    yield
    t = run_engine._ACTIVE_THREADS.pop(SLUG, None)
    if t is not None and t.is_alive():
        t.join(timeout=5)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ── helpers ─────────────────────────────────────────────────────────────


def _post_run(client: TestClient):
    return client.post("/api/pipeline/run")


def _wait_until_done(client: TestClient, timeout_s: float = 10.0) -> dict:
    """Poll GET /api/pipeline/run until the status leaves 'running'."""
    deadline = time.monotonic() + timeout_s
    state = None
    while time.monotonic() < deadline:
        resp = client.get("/api/pipeline/run")
        assert resp.status_code == 200
        state = resp.json()
        if state["status"] != "running":
            return state
        time.sleep(0.05)
    assert state is not None and state["status"] != "running", (
        f"run did not finish within {timeout_s}s: {state}")
    return state


# ── tests ───────────────────────────────────────────────────────────────


def test_post_run_202_running_seven_pending(workspace, quiet_stages, client):
    """(a) POST on an empty scratch workspace → 202, running, 7 pending stages."""
    resp = _post_run(client)
    assert resp.status_code == 202
    state = resp.json()
    assert state["status"] == "running"
    assert state["project"] == SLUG
    assert len(state["stages"]) == 7
    assert all(s["status"] == "pending" for s in state["stages"])
    assert state["run_id"]
    assert state["next_action"] is not None
    _wait_until_done(client)  # let the runner finish before teardown


def test_get_run_returns_state(workspace, quiet_stages, client):
    """(b) GET /api/pipeline/run returns the persisted state."""
    run_id = _post_run(client).json()["run_id"]
    resp = client.get("/api/pipeline/run")
    assert resp.status_code == 200
    assert resp.json()["run_id"] == run_id
    _wait_until_done(client)


def test_get_run_without_run_is_404(workspace, client):
    """(c) GET with no persisted run → 404."""
    resp = client.get("/api/pipeline/run")
    assert resp.status_code == 404


def test_duplicate_run_is_409(workspace, quiet_stages, client):
    """(d) A persisted running state + a live thread → second POST is 409
    with the existing run_id in detail."""
    state = {
        "run_id": "dup-run-001",
        "project": SLUG,
        "status": "running",
        "started_at": "2026-01-01T00:00:00+00:00",
        "completed_at": None,
        "stages": [],
    }
    (workspace / "run_state.json").write_text(json.dumps(state), encoding="utf-8")

    stop = threading.Event()
    live = threading.Thread(target=stop.wait, daemon=True)
    live.start()
    run_engine._ACTIVE_THREADS[SLUG] = live
    try:
        resp = _post_run(client)
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["run_id"] == "dup-run-001"
    finally:
        stop.set()
        live.join(timeout=5)


def test_stale_running_state_recovers(workspace, quiet_stages, client):
    """(e) running state with NO live thread → POST succeeds (202), new run."""
    stale = {
        "run_id": "stale-run-001",
        "project": SLUG,
        "status": "running",
        "started_at": "2026-01-01T00:00:00+00:00",
        "completed_at": None,
        "stages": [],
    }
    (workspace / "run_state.json").write_text(json.dumps(stale), encoding="utf-8")
    assert SLUG not in run_engine._ACTIVE_THREADS  # precondition: thread dead

    resp = _post_run(client)
    assert resp.status_code == 202
    new_id = resp.json()["run_id"]
    assert new_id != "stale-run-001"
    assert resp.json()["status"] == "running"
    _wait_until_done(client)


def test_run_completes_every_stage_done_or_skipped(workspace, quiet_stages, client):
    """(f) With no-op stages the run reaches a terminal state; every stage is
    done or skipped and next_action is present.

    These stages genuinely write their declared artifacts, so the run reaches
    "completed" -- which now means the run actually produced its final
    artifact, not merely that the thread finished.
    """
    resp = _post_run(client)
    assert resp.status_code == 202

    state = _wait_until_done(client)
    assert state["status"] == "completed", state["status"]
    assert state["completed_at"]
    for s in state["stages"]:
        assert s["status"] in ("done", "skipped"), (
            f"stage {s['key']} ended as {s['status']} — {s.get('reason') or s.get('error')}")
    assert state["next_action"]
    assert state["next_action"]["kind"] in ("upload_revit", "review", "retry")


def test_get_after_completion_persists(workspace, quiet_stages, client):
    """After the run ends, GET still serves the finished state (persistence).

    This test is about PERSISTENCE, not about which terminal status was
    reached -- with no-op stages that is "blocked" (nothing was produced).
    Asserting the terminal status is the job of the test above."""
    _post_run(client)
    state = _wait_until_done(client)
    resp = client.get("/api/pipeline/run")
    assert resp.status_code == 200
    assert resp.json()["status"] == state["status"] != "running"
    assert resp.json()["run_id"] == state["run_id"]

def test_run_with_missing_revit_data_is_blocked_not_completed(
    workspace, blocked_stages, client
) -> None:
    """A run whose answer-producing stages all skipped produced NO answer, and
    must not report success.

    This is the real `madera` case: PDF uploaded, Revit export never supplied,
    so revit_convert/ransac/compare/match skip on missing prerequisites. The
    run used to report "completed", which is how a project that could never
    produce a result came to look finished.
    """
    assert _post_run(client).status_code == 202
    state = _wait_until_done(client)

    assert state["status"] == "blocked", state["status"]
    assert state["skipped_stages"], "a blocked run must name what it skipped"
    # It must point at the real remedy, not at a broken stage.
    assert state["next_action"]["kind"] == "upload_revit"
    # And nothing may be reported as failed -- nothing broke; input was absent.
    assert not [s for s in state["stages"] if s["status"] == "failed"]
