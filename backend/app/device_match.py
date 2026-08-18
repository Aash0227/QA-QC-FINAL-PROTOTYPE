"""Hold Down + Shear Wall adapters onto the generic matching engine
(matching_engine.py) -- Stage 9 Gate 4 extracted this module's category-
agnostic core (registration inverse, clustering, assignment, ambiguity,
adaptive gate) into matching_engine.py. This module now owns only what's
genuinely Hold-Down/Shear-Wall specific: which rows/targets to feed the
engine, the two categories' numeric tolerances, and folding results back
onto sheet rows (docs/ACCURACY_100_PLAN.md P1-P3):

P1  inverse-project every sheet callout to model space and cluster same-mark
    points across sheets into physical devices (matching_engine.build_devices);
P2  global one-to-one assignment devices <-> Revit assemblies via the generic
    engine's evidence-gated assign() (mark, adaptive distance gate, ambiguity
    margin, level compatibility);
P3  honest device statuses folded back onto the sheet rows, original
    per-sheet verdicts retained as sheet_status for audit.

This is a pure extraction: every constant, gate, and code path below behaves
identically to the pre-Gate-4 device_match.py (regression-locked against
real Madera data -- see docs/QBC_RND_MASTER_REPORT.md Gate 3 and the Gate 4
migration notes). The wrapper functions (build_devices/assign/etc. with the
old positional signatures) exist so existing callers and tests don't need to
change; new adapters should call matching_engine directly with an
AdapterConfig instead of adding more wrappers here.
"""
from __future__ import annotations

import logging
import math
import os
import re
from typing import Any, Callable

from . import matching_engine as engine
from .matching_engine import (  # re-exported for existing callers/tests
    AdapterConfig,
    build_devices,
    fit_inverse,
    inverse_from_calibration,
    point_distance,
    row_z_ft,
    segment_distance,
)

logger = logging.getLogger(__name__)

# ponytail: tuned on Madera ground truth; knobs, not gospel -- all overridable
# via env so a project with a different drafting convention or element
# density isn't stuck with these exact numbers.
CLUSTER_TOL_FT = float(os.environ.get("QAQC_DEVICE_CLUSTER_TOL_FT", "3.0"))
MATCH_FT = float(os.environ.get("QAQC_DEVICE_MATCH_FT", "2.0"))
MISMATCH_FT = float(os.environ.get("QAQC_DEVICE_MISMATCH_FT", "6.0"))
LEVEL_DELTA_FT = float(os.environ.get("QAQC_DEVICE_LEVEL_DELTA_FT", "8.0"))
AMBIGUITY_MARGIN_FT = float(os.environ.get("QAQC_DEVICE_AMBIGUITY_MARGIN_FT", "1.0"))
MATCH_GATE_CEILING_MULT = float(os.environ.get("QAQC_DEVICE_MATCH_GATE_CEILING_MULT", "3.0"))
SW_TOKEN_RE = re.compile(r"SW\s*-?\s*(\d+)", re.IGNORECASE)

HOLDOWN_ADAPTER = AdapterConfig(
    match_ft=MATCH_FT, mismatch_ft=MISMATCH_FT, distance=point_distance,
    mark_blind=True, cluster_tol_ft=CLUSTER_TOL_FT, level_delta_ft=LEVEL_DELTA_FT,
    ambiguity_margin_ft=AMBIGUITY_MARGIN_FT, match_gate_ceiling_mult=MATCH_GATE_CEILING_MULT,
)
SHEAR_WALL_ADAPTER = AdapterConfig(
    match_ft=4.0, mismatch_ft=12.0, distance=segment_distance,
    mark_blind=False, cluster_tol_ft=CLUSTER_TOL_FT, level_delta_ft=LEVEL_DELTA_FT,
    ambiguity_margin_ft=AMBIGUITY_MARGIN_FT, match_gate_ceiling_mult=MATCH_GATE_CEILING_MULT,
    # Revit walls carry a level name and one plan sheet draws one story, so
    # two same-mark walls stacked at identical plan coordinates on different
    # floors are distinguishable -- the dominant ambiguity cause found in the
    # Shear Wall investigation. Hold-down assemblies carry no level field in
    # the export (only a raw z), so HOLDOWN_ADAPTER leaves context_key unset.
    context_key="level",
    # The drawn wall's direction, extracted from the sheet's own vector
    # geometry (pdf_wall_geometry.py), validated against the real Madera
    # sheets at ~2 deg median error. Length is deliberately NOT used: one
    # drawn hatch run legitimately spans SEVERAL Revit wall segments (the
    # same reason absorb_same_mark exists), so drawn-vs-segment length is a
    # cardinality mismatch, not a discrepancy -- measured median error 2.4 ft
    # vs orientation's 1.9 deg.
    orientation_tolerance_deg=20.0,
)


