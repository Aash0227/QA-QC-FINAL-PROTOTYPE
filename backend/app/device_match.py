"""Physical-device matching layer (docs/ACCURACY_100_PLAN.md P1-P3).

The frozen pipeline scores SHEET APPEARANCES: the same physical hold-down
drawn on S-201, S-202 and S-205 becomes three independent rows, so one
device can be MATCH on one sheet and PDF_ONLY on another. This module
re-accounts everything at the physical-device level, in model FEET:

P1  inverse-project every sheet callout to model space (chirality-aware —
    PDF y is flipped vs model y) and cluster same-mark points across sheets
    into physical devices;
P2  global one-to-one assignment devices <-> Revit assemblies with explicit
    gates in feet (no fake matches: model-space points come only from the
    verified per-sheet calibrations that the frozen pipeline produced);
P3  honest device statuses folded back onto the sheet rows, original
    per-sheet verdicts retained as sheet_status for audit.
"""
from __future__ import annotations

import logging
import math
import os
import re
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ponytail: tuned on Madera ground truth; knobs, not gospel -- all overridable
# via env so a project with a different drafting convention or element
# density isn't stuck with these exact numbers.
CLUSTER_TOL_FT = float(os.environ.get("QAQC_DEVICE_CLUSTER_TOL_FT", "3.0"))
    # same mark within this box, on DIFFERENT sheets, = same physical device
    # re-drawn. This covers cross-sheet registration noise (each sheet solves
    # its own transform), not element footprint -- see build_devices()
    # same-sheet guard.
MATCH_FT = float(os.environ.get("QAQC_DEVICE_MATCH_FT", "2.0"))
    # device-to-assembly gate for MATCH
MISMATCH_FT = float(os.environ.get("QAQC_DEVICE_MISMATCH_FT", "6.0"))
    # beyond MATCH up to this = LOCATION_MISMATCH
LEVEL_DELTA_FT = float(os.environ.get("QAQC_DEVICE_LEVEL_DELTA_FT", "8.0"))
    # |dz| above this = probably a different floor (R-03)
AMBIGUITY_MARGIN_FT = float(os.environ.get("QAQC_DEVICE_AMBIGUITY_MARGIN_FT", "1.0"))
    # if the runner-up same-mark candidate is this close behind the best one,
    # refuse to auto-pick -- a confident wrong MATCH is worse than a
    # NEEDS_REVIEW (accuracy > match rate).
MATCH_GATE_CEILING_MULT = float(os.environ.get("QAQC_DEVICE_MATCH_GATE_CEILING_MULT", "3.0"))
    # the adaptive match gate (base + registration residual) never exceeds
    # base_ft * this -- a bad calibration must surface as a registration
    # blocker elsewhere, not silently widen the match gate until it swallows
    # everything nearby (Stage 9 §D: "registration error eats the budget").
SW_TOKEN_RE = re.compile(r"SW\s*-?\s*(\d+)", re.IGNORECASE)


# ---------------------------------------------------------------- P1: fit

def inverse_from_calibration(cal: dict[str, Any] | None) -> Callable | None:
    """Exact pdf(pt)->model(ft) inverse from the calibration's stored
    transform.inverse_matrix — the authoritative transform, chirality
    already resolved by registration.py. Preferred over refitting."""
    matrix = ((cal or {}).get("transform") or {}).get("inverse_matrix")
    if not matrix or len(matrix) != 6:
        return None
    a, b, c, d, e, f = matrix

    def inv(u, v, _a=a, _b=b, _c=c, _d=d, _e=e, _f=f):
        return (_a * u + _b * v + _e, _c * u + _d * v + _f)

    return inv


def fit_inverse(point_pairs: list[dict[str, Any]]) -> Callable | None:
    """pdf(pt) -> model(ft) inverse of the sheet's similarity transform.
    Tries both chiralities and keeps the lower-residual fit.

    Needs >= 3 pairs: with only 2, BOTH chiralities fit exactly and the
    winner is float noise — a mirrored transform scatters every device
    20-60 ft off. Calibrations with 2 pairs (benchmark_2pt) carry
    inverse_matrix, so run() never reaches this path for them."""
    if not point_pairs or len(point_pairs) < 3:
        return None
    best = None
    for flip in (1.0, -1.0):
        fitted = _fit_one(point_pairs, flip)
        if fitted and (best is None or fitted[1] < best[1]):
            best = fitted
    return best[0] if best else None


