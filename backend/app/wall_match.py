"""Shear-wall matching: PDF SW-x callouts vs Revit wall centerlines.

Geometry differs from hold-downs: a SW callout hexagon hangs off the wall on a
leader, so the natural distance is POINT-TO-SEGMENT (callout anchor to the
transformed wall centerline), and the gate is a wider, separately documented
constant — the 16/40pt hold-down thresholds in compare.py are untouched.

MATCH stays gated on registration.registration_usable(calibration): without a
verified per-sheet calibration every pairing is NEEDS_REVIEW, never MATCH.
"""

from __future__ import annotations

import logging
import math
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

from . import registration

# ponytail: tuned on Madera S-202 ground truth; knobs, not gospel.
# All thresholds configurable via env vars.
SW_MATCH_MAX_PT = float(os.environ.get("QAQC_SW_MATCH_MAX_PT", "60.0"))
SW_LOCATION_MISMATCH_MAX_PT = float(os.environ.get("QAQC_SW_LOCATION_MISMATCH_MAX_PT", "120.0"))

SW_TOKEN_RE = re.compile(r"\bSW[- ]?(\d{1,2})\b", re.IGNORECASE)

# Leader-line anchor correction: a SW callout bubble hangs off the wall on a
# leader line; the physical reference is the leader TIP, not the bubble.
LEADER_ATTACH_TOL_PT = 18.0    # leader must start this close to the bubble
LEADER_MIN_LEN_PT = float(os.environ.get("QAQC_LEADER_MIN_LEN", "8.0"))
LEADER_MAX_LEN_PT = float(os.environ.get("QAQC_LEADER_MAX_LEN", "220.0"))
MAX_LEADER_CANDIDATES = 6