def adaptive_match_ft(device: dict[str, Any],
                      registration_quality: dict[str, dict[str, Any]],
                      base_ft: float) -> float:
    return engine.adaptive_match_ft(device, registration_quality, base_ft,
                                    MATCH_GATE_CEILING_MULT)


def build_devices(rows: list[dict[str, Any]],  # noqa: F811 -- old positional signature
                  inverse_by_sheet: dict[str, Callable],
                  prefix: str) -> tuple[list[dict[str, Any]], int]:
    return engine.build_devices(rows, inverse_by_sheet, prefix, CLUSTER_TOL_FT)


def _flag_ambiguous(devices, targets, distance, mismatch_ft) -> None:
    engine._flag_ambiguous(devices, targets, distance, mismatch_ft, AMBIGUITY_MARGIN_FT)


def assign(devices: list[dict[str, Any]],
           targets: list[dict[str, Any]],
           distance: Callable[[dict[str, Any], dict[str, Any]], float],
           match_ft: float = MATCH_FT,
           mismatch_ft: float = MISMATCH_FT,
           mark_blind: bool = True,
           registration_quality: dict[str, dict[str, Any]] | None = None) -> None:
    config = AdapterConfig(
        match_ft=match_ft, mismatch_ft=mismatch_ft, distance=distance,
        mark_blind=mark_blind, cluster_tol_ft=CLUSTER_TOL_FT,
        level_delta_ft=LEVEL_DELTA_FT, ambiguity_margin_ft=AMBIGUITY_MARGIN_FT,
        match_gate_ceiling_mult=MATCH_GATE_CEILING_MULT,
    )
    engine.assign(devices, targets, config, registration_quality)


def sw_token(text: str) -> str | None:
    m = SW_TOKEN_RE.search(text or "")
    return f"SW-{int(m.group(1))}" if m else None


# ------------------------------------------------------------ P3: driver