def _fit_one(pairs, flip):
    src = [(p["revit_point"]["x"], flip * p["revit_point"]["y"]) for p in pairs]
    dst = [(p["pdf_point"]["x"], p["pdf_point"]["y"]) for p in pairs]
    n = len(src)
    mx = sum(x for x, _ in src) / n
    my = sum(y for _, y in src) / n
    ux = sum(x for x, _ in dst) / n
    uy = sum(y for _, y in dst) / n
    sxx = sxy = ss = 0.0
    for (x, y), (u, v) in zip(src, dst):
        dx, dy, du, dv = x - mx, y - my, u - ux, v - uy
        sxx += dx * du + dy * dv
        sxy += dx * dv - dy * du
        ss += dx * dx + dy * dy
    if ss <= 0:
        return None
    a, b = sxx / ss, sxy / ss
    det = a * a + b * b
    if det <= 0:
        return None
    tx = ux - a * mx + b * my
    ty = uy - b * mx - a * my

    def inv(u, v, _a=a, _b=b, _tx=tx, _ty=ty, _det=det, _flip=flip):
        u2, v2 = u - _tx, v - _ty
        return ((_a * u2 + _b * v2) / _det,
                _flip * (-_b * u2 + _a * v2) / _det)

    rms = math.sqrt(sum(
        (a * x - b * y + tx - u) ** 2 + (b * x + a * y + ty - v) ** 2
        for (x, y), (u, v) in zip(src, dst)) / n)
    return inv, rms


# ------------------------------------------------------------ P1: devices

def row_z_ft(row: dict[str, Any]) -> float | None:
    """Model-space Z of a PDF callout row, when the row carries one (R-03).

    The inverse transform is 2D, so a projected callout has no Z of its own —
    only an explicit elevation/level height on the row can supply it. Today's
    element rows carry none, so this returns None everywhere and the
    different-level note below stays dormant; it lights up as soon as the
    extractor starts stamping rows with an elevation."""
    for key in ("elevation_ft", "level_elevation_ft"):
        z = row.get(key)
        if isinstance(z, (int, float)):
            return float(z)
    level = row.get("level")
    if isinstance(level, dict) and isinstance(level.get("elevation_ft"), (int, float)):
        return float(level["elevation_ft"])
    return None


def build_devices(rows: list[dict[str, Any]],
                  inverse_by_sheet: dict[str, Callable],
                  prefix: str) -> tuple[list[dict[str, Any]], int]:
    """Cluster sheet callout rows into physical devices (model feet).
    Returns (devices, rows_without_usable_projection).

    Two rows only ever describe the SAME physical device when they're the same
    mark, on DIFFERENT sheets (one sheet draws each physical element once --
    two same-mark callouts on one sheet, e.g. paired hardware at a panel edge,
    are always two distinct devices, however close together). A prior version
    clustered by same-sheet-blind proximity with a running centroid, which
    could (a) silently merge two real, closely-spaced same-mark hold-downs on
    one sheet into a single device, and (b) chain-drift: the centroid moves as
    members join, so a point just outside CLUSTER_TOL_FT of the true anchor
    could still be absorbed via an intermediate member. Anchoring to the first
    member's location (not a moving centroid) and forbidding same-sheet merges
    closes both false-merge paths."""
    devices: list[dict[str, Any]] = []
    unprojected = 0
    for r in rows:
        inv = inverse_by_sheet.get(r.get("sheet"))
        p = r.get("pdf_point")
        if inv is None or not p:
            unprojected += 1
            continue
        x, y = inv(p["x"], p["y"])
        mark = r.get("mark")
        sheet = r.get("sheet")
        for d in devices:
            if (d["mark"] == mark
                    and sheet not in d["sheets"]
                    and abs(d["_anchor_x"] - x) <= CLUSTER_TOL_FT
                    and abs(d["_anchor_y"] - y) <= CLUSTER_TOL_FT):
                d["appearances"].append(r["id"])
                d["sheets"].append(sheet)
                # centroid for display/matching; anchor (fixed) gates membership
                k = len(d["appearances"])
                d["x"] += (x - d["x"]) / k
                d["y"] += (y - d["y"]) / k
                if d.get("z") is None and row_z_ft(r) is not None:
                    d["z"] = row_z_ft(r)
                break
        else:
            dev = {"mark": mark, "x": x, "y": y,
                   "_anchor_x": x, "_anchor_y": y,
                   "appearances": [r["id"]],
                   "sheets": [sheet]}
            if row_z_ft(r) is not None:
                dev["z"] = row_z_ft(r)
            devices.append(dev)
    for i, d in enumerate(devices, start=1):
        d["id"] = f"{prefix}_dev_{i:03d}"
        d.pop("_anchor_x", None)
        d.pop("_anchor_y", None)
    return devices, unprojected


