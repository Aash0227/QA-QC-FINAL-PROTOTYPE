"""Generic evidence-based matching engine (Stage 9 Gate 4).

Extracted, category-agnostic core of the physical-device matching layer
proven on Hold Downs (Gate 2/3): inverse-project PDF callouts into model
space, cluster into physical devices, and run global one-to-one assignment
against Revit candidates with a registration-uncertainty-aware match gate,
an ambiguity guard, and an (currently dormant, data-pending) level-compat
gate. None of this module knows what a "hold-down" or "shear wall" is --
category-specific numbers, geometry, and row/target shaping live in an
AdapterConfig supplied by the caller (see device_match.py for the Hold Down
and Shear Wall adapters).

Evidence model (what actually decides a verdict today):
  1. mark equal (required -- callers pre-group same-mark pairs before
     assignment; a device never claims a target of a different mark in the
     same-mark pass)
  2. distance within an uncertainty-derived gate (adaptive_match_ft --
     widens the flat base tolerance by this device's own registration
     residual, never narrows it, capped at match_gate_ceiling_mult x base)
  3. uniqueness margin (_flag_ambiguous -- a near-tied runner-up refuses the
     auto-pick rather than coin-flipping)
  4. level compatible, when both sides carry real elevation (currently only
     the Revit side does in production -- see Gate 3 report; dormant until
     PDF rows carry elevation_ft too)

Spec/host-context corroboration (evidence channel 5 from the Gate 2
proposal) is NOT yet part of this engine -- Gate 3 found the "host" half
needs wall-centerline-proximity geometry, not Revit's host field, which is
a bigger, separate design. Not silently dropped: this is the named next
increment.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class AdapterConfig:
    """Everything a category needs to plug into the generic engine.
    Category-specific geometry/behavior only -- no evidence logic here."""
    match_ft: float
    mismatch_ft: float
    distance: Callable[[dict[str, Any], dict[str, Any]], float]
    mark_blind: bool = True
    cluster_tol_ft: float = 3.0
    level_delta_ft: float = 8.0
    ambiguity_margin_ft: float = 1.0
    match_gate_ceiling_mult: float = 3.0
    # Optional context evidence channel: the name of a target attribute
    # (e.g. "level") whose value is expected to be consistent across all
    # elements drawn on one sheet. When set, resolve_ambiguity_by_context()
    # can break distance-ties between candidates that disagree on it. Leave
    # None for categories whose targets carry no such attribute.
    context_key: str | None = None
    context_min_samples: int = 3
    context_min_consensus: float = 0.6
    # Optional orientation evidence channel: when BOTH the device (from PDF
    # geometry) and the target (from model geometry) carry an
    # "orientation_deg", a candidate whose direction disagrees by more than
    # this tolerance can be ruled out of a distance-tie. Unset (None)
    # disables the channel entirely.
    orientation_tolerance_deg: float | None = None


# ---------------------------------------------------------------- registration

def inverse_from_calibration(cal: dict[str, Any] | None) -> Callable | None:
    """Exact pdf(pt)->model(ft) inverse from the calibration's stored
    transform.inverse_matrix -- the authoritative transform, chirality
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
    winner is float noise -- a mirrored transform scatters every device
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


# ------------------------------------------------------------------- devices

def row_z_ft(row: dict[str, Any]) -> float | None:
    """Model-space Z of a PDF callout row, when the row carries one.

    The inverse transform is 2D, so a projected callout has no Z of its own
    -- only an explicit elevation/level height on the row can supply it."""
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
                  prefix: str,
                  cluster_tol_ft: float) -> tuple[list[dict[str, Any]], int]:
    """Cluster sheet callout rows into physical devices (model feet).
    Returns (devices, rows_without_usable_projection).

    Two rows only ever describe the SAME physical device when they're the
    same mark, on DIFFERENT sheets (a sheet draws each physical element
    once -- two same-mark callouts on one sheet are always two distinct
    devices, however close together). Anchoring to the first member's
    location (not a moving centroid) and forbidding same-sheet merges
    closes both the false-merge and chain-drift failure modes."""
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
                    and abs(d["_anchor_x"] - x) <= cluster_tol_ft
                    and abs(d["_anchor_y"] - y) <= cluster_tol_ft):
                d["appearances"].append(r["id"])
                d["sheets"].append(sheet)
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
            # PDF-side measured orientation, when the row carries one (see
            # the orientation evidence channel). Model-space direction, so
            # it is directly comparable to a target's orientation_deg.
            if isinstance(r.get("orientation_deg"), (int, float)):
                dev["orientation_deg"] = float(r["orientation_deg"])
            devices.append(dev)
    for i, d in enumerate(devices, start=1):
        d["id"] = f"{prefix}_dev_{i:03d}"
        d.pop("_anchor_x", None)
        d.pop("_anchor_y", None)
    return devices, unprojected