def extract_leader_segments(page: Any) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Straight vector segments on a fitz page, sized like leader lines.
    Best-effort: drawing extraction failures return [] (anchors stay bubbles)."""
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    try:
        for path in page.get_drawings():
            for item in path.get("items", []):
                if item[0] != "l":
                    continue
                p1, p2 = item[1], item[2]
                a, b = (float(p1.x), float(p1.y)), (float(p2.x), float(p2.y))
                if LEADER_MIN_LEN_PT <= math.hypot(b[0] - a[0], b[1] - a[1]) <= LEADER_MAX_LEN_PT:
                    segments.append((a, b))
    except (AttributeError, TypeError, ValueError, OSError):
        return []
    return segments


def leader_tips(
    anchor: tuple[float, float],
    segments: list[tuple[tuple[float, float], tuple[float, float]]],
) -> list[tuple[float, float]]:
    """Far endpoints of segments that start at the callout bubble — the
    physical points the drafter was actually pointing at."""
    tips: list[tuple[float, float, float]] = []  # (attach_dist, x, y)
    ax, ay = anchor
    for a, b in segments:
        for near, far in ((a, b), (b, a)):
            attach = math.hypot(near[0] - ax, near[1] - ay)
            if attach <= LEADER_ATTACH_TOL_PT:
                tips.append((attach, far[0], far[1]))
                break
    tips.sort(key=lambda t: t[0])
    return [(x, y) for _, x, y in tips[:MAX_LEADER_CANDIDATES]]


def sw_token(type_name: str | None) -> str | None:
    """'N-INT-LB-54-SO-6" SW1' -> 'SW-1' (normalized with hyphen)."""
    if not type_name:
        return None
    m = SW_TOKEN_RE.search(type_name)
    return f"SW-{int(m.group(1))}" if m else None


def normalize_sw_mark(mark: str) -> str:
    m = SW_TOKEN_RE.search(mark)
    return f"SW-{int(m.group(1))}" if m else mark.upper()


def point_to_segment_distance(
    p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> float:
    """Clamped-projection distance from point p to segment ab."""
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    seg_len2 = dx * dx + dy * dy
    if seg_len2 <= 1e-12:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _wall_records(revit_walls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for w in revit_walls:
        token = sw_token(w.get("type_name"))
        line = w.get("centerline")
        if not token or not line or len(line) != 2:
            continue
        out.append({"id": w.get("id"), "type_name": w.get("type_name"),
                    "token": token, "centerline_ft": line})
    return out


def drawn_wall_orientation_deg(
    anchor: tuple[float, float],
    wall_runs: list[dict[str, Any]] | None,
    inverse_matrix: list[float] | None,
    max_distance_pt: float = 45.0,
) -> float | None:
    """Direction of the wall actually DRAWN at this callout's anchor, in
    MODEL space degrees, or None when no drawn run is near enough.

    wall_runs come from pdf_wall_geometry.extract_wall_runs(page). Both ends
    of the run are inverse-projected through the sheet's OWN registration
    before the angle is measured, so the result is directly comparable to a
    Revit wall's direction and any rotation the sheet carries is handled by
    the same transform that handles every other PDF<->model conversion --
    no assumption that plan north matches model north."""
    if not wall_runs or not inverse_matrix or len(inverse_matrix) != 6:
        return None
    from . import pdf_wall_geometry

    run = pdf_wall_geometry.nearest_run(wall_runs, anchor, max_distance_pt)
    if run is None:
        return None
    a, b, c, d, e, f = inverse_matrix
    (ax, ay), (bx, by) = run["segment"]
    p = (a * ax + b * ay + e, c * ax + d * ay + f)
    q = (a * bx + b * by + e, c * bx + d * by + f)
    return math.degrees(math.atan2(q[1] - p[1], q[0] - p[0])) % 180.0


def match_shear_walls(
    sheet_marks: list[dict[str, Any]],
    revit_walls: list[dict[str, Any]],
    calibration: dict[str, Any] | None,
    leader_segments: list[tuple[tuple[float, float], tuple[float, float]]] | None = None,
    wall_runs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Greedy one-to-one SW matching for one sheet.

    sheet_marks: element_intelligence marks with category=="shear_wall".
    Returns {usable, rows:[{pdf_mark_id, mark, verdict, distance_pdf_points,
    revit_wall_id, ...}], summary}.
    """
    callouts = [
        {"id": m["id"], "mark": normalize_sw_mark(m["mark"]),
         "point": (m["center_pdf"][0], m["center_pdf"][1])}
        for m in sheet_marks
        if m.get("category") == "shear_wall" and m.get("center_pdf")
    ]
    walls = _wall_records(revit_walls)
    usable = registration.registration_usable(calibration)
    # `.get("transform", {})` returns the stored value, and a failed calibration
    # stores transform:None — so the default never fires and None.get() raises.
    matrix = ((calibration or {}).get("transform") or {}).get("matrix")

    rows: list[dict[str, Any]] = []
    if matrix is None:
        for c in callouts:
            rows.append(_row(c, None, None, "NEEDS_REVIEW",
                             "No calibration for this sheet; distances unavailable."))
        return _report(rows, walls, set(), usable=False)

    walls_pdf = []
    for w in walls:
        (x1, y1), (x2, y2) = w["centerline_ft"]
        a = registration.apply_transform(matrix, float(x1), float(y1))
        b = registration.apply_transform(matrix, float(x2), float(y2))
        walls_pdf.append({**w, "segment_pdf": (a, b)})

    # Anchor candidates per callout: the bubble itself + leader-line tips.
    # A tip is accepted per-pair only when it REDUCES the distance — a wrong
    # leader can never make a result worse than the bubble baseline.
    anchors_by_callout: list[list[tuple[str, tuple[float, float]]]] = []
    for c in callouts:
        anchors = [("bubble", c["point"])]
        if leader_segments:
            anchors += [("leader_tip", t) for t in leader_tips(c["point"], leader_segments)]
        anchors_by_callout.append(anchors)

    candidates: list[tuple[float, int, int, str, tuple[float, float]]] = []
    for ci, c in enumerate(callouts):
        for wi, w in enumerate(walls_pdf):
            if w["token"] != c["mark"]:
                continue
            best_d, best_method, best_pt = None, "bubble", c["point"]
            for method, pt in anchors_by_callout[ci]:
                d = point_to_segment_distance(pt, *w["segment_pdf"])
                if best_d is None or d < best_d:
                    best_d, best_method, best_pt = d, method, pt
            if best_d is not None and best_d <= SW_LOCATION_MISMATCH_MAX_PT:
                candidates.append((best_d, ci, wi, best_method, best_pt))
    candidates.sort(key=lambda t: t[0])

    used_c: set[int] = set()
    used_w: set[int] = set()
    for d, ci, wi, anchor_method, anchor_pt in candidates:
        if ci in used_c or wi in used_w:
            continue
        used_c.add(ci)
        used_w.add(wi)
        c, w = callouts[ci], walls_pdf[wi]
        if not usable:
            verdict, reason = "NEEDS_REVIEW", (
                f"Nearest same-token wall at {d:.1f}pt, but calibration is not "
                "verified for MATCH (registration gate)."
            )
        elif d <= SW_MATCH_MAX_PT:
            via = " (via leader tip)" if anchor_method == "leader_tip" else ""
            verdict, reason = "MATCH", (
                f"Same token {c['mark']}; callout-to-centerline distance "
                f"{d:.1f}pt <= {SW_MATCH_MAX_PT:.0f}pt{via}."
            )
        else:
            verdict, reason = "LOCATION_MISMATCH", (
                f"Same token {c['mark']}; distance {d:.1f}pt in "
                f"({SW_MATCH_MAX_PT:.0f}, {SW_LOCATION_MISMATCH_MAX_PT:.0f}]pt."
            )
        row = _row(c, w, d, verdict, reason)
        row["anchor_method"] = anchor_method
        row["anchor_point_pdf"] = [round(anchor_pt[0], 2), round(anchor_pt[1], 2)]
        # PDF-side measured evidence: the direction of the wall actually
        # drawn at this anchor. Consumed downstream as a tie-breaker between
        # otherwise-equidistant same-mark candidates.
        drawn_deg = drawn_wall_orientation_deg(
            anchor_pt, wall_runs,
            ((calibration or {}).get("transform") or {}).get("inverse_matrix"))
        if drawn_deg is not None:
            row["orientation_deg"] = round(drawn_deg, 1)
        rows.append(row)

    for ci, c in enumerate(callouts):
        if ci not in used_c:
            rows.append(_row(c, None, None, "PDF_ONLY",
                             f"No {c['mark']} wall centerline within "
                             f"{SW_LOCATION_MISMATCH_MAX_PT:.0f}pt."))
    matched_wall_ids = {r["revit_wall_id"] for r in rows if r["revit_wall_id"]}
    return _report(rows, walls, matched_wall_ids, usable)


