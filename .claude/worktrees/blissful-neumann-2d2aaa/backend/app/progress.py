"""In-memory pipeline progress bus + SSE stream.

Step endpoints (main.py) and the extraction loop emit real signals — pages
scanned, tables found, inliers, verdict counts — and the pipeline UI streams
them live. Honest by construction: events describe what actually happened;
frozen modules are not instrumented, so their steps report start + an
artifact-derived summary at the end.

Ring buffer, no persistence: progress is a live view, artifacts remain the
audit trail.
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
        with _LOCK:
            _SEQ += 1
            _EVENTS.append(
                {
                    "seq": _SEQ,
                    "ts": time.time(),
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


def events_since(seq: int) -> list[dict[str, Any]]:
    with _LOCK:
        return [e for e in _EVENTS if e["seq"] > seq]


async def sse_stream(poll_s: float = 0.25):
    """Async generator for StreamingResponse (text/event-stream)."""
    last = 0
    # Send a hello so the client knows the stream is live.
    yield "event: hello\ndata: {}\n\n"
    while True:
        fresh = events_since(last)
        for e in fresh:
            last = e["seq"]
            yield f"id: {e['seq']}\ndata: {json.dumps(e)}\n\n"
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