# ---------------------------------------------------------------- assignment

def adaptive_match_ft(device: dict[str, Any],
                      registration_quality: dict[str, dict[str, Any]],
                      base_ft: float,
                      ceiling_mult: float) -> float:
    """Match gate widened by this device's own registration uncertainty (a
    fixed point gate ignores that the calibration's own solve residual can
    eat the whole budget). residual_pt / scale (PDF-pt per model-ft)
    converts the sheet's solve RMS into model feet; a multi-sheet device
    uses its worst sheet (conservative). Missing/non-numeric quality data
    leaves the gate at base_ft -- this only ever widens the gate, never
    narrows it below the original fixed tolerance."""
    worst_ft = 0.0
    for sheet in device.get("sheets", []):
        q = registration_quality.get(sheet) or {}
        rms_pt, scale = q.get("rms_residual_pt"), q.get("scale")
        if not isinstance(rms_pt, (int, float)) or not isinstance(scale, (int, float)) or scale <= 0:
            continue
        worst_ft = max(worst_ft, rms_pt / scale)
    return min(base_ft + worst_ft, base_ft * ceiling_mult)


def _flag_ambiguous(devices: list[dict[str, Any]],
                    targets: list[dict[str, Any]],
                    distance: Callable[[dict[str, Any], dict[str, Any]], float],
                    mismatch_ft: float,
                    ambiguity_margin_ft: float) -> None:
    """Mark devices whose best same-mark candidate isn't decisively closer
    than the runner-up. Greedy nearest-neighbor assignment picks A winner,
    but when two candidates are nearly tied it's a coin flip dressed as a
    distance comparison -- exactly the "confident wrong MATCH" this system
    must refuse to produce."""
    for d in devices:
        same_mark = [t for t in targets if t.get("mark") == d["mark"]]
        if len(same_mark) < 2:
            continue
        dists = sorted((distance(d, t), t["id"]) for t in same_mark)
        best_dist, best_id = dists[0]
        second_dist, second_id = dists[1]
        if best_dist <= mismatch_ft and (second_dist - best_dist) < ambiguity_margin_ft:
            d["_ambiguous"] = True
            d["_ambiguous_candidates"] = [best_id, second_id]


def assign(devices: list[dict[str, Any]],
           targets: list[dict[str, Any]],
           config: AdapterConfig,
           registration_quality: dict[str, dict[str, Any]] | None = None) -> None:
    """Global one-to-one assignment. Mutates devices (status/target/dist)
    and targets (claimed flag). Same-mark pass first, then mark-blind
    (-> MARK_MISMATCH). Greedy on globally sorted distances -- except where
    two candidates are nearly tied, which _flag_ambiguous() catches before
    any claiming happens."""
    for d in devices:
        d["_match_gate_ft"] = adaptive_match_ft(
            d, registration_quality or {}, config.match_ft, config.match_gate_ceiling_mult)
    _flag_ambiguous(devices, targets, config.distance, config.mismatch_ft,
                    config.ambiguity_margin_ft)
    pairs = sorted(
        (config.distance(d, t), di, ti)
        for di, d in enumerate(devices)
        for ti, t in enumerate(targets)
        if d["mark"] and d["mark"] == t.get("mark"))
    _claim(pairs, devices, targets, config.mismatch_ft, config.match_ft,
          config.level_delta_ft, config.ambiguity_margin_ft, same_mark=True)
    if config.mark_blind:
        # a device drawn with the wrong mark still occupies the spot --
        # meaningful for sparse point devices; too noisy for dense walls.
        pairs = sorted(
            (config.distance(d, t), di, ti)
            for di, d in enumerate(devices)
            for ti, t in enumerate(targets))
        _claim(pairs, devices, targets, config.match_ft, config.match_ft,
              config.level_delta_ft, config.ambiguity_margin_ft, same_mark=False)
    # Evidence channels 5 & 6: break remaining distance-ties, first with
    # real PDF<->model orientation agreement (a direct measurement on both
    # sides), then with sheet context consensus (an inference across
    # devices). Both run after the claim passes so they only ever see
    # genuinely unresolved ambiguities, and both refuse unless exactly one
    # candidate agrees.
    resolve_ambiguity_by_orientation(devices, targets, config)
    resolve_ambiguity_by_context(devices, targets, config, registration_quality)
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
                               f"{config.mismatch_ft:g} ft of "
                               f"({d['x']:.1f}, {d['y']:.1f}) ft.")


