"""Element list, devices, 3D scene, sheet renders, the S-201 review
overlay, the human review workspace (comments/dispositions/evidence), accuracy
metrics, run comparison, and the punch-list export."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from .. import config, element_registry, review, review_overlay, scene3d
from .common import load_artifact, make_router, project_pdf_path, save_artifact

router = make_router()

_UNSAFE_IN_PATH_PARAM = ("/", "\\", "..", ":", "\x00")


def safe_path_param(value: str, what: str) -> str:
    """A URL path parameter that will be joined onto a directory.

    Anything that could climb out of that directory is a 404, not a read:
    the caller asked for a name, and a name is all it may be."""
    if not value or any(u in value for u in _UNSAFE_IN_PATH_PARAM):
        raise HTTPException(status_code=404, detail=f"{what} '{value}' not found.")
    return value


def contained_project_pdf(source_file: str) -> Path:
    """Resolve an artifact-supplied PDF path inside the active project dir.

    ``source_file`` comes out of pdf_page_intelligence.json, which is written by
    the pipeline but is still just a file on disk — it is untrusted input to this
    handler, so the resolved path must stay under the project's artifact dir."""
    root = Path(config.ARTIFACT_DIR).resolve()
    path = Path(source_file)
    path = (path if path.is_absolute() else root / path).resolve()
    if not path.is_relative_to(root):
        raise HTTPException(
            status_code=404,
            detail=f"Source PDF '{source_file}' resolves outside the project directory.",
        )
    return path


@router.get("/api/elements")
def elements_get() -> JSONResponse:
    return JSONResponse(load_artifact("element_list"))


@router.get("/api/devices")
def devices_get() -> JSONResponse:
    """Physical-device registry (accuracy plan P1-P3)."""
    return JSONResponse(load_artifact("device_registry"))


@router.get("/api/scene3d")
def scene3d_get() -> JSONResponse:
    path = config.artifact_path("scene3d")
    if not path.exists():
        raw_revit = load_artifact("raw_revit")
        ai_path = config.artifact_path("ai_revit")
        ai_revit = json.loads(ai_path.read_text(encoding="utf-8")) if ai_path.exists() else None
        el_path = config.artifact_path("element_list")
        element_list = (
            json.loads(el_path.read_text(encoding="utf-8")) if el_path.exists() else None
        )
        save_artifact("scene3d", scene3d.build_scene(raw_revit, element_list, ai_revit))
    return JSONResponse(json.loads(path.read_text(encoding="utf-8")))


@router.get("/api/sheets/{sheet}/page.png")
def sheet_page_png(sheet: str, dpi: int = Query(default=200, ge=72, le=300)) -> FileResponse:
    """Render (and cache) any discovered sheet's page as a PNG."""
    sheet = safe_path_param(sheet, "Sheet").upper()
    cache = config.PAGES_DIR / f"{sheet}_{dpi}.png"
    if not cache.exists():
        ei = load_artifact("element_intelligence")
        entry = next(
            (s for s in ei.get("sheets", []) if s["sheet_number"] == sheet), None
        )
        if entry is None:
            raise HTTPException(status_code=404, detail=f"Sheet {sheet} not found.")
        import fitz

        with fitz.open(project_pdf_path()) as doc:
            page = doc[entry["page_index"]]
            pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
            pix.save(cache)
    return FileResponse(cache, media_type="image/png", filename=f"{sheet}_{dpi}.png")


@router.get("/api/sheets/primary")
def sheets_primary() -> JSONResponse:
    """The project's compare/primary sheet — the one whose registration lives
    in the GLOBAL calibration artifact (`GET /api/registration`); every other
    sheet has its own per-sheet calibration.

    Same field routers/pipeline.py resolves `compare_sheet` from, so the two
    can't drift. It is not always "S-201" (Dogwood: S-05, Country Side: S7),
    which is exactly why the frontend must not hardcode it."""
    path = config.artifact_path("pdf_page_intelligence")
    sheet = None
    if path.exists():
        sheet = json.loads(path.read_text(encoding="utf-8")).get("sheet_number")
    return JSONResponse({"sheet": sheet})


