"""Leader-dot anchor snap (accuracy Phase 2).

A holdown callout's true location is the leader's target dot on the wall, not
the label text — drafters park the "H1" text wherever it fits and draw a
leader to the actual device. Anchoring at the text inflates every distance by
the leader length (live case: s-205_holdown_h1_003 measured 2.04 ft against
the 2.00 ft gate purely from label offset).

Post-extraction pass over AIConvert_pdf holdowns[] (the detectors are frozen —
this runs downstream of them). A callout is re-anchored ONLY when the vector
layer proves the link: a leader segment with one endpoint near the label and
the other near a small filled dot. No leader, no move — on hatch-dense
structural sheets anything looser false-snaps.

The original label point is kept as label_point for audit; overlays and
matching both consume the corrected center_point automatically.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

SEARCH_RADIUS_PT = 45.0    # ~2.5 ft @ 3/16" scale — max plausible leader length
DOT_MAX_SIZE_PT = 7.0      # filled anchor dots / arrowheads are ~2-6 pt across
LABEL_TOL_PT = 25.0        # leader start must be this close to the label point
DOT_TOL_PT = 8.0           # leader end must be this close to the dot centre
MIN_SNAP_PT = 3.0          # already on the dot — nothing to fix


def _page_vectors(page) -> tuple[list[tuple[float, float]], list[tuple]]:
    """Small filled dots + line/bezier segment endpoints from the vector layer."""
    dots: list[tuple[float, float]] = []
    segs: list[tuple] = []
    for d in page.get_drawings():
        r = d["rect"]
        if d.get("fill") is not None and r.width <= DOT_MAX_SIZE_PT and r.height <= DOT_MAX_SIZE_PT:
            dots.append(((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))
        for it in d["items"]:
            if it[0] == "l":
                segs.append(((it[1].x, it[1].y), (it[2].x, it[2].y)))
            elif it[0] == "c":  # bezier leader — endpoints are what matter
                segs.append(((it[1].x, it[1].y), (it[4].x, it[4].y)))
    return dots, segs


def _snap_one(label: tuple[float, float], dots, segs) -> tuple[float, float] | None:
    """The dot a leader connects this label to, or None."""
    lx, ly = label
    near_dots = [(dx, dy) for dx, dy in dots
                 if math.hypot(dx - lx, dy - ly) <= SEARCH_RADIUS_PT]
    if not near_dots:
        return None
    best: tuple[float, tuple[float, float]] | None = None
    for (ax, ay), (bx, by) in segs:
        for (sx, sy), (ex, ey) in (((ax, ay), (bx, by)), ((bx, by), (ax, ay))):
            if math.hypot(sx - lx, sy - ly) > LABEL_TOL_PT:
                continue
            for dx, dy in near_dots:
                if math.hypot(ex - dx, ey - dy) <= DOT_TOL_PT:
                    dist = math.hypot(dx - lx, dy - ly)
                    if best is None or dist < best[0]:
                        best = (dist, (dx, dy))
    if best is None or best[0] < MIN_SNAP_PT:
        return None
    return best[1]


def snap_holdowns(ai_pdf: dict[str, Any], pdf_path: Path) -> dict[str, Any]:
    """Re-anchor holdown callouts at their leader dots (in place; returns ai_pdf).
    Adds ai_pdf['leader_anchor'] stats — honest accounting of what moved."""
    import fitz

    holdowns = ai_pdf.get("holdowns") or []
    stats = {"total": len(holdowns), "snapped": 0, "kept": 0, "max_move_pt": 0.0}
    if not holdowns or not Path(pdf_path).exists():
        ai_pdf["leader_anchor"] = {**stats, "note": "no holdowns or PDF missing"}
        return ai_pdf

    page_cache: dict[int, tuple[list, list]] = {}
    with fitz.open(pdf_path) as doc:
        for h in holdowns:
            c = h.get("center_point") or {}
            pi = h.get("page_index")
            if c.get("x") is None or pi is None or not (0 <= pi < doc.page_count):
                stats["kept"] += 1
                continue
            if pi not in page_cache:
                page_cache[pi] = _page_vectors(doc[pi])
            dots, segs = page_cache[pi]
            hit = _snap_one((float(c["x"]), float(c["y"])), dots, segs)
            if hit is None:
                stats["kept"] += 1
                continue
            move = math.hypot(hit[0] - float(c["x"]), hit[1] - float(c["y"]))
            h["label_point"] = {"x": c["x"], "y": c["y"]}
            h["center_point"] = {**c, "x": round(hit[0], 2), "y": round(hit[1], 2)}
            h["anchor"] = "leader_dot"
            stats["snapped"] += 1
            stats["max_move_pt"] = max(stats["max_move_pt"], round(move, 2))
    ai_pdf["leader_anchor"] = stats
    return ai_pdf


def snap_element_marks(intel: dict[str, Any], pdf_path: Path) -> dict[str, Any]:
    """Same snap for the generalized pipeline: element_intelligence
    sheets[].marks[] holdown rows carry center_pdf [x, y]."""
    import fitz

    stats = {"total": 0, "snapped": 0, "kept": 0, "max_move_pt": 0.0}
    sheets = intel.get("sheets") or []
    if not sheets or not Path(pdf_path).exists():
        intel["leader_anchor"] = {**stats, "note": "no sheets or PDF missing"}
        return intel

    page_cache: dict[int, tuple[list, list]] = {}
    with fitz.open(pdf_path) as doc:
        for sh in sheets:
            pi = sh.get("page_index")
            if pi is None or not (0 <= pi < doc.page_count):
                continue
            for m in sh.get("marks") or []:
                if m.get("category") != "holdown" or not m.get("center_pdf"):
                    continue
                stats["total"] += 1
                if pi not in page_cache:
                    page_cache[pi] = _page_vectors(doc[pi])
                dots, segs = page_cache[pi]
                cx, cy = float(m["center_pdf"][0]), float(m["center_pdf"][1])
                hit = _snap_one((cx, cy), dots, segs)
                if hit is None:
                    stats["kept"] += 1
                    continue
                m["label_point"] = [cx, cy]
                m["center_pdf"] = [round(hit[0], 2), round(hit[1], 2)]
                m["anchor"] = "leader_dot"
                stats["snapped"] += 1
                stats["max_move_pt"] = max(stats["max_move_pt"],
                                           round(math.hypot(hit[0] - cx, hit[1] - cy), 2))
    intel["leader_anchor"] = stats
    return intel


if __name__ == "__main__":
    # Self-check: synthetic page — "H1" label, leader line, filled dot.
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((100, 100), "H1", fontsize=10)
    shape = page.new_shape()
    shape.draw_line(fitz.Point(108, 104), fitz.Point(133, 127))
    shape.finish(width=0.5)
    shape.draw_circle(fitz.Point(135, 129), 2.0)
    shape.finish(fill=(0, 0, 0))
    shape.commit()
    import tempfile, os
    tmp = os.path.join(tempfile.gettempdir(), "leader_anchor_selfcheck.pdf")
    doc.save(tmp)
    doc.close()

    ai = {"holdowns": [{"id": "t1", "page_index": 0,
                        "center_point": {"x": 105.0, "y": 103.0, "space": "pdf_page"}}]}
    out = snap_holdowns(ai, Path(tmp))
    h = out["holdowns"][0]
    assert h.get("anchor") == "leader_dot", out["leader_anchor"]
    assert math.hypot(h["center_point"]["x"] - 135, h["center_point"]["y"] - 129) < 3, h
    assert h["label_point"]["x"] == 105.0
    # No-leader label must NOT move.
    ai2 = {"holdowns": [{"id": "t2", "page_index": 0,
                         "center_point": {"x": 300.0, "y": 300.0}}]}
    out2 = snap_holdowns(ai2, Path(tmp))
    assert "anchor" not in out2["holdowns"][0]
    assert out2["leader_anchor"]["kept"] == 1
    print("leader_anchor self-check OK")
