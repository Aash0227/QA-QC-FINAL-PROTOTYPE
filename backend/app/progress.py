"""In-memory pipeline progress bus + SSE stream.

Step endpoints (main.py) and the extraction loop emit real signals — pages
scanned, tables found, inliers, verdict counts — and the pipeline UI streams
them live. Honest by construction: events describe what actually happened;
frozen modules are not instrumented, so their steps report start + an
artifact-derived summary at the end.

Ring buffer, no persistence: progress is a live view, artifacts remain the
audit trail.

Every event carries the PROJECT it belongs to, and ``sse_stream`` refuses to
deliver another project's events. Without that, one global buffer replayed
from seq 0 to every listener: opening the pipeline on a project whose stages
had all skipped showed the *previous* project's "complete" events painted onto
them, because the UI applies events by stage key. A QA tool reporting another
project's success on your screen is the worst class of bug this system can
have, so the project stamp is applied at emit time -- where the truth is
known -- rather than being inferred later.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any

_LOCK = threading.Lock()
_EVENTS: list[dict[str, Any]] = []
_SEQ = 0
_MAX_EVENTS = 500


def emit(step: str, kind: str, message: str, data: dict[str, Any] | None = None) -> None:
    """kind: start | info | done | error. Never raises."""
    global _SEQ
    try:
        # Resolve the project HERE, on the emitting thread, where the request
        # or run context is still bound. Doing it at read time would attribute
        # every event to whichever project happened to be active then.
        try:
            from . import config
            project = config.active_project()
        except Exception:
            project = None
        with _LOCK:
            _SEQ += 1
            _EVENTS.append(
                {
                    "seq": _SEQ,
                    "ts": time.time(),
                    "project": project,
                    "step": step,
                    "kind": kind,
                    "message": message,
                    "data": data or {},
                }
            )
            if len(_EVENTS) > _MAX_EVENTS:
                del _EVENTS[: len(_EVENTS) - _MAX_EVENTS]
    except Exception:
        pass  # progress must never break the pipeline


def events_since(seq: int, project: str | None = None) -> list[dict[str, Any]]:
    """Events after ``seq``. When ``project`` is given, ONLY that project's
    events -- an event with no project stamp is never delivered to a filtered
    listener, because an unattributed event cannot be shown to be yours."""
    with _LOCK:
        fresh = [e for e in _EVENTS if e["seq"] > seq]
    if project is None:
        return fresh
    return [e for e in fresh if e.get("project") == project]


def current_seq() -> int:
    """Newest sequence number, for a listener that wants only what happens
    from NOW on rather than a replay of history."""
    with _LOCK:
        return _SEQ


async def sse_stream(poll_s: float = 0.25, project: str | None = None,
                     since: int | None = None):
    """Async generator for StreamingResponse (text/event-stream).

    ``project`` scopes the stream. ``since`` defaults to the CURRENT sequence,
    so a fresh listener receives live events rather than a replay of the whole
    buffer -- replaying from 0 is what let a previous run's "complete" events
    repaint a project whose stages had actually skipped."""
    last = current_seq() if since is None else since
    # Hello so the client knows the stream is live.
    yield "event: hello\ndata: {}\n\n"
    while True:
        fresh = events_since(last, project)
        for e in fresh:
            last = max(last, e["seq"])
            yield f"id: {e['seq']}\ndata: {json.dumps(e)}\n\n"
        if not fresh:
            # Keep `last` moving even when everything was filtered out, or a
            # scoped listener re-scans the whole buffer forever.
            last = max(last, current_seq())
        await asyncio.sleep(poll_s)


if __name__ == "__main__":
    emit("extract", "start", "Scanning PDF")
    emit("extract", "info", "S-204: 3 tables, 41 marks", {"sheet": "S-204"})
    emit("extract", "done", "26 sheets", {"sheets": 26})
    evs = events_since(0)
    assert [e["kind"] for e in evs] == ["start", "info", "done"]
    assert events_since(evs[-1]["seq"]) == []
    emit("x", "info", "overflow test")
    assert events_since(0)[-1]["message"] == "overflow test"
    print("progress self-check OK:", len(events_since(0)), "events")
