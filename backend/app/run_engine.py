"""Background pipeline runner with persisted run state and duplicate-run lock.

One run per project at a time. Run state lives in ``run_state.json`` in the
workspace so a browser refresh / disconnect never loses it. SSE events are
emitted via progress.py for every stage transition (start/done/error/skip).

ponytail: in-memory lock + persisted in-flight flag, no DB, single user.
"""
from __future__ import annotations

import logging

import json
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config, progress, stage_graph


# ---------------------------------------------------------------------------
# In-memory lock registry (per project) so concurrent requests can't clash.
# ---------------------------------------------------------------------------
_RUN_LOCKS: dict[str, threading.Lock] = {}
_ACTIVE_THREADS: dict[str, threading.Thread] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_state_path() -> Path:
    return config.artifact_path("project_manifest").parent / "run_state.json"


def _read_state() -> dict[str, Any] | None:
    p = _run_state_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None  # torn file on crash — treat as absent


def _write_state(state: dict[str, Any]) -> None:
    """Atomically persist the run state.

    On Windows, os.replace fails with PermissionError (WinError 5) if another
    handle has the destination open — and the UI polls GET /api/pipeline/run
    every few hundred milliseconds while the runner thread writes after every
    stage transition, so the two collide regularly. Unhandled, the exception
    propagated out of the runner and the whole run was marked failed because a
    *status write* lost a race, which is how a healthy run could report
    failure. Retry briefly, then give up quietly: the next transition writes
    again, and losing one intermediate status update is not worth failing a
    run over."""
    p = _run_state_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    for attempt in range(8):
        try:
            tmp.replace(p)
            return
        except PermissionError:
            if attempt < 7:
                time.sleep(0.02 * (attempt + 1))
                continue
            # Out of retries. Swallowing is only safe when a previous state is
            # already on disk -- readers then see slightly stale status instead
            # of nothing. If this is the FIRST write there is no fallback: the
            # run would appear never to have started (GET returns 404), so the
            # failure must surface rather than be hidden.
            if not p.exists():
                raise
            logging.getLogger(__name__).debug(
                "run_state update lost the write race; keeping previous state")
            return


def run_state() -> dict[str, Any] | None:
    """Current/last persisted run state for the bound project."""
    return _read_state()


def start_run(*, force: bool = False) -> dict[str, Any]:
    """Begin a new pipeline run in a background thread. Returns the initial
    run-state payload (202) or raises HTTPException(409) if a run is already
    in flight for this project.

    The caller must have already bound the project via ContextVar.
    """
    slug = config._PROJECT_SLUG.get()
    if not slug:
        raise RuntimeError("No project bound — call inside a request or bind_project()")

    # Check persisted in-flight
    existing = _read_state()
    if existing and existing.get("status") == "running":
        # If the thread died (server restart), mark it stale
        alive = slug in _ACTIVE_THREADS and _ACTIVE_THREADS[slug].is_alive()
        if alive:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=409,
                detail={"message": "A run is already in progress for this project.",
                        "run_id": existing["run_id"]})
        # Stale run — mark failed so a new one can start
        existing["status"] = "failed"
        existing["completed_at"] = _now_iso()
        if not existing.get("error"):
            existing["error"] = "Server restarted while run was in flight."
        _write_state(existing)

    if force and existing:
        # Force: invalidate ALL stage outputs so nothing is stale
        for key, _title, _prereqs, output in stage_graph.STAGES:
            p = config.artifact_path(output)
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    initial = {
        "run_id": run_id,
        "project": slug,
        "status": "running",
        "started_at": _now_iso(),
        "completed_at": None,
        "force": force,
        "stages": stage_graph.stages_payload(),
        "error": None,
        "next_action": {"kind": "in_progress", "message": "Pipeline starting…"},
    }
    _write_state(initial)

    # Spawn background runner
    lock = _RUN_LOCKS.setdefault(slug, threading.Lock())
    t = threading.Thread(target=_run_in_thread, args=(slug, run_id, lock, force), daemon=True)
    _RUN_LOCKS[slug] = lock  # keep ref
    _ACTIVE_THREADS[slug] = t
    t.start()

    return initial