def _claim(pairs, devices, targets, gate_ft, match_ft, level_delta_ft,
          ambiguity_margin_ft, same_mark):
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
                f"within {ambiguity_margin_ft:g} ft of each other near "
                f"({d['x']:.1f}, {d['y']:.1f}) ft in model space -- refusing "
                "to auto-pick. Resolve by comparing sheet context/leader lines.")
            continue
        if t.get("_claimed"):
            continue
        if same_mark:
            gate = d.get("_match_gate_ft", match_ft)
            dz, tz = d.get("z"), t.get("z")
            off_level = (isinstance(dz, (int, float)) and isinstance(tz, (int, float))
                        and abs(dz - tz) > level_delta_ft)
            if dist <= gate and off_level:
                # Good XY, wrong floor: not confidently either a MATCH or a
                # LOCATION_MISMATCH -- surface for a human, claim nothing
                # silently. Dormant until rows carry elevation_ft.
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
            d["target_z"] = float(t["z"])
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


# -------------------------------------------------- context evidence channel

def sheet_context_consensus(devices: list[dict[str, Any]],
                            targets_by_id: dict[str, dict[str, Any]],
                            config: AdapterConfig) -> dict[str, str]:
    """Per-sheet consensus value of config.context_key, derived ONLY from
    devices the distance/mark evidence already resolved unambiguously.

    Rationale (Stage 9, Shear Wall investigation): a single plan sheet draws
    ONE story, so every element on it should share a level. That's real
    evidence, but nothing in the pipeline states a sheet's level -- and
    guessing it from sheet numbering would be exactly the "unreliable
    assumption" this program forbids. Instead it's measured: the devices
    that matched WITHOUT needing this channel vote, and their consensus
    becomes the sheet's context. Non-circular (those pairings were decided
    before any context logic ran) and project-agnostic (no sheet-naming or
    level-naming convention is assumed anywhere).

    Returns {sheet: consensus_value} only for sheets clearing BOTH
    config.context_min_samples and config.context_min_consensus -- a sheet
    with thin or split evidence yields nothing and its ambiguities stay
    NEEDS_REVIEW, which is the correct outcome."""
    if not config.context_key:
        return {}
    votes: dict[str, list[str]] = {}
    for d in devices:
        # Only confident, unambiguous pairings vote.
        if d.get("_ambiguous") or not d.get("target_id"):
            continue
        if d.get("status") not in ("MATCH", "LOCATION_MISMATCH"):
            continue
        value = (targets_by_id.get(d["target_id"]) or {}).get(config.context_key)
        if value is None:
            continue
        for sheet in d.get("sheets", []):
            votes.setdefault(sheet, []).append(value)
    consensus: dict[str, str] = {}
    for sheet, values in votes.items():
        if len(values) < config.context_min_samples:
            continue
        top, count = Counter(values).most_common(1)[0]
        if count / len(values) >= config.context_min_consensus:
            consensus[sheet] = top
    return consensus