def run(element_rows: list[dict[str, Any]],
        calibrations: dict[str, dict[str, Any]],
        assemblies: list[dict[str, Any]],
        walls: list[dict[str, Any]]) -> dict[str, Any]:
    """Full device pass. Returns the device_registry artifact; caller folds
    registry['row_overrides'] onto the element rows."""
    inverse = {}
    for sheet, cal in calibrations.items():
        inv = inverse_from_calibration(cal)
        if inv is None:
            inv = fit_inverse((cal or {}).get("point_pairs") or [])
        if inv is not None:
            inverse[sheet] = inv

    registry: dict[str, Any] = {"schema_version": "device-registry/1.0",
                                "gates_ft": {"match": MATCH_FT,
                                             "mismatch": MISMATCH_FT,
                                             "cluster": CLUSTER_TOL_FT},
                                # metadata only — verdict logic doesn't read it
                                "registration_quality": {
                                    sheet: {
                                        "source": (cal or {}).get("calibration_source"),
                                        "confidence": ((cal or {}).get("quality") or {}).get("confidence"),
                                        "rms_residual_pt": ((cal or {}).get("quality") or {}).get("solve_rms_residual_pt"),
                                        # PDF-pt per model-ft; converts rms_residual_pt to
                                        # model feet for the adaptive match gate (Gate 2).
                                        "scale": ((cal or {}).get("transform") or {}).get("scale"),
                                    } for sheet, cal in calibrations.items()},
                                "categories": {}, "row_overrides": {}}

    # --- holdowns (point devices); only real callouts (placeholder
    # REVIT_ONLY rows have no pdf_point and are replaced by device output)
    hd_rows = [r for r in element_rows if r.get("category") == "holdown"
               and r.get("status") not in ("NOT_IN_SCHEDULE",)
               and r.get("pdf_point")]
    targets = []
    for a in assemblies:
        if 'center_point' not in a or a['center_point'].get('x') is None:
            continue
        targets.append({"id": a["id"], "mark": a.get("pdf_mark_candidate"),
                        "x": a["center_point"]["x"], "y": a["center_point"]["y"],
                        "z": a["center_point"].get("z")})
    _run_category(registry, "holdown", hd_rows, inverse, targets,
                  HOLDOWN_ADAPTER)

    # --- shear walls (segment targets)
    # Gate: Shear Wall -- prefer wall_match's leader-tip-corrected anchor
    # (match_anchor_pdf) over the raw callout-bubble pdf_point when present,
    # so the physical-device re-projection doesn't silently discard the
    # correction wall_match already computed. Falls back to pdf_point for
    # rows that predate this field (or never had a leader to correct).
    sw_rows = [
        {**r, "pdf_point": r.get("match_anchor_pdf") or r.get("pdf_point")}
        for r in element_rows
        if r.get("category") == "shear_wall" and r.get("pdf_point")
    ]
    wall_targets = []
    for w in walls:
        tok = sw_token(w.get("type_name") or "")
        cl = w.get("centerline") or []
        if tok and len(cl) == 2:
            (wx1, wy1), (wx2, wy2) = tuple(cl[0]), tuple(cl[1])
            wall_targets.append({"id": w.get("id"), "mark": tok,
                                 "segment": ((wx1, wy1), (wx2, wy2)),
                                 # context evidence channel (see
                                 # SHEAR_WALL_ADAPTER.context_key)
                                 "level": w.get("level"),
                                 # orientation evidence channel; model-space
                                 # direction, compared against the drawn
                                 # wall's direction on the sheet
                                 "orientation_deg": math.degrees(
                                     math.atan2(wy2 - wy1, wx2 - wx1)) % 180.0})
    # Walls: a drawn SW run maps to SEVERAL Revit wall segments, and the
    # callout bubble sits off the run — wall-appropriate gates + absorb
    # unclaimed same-mark segments near a matched device.
    _run_category(registry, "shear_wall", sw_rows, inverse, wall_targets,
                  SHEAR_WALL_ADAPTER, absorb_same_mark=True)
    return registry


def _annotate_reasons(devices: list[dict[str, Any]]) -> None:
    """Additive reason tails. Never touches status.

    R-25: every verdict names the Revit target but nothing on the PDF side, so
    "paired with rev_asm_011" is unfindable on a drawing — append the first
    callout's row id and sheet.
    R-03: when both sides have a Z, flag a pairing that spans floors instead of
    silently trusting a 0.00 ft plan distance."""
    for d in devices:
        tail = ""
        rid = (d.get("appearances") or [None])[0]
        sheet = (d.get("sheets") or [None])[0]
        if rid:
            tail += f" (callout {rid}{f' on {sheet}' if sheet else ''})"
        dz, tz = d.get("z"), d.get("target_z")
        if (d.get("status") in ("MATCH", "LOCATION_MISMATCH")
                and isinstance(dz, (int, float))
                and isinstance(tz, (int, float))
                and abs(dz - tz) > LEVEL_DELTA_FT):
            tail += (" NOTE: paired element is on a different level "
                     f"(Δz≈{abs(dz - tz):.0f} ft) — "
                     "verify the floor.")
        if tail and d.get("reason"):
            d["reason"] += tail


