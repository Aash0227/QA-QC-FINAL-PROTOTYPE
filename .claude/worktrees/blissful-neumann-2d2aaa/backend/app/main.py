"""FastAPI app assembly (production-plan §1 step 2).

main.py is now thin: it builds the app, installs the two cross-cutting
middlewares (optional bearer auth + live pipeline-progress stream), registers
the routers, and mounts the frontend. All endpoints live in ``app.routers.*``;
the per-request project resolution (BUG-03) lives in
``app.routers.common.project_context`` and is bound to every route.

The re-exports at the bottom keep the handful of functions the test-suite
imports as ``app.main.<name>`` working without touching the tests."""

from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import config, maintenance, progress
from .routers import (
    chat,
    elements,
    pipeline,
    projects,
    registration as registration_router,
    revit,
    system,
    workflow,
)
from .routers.common import load_artifact

# BUG-18: optional bearer auth. OFF by default (localhost dev) — set
# QAQC_AUTH_TOKEN to require `Authorization: Bearer <token>` on every /api/
# route (health stays open for probes). Gives non-local deployments a real
# gate instead of relying solely on the bind address.
AUTH_TOKEN = os.environ.get("QAQC_AUTH_TOKEN", "").strip()

# Pipeline step endpoints instrumented for the live progress stream.
STEP_BY_PATH = {
    "/api/upload": "upload",
    "/api/revit/ai-convert": "revit_convert",
    "/api/pdf/page-intelligence": "pdf_intelligence",
    "/api/pdf/ai-convert": "pdf_convert",
    "/api/registration/auto-holdown": "ransac",
    "/api/compare/ai": "compare",
    "/api/elements/extract": "extract",
    "/api/elements/match": "match",
    "/api/review/build": "review",
}


def _step_headline(step: str) -> str:
    """One-line real result summary read from the step's fresh artifact."""
    try:
        if step == "pdf_intelligence":
            d = load_artifact("pdf_page_intelligence")
            if d.get("error"):
                return d["error"]
            return f"{d['summary']['total']} hold-downs on {d.get('sheet_number')}"
        if step == "ransac":
            d = load_artifact("registration")
            r = d.get("ransac", {})
            return (f"{r.get('inlier_pair_count', '?')} inliers, "
                    f"scale {d.get('transform', {}).get('scale', '?')}")
        if step == "compare":
            d = load_artifact("compare")
            v = d.get("summary", {}).get("verdict_counts", {})
            return ", ".join(f"{n} {k}" for k, n in v.items() if n)
        if step == "extract":
            d = load_artifact("element_intelligence")
            s = d.get("summary", {})
            marks = ", ".join(f"{n} {k}" for k, n in s.get("marks_by_category", {}).items())
            return f"{s.get('sheet_count')} sheets · {marks}"
        if step == "match":
            d = load_artifact("element_list")
            v = d.get("counts", {}).get("by_status", {})
            return ", ".join(f"{n} {k}" for k, n in sorted(v.items()))
        if step == "revit_convert":
            d = load_artifact("ai_revit")
            return f"{len(d.get('canonical_holdown_assemblies', []))} canonical assemblies"
        if step == "upload":
            d = load_artifact("project_manifest")
            return f"project '{d.get('project')}' · {d.get('page_count')} pages"
    except Exception:
        pass
    return "completed"


def create_app() -> FastAPI:
    # §10 hardening: rotating log file + evidence-crop GC, once at boot.
    maintenance.run_startup()
    app = FastAPI(title=config.PROTOTYPE_NAME, version=config.PROTOTYPE_VERSION)

    @app.middleware("http")
    async def _require_token(request, call_next):
        if AUTH_TOKEN and request.url.path.startswith("/api/") \
                and request.url.path != "/api/health":
            header = request.headers.get("authorization", "")
            # ?token= is accepted because EventSource (SSE), <img> evidence crops,
            # and window.open exports cannot set an Authorization header.
            supplied = header.removeprefix("Bearer ").strip() \
                or request.query_params.get("token", "")
            if not hmac.compare_digest(supplied, AUTH_TOKEN):
                from fastapi.responses import JSONResponse as _JR
                return _JR(status_code=401, content={"detail": "Unauthorized."})
        return await call_next(request)

    @app.middleware("http")
    async def _pipeline_progress_middleware(request, call_next):
        step = STEP_BY_PATH.get(request.url.path) if request.method == "POST" else None
        if step:
            progress.emit(step, "start", "running…")
        try:
            response = await call_next(request)
        except Exception:
            if step:
                progress.emit(step, "error", "failed with an internal error")
            raise
        if step:
            if response.status_code < 400:
                progress.emit(step, "done", _step_headline(step))
            else:
                progress.emit(step, "error", f"HTTP {response.status_code}")
        return response

    for module in (system, projects, pipeline, elements, registration_router,
                   workflow, revit, chat):
        app.include_router(module.router)

    # Frontend mounted last so /api/* wins.
    if config.FRONTEND_DIR.exists():
        app.mount("/", StaticFiles(directory=str(config.FRONTEND_DIR), html=True),
                  name="frontend")
    return app


app = create_app()


# ---------------------------------------------------------------------------
# Re-exports: the test-suite imports these as ``app.main.<name>`` and calls the
# handlers directly (no TestClient). Keeping thin aliases here means the split
# needs zero test edits.
# ---------------------------------------------------------------------------
benchmark_workflow_advance = workflow.benchmark_workflow_advance
benchmark_workflow_stamp = workflow.benchmark_workflow_stamp
benchmark_workflow_reset = workflow.benchmark_workflow_reset
_stamp_pdf_with_proposal = workflow._stamp_pdf_with_proposal
_maybe_auto_advance_export = workflow._maybe_auto_advance_export
benchmark_workflow_place_markers = revit.benchmark_workflow_place_markers

__all__ = ["app", "create_app"]