def _orientation_delta(p: float, q: float) -> float:
    """Smallest undirected angular difference in degrees (a wall drawn
    left-to-right and the same wall stored right-to-left are the same wall)."""
    d = abs(p - q) % 180.0
    return min(d, 180.0 - d)


def resolve_ambiguity_by_orientation(devices: list[dict[str, Any]],
                                     targets: list[dict[str, Any]],
                                     config: AdapterConfig) -> int:
    """Break a distance-tie when the DRAWN element's direction matches only
    one candidate's direction.

    Distinct from the context channel: this compares a real PDF-side
    measurement (extracted from the sheet's own vector geometry -- see
    pdf_wall_geometry.py) against a real model-side measurement, so it is
    genuine PDF<->Revit evidence rather than a cross-device consensus. It
    only runs for devices that actually carry an orientation, so a callout
    whose drawn geometry could not be extracted is unaffected.

    Same conservative contract as the context channel: only touches devices
    already NEEDS_REVIEW-by-ambiguity, only fires when exactly one candidate
    agrees, never claims a claimed target, and still applies the adaptive
    distance gate to the winner."""
    tol = config.orientation_tolerance_deg
    if tol is None:
        return 0
    targets_by_id = {t["id"]: t for t in targets}
    resolved = 0
    for d in devices:
        if not d.get("_ambiguous") or d.get("status") != "NEEDS_REVIEW":
            continue
        drawn = d.get("orientation_deg")
        if not isinstance(drawn, (int, float)):
            continue
        cands = [targets_by_id[c] for c in d.get("_ambiguous_candidates", [])
                 if c in targets_by_id]
        if len(cands) < 2:
            continue
        if any(not isinstance(t.get("orientation_deg"), (int, float)) for t in cands):
            continue
        agreeing = [t for t in cands
                    if _orientation_delta(drawn, t["orientation_deg"]) <= tol
                    and not t.get("_claimed")]
        if len(agreeing) != 1:
            continue
        winner = agreeing[0]
        dist = config.distance(d, winner)
        if dist > config.mismatch_ft:
            continue
        gate = d.get("_match_gate_ft", config.match_ft)
        winner["_claimed"] = True
        d["target_id"] = winner["id"]
        d["target_mark"] = winner.get("mark")
        if "x" in winner:
            d["target_point"] = [winner["x"], winner["y"]]
        d["distance_ft"] = round(dist, 2)
        d["status"] = "MATCH" if dist <= gate else "LOCATION_MISMATCH"
        d["resolved_by"] = "orientation"
        rejected = [f"{t['id']} ({t['orientation_deg']:.0f}°)" for t in cands
                    if t["id"] != winner["id"]]
        d["reason"] = (
            f"Physical device: mark {d['mark']} paired with {winner['id']} at "
            f"{dist:.2f} ft in model space. Distance alone was ambiguous, but "
            f"the wall drawn on the sheet runs at {drawn:.0f}° and only this "
            f"candidate matches that direction "
            f"({winner['orientation_deg']:.0f}°) — ruled out: "
            f"{', '.join(rejected)}.")
        resolved += 1
    return resolved


