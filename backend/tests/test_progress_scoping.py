"""The progress bus must never show one project's events to another.

QBC issues QA verdicts. Rendering another project's "stage complete" onto a
project whose stages actually skipped is the worst class of bug the system
can have: the screen asserts something the artifacts contradict. These tests
pin the two mechanisms that prevent it -- per-event project attribution, and
a stream that starts from now rather than replaying history.
"""
from __future__ import annotations

import pytest

from app import config, progress


@pytest.fixture(autouse=True)
def _clean_bus():
    with progress._LOCK:
        progress._EVENTS.clear()
    yield
    with progress._LOCK:
        progress._EVENTS.clear()


def _emit_as(project: str, step: str, kind: str, msg: str, monkeypatch):
    """Emit while `project` is the active one -- emit() resolves the project
    on the emitting thread, which is where the truth is known."""
    monkeypatch.setattr(config, "active_project", lambda: project)
    progress.emit(step, kind, msg)


def test_events_are_stamped_with_the_emitting_project(monkeypatch):
    _emit_as("alpha", "match", "done", "Building the review queue complete", monkeypatch)
    ev = progress.events_since(0)[-1]
    assert ev["project"] == "alpha"


def test_a_project_never_receives_another_projects_events(monkeypatch):
    """The reproduced defect: run a stage on one project, open another, and
    the second rendered the first's success."""
    _emit_as("dogwood-lane", "match", "done", "Building the review queue complete", monkeypatch)
    _emit_as("madera", "extract", "done", "Reading drawings complete", monkeypatch)

    madera = progress.events_since(0, project="madera")
    assert [e["step"] for e in madera] == ["extract"]
    assert all(e["project"] == "madera" for e in madera)
    # Specifically: madera must NOT see the match completion it never ran.
    assert not [e for e in madera if e["step"] == "match"]


def test_unattributed_events_are_never_delivered_to_a_scoped_listener(monkeypatch):
    """An event whose project could not be resolved cannot be shown to BE
    yours, so a filtered listener must not receive it."""
    monkeypatch.setattr(config, "active_project",
                        lambda: (_ for _ in ()).throw(RuntimeError("no project")))
    progress.emit("match", "done", "orphaned event")
    assert progress.events_since(0)[-1]["project"] is None
    assert progress.events_since(0, project="madera") == []


def test_unscoped_listener_still_sees_everything(monkeypatch):
    """Scoping is opt-in; an unfiltered reader (diagnostics) is unchanged."""
    _emit_as("alpha", "extract", "done", "a", monkeypatch)
    _emit_as("beta", "extract", "done", "b", monkeypatch)
    assert len(progress.events_since(0)) == 2


@pytest.mark.asyncio
async def test_stream_starts_from_now_not_a_replay_of_history(monkeypatch):
    """A fresh listener must not be handed the whole buffer. Replaying from
    seq 0 is what let a previous run's completions repaint a new project."""
    _emit_as("madera", "match", "done", "stale history", monkeypatch)
    before = progress.current_seq()
    assert before > 0

    gen = progress.sse_stream(poll_s=0.01, project="madera")
    hello = await gen.__anext__()
    assert "hello" in hello

    # Nothing new has happened, so the historical event must NOT arrive.
    _emit_as("madera", "extract", "start", "live event", monkeypatch)
    chunk = await gen.__anext__()
    assert "live event" in chunk
    assert "stale history" not in chunk
    await gen.aclose()