def _row(c, w, d, verdict, reason) -> dict[str, Any]:
    return {
        "pdf_mark_id": c["id"],
        "mark": c["mark"],
        "pdf_point": {"x": c["point"][0], "y": c["point"][1]},
        "revit_wall_id": w["id"] if w else None,
        "revit_wall_type": w["type_name"] if w else None,
        "wall_segment_pdf": (
            [[round(v, 2) for v in w["segment_pdf"][0]],
             [round(v, 2) for v in w["segment_pdf"][1]]]
            if w and "segment_pdf" in w else None
        ),
        "distance_pdf_points": round(d, 2) if d is not None else None,
        "verdict": verdict,
        "reason": reason,
    }


def _report(rows, walls, matched_wall_ids, usable) -> dict[str, Any]:
    unmatched_walls = [
        {"revit_wall_id": w["id"], "token": w["token"], "type_name": w["type_name"],
         "verdict": "REVIT_ONLY"}
        for w in walls
        if w["id"] not in matched_wall_ids
    ]
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    counts["REVIT_ONLY"] = len(unmatched_walls)
    return {
        "usable_calibration": usable,
        "thresholds": {
            "sw_match_max_pt": SW_MATCH_MAX_PT,
            "sw_location_mismatch_max_pt": SW_LOCATION_MISMATCH_MAX_PT,
        },
        "rows": rows,
        "unmatched_revit_walls": unmatched_walls,
        "summary": counts,
    }