def resolve_ambiguity_by_context(devices: list[dict[str, Any]],
                                 targets: list[dict[str, Any]],
                                 config: AdapterConfig,
                                 registration_quality: dict[str, dict[str, Any]] | None = None) -> int:
    """Second pass: break distance-ties using the sheet's context consensus.

    Only fires when the tied candidates actually DISAGREE on the context
    value and exactly one of them agrees with the sheet's consensus -- i.e.
    when a genuinely distinguishing piece of evidence exists that the
    distance-margin guard alone couldn't see. Deliberately conservative:

      * never touches a device that isn't already NEEDS_REVIEW-by-ambiguity,
        so it can't override or weaken any confident verdict;
      * never claims an already-claimed target;
      * still applies the normal adaptive distance gate to the winner, so a
        context-resolved pairing that's too far away becomes an honest
        LOCATION_MISMATCH rather than a MATCH;
      * leaves the device NEEDS_REVIEW when both candidates agree on the
        context value (no distinguishing evidence -> uncertainty is real).

    Returns the number of devices resolved (for reporting/measurement)."""
    if not config.context_key:
        return 0
    targets_by_id = {t["id"]: t for t in targets}
    consensus = sheet_context_consensus(devices, targets_by_id, config)
    if not consensus:
        return 0
    resolved = 0
    for d in devices:
        if not d.get("_ambiguous") or d.get("status") != "NEEDS_REVIEW":
            continue
        sheet_value = next((consensus[s] for s in d.get("sheets", [])
                            if s in consensus), None)
        if sheet_value is None:
            continue
        cands = [targets_by_id[c] for c in d.get("_ambiguous_candidates", [])
                 if c in targets_by_id]
        agreeing = [t for t in cands
                    if t.get(config.context_key) == sheet_value
                    and not t.get("_claimed")]
        # Exactly one candidate on the sheet's own level = the tie was never
        # a real tie; the other candidate is a different story's wall that
        # happens to sit at the same plan coordinates.
        if len(cands) < 2 or len(agreeing) != 1:
            continue
        if all(t.get(config.context_key) == sheet_value for t in cands):
            continue  # no disagreement -> nothing distinguishing to use
        winner = agreeing[0]
        dist = config.distance(d, winner)
        gate = d.get("_match_gate_ft", config.match_ft)
        if dist > config.mismatch_ft:
            continue
        winner["_claimed"] = True
        d["target_id"] = winner["id"]
        d["target_mark"] = winner.get("mark")
        if "x" in winner:
            d["target_point"] = [winner["x"], winner["y"]]
        d["distance_ft"] = round(dist, 2)
        d["status"] = "MATCH" if dist <= gate else "LOCATION_MISMATCH"
        d["resolved_by"] = config.context_key
        rejected = [f"{t['id']} ({t.get(config.context_key)})"
                    for t in cands if t["id"] != winner["id"]]
        d["reason"] = (
            f"Physical device: mark {d['mark']} paired with {winner['id']} at "
            f"{dist:.2f} ft in model space. Distance alone was ambiguous, but "
            f"this sheet's {config.context_key} is {sheet_value!r} (consensus "
            f"of its unambiguous matches) and only this candidate is on it — "
            f"ruled out: {', '.join(rejected)}.")
        resolved += 1
    return resolved


# --------------------------------------------------------------- geometries

def point_distance(d: dict[str, Any], t: dict[str, Any]) -> float:
    return math.hypot(d["x"] - t["x"], d["y"] - t["y"])


def segment_distance(d: dict[str, Any], t: dict[str, Any]) -> float:
    (x1, y1), (x2, y2) = t["segment"]
    px, py = d["x"] - x1, d["y"] - y1
    vx, vy = x2 - x1, y2 - y1
    ll = vx * vx + vy * vy
    s = 0.0 if ll == 0 else max(0.0, min(1.0, (px * vx + py * vy) / ll))
    return math.hypot(d["x"] - (x1 + s * vx), d["y"] - (y1 + s * vy))


# ------------------------------------------------------------ product verdict

MATCH_STATUSES = frozenset({"MATCH"})
MISMATCH_STATUSES = frozenset({"LOCATION_MISMATCH", "MARK_MISMATCH"})
# Everything else (NEEDS_REVIEW, PDF_ONLY, REVIT_ONLY, ...) is an internal
# diagnostic state -- not confidently either verdict.


def product_verdict(status: str) -> str | None:
    """Collapse an internal engine status to the product-facing location
    verdict (Gate 4 §3): LOCATION_MATCH / LOCATION_MISMATCH only, or None
    when the evidence doesn't support a confident verdict either way.

    Not yet wired into any category's output -- compare.py, wall_match.py,
    element_registry.py and the frontend all still read/emit the richer
    internal vocabulary (PDF_ONLY, REVIT_ONLY, NEEDS_REVIEW, ...) across the
    whole product surface. Collapsing that is a separate, cross-cutting
    change spanning API contracts and the UI, deliberately out of scope for
    the engine-extraction pass -- this function is the seam it will hang
    off when that change is made."""
    if status in MATCH_STATUSES:
        return "LOCATION_MATCH"
    if status in MISMATCH_STATUSES:
        return "LOCATION_MISMATCH"
    return None
