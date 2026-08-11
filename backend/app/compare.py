from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from . import openrouter, registration

SCHEMA_VERSION = "ai-compare-report/2.1"

VERDICTS = (
    "MATCH",
    "PDF_ONLY",
    "REVIT_ONLY",
    "TYPE_MISMATCH",
    "LOCATION_MISMATCH",
    "NEEDS_REVIEW",
)

# Distance thresholds in PDF points (configurable via env vars).
MATCH_MAX_PT = float(os.environ.get("QAQC_MATCH_MAX_PT", "16.0"))
LOCATION_MISMATCH_MAX_PT = float(os.environ.get("QAQC_LOCATION_MISMATCH_MAX_PT", "40.0"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _group_revit(ai_revit: dict[str, Any]) -> dict[str | None, list[dict[str, Any]]]:
    grouped: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
    for asm in ai_revit.get("canonical_holdown_assemblies", []):
        grouped[asm.get("pdf_mark_candidate")].append(asm)
    return grouped


def _group_pdf(ai_pdf: dict[str, Any]) -> dict[str | None, list[dict[str, Any]]]:
    grouped: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
    for h in ai_pdf.get("holdowns", []):
        grouped[h.get("normalized_mark")].append(h)
    return grouped


def _xy(center: dict[str, Any] | None) -> tuple[float, float] | None:
    if not isinstance(center, dict):
        return None
    x, y = center.get("x"), center.get("y")
    if x is None or y is None:
        return None
    try:
        return float(x), float(y)
    except (TypeError, ValueError):
        return None


def _verdict_counts_template() -> dict[str, int]:
    return {v: 0 for v in VERDICTS}


# ---------------------------------------------------------------------------
# Nearest-candidate debug helpers
# ---------------------------------------------------------------------------
def _nearest_revit_candidates(
    pdf_pt: tuple[float, float] | None,
    rev: list[dict[str, Any]],
    rev_pts: list[tuple[float, float] | None],
    limit: int = 3,
) -> list[dict[str, Any]]:
    """For an unmatched PDF item, nearest same-mark Revit assemblies (transformed to PDF)."""
    if pdf_pt is None:
        return []
    cand = []
    for i, rp in enumerate(rev_pts):
        if rp is None:
            continue
        dist = math.hypot(rp[0] - pdf_pt[0], rp[1] - pdf_pt[1])
        cand.append((dist, i, rp))
    cand.sort(key=lambda c: c[0])
    return [
        {
            "revit_assembly_id": rev[i].get("id"),
            "distance_pdf_points": round(dist, 2),
            "revit_point_transformed_to_pdf": {"x": round(rp[0], 2), "y": round(rp[1], 2)},
        }
        for dist, i, rp in cand[:limit]
    ]


def _nearest_pdf_candidates(
    rev_pt: tuple[float, float] | None,
    pdf: list[dict[str, Any]],
    pdf_pts: list[tuple[float, float] | None],
    limit: int = 3,
) -> list[dict[str, Any]]:
    """For an unmatched Revit item (transformed to PDF), nearest same-mark PDF instances."""
    if rev_pt is None:
        return []
    cand = []
    for j, pp in enumerate(pdf_pts):
        if pp is None:
            continue
        dist = math.hypot(rev_pt[0] - pp[0], rev_pt[1] - pp[1])
        cand.append((dist, j, pp))
    cand.sort(key=lambda c: c[0])
    return [
        {
            "pdf_holdown_id": pdf[j].get("id"),
            "distance_pdf_points": round(dist, 2),
            "pdf_point": {"x": round(pp[0], 2), "y": round(pp[1], 2)},
        }
        for dist, j, pp in cand[:limit]
    ]


# ---------------------------------------------------------------------------
# Registered (location-aware) matching.
# When diagnostic=True (auto-extent calibration), distances are still computed
# but MATCH is NEVER issued -- paired items are reported as NEEDS_REVIEW.
# ---------------------------------------------------------------------------
def _match_with_location(
    revit_groups: dict[str | None, list[dict[str, Any]]],
    pdf_groups: dict[str | None, list[dict[str, Any]]],
    matrix: list[float],
    diagnostic: bool = False,
) -> dict[str, Any]:
    pairs: list[dict[str, Any]] = []
    per_mark: list[dict[str, Any]] = []
    counts = _verdict_counts_template()
    marks = sorted({m for m in revit_groups if m} | {m for m in pdf_groups if m})

    for mark in marks:
        rev = revit_groups.get(mark, [])
        pdf = pdf_groups.get(mark, [])
        mark_counts = {"matched": 0, "location_mismatch": 0, "pdf_only": 0,
                       "revit_only": 0, "needs_review": 0}

        # Pre-transform Revit points into PDF space.
        rev_pts: list[tuple[float, float] | None] = []
        for r in rev:
            rp = _xy(r.get("center_point"))
            rev_pts.append(registration.apply_transform(matrix, rp[0], rp[1]) if rp else None)
        pdf_pts = [_xy(p.get("center_point")) for p in pdf]

        # Revit assemblies with no usable coordinate -> NEEDS_REVIEW immediately.
        usable_rev = [i for i, pt in enumerate(rev_pts) if pt is not None]
        for i, pt in enumerate(rev_pts):
            if pt is None:
                counts["NEEDS_REVIEW"] += 1
                mark_counts["needs_review"] += 1
                pairs.append(_row(mark, rev[i], None, None, None, None, "NEEDS_REVIEW", 0.3,
                                   "Revit assembly missing coordinates."))

        # Candidate pairs within LOCATION_MISMATCH_MAX_PT, sorted ascending by distance.
        candidates = []
        for ri in usable_rev:
            for pj, ppt in enumerate(pdf_pts):
                if ppt is None:
                    continue
                dist = math.hypot(rev_pts[ri][0] - ppt[0], rev_pts[ri][1] - ppt[1])
                if dist <= LOCATION_MISMATCH_MAX_PT:
                    candidates.append((dist, ri, pj))
        candidates.sort(key=lambda c: c[0])

        used_rev: set[int] = set()
        used_pdf: set[int] = set()
        for dist, ri, pj in candidates:
            if ri in used_rev or pj in used_pdf:
                continue
            used_rev.add(ri)
            used_pdf.add(pj)
            if diagnostic:
                verdict = "NEEDS_REVIEW"
                conf = 0.3
                reason = (f"Diagnostic only (auto-extent calibration): mark {mark} nearest "
                          f"distance {dist:.1f}pt — not counted as MATCH.")
                mark_counts["needs_review"] += 1
            elif dist <= MATCH_MAX_PT:
                verdict = "MATCH"
                conf = round(max(0.6, 0.95 - dist / (2 * MATCH_MAX_PT)), 3)
                reason = f"Same mark {mark}; registered distance {dist:.1f}pt <= {MATCH_MAX_PT:.0f}pt."
                mark_counts["matched"] += 1
            else:
                verdict = "LOCATION_MISMATCH"
                conf = 0.5
                reason = f"Same mark {mark}; nearest registered distance {dist:.1f}pt (>{MATCH_MAX_PT:.0f}pt)."
                mark_counts["location_mismatch"] += 1
            counts[verdict] += 1
            pairs.append(_row(mark, rev[ri], pdf[pj], rev_pts[ri], pdf_pts[pj], round(dist, 2),
                              verdict, conf, reason))

        # Leftovers, each annotated with nearest same-mark candidates for debugging.
        for pj in range(len(pdf)):
            if pj not in used_pdf:
                counts["PDF_ONLY"] += 1
                mark_counts["pdf_only"] += 1
                row = _row(mark, None, pdf[pj], None, pdf_pts[pj], None, "PDF_ONLY", 0.6,
                           f"No Revit {mark} assembly within {LOCATION_MISMATCH_MAX_PT:.0f}pt.")
                row["nearest_revit_candidates"] = _nearest_revit_candidates(pdf_pts[pj], rev, rev_pts)
                pairs.append(row)
        for ri in usable_rev:
            if ri not in used_rev:
                counts["REVIT_ONLY"] += 1
                mark_counts["revit_only"] += 1
                row = _row(mark, rev[ri], None, rev_pts[ri], None, None, "REVIT_ONLY", 0.6,
                           f"No PDF {mark} instance within {LOCATION_MISMATCH_MAX_PT:.0f}pt.")
                row["nearest_pdf_candidates"] = _nearest_pdf_candidates(rev_pts[ri], pdf, pdf_pts)
                pairs.append(row)

        per_mark.append({"mark": mark, "revit_count": len(rev), "pdf_count": len(pdf), **mark_counts})

    # Revit assemblies with no PDF mark candidate.
    for asm in revit_groups.get(None, []):
        counts["REVIT_ONLY"] += 1
        pairs.append(_row(None, asm, None, None, None, None, "REVIT_ONLY", 0.4,
                          "Revit assembly has no resolved PDF mark candidate."))

    return {"pairs": pairs, "per_mark": per_mark, "verdict_counts": counts}


# ---------------------------------------------------------------------------
# Fallback (no usable registration): type + count pairing only
# ---------------------------------------------------------------------------
def _match_type_only(
    revit_groups: dict[str | None, list[dict[str, Any]]],
    pdf_groups: dict[str | None, list[dict[str, Any]]],
) -> dict[str, Any]:
    pairs: list[dict[str, Any]] = []
    per_mark: list[dict[str, Any]] = []
    counts = _verdict_counts_template()
    marks = sorted({m for m in revit_groups if m} | {m for m in pdf_groups if m})

    for mark in marks:
        rev = revit_groups.get(mark, [])
        pdf = pdf_groups.get(mark, [])
        paired = min(len(rev), len(pdf))
        for i in range(paired):
            counts["NEEDS_REVIEW"] += 1
            pairs.append(_row(mark, rev[i], pdf[i],
                              _xy(rev[i].get("center_point")), _xy(pdf[i].get("center_point")),
                              None, "NEEDS_REVIEW", 0.3, "Type matches; location not evaluated."))
        for j in range(paired, len(pdf)):
            counts["PDF_ONLY"] += 1
            pairs.append(_row(mark, None, pdf[j], None, _xy(pdf[j].get("center_point")), None,
                              "PDF_ONLY", 0.6, f"Surplus PDF {mark} instance."))
        for j in range(paired, len(rev)):
            counts["REVIT_ONLY"] += 1
            pairs.append(_row(mark, rev[j], None, _xy(rev[j].get("center_point")), None, None,
                              "REVIT_ONLY", 0.6, f"Surplus Revit {mark} assembly."))
        per_mark.append({
            "mark": mark, "revit_count": len(rev), "pdf_count": len(pdf),
            "matched": 0, "location_mismatch": 0,
            "pdf_only": max(0, len(pdf) - paired), "revit_only": max(0, len(rev) - paired),
            "needs_review": paired,
        })

    for asm in revit_groups.get(None, []):
        counts["REVIT_ONLY"] += 1
        pairs.append(_row(None, asm, None, None, None, None, "REVIT_ONLY", 0.4,
                          "Revit assembly has no resolved PDF mark candidate."))

    return {"pairs": pairs, "per_mark": per_mark, "verdict_counts": counts}


def _row(mark, rev, pdf, rev_pt, pdf_pt, dist, verdict, conf, reason) -> dict[str, Any]:
    rev_xy = _xy(rev.get("center_point")) if rev else None
    return {
        "pdf_holdown_id": pdf.get("id") if pdf else None,
        "revit_assembly_id": rev.get("id") if rev else None,
        "mark": mark,
        "pdf_point": {"x": pdf_pt[0], "y": pdf_pt[1]} if pdf_pt else None,
        "revit_point": {"x": rev_xy[0], "y": rev_xy[1], "space": "revit_internal_feet"} if rev_xy else None,
        "revit_point_transformed_to_pdf": {"x": round(rev_pt[0], 2), "y": round(rev_pt[1], 2)} if rev_pt else None,
        "distance_pdf_points": dist,
        "verdict": verdict,
        "reason": reason,
        "confidence": conf,
    }


# ---------------------------------------------------------------------------
# LLM advisory (real OpenRouter call)
# ---------------------------------------------------------------------------
def _llm_assessment(per_mark, registration_status, blockers) -> dict[str, Any]:
    system_prompt = (
        "You are a structural QA/QC reviewer. Given per-mark hold-down match results, the "
        "coordinate-registration status, and any blockers, assess whether a confident MATCH "
        "is justified. Be conservative. Reply ONLY with JSON "
        '{"match_justified":true|false,"overall_verdict":"..","reasoning":".."}.'
    )
    user_prompt = json.dumps(
        {"registration_status": registration_status, "per_mark": per_mark, "blockers": blockers},
        indent=2,
    )
    status = openrouter.call_llm(
        system_prompt=system_prompt, user_prompt=user_prompt,
        purpose="ai_compare.assessment",
    )
    parsed = None
    if status.get("ok") and status.get("content"):
        try:
            parsed = json.loads(status["content"])
        except json.JSONDecodeError:
            status = {**status, "error": "LLM returned non-JSON content; ignored."}
    return {"status": status, "parsed": parsed}


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------
def compare(
    ai_revit: dict[str, Any],
    ai_pdf: dict[str, Any],
    calibration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    revit_groups = _group_revit(ai_revit)
    pdf_groups = _group_pdf(ai_pdf)
    reg_status = registration.registration_status(calibration)
    usable = registration.registration_usable(calibration)
    quality = (calibration or {}).get("quality") if calibration else None

    source = registration.calibration_source(calibration)
    validation_failed = bool((quality or {}).get("validation_failed"))
    has_transform = bool(calibration and calibration.get("transform"))

    blockers: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    reg_message: str

    if usable:
        # Attempt 1: verified registration -> location-aware matching (MATCH possible).
        matrix = calibration["transform"]["matrix"]
        result = _match_with_location(revit_groups, pdf_groups, matrix)
        reg_message = (
            f"Verified registration ({source}); comparison uses Revit->PDF transformed coordinates."
        )
        attempts.append({
            "attempt": 1, "name": "type_and_verified_registered_location", "status": "used",
            "input_requirements": ["verified source", "high/medium registration", "Revit + PDF coordinates"],
            "result": {"verdict_counts": result["verdict_counts"]}, "blockers": [],
        })
        # Unvalidated calibration is accepted but flagged for transparency.
        if not (quality or {}).get("validation_pair_count"):
            blockers.append({
                "code": "REGISTRATION_UNVALIDATED", "severity": "warning",
                "message": "Calibration accepted without independent holdout validation; interior alignment unproven.",
                "recommended_fix": "Add validation_pairs (known hold-downs not used in the solve).",
            })
    elif reg_status == "diagnostic_only" and has_transform:
        # Auto-extent calibration: compute distances for insight but NEVER issue MATCH.
        matrix = calibration["transform"]["matrix"]
        result = _match_with_location(revit_groups, pdf_groups, matrix, diagnostic=True)
        blockers.append({
            "code": "AUTO_EXTENT_CALIBRATION_DIAGNOSTIC_ONLY", "severity": "blocking",
            "message": registration.DIAGNOSTIC_NOTE,
            "recommended_fix": "Submit manual_verified / grid_verified / anchor_verified point pairs "
                               "at real shared grid/anchor features via POST /api/registration/manual.",
        })
        reg_message = (
            "Auto extent calibration is diagnostic only; distances are shown but MATCH is withheld."
        )
        attempts.append({
            "attempt": 1, "name": "diagnostic_auto_extent_distances", "status": "diagnostic",
            "input_requirements": ["auto_extent_estimate calibration"],
            "result": {"verdict_counts": result["verdict_counts"]},
            "blockers": ["AUTO_EXTENT_CALIBRATION_DIAGNOSTIC_ONLY"],
            "note": "Distances computed from extent-fit transform; not counted as MATCH.",
        })
    else:
        # No usable registration -> one clear global blocker, then type+count fallback.
        if reg_status == "missing":
            blockers.append({
                "code": "REGISTRATION_MISSING", "severity": "blocking",
                "message": "No Revit->PDF coordinate registration exists; location cannot be evaluated.",
                "recommended_fix": "Create a verified manual calibration via POST /api/registration/manual.",
            })
        elif reg_status == "failed":
            blockers.append({
                "code": "REGISTRATION_FAILED", "severity": "blocking",
                "message": (quality or {}).get("confidence_reason")
                or (quality or {}).get("reason", "Registration could not be solved."),
                "recommended_fix": "Provide 3+ non-collinear, correctly matched point pairs.",
            })
        elif validation_failed:
            blockers.append({
                "code": "REGISTRATION_VALIDATION_FAILED", "severity": "blocking",
                "message": (
                    f"Holdout validation RMS={(quality or {}).get('validation_rms_residual_pt')}pt / "
                    f"max={(quality or {}).get('validation_max_residual_pt')}pt exceeds limits; MATCH withheld."
                ),
                "recommended_fix": "Re-pick calibration/validation points; confirm correct correspondences.",
            })
        else:  # low_confidence (verified source but weak solve, or unverified source)
            blockers.append({
                "code": "REGISTRATION_LOW_CONFIDENCE", "severity": "blocking",
                "message": (
                    f"Registration not usable (source={source}, "
                    f"solve RMS={(quality or {}).get('solve_rms_residual_pt')}pt, "
                    f"max={(quality or {}).get('solve_max_residual_pt')}pt); MATCH withheld."
                ),
                "recommended_fix": "Use a verified source and re-pick points to reach medium/high confidence.",
            })
        reg_message = "No usable registration; MATCH is withheld and a global blocker is reported."
        attempts.append({
            "attempt": 1, "name": "type_and_verified_registered_location", "status": "skipped",
            "input_requirements": ["verified source", "high/medium registration", "Revit + PDF coordinates"],
            "result": None, "blockers": [b["code"] for b in blockers],
        })
        result = _match_type_only(revit_groups, pdf_groups)
        attempts.append({
            "attempt": 2, "name": "type_and_count_without_location", "status": "used",
            "input_requirements": ["mark/type agreement only"],
            "result": {"verdict_counts": result["verdict_counts"]}, "blockers": [],
            "note": "Location not evaluated; type-aligned pairs reported as NEEDS_REVIEW.",
        })

    counts = result["verdict_counts"]
    total_items = sum(counts.values())
    matched = counts["MATCH"]
    pdf_total = sum(len(v) for v in pdf_groups.values())
    revit_total = sum(len(v) for v in revit_groups.values())

    # Per-mark count mismatch is informational, not a hard blocker once registered.
    count_mismatch_marks = [m for m in result["per_mark"]
                            if m["revit_count"] != m["pdf_count"]]
    if count_mismatch_marks:
        blockers.append({
            "code": "COUNT_MISMATCH", "severity": "warning",
            "message": "Per-mark Revit vs PDF counts differ: " + ", ".join(
                f"{m['mark']} {m['revit_count']}!={m['pdf_count']}" for m in count_mismatch_marks),
            "recommended_fix": "Review unmatched PDF_ONLY / REVIT_ONLY items individually.",
        })

    full_match = (
        usable and matched == total_items and total_items > 0
        and not any(b["severity"] == "blocking" for b in blockers)
    )

    llm = _llm_assessment(result["per_mark"], reg_status, [b["code"] for b in blockers])

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "inputs": {
            "revit_source": ai_revit.get("source_file"),
            "pdf_source": ai_pdf.get("source_sheet"),
        },
        "registration": {
            "status": reg_status,
            "calibration_source": source,
            "method": (calibration or {}).get("method") if calibration else None,
            "transform_direction": registration.TRANSFORM_DIRECTION,
            "quality": quality,
            "match_allowed": usable,
            "message": reg_message,
        },
        "revit_count_diagnostics": _revit_count_diagnostics(ai_revit),
        "summary": {
            "pdf_holdown_total": pdf_total,
            "revit_assembly_total": revit_total,
            "matched_items": matched,
            "full_match_achieved": full_match,
            "verdict_counts": counts,
            "per_mark": result["per_mark"],
        },
        "attempts": attempts,
        "blockers": blockers,
        "final_verdicts": result["pairs"],
        "honesty_statement": (
            "MATCH is only issued when (a) a VERIFIED calibration source "
            "(manual_verified/grid_verified/anchor_verified) with high/medium confidence and "
            "passing-or-absent validation exists, AND (b) the Revit point, transformed into PDF "
            f"space, lies within {MATCH_MAX_PT:.0f} PDF points of the PDF point. auto_extent_estimate "
            "is diagnostic only and can never produce a MATCH."
        ),
        "llm_assessment": llm["parsed"],
        "openrouter_call_status": llm["status"],
    }
    return report


# ---------------------------------------------------------------------------
# Revit over-count diagnostics (no exporter changes in this phase)
# ---------------------------------------------------------------------------
def _project_pdf_baseline() -> dict[str, int] | None:
    """This project's expected PDF mark counts, read from the
    pdf_page_intelligence artifact's ``expected_baseline``.

    R-27: replaces a hardcoded Madera {H1:10,H2:21,H3:6,H4:17}, which quoted
    Madera's numbers at every other project. None when this project has no such
    artifact — the caller then emits no baseline rather than a borrowed one.

    Deliberately does NOT fall back to the observed ``summary.by_type``: a
    baseline taken from the counts it is meant to check can never disagree with
    them, so the comparison would read as passing while measuring nothing. The
    generic path records no expected_baseline, so it correctly gets None.
    """
    from . import config    # local import: keeps this diagnostics-only change
                            # from adding a module-level dep to frozen compare.py

    try:
        path = config.artifact_path("pdf_page_intelligence")
        if not path.exists():
            return None
        intel = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        return None
    base = intel.get("expected_baseline")
    if not isinstance(base, dict) or not base:
        return None
    try:
        return {str(k): int(v) for k, v in base.items()}
    except (TypeError, ValueError):
        return None


def _revit_count_diagnostics(ai_revit: dict[str, Any]) -> dict[str, Any]:
    """Surface the Revit raw->canonical->by-mark count chain vs the PDF baseline.

    Prefers a precomputed block from AIConvert_revit.json; otherwise derives a
    minimal view from the converted assemblies. DISPLAY ONLY — no verdict, gate
    or threshold reads this block.
    """
    precomputed = ai_revit.get("revit_count_diagnostics")
    if isinstance(precomputed, dict):
        return precomputed

    assemblies = ai_revit.get("canonical_holdown_assemblies", [])
    by_mark: dict[str, int] = {}
    for asm in assemblies:
        mark = asm.get("pdf_mark_candidate")
        if mark:
            by_mark[mark] = by_mark.get(mark, 0) + 1
    pdf_baseline = _project_pdf_baseline()
    marks = tuple(pdf_baseline) if pdf_baseline else tuple(sorted(by_mark))
    diag: dict[str, Any] = {
        "raw_holdown_records": (ai_revit.get("learned_key_points") or {}).get("raw_record_count"),
        "canonical_assemblies": len(assemblies),
        "by_mark": {m: by_mark.get(m, 0) for m in marks},
        "source": "derived_in_compare (AIConvert_revit.json had no revit_count_diagnostics block)",
    }
    if pdf_baseline is None:
        diag["pdf_baseline"] = None
        diag["note"] = ("No PDF baseline available for this project (no "
                        "pdf_page_intelligence artifact, or it recorded no "
                        "expected_baseline) — Revit counts shown alone.")
        return diag
    diag["pdf_baseline"] = pdf_baseline
    diag["likely_issue"] = "Revit export/conversion still includes extra assemblies or wrong scope."
    diag["required_next_fix"] = "Add view/level/schedule/grid scoping before final comparison."
    return diag