# --------------------------------------------------------- P2: assignment

def _flag_ambiguous(devices: list[dict[str, Any]],
                    targets: list[dict[str, Any]],
                    distance: Callable[[dict[str, Any], dict[str, Any]], float],
                    mismatch_ft: float) -> None:
    """Mark devices whose best same-mark candidate isn't decisively closer than
    the runner-up. Greedy nearest-neighbor assignment picks A winner, but when
    two candidates are nearly tied it's a coin flip dressed as a distance
    comparison -- exactly the "confident wrong MATCH" this system must refuse
    to produce. Only candidates within mismatch_ft are considered; a distant
    runner-up would never be claimable anyway."""
    for d in devices:
        same_mark = [t for t in targets if t.get("mark") == d["mark"]]
        if len(same_mark) < 2:
            continue
        dists = sorted((distance(d, t), t["id"]) for t in same_mark)
        best_dist, best_id = dists[0]
        second_dist, second_id = dists[1]
        if best_dist <= mismatch_ft and (second_dist - best_dist) < AMBIGUITY_MARGIN_FT:
            d["_ambiguous"] = True
            d["_ambiguous_candidates"] = [best_id, second_id]


def assign(devices: list[dict[str, Any]],
           targets: list[dict[str, Any]],
           distance: Callable[[dict[str, Any], dict[str, Any]], float],
           match_ft: float = MATCH_FT,
           mismatch_ft: float = MISMATCH_FT,
           mark_blind: bool = True,
           registration_quality: dict[str, dict[str, Any]] | None = None) -> None:
    """Global one-to-one assignment. Mutates devices (status/target/dist)
    and targets (claimed flag). Same-mark pass first, then mark-blind
    (-> MARK_MISMATCH). Greedy on globally sorted distances = stable and
    good enough at these densities -- except where two candidates are nearly
    tied, which _flag_ambiguous() catches before any claiming happens."""
    for d in devices:
        d["_match_gate_ft"] = adaptive_match_ft(d, registration_quality or {}, match_ft)
    _flag_ambiguous(devices, targets, distance, mismatch_ft)
    pairs = sorted(
        (distance(d, t), di, ti)
        for di, d in enumerate(devices)
        for ti, t in enumerate(targets)
        if d["mark"] and d["mark"] == t.get("mark"))
    _claim(pairs, devices, targets, mismatch_ft, match_ft, same_mark=True)
    if mark_blind:
        # a device drawn with the wrong mark still occupies the spot —
        # meaningful for sparse point devices; too noisy for dense walls.
        pairs = sorted(
            (distance(d, t), di, ti)
            for di, d in enumerate(devices)
            for ti, t in enumerate(targets))
        _claim(pairs, devices, targets, match_ft, match_ft, same_mark=False)
    known_marks = {t.get("mark") for t in targets}
    for d in devices:
        if "status" not in d:
            d["status"] = "PDF_ONLY"
            if d["mark"] not in known_marks:
                d["reason"] = (
                    f"Vocabulary gap: NO Revit element carries mark "
                    f"{d['mark']} at all — the model expresses this type "
                    "differently. Teach a type mapping to resolve every "
                    f"{d['mark']} at once.")
            else:
                d["reason"] = (f"No {d['mark']} Revit device within "
                               f"{mismatch_ft:g} ft of "
                               f"({d['x']:.1f}, {d['y']:.1f}) ft.")