if __name__ == "__main__":
    assert sw_token('N-INT-LB-54-SO-6" SW1') == "SW-1"
    assert sw_token('N-EXT-LB-54-SO-6" SW-2') == "SW-2"
    assert sw_token("plain wall") is None
    assert point_to_segment_distance((0, 5), (0, 0), (10, 0)) == 5.0
    assert point_to_segment_distance((-3, 4), (0, 0), (10, 0)) == 5.0   # endpoint clamp
    assert point_to_segment_distance((1, 1), (2, 2), (2, 2)) == math.hypot(1, 1)  # degenerate

    identity_cal = {
        "calibration_source": "manual_verified",
        "transform": {"matrix": [1, 0, 0, 1, 0, 0]},
        "quality": {"match_allowed": True, "confidence": "high"},
    }
    marks = [
        {"id": "m1", "category": "shear_wall", "mark": "SW-1", "center_pdf": [5, 3]},
        {"id": "m2", "category": "shear_wall", "mark": "SW-2", "center_pdf": [100, 100]},
        {"id": "m3", "category": "shear_wall", "mark": "SW-1", "center_pdf": [900, 900]},
    ]
    walls = [
        {"id": "w1", "type_name": 'X SW1', "centerline": [[0, 0], [10, 0]]},
        {"id": "w2", "type_name": 'X SW-2', "centerline": [[95, 95], [105, 95]]},
    ]
    rep = match_shear_walls(marks, walls, identity_cal)
    verdicts = {r["pdf_mark_id"]: r["verdict"] for r in rep["rows"]}
    assert verdicts == {"m1": "MATCH", "m2": "MATCH", "m3": "PDF_ONLY"}, verdicts
    rep2 = match_shear_walls(marks, walls, None)
    assert all(r["verdict"] == "NEEDS_REVIEW" for r in rep2["rows"])
    bad_cal = {**identity_cal, "quality": {"match_allowed": False, "confidence": "low"}}
    rep3 = match_shear_walls(marks, walls, bad_cal)
    assert all(r["verdict"] in ("NEEDS_REVIEW", "PDF_ONLY") for r in rep3["rows"])

    # Leader-tip correction: bubble 70pt off the wall (LOCATION_MISMATCH),
    # leader from the bubble down to the wall -> tip distance 5pt -> MATCH.
    far_marks = [{"id": "f1", "category": "shear_wall", "mark": "SW-1",
                  "center_pdf": [5, 70]}]
    segs = [((6.0, 68.0), (5.0, 5.0))]
    rep4 = match_shear_walls(far_marks, walls, identity_cal, leader_segments=segs)
    r4 = rep4["rows"][0]
    assert r4["verdict"] == "MATCH" and r4["anchor_method"] == "leader_tip", r4
    # Without segments it stays an honest LOCATION_MISMATCH.
    rep5 = match_shear_walls(far_marks, walls, identity_cal)
    assert rep5["rows"][0]["verdict"] == "LOCATION_MISMATCH", rep5["rows"][0]
    # A misleading leader pointing AWAY never worsens the bubble baseline.
    bad_segs = [((6.0, 68.0), (500.0, 500.0))]
    rep6 = match_shear_walls(far_marks, walls, identity_cal, leader_segments=bad_segs)
    assert rep6["rows"][0]["distance_pdf_points"] == rep5["rows"][0]["distance_pdf_points"]
    assert leader_tips((0, 0), [((0.1, 0.1), (9, 9)), ((99, 99), (50, 50))]) == [(9.0, 9.0)]
    print("wall_match self-check OK:", rep["summary"], "| leader:", r4["reason"])
