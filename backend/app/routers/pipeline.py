"""Pipeline endpoints: Revit/PDF conversion, extraction, compare, match, the
live SSE progress stream, and the teach-memory store that feeds extraction.
Frozen math modules (compare, device_match) are called untouched; this layer
only orchestrates artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import Body, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse

from .. import compare as compare_mod
from .. import (
    config,
    control_points,
    device_match,
    element_detector,
    element_registry,
    leader_anchor,
    pdf_convert,
    pdf_intelligence,
    phase_summary,
    progress,
    registration,
    revit_convert,
    revit_v3_adapter,
    scene3d,
    teach,
    wall_match,
)
from .common import (
    SAMPLE_PDF,
    SAMPLE_REVIT_JSON,
    load_artifact,
    make_router,
    project_pdf_path,
    save_artifact,
)

router = make_router()

# Maximum upload size: 50 MB. Rejects oversized payloads before reading them
# into memory (file.size check) and after reading (len(content) check) as a
# defence-in-depth measure against clients that lie about Content-Length.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50MB


def _uploaded_pdf() -> Path:
    # Function (not module constant): ARTIFACT_DIR changes when the active
    # project switches, so the path must resolve at call time.
    return config.ARTIFACT_DIR / "uploaded_madera.pdf"


def _spec_map_with_fallback(ei: dict[str, Any] | None) -> dict[str, str]:
    """Schedule spec->mark map from parsed rows; when a layout defeats the
    row parser (e.g. Dogwood's 1-row mini schedule), re-read the table's own
    bbox region straight from the PDF geometry. Deterministic both ways."""
    mapping = revit_v3_adapter.spec_to_mark_map(ei)
    if not mapping and ei:
        try:
            mapping = revit_v3_adapter.spec_map_from_pdf_tables(
                ei, project_pdf_path())
        except Exception:
            mapping = {}
    return mapping


# ---------------------------------------------------------------------------
# AI Revit Convert
# ---------------------------------------------------------------------------
@router.post("/api/revit/ai-convert")
async def revit_ai_convert(
    file: UploadFile | None = File(default=None),
    use_sample: bool = Query(default=False),
    use_saved: bool = Query(default=False),
) -> JSONResponse:
    if use_saved:
        # Re-run conversion on the raw export saved by /api/upload.
        raw_json = load_artifact("raw_revit")
        source_file = "uploaded_revit_export.json"
        save_artifact("raw_revit", raw_json)
        if revit_v3_adapter.is_v3(raw_json):
            # v3 path: deterministic schedule-spec-driven assembly builder.
            # Marks come from the PDF hold-down schedule learned at Extract
            # time (element_intelligence) — data-driven, any client.
            ei_path = config.artifact_path("element_intelligence")
            ei = (json.loads(ei_path.read_text(encoding="utf-8"))
                  if ei_path.exists() else None)
            result = revit_v3_adapter.build_ai_revit(
                {"elements": raw_json.get("v3_elements", []),
                 "source_model": raw_json.get("source_file", ""),
                 "schema_version": raw_json.get("schema_version")},
                _spec_map_with_fallback(ei),
            )
        else:
            result = revit_convert.convert_revit(raw_json, source_file=source_file)
        save_artifact("ai_revit", result)
        save_artifact(
            "revit_scope_diagnostics", control_points.build_scope_diagnostics(raw_json, result)
        )
        save_artifact(
            "revit_control_points", control_points.extract_revit_control_points(raw_json)
        )
        return JSONResponse(result)
    if file is not None:
        if file.size and file.size > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File too large")
        raw_bytes = await file.read()
        if len(raw_bytes) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File too large")
        try:
            raw_json = json.loads(raw_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON upload: {exc}")
        source_file = file.filename or "uploaded_revit_export.json"
    elif use_sample:
        if not (SAMPLE_REVIT_JSON and SAMPLE_REVIT_JSON.is_file()):
            raise HTTPException(status_code=404, detail="No sample revit_export.json "
                "configured (set QAQC_SAMPLE_REVIT_JSON).")
        raw_json = json.loads(SAMPLE_REVIT_JSON.read_text(encoding="utf-8"))
        source_file = str(SAMPLE_REVIT_JSON)
    else:
        raise HTTPException(
            status_code=400, detail="Provide a file upload or set use_sample=true."
        )

    # v3 exports need adaptation here too, not only in /api/upload —
    # otherwise raw_revit is saved shapeless and every consumer breaks.
    if revit_v3_adapter.is_v3(raw_json):
        raw_json = revit_v3_adapter.adapt_raw(raw_json)
        save_artifact("raw_revit", raw_json)
        ei_path = config.artifact_path("element_intelligence")
        ei = (json.loads(ei_path.read_text(encoding="utf-8"))
              if ei_path.exists() else None)
        result = revit_v3_adapter.build_ai_revit(
            {"elements": raw_json.get("v3_elements", []),
             "source_model": raw_json.get("source_file", ""),
             "schema_version": raw_json.get("schema_version")},
            _spec_map_with_fallback(ei),
        )
        save_artifact("ai_revit", result)
        save_artifact("revit_scope_diagnostics",
                      control_points.build_scope_diagnostics(raw_json, result))
        save_artifact("revit_control_points",
                      control_points.extract_revit_control_points(raw_json))
        return JSONResponse(result)
    # 1) Save the raw export verbatim.
    save_artifact("raw_revit", raw_json)
    # 2-6) Analyse, learn patterns, group, output.
    result = revit_convert.convert_revit(raw_json, source_file=source_file)
    save_artifact("ai_revit", result)
    # Always refresh the standalone scope-diagnostics + revit-control-points artifacts.
    save_artifact(
        "revit_scope_diagnostics", control_points.build_scope_diagnostics(raw_json, result)
    )
    save_artifact(
        "revit_control_points", control_points.extract_revit_control_points(raw_json)
    )
    return JSONResponse(result)


# ---------------------------------------------------------------------------
# PDF Page Intelligence
# ---------------------------------------------------------------------------
@router.post("/api/pdf/page-intelligence")
async def pdf_page_intelligence(
    file: UploadFile | None = File(default=None),
    use_sample: bool = Query(default=False),
    use_saved: bool = Query(default=False),
) -> JSONResponse:
    if use_saved:
        result = pdf_intelligence.run_page_intelligence(project_pdf_path())
        source = "s201_focused"
        if result.get("error"):
            # Not an S-201/H1-H4 drawing set: derive sheet + mark family from
            # the generalized extraction instead (frozen path stays default).
            ei_path = config.artifact_path("element_intelligence")
            if ei_path.exists():
                from ..generic_page_intelligence import run_generic_page_intelligence

                ei = json.loads(ei_path.read_text(encoding="utf-8"))
                result = run_generic_page_intelligence(project_pdf_path(), ei)
                source = "generic"
        # Doc-21 #4: which detector actually produced this artifact. Additive
        # only — path SELECTION is unchanged; this just makes a garbage-in
        # result diagnosable after the fact.
        result["intelligence_source"] = source
        save_artifact("pdf_page_intelligence", result)
        return JSONResponse(result)
    if file is not None:
        if file.size and file.size > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File too large")
        pdf_bytes = await file.read()
        if len(pdf_bytes) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File too large")
        pdf_path = _uploaded_pdf()
        pdf_path.write_bytes(pdf_bytes)
    elif use_sample:
        if not (SAMPLE_PDF and SAMPLE_PDF.is_file()):
            raise HTTPException(status_code=404, detail="No sample PDF configured "
                "(set QAQC_SAMPLE_PDF).")
        pdf_path = SAMPLE_PDF
    else:
        raise HTTPException(
            status_code=400, detail="Provide a PDF upload or set use_sample=true."
        )

    result = pdf_intelligence.run_page_intelligence(pdf_path)
    # Direct-upload branch has no element_intelligence to fall back to, so the
    # frozen S-201 detector is always what ran here.
    result["intelligence_source"] = "s201_focused"
    save_artifact("pdf_page_intelligence", result)
    return JSONResponse(result)


# ---------------------------------------------------------------------------
# AI PDF Convert
# ---------------------------------------------------------------------------
@router.post("/api/pdf/ai-convert")
def pdf_ai_convert() -> JSONResponse:
    page_intel = load_artifact("pdf_page_intelligence")
    revit_memory: dict[str, Any] | None = None
    revit_path = config.artifact_path("ai_revit")
    if revit_path.exists():
        revit_memory = json.loads(revit_path.read_text(encoding="utf-8"))
    result = pdf_convert.convert_pdf(page_intel, revit_ai_memory=revit_memory)
    # Leader-dot anchor snap: holdown distances measure the device dot, not
    # wherever the drafter parked the label text (see leader_anchor.py).
    result = leader_anchor.snap_holdowns(result, project_pdf_path())
    save_artifact("ai_pdf", result)
    return JSONResponse(result)


# ---------------------------------------------------------------------------
# AI Compare
# ---------------------------------------------------------------------------
MIN_REFIT_PAIRS = 8


def _refit_and_recompare(
    ai_revit: dict[str, Any],
    ai_pdf: dict[str, Any],
    calibration: dict[str, Any] | None,
    report: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """A2: use the verified MATCH pairs as control points, re-fit the
    transform (anchor_verified) and compare once more. Accept ONLY if MATCH
    strictly increases and no pairing is lost — otherwise keep the original.
    Returns (best_report, refined_calibration_or_None)."""
    if not calibration:
        return report, None
    assemblies = {
        a.get("id"): a.get("center_point") or {}
        for a in ai_revit.get("canonical_holdown_assemblies", [])
    }
    pairs = []
    for row in report.get("final_verdicts", []):
        if row.get("verdict") != "MATCH":
            continue
        cp = assemblies.get(row.get("revit_assembly_id")) or {}
        pdf_pt = row.get("pdf_point") or {}
        if cp.get("x") is None or pdf_pt.get("x") is None:
            continue
        pairs.append({
            "id": row.get("pdf_holdown_id"),
            "revit_point": {"x": cp["x"], "y": cp["y"]},
            "pdf_point": {"x": pdf_pt["x"], "y": pdf_pt["y"]},
        })
    if len(pairs) < MIN_REFIT_PAIRS:
        return report, None
    refit = registration.compute_calibration(pairs, calibration_source="anchor_verified")
    if not registration.registration_usable(refit):
        return report, None
    report2 = compare_mod.compare(ai_revit, ai_pdf, calibration=refit)
    v1 = report.get("summary", {}).get("verdict_counts", {})
    v2 = report2.get("summary", {}).get("verdict_counts", {})
    if (v2.get("MATCH", 0) > v1.get("MATCH", 0)
            and v2.get("MATCH", 0) + v2.get("LOCATION_MISMATCH", 0)
            >= v1.get("MATCH", 0) + v1.get("LOCATION_MISMATCH", 0)):
        report2["registration_refinement"] = {
            "applied": True,
            "control_pairs": len(pairs),
            "match_before": v1.get("MATCH", 0),
            "match_after": v2.get("MATCH", 0),
            "note": "Transform re-fit from verified MATCH pairs (anchor_verified); "
                    "accepted because MATCH increased and no pairing was lost.",
        }
        return report2, refit
    return report, None


@router.post("/api/compare/ai")
def compare_ai(scope_level: bool | None = Query(default=None)) -> JSONResponse:
    # scope_level filters Revit assemblies to the foundation elevation band
    # before comparing (kills upper-level stacking noise). Default: AUTO —
    # on for v3 exports (trustworthy per-element elevations), off for legacy
    # v2 (Madera baseline preserved: forcing it costs 32 -> 29 MATCH there).
    ai_revit = load_artifact("ai_revit")
    ai_pdf = load_artifact("ai_pdf")
    scope_note = None
    if scope_level is None:
        raw_path = config.artifact_path("raw_revit")
        scope_level = raw_path.exists() and revit_v3_adapter.is_v3(
            json.loads(raw_path.read_text(encoding="utf-8"))
        )
    if scope_level:
        # Evidence-based level scoping: the compared sheet is one floor plan,
        # but a whole-model export stacks hold-downs from every level at the
        # same x,y. Keep only the lowest elevation band (the foundation level
        # the comparison_view names). compare.py itself stays untouched.
        raw_path = config.artifact_path("raw_revit")
        if raw_path.exists():
            raw = json.loads(raw_path.read_text(encoding="utf-8"))
            ai_revit, scope_note = _scope_assemblies_to_foundation(ai_revit, raw)
    calibration = registration.load_calibration()
    # Keep the registration report in sync with the calibration used for this compare.
    registration.save_registration_report(calibration)
    result = compare_mod.compare(ai_revit, ai_pdf, calibration=calibration)
    # A2: refine the transform from verified MATCH pairs and re-compare once.
    # The global calibration artifact stays untouched (frozen); only the
    # report improves, and only when strictly better.
    result, _refit = _refit_and_recompare(ai_revit, ai_pdf, calibration, result)
    if scope_note:
        result["level_scoping"] = scope_note
    save_artifact("compare", result)
    return JSONResponse(result)


ELEVATION_BAND_GAP_FT = 6.0


def _scope_assemblies_to_foundation(
    ai_revit: dict[str, Any], raw_revit: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Filter canonical assemblies to the lowest elevation band via their
    member records' elevations. Returns (scoped ai_revit copy, note). If
    elevations are unusable, returns the input unchanged with a warning note."""
    elev_by_id: dict[str, float] = {}
    for rec in raw_revit.get("discovery_instances") or raw_revit.get("holdowns") or []:
        eid = rec.get("element_id")
        elev = rec.get("elevation")
        if eid and isinstance(elev, (int, float)):
            elev_by_id[str(eid)] = float(elev)
    assemblies = ai_revit.get("canonical_holdown_assemblies", [])
    if not elev_by_id or not assemblies:
        return ai_revit, {"applied": False, "reason": "No per-record elevations in export."}

    def asm_elev(a: dict[str, Any]) -> float | None:
        vals = [elev_by_id[m] for m in a.get("member_element_ids", []) if m in elev_by_id]
        return min(vals) if vals else None

    elevs = sorted({e for a in assemblies if (e := asm_elev(a)) is not None})
    if not elevs:
        return ai_revit, {"applied": False, "reason": "Assemblies have no elevation data."}
    # Lowest band = foundation: everything within the first gap > BAND_GAP.
    cutoff = elevs[0]
    for e in elevs[1:]:
        if e - cutoff > ELEVATION_BAND_GAP_FT:
            break
        cutoff = e
    kept = [a for a in assemblies if (e := asm_elev(a)) is None or e <= cutoff]
    in_band = kept
    scoped = {**ai_revit, "canonical_holdown_assemblies": kept}
    return scoped, {
        "applied": True,
        "band_max_elevation_ft": cutoff,
        "assemblies_total": len(assemblies),
        "assemblies_in_band": len(in_band),
        "assemblies_kept": len(kept),
        "assemblies_scoped_out": len(assemblies) - len(kept),
        "note": "Assemblies above the foundation elevation band belong to other "
                "levels/sheets and are excluded from this sheet's comparison — "
                "not missing, just out of scope.",
    }


# ---------------------------------------------------------------------------
# Generalized multi-element pipeline (any PDF + Revit export)
# ---------------------------------------------------------------------------
@router.post("/api/elements/extract")
def elements_extract() -> JSONResponse:
    """Scan every page: discover schedule tables, learn the mark vocabulary,
    extract all element marks (holdowns, shear walls, posts, columns...)."""
    overrides = teach.build_overrides()
    result = element_detector.scan_pdf(project_pdf_path(), overrides=overrides)
    result["applied_memory_rules"] = sum(len(v) for v in overrides.values())
    # Leader-dot anchor snap (holdowns): measure the device dot, not the label.
    result = leader_anchor.snap_element_marks(result, project_pdf_path())
    save_artifact("element_intelligence", result)
    return JSONResponse(result)


@router.get("/api/elements/intelligence")
def elements_intelligence_get() -> JSONResponse:
    return JSONResponse(load_artifact("element_intelligence"))


@router.post("/api/elements/match")
def elements_match() -> JSONResponse:
    """Run shear-wall matching on every registered sheet and build the unified
    element list (holdown verdicts joined from the frozen compare pipeline)."""
    ei = load_artifact("element_intelligence")
    raw_revit = load_artifact("raw_revit")
    ai_revit = load_artifact("ai_revit")
    compare_path = config.artifact_path("compare")
    compare_report = (
        json.loads(compare_path.read_text(encoding="utf-8")) if compare_path.exists() else None
    )
    page_intel_path = config.artifact_path("pdf_page_intelligence")
    compare_sheet = "S-201"
    if page_intel_path.exists():
        compare_sheet = json.loads(page_intel_path.read_text(encoding="utf-8")).get(
            "sheet_number", "S-201"
        )

    wall_reports: dict[str, dict[str, Any]] = {}
    holdown_sheet_reports: dict[str, dict[str, Any]] = {}
    point_reports: dict[str, dict[str, dict[str, Any]]] = {}
    sheet_calibrations: dict[str, dict[str, Any]] = {}
    registration_notes: dict[str, str] = {}

    # v3 exports carry posts/columns: group Revit points per normalized mark
    # family so the frozen compare() can pair them per sheet.
    V3_POINT_CATEGORIES = {"post": ("P",), "steel_column": ("C",)}
    v3_points: dict[str, list[dict[str, Any]]] = {}
    for e in raw_revit.get("v3_elements", []):
        mark = revit_v3_adapter.normalize_point_mark(e.get("mark") or "")
        if not mark or "-" not in mark:
            continue
        prefix = mark.split("-")[0]
        for category, prefixes in V3_POINT_CATEGORIES.items():
            if prefix in prefixes:
                point = (e.get("location") or {}).get("point") or [None, None]
                if point[0] is None:
                    continue
                v3_points.setdefault(category, []).append({
                    "id": e.get("id"),
                    "pdf_mark_candidate": mark,
                    "core_token": e.get("family") or "",
                    "scheduled_type_raw": e.get("family") or "",
                    "family_type_summary": {e.get("family") or "?": 1},
                    "member_element_ids": [e.get("id")],
                    "primary_element_id": e.get("id"),
                    "center_point": {"x": point[0], "y": point[1],
                                     "z": e.get("elevation_ft")},
                    "bbox": None,
                    "level": e.get("level"),
                })

    def _sheet_calibration(sheet: dict[str, Any]) -> dict[str, Any] | None:
        """Per-sheet calibration: saved -> global (for the compare sheet)."""
        sheet_number = sheet["sheet_number"]
        sheet_cal_path = config.sheet_calibration_path(sheet_number)
        if sheet_cal_path.exists():
            try:
                return json.loads(sheet_cal_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        if sheet_number == compare_sheet:
            # The compare sheet was registered by the main RANSAC run — that
            # verified transform lives in the global calibration artifact.
            global_cal = registration.load_calibration()
            if registration.registration_usable(global_cal):
                return global_cal
        registration_notes[sheet_number] = "unregistered"
        return None

    for sheet in ei.get("sheets", []):
        sheet_number = sheet["sheet_number"]
        sw_marks = [m for m in sheet.get("marks", []) if m["category"] == "shear_wall"]
        hd_marks = [
            m for m in sheet.get("marks", [])
            if m["category"] == "holdown" and m.get("schedule_listed")
        ]
        has_point_marks = bool(v3_points) and any(
            m["category"] in V3_POINT_CATEGORIES and m.get("schedule_listed")
            for m in sheet.get("marks", [])
        )
        if (not sw_marks and not has_point_marks
                and not (hd_marks and sheet_number != compare_sheet)):
            continue
        cal = _sheet_calibration(sheet)
        if cal is not None:
            sheet_calibrations[sheet_number] = cal
        if sw_marks:
            # Leader-line segments from the sheet's vector drawing: the SW
            # bubble hangs on a leader; the tip is the physical reference.
            segments = None
            try:
                import fitz

                with fitz.open(project_pdf_path()) as _doc:
                    segments = wall_match.extract_leader_segments(
                        _doc[sheet["page_index"]]
                    )
            except Exception:
                segments = None  # anchors stay bubbles — never blocks matching
            wall_reports[sheet_number] = wall_match.match_shear_walls(
                sw_marks, raw_revit.get("walls", []), cal,
                leader_segments=segments,
            )
        if hd_marks and sheet_number != compare_sheet and cal is not None:
            # Same frozen compare(), this sheet's marks + calibration.
            pseudo_pdf = {
                "holdowns": [
                    {"id": m["id"], "normalized_mark": m["mark"],
                     "center_point": {"x": m["center_pdf"][0], "y": m["center_pdf"][1]}}
                    for m in hd_marks
                ]
            }
            _hd_report = compare_mod.compare(ai_revit, pseudo_pdf, calibration=cal)
            _hd_report, _hd_refit = _refit_and_recompare(
                ai_revit, pseudo_pdf, cal, _hd_report
            )
            if _hd_refit is not None:
                # Persist the refined per-sheet calibration (my artifact, not
                # the frozen global one) so the next run starts better.
                _hd_refit["sheet_number"] = sheet_number
                config.sheet_calibration_path(sheet_number).write_text(
                    json.dumps(_hd_refit, indent=2), encoding="utf-8"
                )
            holdown_sheet_reports[sheet_number] = _hd_report
        # Posts / steel columns via v3 element data, same frozen compare().
        if cal is not None:
            for category, rev_points in v3_points.items():
                cat_marks = [
                    m for m in sheet.get("marks", [])
                    if m["category"] == category and m.get("schedule_listed")
                ]
                if not cat_marks:
                    continue
                pseudo_pdf = {
                    "holdowns": [
                        {"id": m["id"], "normalized_mark": m["mark"],
                         "center_point": {"x": m["center_pdf"][0],
                                          "y": m["center_pdf"][1]}}
                        for m in cat_marks
                    ]
                }
                point_reports.setdefault(category, {})[sheet_number] = (
                    compare_mod.compare(
                        {"canonical_holdown_assemblies": rev_points},
                        pseudo_pdf, calibration=cal,
                    )
                )

    result = element_registry.build_element_list(
        ei, compare_report, wall_reports, compare_sheet=compare_sheet,
        holdown_sheet_reports=holdown_sheet_reports,
        point_reports=point_reports,
    )
    result["registration_notes"] = registration_notes
    # Physical-device pass (docs/ACCURACY_100_PLAN.md): re-account holdown +
    # shear-wall SHEET rows as physical devices in model feet. Original
    # per-sheet verdicts are kept on each row as sheet_status (audit trail).
    if compare_sheet not in sheet_calibrations:
        # The compare sheet skips the per-sheet loop (its verified transform
        # is the global RANSAC calibration) — seed it for device projection.
        _g = registration.load_calibration()
        if registration.registration_usable(_g):
            sheet_calibrations[compare_sheet] = _g
    device_registry = device_match.run(
        result.get("elements", []), sheet_calibrations,
        (ai_revit or {}).get("canonical_holdown_assemblies", []),
        (raw_revit or {}).get("walls", []),
    )
    for row in result.get("elements", []):
        ov = device_registry["row_overrides"].get(row["id"])
        if not ov:
            continue
        row["sheet_status"] = ov["sheet_status"]
        row["status"] = ov["status"]
        row["device_id"] = ov["device_id"]
        row["distance_ft"] = ov["distance_ft"]
        if ov.get("revit_ref"):
            row["revit_ref"] = {
                "id": ov["revit_ref"],
                "kind": ("wall" if row.get("category") == "shear_wall"
                         else "holdown_assembly"),
            }
        row["reason"] = ov["reason"]
    # Replace per-sheet REVIT_ONLY placeholder rows (one per sheet = the
    # same unmatched assembly counted 3x) with ONE device-honest row each.
    device_cats = set(device_registry["categories"])
    result["elements"] = [
        row for row in result.get("elements", [])
        if not (row.get("category") in device_cats
                and row.get("status") == "REVIT_ONLY"
                and str(row.get("id", "")).startswith(
                    ("revit_only_", "revit_wall_")))
    ]
    # R-18: same REVIT_ONLY status, but say WHICH kind of REVIT_ONLY it is.
    revit_only_cause = {
        d["id"]: d["cause"]
        for c in device_registry["categories"].values()
        for d in c.get("revit_only_detail", [])
    }
    for cat, c in device_registry["categories"].items():
        for tid in c["revit_only_ids"]:
            unclassified = revit_only_cause.get(tid) == "unclassified"
            result["elements"].append({
                "id": f"revit_only_{tid}", "category": cat, "mark": None,
                "sheet": None, "page_index": None, "pdf_point": None,
                "revit_point_transformed_to_pdf": None, "bbox_pdf": None,
                "spec": None, "status": "REVIT_ONLY",
                "status_detail": ("REVIT_UNCLASSIFIED" if unclassified
                                  else "REVIT_ONLY"),
                "distance_pdf_points": None,
                "revit_ref": {"id": tid,
                              "kind": ("wall" if cat == "shear_wall"
                                       else "holdown_assembly")},
                "drawable": False, "schedule_listed": None,
                "reason": (
                    "The Revit family for this element matched no row of the "
                    "PDF schedule — vocabulary gap, teachable."
                    if unclassified else
                    "No PDF callout claimed this device anywhere — genuinely "
                    "extra in the model, or the sheet doesn't call it out."),
                "confidence": None, "nearest_revit_candidates": [],
                "nearest_pdf_candidates": [],
            })
    # Re-apply prior human-review accepts whose device pairing still exists
    # (statuses come from geometry first; only stored HUMAN decisions can
    # upgrade a mismatch, and the resolution block keeps the audit trail).
    from .. import review

    reapplied = review.apply_stored_resolutions(result, device_registry)
    if reapplied:
        # registration_notes is a {sheet: reason} dict — keep this separate.
        result["resolutions_reapplied"] = reapplied
    result["counts"] = element_registry._counts(result.get("elements", []))
    result["device_summary"] = {
        cat: c["summary"] for cat, c in device_registry["categories"].items()
    }
    result["scope_warnings"] = element_registry.scope_warnings(
        result["device_summary"], raw_revit)
    save_artifact("device_registry", device_registry)
    save_artifact("element_list", result)
    # Refresh the 3D scene with the new statuses.
    save_artifact("scene3d", scene3d.build_scene(raw_revit, result, ai_revit))
    systematic, sampled = phase_summary.count_systematic(result, device_registry)
    phase_summary.record("match", phase_summary.match(result, systematic, sampled))
    return JSONResponse(result)


# ---------------------------------------------------------------------------
# Teach-the-AI memory (non-standardized client PDFs) — feeds extraction
# ---------------------------------------------------------------------------
@router.post("/api/teach/chat")
def teach_chat(payload: dict[str, Any] = Body(...)) -> JSONResponse:
    message = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(message, str):
        raise HTTPException(status_code=400, detail='Body must be {"message": "..."}')
    return JSONResponse(teach.teach(message, context=payload.get("context")))


@router.get("/api/teach/memory")
def teach_memory_get() -> JSONResponse:
    memory = teach.load_memory()
    return JSONResponse({**memory, "overrides": teach.build_overrides(memory)})


@router.delete("/api/teach/memory/{entry_id}")
def teach_memory_delete(entry_id: str) -> JSONResponse:
    return JSONResponse({"deleted": teach.delete_entry(entry_id)})


@router.get("/api/teach/unrecognized")
def teach_unrecognized() -> JSONResponse:
    ei = load_artifact("element_intelligence")
    return JSONResponse({"items": teach.unrecognized_report(ei)})


# ---------------------------------------------------------------------------
# Live progress stream (SSE) + per-step artifact presence
# ---------------------------------------------------------------------------
@router.get("/api/pipeline/events")
async def pipeline_events():
    """Live progress stream (SSE) for the pipeline view."""
    from fastapi.responses import StreamingResponse

    return StreamingResponse(
        progress.sse_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/pipeline/status")
def pipeline_status() -> JSONResponse:
    """Per-step artifact presence for the pipeline explainer view."""
    steps = [
        ("upload", "project_manifest"),
        ("revit_convert", "ai_revit"),
        ("pdf_intelligence", "pdf_page_intelligence"),
        ("pdf_convert", "ai_pdf"),
        ("ransac", "registration"),
        ("compare", "compare"),
        ("extract", "element_intelligence"),
        ("match", "element_list"),
        ("review", "review_items"),
    ]
    return JSONResponse(
        {
            "steps": [
                {"key": key, "artifact": config.ARTIFACT_FILES[art],
                 "done": config.artifact_path(art).exists()}
                for key, art in steps
            ],
            "memory_rules": len(teach.load_memory()["entries"]),
        }
    )
