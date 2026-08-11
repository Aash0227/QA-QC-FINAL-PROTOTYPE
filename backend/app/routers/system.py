"""App-level meta endpoints: health probe, artifact listing/serving, and the
OpenRouter call log."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastapi.responses import FileResponse

from .. import config, openrouter, registration
from .common import SAMPLE_PDF, SAMPLE_REVIT_JSON, make_router

router = make_router()


@router.get("/api/health")
def health() -> dict[str, Any]:
    artifacts = {
        name: (config.ARTIFACT_DIR / name).exists()
        for name in config.ARTIFACT_FILES.values()
    }
    return {
        "status": "ok",
        "prototype": config.PROTOTYPE_NAME,
        "version": config.PROTOTYPE_VERSION,
        "artifact_dir": str(config.ARTIFACT_DIR),
        "artifacts_present": artifacts,
        "openrouter": openrouter.call_status_summary(),
        "registration": {
            "status": registration.registration_status(registration.load_calibration()),
            "calibration_source": registration.calibration_source(registration.load_calibration()),
            "match_allowed": registration.registration_usable(registration.load_calibration()),
            "transform_direction": registration.TRANSFORM_DIRECTION,
        },
        "sample_inputs": {
            "revit_json": str(SAMPLE_REVIT_JSON) if SAMPLE_REVIT_JSON else None,
            "revit_json_exists": bool(SAMPLE_REVIT_JSON and SAMPLE_REVIT_JSON.is_file()),
            "pdf": str(SAMPLE_PDF) if SAMPLE_PDF else None,
            "pdf_exists": bool(SAMPLE_PDF and SAMPLE_PDF.is_file()),
        },
    }


@router.get("/api/artifacts")
def list_artifacts() -> dict[str, Any]:
    items = []
    for name in config.ARTIFACT_FILES.values():
        p = config.ARTIFACT_DIR / name
        items.append(
            {
                "filename": name,
                "exists": p.exists(),
                "size_bytes": p.stat().st_size if p.exists() else 0,
                "url": f"/api/artifacts/{name}",
            }
        )
    return {"artifact_dir": str(config.ARTIFACT_DIR), "artifacts": items}


@router.get("/api/artifacts/{filename}")
def get_artifact(filename: str) -> FileResponse:
    # Guard against path traversal; only serve from the artifact directory.
    safe = Path(filename).name
    path = config.ARTIFACT_DIR / safe
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Artifact '{safe}' not found.")
    media = "application/json" if safe.endswith(".json") else "application/octet-stream"
    return FileResponse(path, media_type=media, filename=safe)


@router.get("/api/openrouter/log")
def openrouter_log() -> dict[str, Any]:
    return {
        "summary": openrouter.call_status_summary(),
        "log": openrouter.read_call_log(),
    }