def _run_in_thread(slug: str, run_id: str, lock: threading.Lock, force: bool) -> None:
    """Execute all runnable stages in dependency order, persisting state + SSE."""
    from .routers import pipeline as _pipe_router
    from .routers import registration as _reg_router
    import asyncio as _asyncio

    try:
        config._PROJECT_SLUG.set(slug)
        state = _read_state()
        if not state or state.get("run_id") != run_id:
            return  # superseded

        stage_map = {s["key"]: s for s in state["stages"]}

        for key, title, prereqs, output_artifact in stage_graph.STAGES:
            # Re-read state in case external changes invalidated
            state = _read_state()
            if not state or state.get("status") != "running":
                break
            si = state["stages"][next(i for i, s in enumerate(state["stages"]) if s["key"] == key)]

            if stage_graph.artifact_present((output_artifact,)):
                si["status"] = "done"
                si["reason"] = "already run"
                progress.emit(key, "skip", f"{title} — already run")
                _write_state(state)
                continue

            if not stage_graph.artifact_present(prereqs):
                si["status"] = "skipped"
                si["reason"] = f"waiting on: {', '.join(prereqs) or 'PDF upload'}"
                progress.emit(key, "skip", f"{title} — {si['reason']}")
                _write_state(state)
                continue

            si["status"] = "running"
            si["started_at"] = _now_iso()
            progress.emit(key, "start", f"{title} started")
            _write_state(state)

            start = time.monotonic()
            try:
                _exec_stage(key)
                dur = round(time.monotonic() - start, 1)
                # A stage is only "done" if it actually produced its declared
                # output. Several handlers return HTTP 200 while reporting
                # failure in the body -- ransac_holdown returns ok:false when
                # the solve fails and routers/registration.py passes that
                # through as 200 -- so a stage could be marked done having
                # saved no calibration. The next stage then skips "waiting on:
                # registration", pointing the user at the wrong stage. Checking
                # the artifact closes every such path at once, whatever the
                # handler chose to return.
                if not stage_graph.artifact_present((output_artifact,)):
                    si["status"] = "failed"
                    si["duration_s"] = dur
                    si["error"] = (
                        f"{title} reported success but produced no "
                        f"{output_artifact!r}. Its inputs were present, so this "
                        "is a failure inside the stage, not a missing "
                        "prerequisite.")
                    progress.emit(key, "error", f"{title} failed — no {output_artifact} written")
                    stage_graph.invalidate_downstream(key)
                else:
                    si["status"] = "done"
                    si["duration_s"] = dur
                    progress.emit(key, "done", f"{title} complete ({dur}s)")
            except Exception as exc:  # noqa: BLE001
                from fastapi import HTTPException
                dur = round(time.monotonic() - start, 1)
                if isinstance(exc, HTTPException) and exc.status_code in (404, 409):
                    # Missing input = skip, not failure — the run isn't broken,
                    # the project just isn't ready for this stage yet.
                    si["status"] = "skipped"
                    si["reason"] = exc.detail if isinstance(exc.detail, str) else "input missing"
                    progress.emit(key, "skip", f"{title} — {si['reason']}")
                else:
                    si["status"] = "failed"
                    si["error"] = f"{type(exc).__name__}: {exc}"
                    si["duration_s"] = dur
                    progress.emit(key, "error", f"{title} failed — {si['error']}")
                    # Invalidate downstream — this stage failed, its output is junk
                    stage_graph.invalidate_downstream(key)
            si["completed_at"] = _now_iso()
            _write_state(state)

        # Post-run: set completion + next_action
        state = _read_state()
        if state and state.get("status") == "running":
            # "completed" used to mean only "the thread finished". A run whose
            # answer-producing stages all SKIPPED for missing inputs reported
            # success, so a project that could never produce a result looked
            # finished. Distinguish the three real outcomes:
            #   failed    - a stage broke
            #   blocked   - nothing broke, but the run produced no element_list
            #               because inputs were missing (the honest state for a
            #               project with no Revit export)
            #   completed - the run produced its final artifact
            stages = state.get("stages") or []
            any_failed = any(st.get("status") == "failed" for st in stages)
            produced = stage_graph.artifact_present(("element_list",))
            if any_failed:
                state["status"] = "failed"
            elif produced:
                state["status"] = "completed"
            else:
                state["status"] = "blocked"
            state["skipped_stages"] = [
                st.get("key") for st in stages if st.get("status") == "skipped"
            ]
            state["completed_at"] = _now_iso()
            if stage_graph.artifact_present(("element_list",)):
                state["next_action"] = {"kind": "review", "message": "QA/QC complete — review the results."}
            elif not stage_graph.artifact_present(("raw_revit",)):
                state["next_action"] = {"kind": "upload_revit", "message": "Export + upload the Revit JSON."}
            else:
                failed = any(s["status"] == "failed" for s in state["stages"])
                state["next_action"] = {"kind": "retry" if failed else "review",
                                        "message": "Some steps failed — retry." if failed else "QA/QC complete."}
            _write_state(state)
    except Exception as exc:  # noqa: BLE001
        state = _read_state()
        if state:
            state["status"] = "failed"
            state["error"] = f"{type(exc).__name__}: {exc}"
            state["completed_at"] = _now_iso()
            _write_state(state)
        progress.emit("run", "error", f"Pipeline runner crashed: {exc}")
    finally:
        _ACTIVE_THREADS.pop(slug, None)


