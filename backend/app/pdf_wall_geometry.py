"""Extract DRAWN wall runs from a structural sheet's PDF vector geometry.

Why this exists (Stage 9, Shear Wall validation): the matcher knew where a
callout POINTED but never what the drawn wall WAS. With no PDF-side length or
orientation -- the schedule's LENGTH column literally reads "AS PER PLAN", and
a callout is a point -- two same-mark Revit walls that differ in length or
direction were indistinguishable, so genuinely ambiguous cases could only be
sent to a human. This module supplies the missing PDF-side geometry.

How walls are actually drawn (verified on the real Madera S-202/S-205 sheets
against a Revit wall whose correspondence was already established): a shear
wall is rendered as a dense RUN of short, parallel hatch strokes laid along
the wall -- not as a single long line. Extraction therefore looks for the run
structure rather than any one stroke:

    short strokes  ->  group by shared hatch angle  ->  spatially cluster
    into runs  ->  fit each run's principal axis  ->  drawn wall segment

Deliberately signature-free: no stroke width, colour, layer name, hatch angle
or wall thickness is hardcoded. The hatch angle is DERIVED per page (the
dominant short-stroke orientation), and a run is accepted on density and
collinearity alone, so a project that hatches at a different angle, weight or
spacing still works. Nothing here is Madera-specific.

Returns geometry in PDF points; callers transform to model feet with the
sheet's own registration, exactly as every other PDF-side measurement is.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable

# A hatch tick is short; a wall run is long. Both are expressed relative to
# the page's own linework so a differently-scaled sheet still works.
MAX_TICK_LEN_PT = 8.0          # a hatch stroke is small by construction
ANGLE_BUCKET_DEG = 10.0        # tolerance when grouping ticks by orientation
MIN_TICKS_PER_RUN = 6          # fewer than this is noise, not a wall
MAX_TICK_GAP_PT = 14.0         # neighbouring ticks in one run are close
MIN_RUN_LEN_PT = 12.0          # a run shorter than this is not a wall


def _angle_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Undirected orientation in [0, 180)."""
    return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180.0


def _angle_delta(p: float, q: float) -> float:
    """Smallest undirected angular difference in degrees."""
    d = abs(p - q) % 180.0
    return min(d, 180.0 - d)


def iter_short_strokes(page: Any) -> list[dict[str, Any]]:
    """Every short straight stroke on the page, with its midpoint and angle.

    Best-effort: a page whose drawing extraction fails yields [] so callers
    degrade to their existing point-only behaviour rather than erroring."""
    out: list[dict[str, Any]] = []
    try:
        drawings = page.get_drawings()
    except (AttributeError, TypeError, ValueError, OSError):
        return []
    for path in drawings:
        for item in path.get("items", []):
            if item[0] != "l":
                continue
            try:
                a = (float(item[1].x), float(item[1].y))
                b = (float(item[2].x), float(item[2].y))
            except (AttributeError, TypeError, ValueError):
                continue
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            if not (0.0 < length <= MAX_TICK_LEN_PT):
                continue
            out.append({
                "mid": ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0),
                "angle": _angle_deg(a, b),
                "length": length,
            })
    return out


