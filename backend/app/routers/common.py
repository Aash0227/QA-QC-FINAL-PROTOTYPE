"""Shared router helpers: request-scoped ProjectContext + artifact I/O.

All routers register ``project_context`` as a route dependency (via
``make_router()``), so every request resolves and binds its target project
before the handler reads or writes any artifact — the read/write paths that
used to depend on ``config.set_active_project``'s global mutation now flow
through this one place (BUG-03)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import config

# BUG-02: sample inputs come from env, never a hardcoded personal path. Unset by
# default → the only real inputs are per-project uploads. Set QAQC_SAMPLE_PDF /
# QAQC_SAMPLE_REVIT_JSON locally to re-enable the demo convenience.
_sample_revit = os.environ.get("QAQC_SAMPLE_REVIT_JSON", "").strip()
_sample_pdf = os.environ.get("QAQC_SAMPLE_PDF", "").strip()
SAMPLE_REVIT_JSON = Path(_sample_revit) if _sample_revit else None
SAMPLE_PDF = Path(_sample_pdf) if _sample_pdf else None


async def project_context(request: Request) -> str:
    """Resolve + bind the target project for this request (BUG-03, full fix).

    Resolution order: ``X-Project`` header → ``?project=`` query → the persisted
    active-project preference. The existing frontend sends none of these, so it
    keeps hitting the active project unchanged. Binds the artifact dirs for the
    request WITHOUT rewriting the preference, so ``/api/projects/activate`` is a
    UI preference write only and is no longer required for other endpoints'
    correctness.

    Request-scoped via ``config._PROJECT_SLUG`` (a ContextVar): concurrent
    clients on different projects can't redirect each other's writes anymore.
    This dependency is ``async`` on purpose — the ContextVar is set in the
    request's own context, which Starlette then copies into the threadpool that
    runs the sync route handlers, so they observe this request's project. (Set
    from a sync dependency, the value would land in a throwaway threadpool
    context and never reach the handler.)"""
    slug = request.headers.get("X-Project") or request.query_params.get("project")
    slug = config.slugify(slug) if slug else config.active_project()
    config.bind_project(slug)
    return slug


def make_router() -> APIRouter:
    """An APIRouter with the request-scoped project context bound to every route."""
    return APIRouter(dependencies=[Depends(project_context)])


def save_artifact(key: str, data: dict[str, Any]) -> Path:
    path = config.artifact_path(key)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def load_artifact(key: str) -> dict[str, Any]:
    path = config.artifact_path(key)
    if not path.exists():
        raise HTTPException(
            status_code=409,
            detail=f"Required artifact '{config.ARTIFACT_FILES[key]}' not found. "
            "Run the prerequisite step first.",
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        # A torn or truncated write is not a server bug — tell the caller which
        # artifact to regenerate instead of 500ing on eleven endpoints.
        raise HTTPException(
            status_code=409,
            detail=f"Artifact '{config.ARTIFACT_FILES[key]}' exists but is not valid "
            f"JSON ({exc.msg} at line {exc.lineno}) — re-run the producing step.",
        ) from exc


def project_pdf_path() -> Path:
    """Active project PDF: uploaded manifest wins; optional env sample fallback."""
    manifest_path = config.artifact_path("project_manifest")
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        pdf = Path(manifest.get("pdf_path", ""))
        # is_file, not exists: Path("") == Path(".") and "." exists.
        if pdf.is_file():
            return pdf
    if SAMPLE_PDF and SAMPLE_PDF.is_file():
        return SAMPLE_PDF
    raise HTTPException(
        status_code=409,
        detail="No project PDF. POST /api/upload a PDF (and Revit JSON) first.",
    )
