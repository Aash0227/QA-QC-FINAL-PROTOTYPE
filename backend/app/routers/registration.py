"""Coordinate registration: manual/RANSAC calibration, control points,
2-benchmark registration, scope diagnostics. The frozen math modules
(registration, ransac_holdown, benchmarks) are called untouched — this layer
only wires artifacts to them."""

from __future__ import annotations

import json
from typing import Any

from fastapi import Body, HTTPException
from fastapi.responses import JSONResponse

from .. import (
    benchmark_workflow,
    config,
    control_points,
    phase_summary,
    ransac_holdown,
    registration as registration_mod,
)
from .common import load_artifact, make_router, project_pdf_path, save_artifact

router = make_router()


@router.post("/api/registration/manual")
async def registration_manual(payload: dict[str, Any]) -> JSONResponse:
    point_pairs = payload.get("point_pairs") if isinstance(payload, dict) else None
    if not isinstance(point_pairs, list):
        raise HTTPException(
            status_code=400,
            detail="Body must be {\"calibration_source\":..,\"point_pairs\":[{\"id\":..,\"label\":..,"
            "\"pdf_point\":{x,y},\"revit_point\":{x,y}}, ...],\"validation_pairs\":[...]}.",
        )
    calibration_source = payload.get("calibration_source")
    validation_pairs = payload.get("validation_pairs")
    if validation_pairs is not None and not isinstance(validation_pairs, list):
        raise HTTPException(status_code=400, detail="validation_pairs must be a list when provided.")
    calibration = registration_mod.compute_calibration(
        point_pairs,
        calibration_source=calibration_source,
        validation_pairs=validation_pairs,
    )
    registration_mod.save_calibration(calibration)
    registration_mod.save_registration_report(calibration)
    return JSONResponse(calibration)


@router.get("/api/registration")
def registration_get() -> JSONResponse:
    calibration = registration_mod.load_calibration()
    return JSONResponse(
        {
            "present": calibration is not None,
            "status": registration_mod.registration_status(calibration),
            "calibration_source": registration_mod.calibration_source(calibration),
            "match_allowed": registration_mod.registration_usable(calibration),
            "calibration": calibration,
        }
    )


def _primary_sheet() -> str | None:
    """The project's compare sheet — same field routers/pipeline.py and
    /api/sheets/primary read, so the three cannot drift."""
    path = config.artifact_path("pdf_page_intelligence")
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("sheet_number")
    except json.JSONDecodeError:
        return None


@router.get("/api/registration/sheet/{sheet}")
def registration_sheet_get(sheet: str) -> JSONResponse:
    """Per-sheet calibration, in the SAME shape as /api/registration.

    The frontend's measure tool asks this for every non-primary sheet; the
    route simply did not exist, so every sheet read as "scale unverified".
    The primary/compare sheet has no per-sheet artifact — its verified
    transform IS the global calibration (see pipeline._sheet_calibration)."""
    path = config.sheet_calibration_path(sheet)
    calibration = None
    if path.exists():
        try:
            calibration = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            calibration = None
    primary = _primary_sheet()
    if calibration is None and primary and sheet.strip().upper() == primary.strip().upper():
        calibration = registration_mod.load_calibration()
    if calibration is None:
        raise HTTPException(
            status_code=404,
            detail=f"No registration calibration for sheet '{sheet}'. Sheets are "
                   f"registered by /api/elements/match; the primary sheet "
                   f"({primary or 'unknown'}) uses GET /api/registration.",
        )
    return JSONResponse(
        {
            "present": True,
            "sheet": sheet,
            "status": registration_mod.registration_status(calibration),
            "calibration_source": registration_mod.calibration_source(calibration),
            "match_allowed": registration_mod.registration_usable(calibration),
            "calibration": calibration,
        }
    )


@router.delete("/api/registration")
def registration_delete() -> JSONResponse:
    deleted = registration_mod.delete_calibration()
    registration_mod.save_registration_report(None)
    return JSONResponse({"deleted": deleted})


@router.post("/api/revit/control-points")
def revit_control_points_rebuild() -> JSONResponse:
    raw = load_artifact("raw_revit")
    payload = control_points.extract_revit_control_points(raw)
    save_artifact("revit_control_points", payload)
    return JSONResponse(payload)


@router.get("/api/revit/control-points")
def revit_control_points_get() -> JSONResponse:
    path = config.artifact_path("revit_control_points")
    if not path.exists():
        return JSONResponse(
            {"present": False, "points": [], "warnings": ["Run /api/revit/control-points (POST) first."]}
        )
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))


@router.post("/api/pdf/control-points")
def pdf_control_points_save(payload: dict[str, Any] = Body(...)) -> JSONResponse:
    if not isinstance(payload, dict) or not isinstance(payload.get("points"), list):
        raise HTTPException(
            status_code=400,
            detail='Body must be {"points":[{"id":..,"label":..,"point":{"x":..,"y":..}}], '
                   '"page_index":?, "sheet_number":?}.',
        )
    sheet = payload.get("sheet_number") or _primary_sheet()
    saved = control_points.save_pdf_control_points(
        payload["points"],
        sheet_number=sheet,
        page_index=payload.get("page_index"),
    )
    return JSONResponse(saved)


@router.get("/api/pdf/control-points")
def pdf_control_points_get() -> JSONResponse:
    return JSONResponse(control_points.load_or_init_pdf_control_points())