def _claim(pairs, devices, targets, gate_ft, match_ft, same_mark):
    for dist, di, ti in pairs:
        d, t = devices[di], targets[ti]
        if "status" in d or dist > gate_ft:
            continue
        if same_mark and d.get("_ambiguous"):
            # Don't consume a target on an ambiguous pick -- leave both
            # candidates free in case a *different* device unambiguously
            # claims one of them, and surface this one for human review.
            cands = ", ".join(d.get("_ambiguous_candidates", []))
            d["status"] = "NEEDS_REVIEW"
            d["reason"] = (
                f"Ambiguous: two Revit {d['mark']} candidates ({cands}) are "
                f"within {AMBIGUITY_MARGIN_FT:g} ft of each other near "
                f"({d['x']:.1f}, {d['y']:.1f}) ft in model space -- refusing "
                "to auto-pick. Resolve by comparing sheet context/leader lines.")
            continue
        if t.get("_claimed"):
            continue
        if same_mark:
            gate = d.get("_match_gate_ft", match_ft)
            dz, tz = d.get("z"), t.get("z")
            off_level = (isinstance(dz, (int, float)) and isinstance(tz, (int, float))
                        and abs(dz - tz) > LEVEL_DELTA_FT)
            if dist <= gate and off_level:
                # Good XY, wrong floor: not confidently either a MATCH or a
                # LOCATION_MISMATCH (the horizontal evidence disagrees with
                # the vertical evidence) -- surface for a human, claim
                # nothing silently (same pattern as the ambiguous-pick
                # branch above). Dormant until rows carry elevation_ft.
                d["status"] = "NEEDS_REVIEW"
                d["reason"] = (
                    f"Physical device: mark {d['mark']} is {dist:.2f} ft from "
                    f"{t['id']} in plan but Δz≈{abs(dz - tz):.0f} ft — "
                    "different level; refusing to auto-pick.")
                continue
        t["_claimed"] = True
        d["target_id"] = t["id"]
        d["target_mark"] = t.get("mark")
        if "x" in t:
            d["target_point"] = [t["x"], t["y"]]
        if isinstance(t.get("z"), (int, float)):
            d["target_z"] = float(t["z"])   # R-03: carried for the level check
        d["distance_ft"] = round(dist, 2)
        if same_mark:
            gate = d.get("_match_gate_ft", match_ft)
            d["status"] = "MATCH" if dist <= gate else "LOCATION_MISMATCH"
            gate_note = (f" ({'<=' if dist <= gate else '>'} {gate:g} ft MATCH gate"
                        f", widened from {match_ft:g} ft for registration "
                        "uncertainty)" if gate > match_ft else "")
            d["reason"] = (
                f"Physical device: mark {d['mark']} paired with {t['id']} at "
                f"{dist:.2f} ft in model space{gate_note}.")
        else:
            d["status"] = "MARK_MISMATCH"
            d["reason"] = (
                f"Device at ({d['x']:.1f}, {d['y']:.1f}) ft: PDF says "
                f"{d['mark']}, model has {t.get('mark')!r} ({t['id']}) "
                f"{dist:.2f} ft away — check the callout or the family.")


# ------------------------------------------------------------- distances

def adaptive_match_ft(device: dict[str, Any],
                      registration_quality: dict[str, dict[str, Any]],
                      base_ft: float) -> float:
    """Match gate widened by this device's own registration uncertainty
    (Stage 9 §D: a fixed point gate ignores that the calibration's own solve
    residual can eat the whole budget). residual_pt / scale (PDF-pt per
    model-ft) converts the sheet's solve RMS into model feet; a multi-sheet
    device uses its worst sheet (conservative). Missing/non-numeric quality
    data (e.g. a device with no sheets, or a calibration that never recorded
    scale) leaves the gate at base_ft -- this only ever widens the gate, never
    narrows it below the original fixed tolerance."""
    worst_ft = 0.0
    for sheet in device.get("sheets", []):
        q = registration_quality.get(sheet) or {}
        rms_pt, scale = q.get("rms_residual_pt"), q.get("scale")
        if not isinstance(rms_pt, (int, float)) or not isinstance(scale, (int, float)) or scale <= 0:
            continue
        worst_ft = max(worst_ft, rms_pt / scale)
    return min(base_ft + worst_ft, base_ft * MATCH_GATE_CEILING_MULT)