def dominant_hatch_angles(ticks: Iterable[dict[str, Any]],
                          top_n: int = 2) -> list[float]:
    """The page's prevailing short-stroke orientation(s), derived from the
    data rather than assumed. Hatching is by far the most common source of
    short parallel strokes on a structural sheet, so the modal angle is the
    hatch angle -- whatever convention the drafter used."""
    buckets: dict[int, int] = defaultdict(int)
    for t in ticks:
        buckets[int(t["angle"] // ANGLE_BUCKET_DEG)] += 1
    ranked = sorted(buckets.items(), key=lambda kv: -kv[1])
    return [(k + 0.5) * ANGLE_BUCKET_DEG for k, _ in ranked[:top_n]]


def _cluster_runs(points: list[tuple[float, float]]) -> list[list[tuple[float, float]]]:
    """Single-link spatial clustering of tick midpoints into runs.

    A hatch band is a chain of closely-spaced ticks, so single-link (connect
    anything within MAX_TICK_GAP_PT) is the right shape of clustering here --
    it follows the band along its length without assuming how long it is or
    which way it points. Grid-bucketed so this stays near-linear on the
    ~10k short strokes a real sheet carries."""
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    cell = MAX_TICK_GAP_PT
    for i, p in enumerate(points):
        grid[(int(p[0] // cell), int(p[1] // cell))].append(i)

    seen = [False] * len(points)
    runs: list[list[tuple[float, float]]] = []
    for start in range(len(points)):
        if seen[start]:
            continue
        seen[start] = True
        stack, members = [start], [start]
        while stack:
            i = stack.pop()
            px, py = points[i]
            gx, gy = int(px // cell), int(py // cell)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for j in grid.get((gx + dx, gy + dy), ()):
                        if seen[j]:
                            continue
                        qx, qy = points[j]
                        if math.hypot(qx - px, qy - py) <= MAX_TICK_GAP_PT:
                            seen[j] = True
                            stack.append(j)
                            members.append(j)
        if len(members) >= MIN_TICKS_PER_RUN:
            runs.append([points[i] for i in members])
    return runs


def _principal_segment(points: list[tuple[float, float]]) -> tuple[tuple[float, float], tuple[float, float]]:
    """The run's long axis, as a segment spanning its extent.

    Two-pass: the covariance's principal eigenvector gives the direction
    (robust to the band's width and to ragged ends), then members are
    projected onto it and the extremes become the endpoints."""
    n = len(points)
    cx = sum(p[0] for p in points) / n
    cy = sum(p[1] for p in points) / n
    sxx = syy = sxy = 0.0
    for x, y in points:
        dx, dy = x - cx, y - cy
        sxx += dx * dx
        syy += dy * dy
        sxy += dx * dy
    # principal eigenvector of [[sxx, sxy], [sxy, syy]]
    theta = 0.5 * math.atan2(2.0 * sxy, sxx - syy)
    ux, uy = math.cos(theta), math.sin(theta)
    ts = [(x - cx) * ux + (y - cy) * uy for x, y in points]
    t0, t1 = min(ts), max(ts)
    return ((cx + t0 * ux, cy + t0 * uy), (cx + t1 * ux, cy + t1 * uy))


def extract_wall_runs(page: Any) -> list[dict[str, Any]]:
    """Drawn wall runs on this page, in PDF points.

    Each run: {"segment": ((x0,y0),(x1,y1)), "length_pt", "angle_deg",
    "tick_count"}. tick_count is the supporting evidence weight -- a run
    built from more strokes is a more confident detection."""
    ticks = iter_short_strokes(page)
    if not ticks:
        return []
    runs: list[dict[str, Any]] = []
    for hatch_angle in dominant_hatch_angles(ticks):
        members = [t["mid"] for t in ticks
                   if _angle_delta(t["angle"], hatch_angle) <= ANGLE_BUCKET_DEG]
        if len(members) < MIN_TICKS_PER_RUN:
            continue
        for cluster in _cluster_runs(members):
            a, b = _principal_segment(cluster)
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            if length < MIN_RUN_LEN_PT:
                continue
            runs.append({
                "segment": (a, b),
                "length_pt": length,
                "angle_deg": _angle_deg(a, b),
                "tick_count": len(cluster),
            })
    return runs


def nearest_run(runs: list[dict[str, Any]],
                point: tuple[float, float],
                max_distance_pt: float) -> dict[str, Any] | None:
    """The drawn wall run a callout anchor most plausibly refers to.

    Nearest by point-to-segment distance, and only within max_distance_pt --
    a callout whose anchor lands nowhere near any drawn run yields None, so
    the caller keeps its existing (geometry-free) behaviour rather than
    attaching a wrong wall."""
    best = None
    for run in runs:
        d = point_to_segment_distance(point, *run["segment"])
        if d <= max_distance_pt and (best is None or d < best[0]):
            best = (d, run)
    if best is None:
        return None
    return {**best[1], "anchor_distance_pt": best[0]}


def point_to_segment_distance(p: tuple[float, float],
                              a: tuple[float, float],
                              b: tuple[float, float]) -> float:
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    seg_len2 = dx * dx + dy * dy
    if seg_len2 <= 1e-12:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))