# ---------------------------------------------------------------------------
# S-201 Manual Review Overlay
# ---------------------------------------------------------------------------
@router.post("/api/review/build")
def review_build() -> JSONResponse:
    """Build review overlay with discrepancy boxes on S-201 page."""
    compare_report = load_artifact("compare")
    page_intel = load_artifact("pdf_page_intelligence")

    # Get page index and source PDF from page intelligence
    page_index = page_intel.get("page_index", 4)
    source_file = page_intel.get("source_file")
    if not source_file:
        raise HTTPException(
            status_code=409,
            detail="pdf_page_intelligence.json is missing 'source_file'. Run /api/pdf/page-intelligence first."
        )

    pdf_path = contained_project_pdf(source_file)
    if not pdf_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Source PDF not found at '{source_file}'"
        )

    result = review_overlay.build_and_save(
        compare_report,
        pdf_path,
        page_index,
        config.ARTIFACT_DIR,
    )
    return JSONResponse(result)


@router.get("/api/review/items")
def review_items_get() -> JSONResponse:
    """Get review items JSON (build on demand)."""
    items_path = config.artifact_path("review_items")
    if not items_path.exists():
        # Try building it
        compare_report = load_artifact("compare")
        page_intel = load_artifact("pdf_page_intelligence")
        page_index = page_intel.get("page_index", 4)
        source_file = page_intel.get("source_file")
        if source_file:
            pdf_path = contained_project_pdf(source_file)
            if pdf_path.exists():
                review_overlay.build_and_save(
                    compare_report,
                    pdf_path,
                    page_index,
                    config.ARTIFACT_DIR,
                )

    if not items_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Review items not found. Run POST /api/review/build first."
        )
    return JSONResponse(json.loads(items_path.read_text(encoding="utf-8")))


@router.get("/api/review/page.png")
def review_page_png() -> FileResponse:
    """Get rendered S-201 page PNG."""
    path = config.artifact_path("review_page")
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="Page PNG not found. Run POST /api/review/build first."
        )
    return FileResponse(path, media_type="image/png", filename="s201_review_page.png")


@router.get("/api/review/overlay.png")
def review_overlay_png() -> FileResponse:
    """Get annotated overlay PNG with boxes."""
    path = config.artifact_path("review_overlay_png")
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="Overlay PNG not found. Run POST /api/review/build first."
        )
    return FileResponse(path, media_type="image/png", filename="s201_review_overlay.png")


@router.get("/api/review/overlay.svg")
def review_overlay_svg() -> FileResponse:
    """Get annotated overlay SVG with boxes."""
    path = config.artifact_path("review_overlay_svg")
    if not path.exists():
        raise HTTPException(
            status_code=404,
            detail="Overlay SVG not found. Run POST /api/review/build first."
        )
    return FileResponse(path, media_type="image/svg+xml", filename="s201_review_overlay.svg")


# ---------------------------------------------------------------------------
# Human review workspace (comments + dispositions + evidence crops)
# ---------------------------------------------------------------------------
def _find_element(element_id: str) -> dict[str, Any]:
    el = load_artifact("element_list")
    for e in el.get("elements", []):
        if e.get("id") == element_id:
            return e
    raise HTTPException(status_code=404, detail=f"Element '{element_id}' not found.")


@router.get("/api/review/queue")
def review_queue() -> JSONResponse:
    return JSONResponse(review.build_queue(load_artifact("element_list")))


@router.post("/api/review/{element_id}/comment")
def review_comment(element_id: str, payload: dict[str, Any]) -> JSONResponse:
    comment = str(payload.get("comment", "")).strip()
    if not comment:
        raise HTTPException(status_code=400, detail="Empty comment.")
    element = _find_element(element_id)
    return JSONResponse(review.add_comment(element, comment, payload.get("author")))


@router.post("/api/review/{element_id}/disposition")
def review_disposition(element_id: str, payload: dict[str, Any]) -> JSONResponse:
    _find_element(element_id)  # 404 for unknown ids
    try:
        return JSONResponse(review.set_disposition(element_id, str(payload.get("disposition"))))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/review/{element_id}/analysis")
def review_analysis(element_id: str) -> JSONResponse:
    """Deterministic AI analysis of a mismatch (Human Review v2)."""
    try:
        return JSONResponse(review.analyze(
            element_id, load_artifact("element_list"),
            load_artifact("device_registry")))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/api/review/{element_id}/evaluate")
def review_evaluate(element_id: str, payload: dict[str, Any]) -> JSONResponse:
    """Judge the reviewer's logic against the deterministic facts."""
    comment = str(payload.get("comment", "")).strip()
    if not comment:
        raise HTTPException(status_code=400, detail="Empty comment.")
    analysis = review.analyze(
        element_id, load_artifact("element_list"),
        load_artifact("device_registry"))
    return JSONResponse({
        "analysis": analysis,
        "verdict": review.evaluate(element_id, comment, analysis),
    })