def _exec_stage(key: str) -> None:
    """Call the existing handler function for one stage (must be inside
    a bound project context). Reuses the same handlers as the old
    pipeline_run — these are the single-step POST endpoint functions."""
    from .routers import pipeline as _r
    from .routers import registration as _reg
    import asyncio

    if key == "extract":
        _r.elements_extract()
    elif key == "revit_convert":
        asyncio.run(_r.revit_ai_convert(use_saved=True))
    elif key == "pdf_intelligence":
        _r.pdf_page_intelligence(use_saved=True)  # sync (def) — runs in bg thread
    elif key == "pdf_convert":
        _r.pdf_ai_convert()
    elif key == "ransac":
        _reg.registration_auto_holdown()
    elif key == "compare":
        _r.compare_ai()
    elif key == "match":
        _r.elements_match()
    else:
        raise ValueError(f"unknown stage {key}")
    _narrate_stage(key)


# Stage -> (artifact key, phase_summary function). Only stages whose summary
# is not already recorded by their own handler appear here: `ransac` and
# `match` narrate themselves inside routers/registration.py and
# routers/pipeline.py, where they hold richer in-memory state than the saved
# artifact carries.
_STAGE_NARRATION: dict[str, tuple[str, str]] = {
    "extract": ("element_intelligence", "extract"),
    "revit_convert": ("ai_revit", "revit_convert"),
    "pdf_intelligence": ("pdf_page_intelligence", "pdf_intelligence"),
    "pdf_convert": ("ai_pdf", "pdf_convert"),
    "compare": ("compare", "compare"),
}


def _narrate_stage(key: str) -> None:
    """Emit this stage's plain-English summary onto the progress bus.

    Built from the artifact the stage just wrote, so the text can never
    describe something that did not happen. Never raises: commentary must not
    be able to fail a pipeline that otherwise succeeded."""
    entry = _STAGE_NARRATION.get(key)
    if not entry:
        return
    artifact_key, fn_name = entry
    try:
        import json

        from . import config, phase_summary

        path = config.artifact_path(artifact_key)
        if not path.exists():
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        phase_summary.record(key, getattr(phase_summary, fn_name)(payload))
    except Exception:  # noqa: BLE001 — commentary is best-effort by design
        logging.getLogger(__name__).debug(
            "stage narration failed for %s", key, exc_info=True)