def _run_category(registry, category, rows, inverse, targets,
                  config: AdapterConfig, absorb_same_mark=False):
    devices, unprojected = build_devices(rows, inverse, category)
    # engine.assign directly, NOT the back-compat assign() wrapper above --
    # that wrapper rebuilds an AdapterConfig from positional args and would
    # silently drop this adapter's context_key / context thresholds.
    engine.assign(devices, targets, config,
                  registry.get("registration_quality"))
    _annotate_reasons(devices)
    claimed = {t["id"] for t in targets if t.pop("_claimed", False)}
    if absorb_same_mark:
        by_id = {d.get("target_id"): d for d in devices if d.get("target_id")}
        matched = [d for d in devices if d.get("status") == "MATCH"]
        for t in targets:
            if t["id"] in claimed:
                continue
            near = [d for d in matched if d["mark"] == t.get("mark")
                    and config.distance(d, t) <= config.mismatch_ft]
            if near:
                d = min(near, key=lambda d: config.distance(d, t))
                d.setdefault("also_covers", []).append(t["id"])
                claimed.add(t["id"])
    revit_only = [t["id"] for t in targets if t["id"] not in claimed]
    # R-18: REVIT_ONLY conflates two very different problems. A target with no
    # mark never had a schedule spec to match against (vocabulary gap —
    # teachable); a marked one genuinely lost/never had a callout. Metadata
    # only: statuses and revit_only_ids are unchanged.
    by_target = {t["id"]: t for t in targets}
    revit_only_detail = [
        {"id": tid,
         "mark": by_target[tid].get("mark"),
         "cause": "unclassified" if by_target[tid].get("mark") is None
                  else "unmatched"}
        for tid in revit_only
    ]
    rows_by_id = {r["id"]: r for r in rows}
    for d in devices:
        for rid in d["appearances"]:
            row = rows_by_id.get(rid)
            registry["row_overrides"][rid] = {
                "status": d["status"],
                "device_id": d["id"],
                "distance_ft": d.get("distance_ft"),
                "revit_ref": d.get("target_id"),
                "reason": d["reason"] + (
                    f" Drawn on {len(set(d['sheets']))} sheet(s): "
                    f"{', '.join(sorted(set(d['sheets'])))}."
                    if len(d["appearances"]) > 1 else ""),
                "sheet_status": (row or {}).get("status"),
            }
    from collections import Counter
    registry["categories"][category] = {
        "devices": devices,
        "revit_only_ids": revit_only,
        "revit_only_detail": revit_only_detail,
        "summary": {
            "callout_rows": len(rows),
            "physical_devices": len(devices),
            "unprojected_rows": unprojected,
            "revit_targets": len(targets),
            "by_status": dict(Counter(d["status"] for d in devices)),
            "revit_only": len(revit_only),
        },
    }