@router.post("/api/review/{element_id}/resolve")
def review_resolve(element_id: str, payload: dict[str, Any]) -> JSONResponse:
    """Human accept/reject. Accept propagates MATCH (with permanent
    resolution audit block) to every artifact: element list, device
    registry, 3D scene, punch list."""
    action = str(payload.get("action", "")).strip()
    comment = str(payload.get("comment", "")).strip() or "(no comment)"
    element_list = load_artifact("element_list")
    registry = load_artifact("device_registry")
    try:
        outcome = review.resolve(element_id, action, comment,
                                 element_list, registry,
                                 payload.get("author"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    element_list["counts"] = element_registry._counts(
        element_list.get("elements", []))
    save_artifact("element_list", element_list)
    save_artifact("device_registry", registry)
    raw_revit = load_artifact("raw_revit")
    ai_revit = load_artifact("ai_revit")
    save_artifact("scene3d",
                  scene3d.build_scene(raw_revit, element_list, ai_revit))
    return JSONResponse(outcome)


@router.get("/api/review/{element_id}/evidence.png")
def review_evidence(element_id: str):
    from fastapi.responses import Response

    e = _find_element(element_id)
    if e.get("page_index") is None:
        raise HTTPException(status_code=409, detail="Element has no page.")
    try:
        png = review.render_evidence_crop(
            project_pdf_path(), e["page_index"],
            e.get("pdf_point"), e.get("revit_point_transformed_to_pdf"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return Response(content=png, media_type="image/png")


@router.get("/api/metrics/accuracy")
def metrics_accuracy() -> JSONResponse:
    """Honest accuracy definition, shown in the UI:
    accuracy  = MATCH / evaluable   (evaluable = statuses where both sources
                had a chance to agree: MATCH, LOCATION_MISMATCH, PDF_ONLY,
                REVIT_ONLY, MARK_MISMATCH)
    coverage  = evaluable / total   (NO_REVIT_DATA / NOT_EVALUATED / SPEC_ONLY
                elements never had that chance — they are honesty flags)."""
    el = load_artifact("element_list")
    by_status = el["counts"]["by_status"]
    # R-21: MARK_MISMATCH is a disagreement both sources took part in — leaving
    # it out of the denominator flattered accuracy and made the headline number
    # disagree with the status table it sits next to.
    evaluable = sum(
        by_status.get(s, 0)
        for s in ("MATCH", "LOCATION_MISMATCH", "PDF_ONLY", "REVIT_ONLY",
                  "MARK_MISMATCH")
    )
    total = el["counts"]["total"]
    match = by_status.get("MATCH", 0)
    return JSONResponse({
        "project": config.active_project(),
        "total_elements": total,
        "evaluable": evaluable,
        "match": match,
        "accuracy": round(match / evaluable, 4) if evaluable else None,
        "coverage": round(evaluable / total, 4) if total else None,
        "by_status": by_status,
        "definition": "accuracy = MATCH / (MATCH+LOCATION_MISMATCH+PDF_ONLY+REVIT_ONLY"
                      "+MARK_MISMATCH); "
                      "coverage = evaluable / total. No fake matches: MATCH requires "
                      "verified per-sheet registration + distance gates.",
    })


def _device_key(category: str, d: dict[str, Any]) -> str:
    """R-29 diff key. Stable across runs as long as the pairing survives;
    unpaired devices fall back to their rounded model-space position."""
    target = d.get("target_id") or f"@{d.get('x', 0):.0f},{d.get('y', 0):.0f}"
    return f"{category}:{d.get('mark')}:{target}"


def _device_snapshot() -> list[dict[str, Any]] | None:
    """Compact per-device snapshot from the device registry, or None when the
    registry artifact doesn't exist (nothing to be honest about yet)."""
    if not config.artifact_path("device_registry").exists():
        return None
    registry = load_artifact("device_registry")
    return [
        {"key": _device_key(category, d), "status": d.get("status"),
         "distance_ft": d.get("distance_ft")}
        for category, c in (registry.get("categories") or {}).items()
        for d in c.get("devices", [])
    ]


@router.post("/api/runs/baseline")
def runs_baseline_save(label: str = Query(default="baseline")) -> JSONResponse:
    """Snapshot the current element list as the project's comparison baseline."""
    el = load_artifact("element_list")
    rows = el.get("rows") or el.get("elements") or []
    from datetime import datetime, timezone

    out = {
        "label": label,
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "rows": [{"category": r.get("category"), "status": r.get("status"),
                  "mark": r.get("mark"), "sheet": r.get("sheet")} for r in rows],
        # R-29: counts alone can't say WHICH device moved.
        "devices": _device_snapshot(),
    }
    (config.ARTIFACT_DIR / "run_baseline.json").write_text(
        json.dumps(out), encoding="utf-8")
    return JSONResponse({"saved": True, "label": label, "rows": len(out["rows"])})


@router.get("/api/runs/compare")
def runs_compare() -> JSONResponse:
    """Previous-run vs current-run comparison table (per category x status)."""
    base_path = config.ARTIFACT_DIR / "run_baseline.json"
    if not base_path.exists():
        raise HTTPException(status_code=404, detail="No run baseline saved. POST /api/runs/baseline first.")
    baseline = json.loads(base_path.read_text(encoding="utf-8"))
    el = load_artifact("element_list")
    cur_rows = el.get("rows") or el.get("elements") or []

    def table(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for r in rows:
            cat = r.get("category") or "?"
            st = r.get("status") or "?"
            out.setdefault(cat, {})[st] = out.setdefault(cat, {}).get(st, 0) + 1
        return out

    def totals(rows: list[dict[str, Any]]) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in rows:
            st = r.get("status") or "?"
            out[st] = out.get(st, 0) + 1
        return out

    # R-29: per-device diff. A baseline saved before this existed carries no
    # device snapshot — say so instead of inventing an empty diff.
    old_devices = baseline.get("devices")
    cur_devices = _device_snapshot()
    device_changes = device_added = device_removed = None
    device_note = None
    if old_devices is None:
        device_note = ("baseline predates per-device tracking — "
                       "save a new baseline")
    elif cur_devices is None:
        device_note = "no device registry in the current run"
    else:
        old = {d["key"]: d for d in old_devices}
        cur = {d["key"]: d for d in cur_devices}
        device_changes = [
            {"key": k, "old_status": old[k].get("status"),
             "new_status": cur[k].get("status"),
             "old_distance_ft": old[k].get("distance_ft"),
             "new_distance_ft": cur[k].get("distance_ft")}
            for k in sorted(old.keys() & cur.keys())
            if old[k].get("status") != cur[k].get("status")
        ]
        device_added = sorted(cur.keys() - old.keys())
        device_removed = sorted(old.keys() - cur.keys())

    return JSONResponse({
        "project": config.active_project(),
        "device_changes": device_changes,
        "device_added": device_added,
        "device_removed": device_removed,
        "device_note": device_note,
        "baseline": {"label": baseline.get("label"), "saved_at": baseline.get("saved_at"),
                     "totals": totals(baseline["rows"]), "by_category": table(baseline["rows"]),
                     "row_count": len(baseline["rows"])},
        "current": {"label": "current run", "totals": totals(cur_rows),
                    "by_category": table(cur_rows), "row_count": len(cur_rows)},
    })


@router.get("/api/export/punch-list.csv")
def export_punch_list() -> FileResponse:
    """Punch list of every actionable non-MATCH element."""
    import csv

    element_list = load_artifact("element_list")
    review_data = review.load()
    comments_by_el: dict[str, list[str]] = {}
    for c in review_data["comments"]:
        comments_by_el.setdefault(c["element_id"], []).append(c["comment"])
    out = config.ARTIFACT_DIR / "punch_list.csv"
    skip = {"MATCH", "SPEC_ONLY", "NOT_EVALUATED"}
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        # R-22: the status is decided in model FEET by the device pass, so feet
        # is the primary distance column. distance_pdf_points is the frozen
        # per-sheet pipeline's number and is kept for audit — blank on rows the
        # device pass owns rather than shown as if it explained the verdict.
        writer.writerow(
            ["sheet", "category", "mark", "status", "distance_ft",
             "distance_pdf_points", "pdf_x", "pdf_y", "revit_ref", "reason",
             "reviewer_disposition", "reviewer_comments"]
        )
        for e in element_list.get("elements", []):
            if e["status"] in skip:
                continue
            p = e.get("pdf_point") or {}
            ref = e.get("revit_ref") or {}
            disp = review_data["dispositions"].get(e["id"], {}).get("disposition", "")
            writer.writerow(
                [e.get("sheet") or "", e["category"], e["mark"], e["status"],
                 e.get("distance_ft") if e.get("distance_ft") is not None else "",
                 e.get("distance_pdf_points")
                 if e.get("distance_pdf_points") is not None else "",
                 p.get("x") or "", p.get("y") or "",
                 ref.get("id") or "", (e.get("reason") or "")[:200],
                 disp, " | ".join(comments_by_el.get(e["id"], []))[:300]]
            )
    return FileResponse(out, media_type="text/csv", filename="punch_list.csv")