@router.post("/api/registration/auto-grid")
def registration_auto_grid(
    payload: dict[str, Any] | None = Body(default=None),
) -> JSONResponse:
    raw = load_artifact("raw_revit")
    pdf_cp = control_points.load_or_init_pdf_control_points()
    validation = (payload or {}).get("validation_pairs") if isinstance(payload, dict) else None
    result = control_points.auto_calibrate_from_grids(
        raw, pdf_cp, validation_pairs=validation
    )
    return JSONResponse(result)


@router.post("/api/registration/auto-holdown")
def registration_auto_holdown(
    payload: dict[str, Any] | None = Body(default=None),
) -> JSONResponse:
    """Mark-constrained RANSAC: derive Revit->PDF similarity from hold-down centers."""
    ai_revit = load_artifact("ai_revit")
    ai_pdf = load_artifact("ai_pdf")
    threshold = (payload or {}).get("distance_threshold_pt", 16.0) if isinstance(payload, dict) else 16.0
    iterations = (payload or {}).get("iterations", 4000) if isinstance(payload, dict) else 4000
    result = ransac_holdown.ransac_calibrate(
        ai_revit, ai_pdf,
        distance_threshold_pt=float(threshold),
        iterations=int(iterations),
    )
    # Summarise the calibration this run produced — the RANSAC response wraps it
    # (and may decline to save it when a benchmark solve outranks it).
    phase_summary.record(
        "registration",
        phase_summary.registration(result.get("calibration")
                                   or registration_mod.load_calibration()),
    )
    return JSONResponse(result)


@router.post("/api/pdf/benchmarks")
def pdf_benchmarks_extract(
    payload: dict[str, Any] | None = Body(default=None),
) -> JSONResponse:
    """Find BM-1/BM-2 stamps on the uploaded PDF, save pdf_benchmarks.json."""
    body = payload if isinstance(payload, dict) else {}
    page_index = body.get("page_index")
    result = benchmark_workflow.extract_pdf_benchmarks(
        project_pdf_path(),
        page_index=int(page_index) if page_index is not None else None,
    )
    save_artifact("pdf_benchmarks", result)
    return JSONResponse(result)


@router.get("/api/pdf/benchmarks")
def pdf_benchmarks_get() -> JSONResponse:
    path = config.artifact_path("pdf_benchmarks")
    if not path.exists():
        return JSONResponse(
            {"present": False, "benchmarks": [],
             "warnings": ["Run /api/pdf/benchmarks (POST) first."]}
        )
    return JSONResponse({"present": True,
                         **json.loads(path.read_text(encoding="utf-8"))})


@router.post("/api/registration/benchmarks")
def registration_benchmarks(
    payload: dict[str, Any] | None = Body(default=None),
) -> JSONResponse:
    """Join PDF + Revit benchmarks by mark -> exact 2-point calibration.

    Saves the calibration ONLY when its quality gate allows matching — a
    failed benchmark solve must never overwrite a working calibration.
    """
    body = payload if isinstance(payload, dict) else {}
    pdf_bm = load_artifact("pdf_benchmarks")
    if pdf_bm.get("error"):
        raise HTTPException(status_code=409, detail=pdf_bm["error"])
    revit_bm = load_artifact("raw_revit").get("benchmarks") or []
    if not revit_bm:
        raise HTTPException(
            status_code=409,
            detail="Revit export has no benchmarks — place the benchmark "
            "family (Mark BM-1/BM-2) at the stamped grid intersections and "
            "re-export (schema v3.1+).",
        )

    # Chirality evidence: the hold-down detection clouds, best effort.
    chirality_evidence = None
    try:
        rev_pts = [p for pts in ransac_holdown._gather(
            load_artifact("ai_revit").get("canonical_holdown_assemblies", []),
            "pdf_mark_candidate").values() for p in pts]
        pdf_pts = [p for pts in ransac_holdown._gather(
            load_artifact("ai_pdf").get("holdowns", []),
            "normalized_mark").values() for p in pts]
        if len(rev_pts) >= 3 and len(pdf_pts) >= 3:
            chirality_evidence = {"revit_points": rev_pts, "pdf_points": pdf_pts}
    except HTTPException:
        pass  # clouds not built yet — calibration still valid, just uncrosschecked

    calibration = registration_mod.compute_calibration_from_benchmarks(
        pdf_bm.get("benchmarks", []),
        revit_bm,
        expected_scale_pt_per_ft=body.get("expected_scale_pt_per_ft", 18.0),
        assume_reflection=bool(body.get("assume_reflection", True)),
        validation_pairs=body.get("validation_pairs"),
        chirality_evidence=chirality_evidence,
    )
    saved = registration_mod.registration_usable(calibration)
    if saved:
        registration_mod.save_calibration(calibration)
        registration_mod.save_registration_report(calibration)
    phase_summary.record("registration", phase_summary.registration(calibration))
    return JSONResponse({"saved": saved, **calibration})


@router.post("/api/revit/scope-diagnostics")
def revit_scope_diagnostics_rebuild() -> JSONResponse:
    raw = load_artifact("raw_revit")
    ai = load_artifact("ai_revit")
    diag = control_points.save_scope_diagnostics(raw, ai)
    return JSONResponse(diag)


@router.get("/api/revit/scope-diagnostics")
def revit_scope_diagnostics_get() -> JSONResponse:
    path = config.artifact_path("revit_scope_diagnostics")
    if not path.exists():
        return JSONResponse(
            {"present": False, "warnings": ["Run /api/revit/scope-diagnostics (POST) first."]}
        )
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))