if __name__ == "__main__":
    # inverse fit round-trip (flipped chirality like real PDFs)
    pairs = [{"revit_point": {"x": x, "y": y},
              "pdf_point": {"x": 100 + 4 * x, "y": 900 - 4 * y}}
             for x, y in ((0, 0), (50, 0), (0, 30), (25, 60))]
    inv = fit_inverse(pairs)
    x, y = inv(100 + 4 * 10, 900 - 4 * 20)
    assert abs(x - 10) < 1e-6 and abs(y - 20) < 1e-6, (x, y)

    # 2 pairs cannot determine chirality — must refuse, not coin-flip (R-01)
    assert fit_inverse(pairs[:2]) is None

    # stored inverse_matrix is used verbatim: x_ft=(u-100)/4, y_ft=(900-v)/4
    cal2 = {"transform": {"inverse_matrix": [0.25, 0, 0, -0.25, -25.0, 225.0]}}
    x, y = inverse_from_calibration(cal2)(140, 860)
    assert abs(x - 10) < 1e-9 and abs(y - 10) < 1e-9, (x, y)
    assert inverse_from_calibration({"transform": {}}) is None

    rows = [
        {"id": "s1_h1_a", "sheet": "S1", "category": "holdown", "mark": "H1",
         "status": "MATCH", "pdf_point": {"x": 140, "y": 860}},   # (10,10)
        {"id": "s2_h1_a", "sheet": "S2", "category": "holdown", "mark": "H1",
         "status": "PDF_ONLY", "pdf_point": {"x": 141, "y": 861}},  # same spot
        {"id": "s1_h2_b", "sheet": "S1", "category": "holdown", "mark": "H2",
         "status": "PDF_ONLY", "pdf_point": {"x": 300, "y": 700}},  # (50,50)
    ]
    cals = {"S1": {"point_pairs": pairs}, "S2": {"point_pairs": pairs}}
    asm = [{"id": "rev_asm_001", "pdf_mark_candidate": "H1",
            "center_point": {"x": 10.3, "y": 10.2}},
           {"id": "rev_asm_002", "pdf_mark_candidate": "H3",
            "center_point": {"x": 50.1, "y": 50.1}}]
    reg = run(rows, cals, asm, walls=[])
    hd = reg["categories"]["holdown"]
    assert hd["summary"]["physical_devices"] == 2, hd["summary"]
    sts = {d["mark"]: d["status"] for d in hd["devices"]}
    assert sts == {"H1": "MATCH", "H2": "MARK_MISMATCH"}, sts
    # both sheet appearances of the H1 device inherit MATCH
    assert reg["row_overrides"]["s2_h1_a"]["status"] == "MATCH"
    assert reg["row_overrides"]["s2_h1_a"]["sheet_status"] == "PDF_ONLY"
    assert hd["summary"]["revit_only"] == 0

    # R-25: every reason names a findable PDF callout, not just rev_asm_NNN
    assert "(callout s1_h1_a on S1)" in reg["row_overrides"]["s1_h1_a"]["reason"]
    assert "(callout s1_h2_b on S1)" in reg["row_overrides"]["s1_h2_b"]["reason"]

    # Gate 2 (R-03 superseded): with a Z on both sides, a cross-floor pairing
    # is neither a confident MATCH nor a confident MISMATCH -- good XY, wrong
    # floor -- so it's NEEDS_REVIEW and nothing is claimed. Today's element
    # rows carry no elevation, so this is dormant in production -- the
    # plumbing is here for when they do.
    rows_z = [dict(rows[0], elevation_ft=0.0)]
    asm_z = [{"id": "rev_asm_001", "pdf_mark_candidate": "H1",
              "center_point": {"x": 10.3, "y": 10.2, "z": 30.0}}]
    dev_z = run(rows_z, cals, asm_z, walls=[])["categories"]["holdown"]["devices"][0]
    assert dev_z["status"] == "NEEDS_REVIEW", dev_z
    assert "different level" in dev_z["reason"], dev_z["reason"]
    assert dev_z.get("target_id") is None, dev_z  # nothing claimed
    # same floor -> normal MATCH, no level note
    asm_same = [{"id": "rev_asm_001", "pdf_mark_candidate": "H1",
                 "center_point": {"x": 10.3, "y": 10.2, "z": 1.0}}]
    dev_same = run(rows_z, cals, asm_same,
                   walls=[])["categories"]["holdown"]["devices"][0]
    assert dev_same["status"] == "MATCH", dev_same
    assert "different level" not in dev_same["reason"], dev_same["reason"]
    # no Z on the row -> dormant, never guesses
    assert "different level" not in reg["row_overrides"]["s1_h1_a"]["reason"]

    # R-18: an unmarked Revit target is "unclassified" (no schedule spec
    # matched the family), a marked one that nothing claimed is "unmatched".
    asm2 = asm + [{"id": "rev_asm_003", "pdf_mark_candidate": None,
                   "center_point": {"x": 900.0, "y": 900.0}},
                  {"id": "rev_asm_004", "pdf_mark_candidate": "H9",
                   "center_point": {"x": 800.0, "y": 800.0}}]
    hd2 = run(rows, cals, asm2, walls=[])["categories"]["holdown"]
    causes = {d["id"]: d["cause"] for d in hd2["revit_only_detail"]}
    assert causes == {"rev_asm_003": "unclassified",
                      "rev_asm_004": "unmatched"}, causes

    # wall segment distance
    seg = {"segment": ((0.0, 0.0), (10.0, 0.0))}
    assert abs(segment_distance({"x": 5, "y": 3}, seg) - 3) < 1e-9
    assert sw_token('N-INT-LB-54-SO-6" SW1') == "SW-1"

    # Same-sheet same-mark rows are NEVER the same physical device, however
    # close -- a sheet draws each element once. Two H1 callouts 1ft apart on
    # S1 (e.g. paired hold-downs at a panel edge) must stay two devices.
    paired_rows = [
        {"id": "s1_h1_left", "sheet": "S1", "category": "holdown", "mark": "H1",
         "status": "PDF_ONLY", "pdf_point": {"x": 140, "y": 860}},   # (10, 10)
        {"id": "s1_h1_right", "sheet": "S1", "category": "holdown", "mark": "H1",
         "status": "PDF_ONLY", "pdf_point": {"x": 144, "y": 860}},   # (11, 10)
    ]
    hd3 = run(paired_rows, cals, asm, walls=[])["categories"]["holdown"]
    assert hd3["summary"]["physical_devices"] == 2, hd3["summary"]

    # Ambiguous assignment: two same-mark Revit targets nearly equidistant
    # from one device must NOT be force-matched to whichever is marginally
    # closer -- that's a coin flip, not a match. NEEDS_REVIEW instead, and
    # neither target is silently claimed (so a legitimate distinct device
    # could still claim the correct one).
    asm_ambiguous = [
        {"id": "rev_asm_near_a", "pdf_mark_candidate": "H1",
         "center_point": {"x": 10.4, "y": 10.0}},   # 0.40 ft away
        {"id": "rev_asm_near_b", "pdf_mark_candidate": "H1",
         "center_point": {"x": 9.7, "y": 10.0}},    # 0.30 ft away, nearly tied
    ]
    hd4 = run(rows, cals, asm_ambiguous, walls=[])["categories"]["holdown"]
    dev4 = next(d for d in hd4["devices"] if d["mark"] == "H1")
    assert dev4["status"] == "NEEDS_REVIEW", dev4
    assert "Ambiguous" in dev4["reason"], dev4["reason"]
    assert dev4.get("target_id") is None, dev4          # no target consumed
    assert hd4["summary"]["revit_only"] == 2, hd4["summary"]  # both left free

    # A decisive nearest candidate (well clear of the ambiguity margin) still
    # matches normally -- the fix must not make every pairing NEEDS_REVIEW.
    asm_decisive = [
        {"id": "rev_asm_close", "pdf_mark_candidate": "H1",
         "center_point": {"x": 10.1, "y": 10.0}},   # 0.10 ft away
        {"id": "rev_asm_far", "pdf_mark_candidate": "H1",
         "center_point": {"x": 15.0, "y": 10.0}},   # 5.0 ft away -- not close
    ]
    hd5 = run(rows, cals, asm_decisive, walls=[])["categories"]["holdown"]
    dev5 = next(d for d in hd5["devices"] if d["mark"] == "H1")
    assert dev5["status"] == "MATCH" and dev5["target_id"] == "rev_asm_close", dev5

    # Gate 2: adaptive match gate widens with registration residual.
    cals_noisy = {
        "S1": {"point_pairs": pairs,
               "transform": {"scale": 4.0},
               "quality": {"solve_rms_residual_pt": 8.0}},
    }
    rows_noisy = [{"id": "s1_h1_a", "sheet": "S1", "category": "holdown",
                   "mark": "H1", "status": "MATCH",
                   "pdf_point": {"x": 140, "y": 860}}]  # (10,10)
    asm_noisy = [{"id": "rev_asm_001", "pdf_mark_candidate": "H1",
                  "center_point": {"x": 13.0, "y": 10.0}}]  # 3.0 ft away
    reg_noisy = run(rows_noisy, cals_noisy, asm_noisy, walls=[])
    dev_noisy = reg_noisy["categories"]["holdown"]["devices"][0]
    assert dev_noisy["status"] == "MATCH", dev_noisy
    assert "widened from 2 ft" in dev_noisy["reason"], dev_noisy["reason"]

    # Gate never widens past MATCH_GATE_CEILING_MULT * base_ft.
    cals_awful = {
        "S1": {"point_pairs": pairs,
               "transform": {"scale": 0.5},
               "quality": {"solve_rms_residual_pt": 100.0}},
    }
    asm_far = [{"id": "rev_asm_001", "pdf_mark_candidate": "H1",
                "center_point": {"x": 10.0 + MATCH_FT * 3 + 1, "y": 10.0}}]
    dev_awful = run(rows_noisy, cals_awful, asm_far,
                    walls=[])["categories"]["holdown"]["devices"][0]
    assert dev_awful["status"] == "PDF_ONLY", dev_awful

    # Missing/incomplete registration_quality must never NARROW the gate.
    dev_plain = run(rows, cals, asm, walls=[])["categories"]["holdown"]["devices"][0]
    assert dev_plain["status"] == "MATCH", dev_plain

    print("device_match self-check OK")