def point_distance(d: dict[str, Any], t: dict[str, Any]) -> float:
    return math.hypot(d["x"] - t["x"], d["y"] - t["y"])


def segment_distance(d: dict[str, Any], t: dict[str, Any]) -> float:
    (x1, y1), (x2, y2) = t["segment"]
    px, py = d["x"] - x1, d["y"] - y1
    vx, vy = x2 - x1, y2 - y1
    ll = vx * vx + vy * vy
    s = 0.0 if ll == 0 else max(0.0, min(1.0, (px * vx + py * vy) / ll))
    return math.hypot(d["x"] - (x1 + s * vx), d["y"] - (y1 + s * vy))


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
                                        # model feet for the adaptive match gate (§Gate 2).
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
                  point_distance)

    # --- shear walls (segment targets)
    sw_rows = [r for r in element_rows if r.get("category") == "shear_wall"
               and r.get("pdf_point")]
    wall_targets = []
    for w in walls:
        tok = sw_token(w.get("type_name") or "")
        cl = w.get("centerline") or []
        if tok and len(cl) == 2:
            wall_targets.append({"id": w.get("id"), "mark": tok,
                                 "segment": (tuple(cl[0]), tuple(cl[1]))})
    # Walls: a drawn SW run maps to SEVERAL Revit wall segments, and the
    # callout bubble sits off the run — wall-appropriate gates + absorb
    # unclaimed same-mark segments near a matched device.
    _run_category(registry, "shear_wall", sw_rows, inverse, wall_targets,
                  segment_distance, mark_blind=False,
                  match_ft=4.0, mismatch_ft=12.0, absorb_same_mark=True)
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


def _run_category(registry, category, rows, inverse, targets, distance,
                  mark_blind=True, match_ft=MATCH_FT,
                  mismatch_ft=MISMATCH_FT, absorb_same_mark=False):
    devices, unprojected = build_devices(rows, inverse, category)
    assign(devices, targets, distance, match_ft=match_ft,
           mismatch_ft=mismatch_ft, mark_blind=mark_blind,
           registration_quality=registry.get("registration_quality"))
    _annotate_reasons(devices)
    claimed = {t["id"] for t in targets if t.pop("_claimed", False)}
    if absorb_same_mark:
        by_id = {d.get("target_id"): d for d in devices if d.get("target_id")}
        matched = [d for d in devices if d.get("status") == "MATCH"]
        for t in targets:
            if t["id"] in claimed:
                continue
            near = [d for d in matched if d["mark"] == t.get("mark")
                    and distance(d, t) <= mismatch_ft]
            if near:
                d = min(near, key=lambda d: distance(d, t))
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

    # Gate 2: adaptive match gate widens with registration residual (Stage 9
    # §D -- a fixed point gate ignores that the calibration's own solve
    # residual can eat the whole budget). rms_residual_pt=8, scale=4 pt/ft ->
    # +2.0 ft on top of the 2.0 ft base = 4.0 ft gate; a device 3.0 ft away
    # (mismatch under the flat gate) now MATCHes because that 3.0 ft is
    # explainable by the sheet's own registration noise.
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

    # Gate never widens past MATCH_GATE_CEILING_MULT * base_ft, however bad
    # the residual -- a garbage calibration must surface as a registration
    # blocker elsewhere, not silently swallow every nearby device. With
    # defaults, ceiling (2.0*3=6.0 ft) == MISMATCH_FT (6.0 ft), so a device
    # just beyond it is never even considered a candidate -> PDF_ONLY, not a
    # gate-widened MATCH.
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

    # Missing/incomplete registration_quality (no scale, or sheet absent) must
    # never NARROW the gate below the flat base -- only ever widen it.
    dev_plain = run(rows, cals, asm, walls=[])["categories"]["holdown"]["devices"][0]
    assert dev_plain["status"] == "MATCH", dev_plain

    print("device_match self-check OK")
