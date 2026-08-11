from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from typing import Any

from . import config

SCHEMA_VERSION = "registration-calibration/2.0"
REPORT_SCHEMA_VERSION = "coordinate-registration-report/2.0"

# Transform direction is fixed: Revit model space -> PDF page space.
TRANSFORM_DIRECTION = "revit_internal_feet->pdf_points"

# Calibration provenance. Only "verified" sources may ever allow a production MATCH.
DIAGNOSTIC_SOURCE = "auto_extent_estimate"
VERIFIED_SOURCES = ("manual_verified", "grid_verified", "anchor_verified", "holdown_ransac",
                    "benchmark_verified")
VALID_SOURCES = (DIAGNOSTIC_SOURCE,) + VERIFIED_SOURCES
DEFAULT_SOURCE = "manual_verified"

# Quality thresholds (PDF points).
HIGH_RMS, HIGH_MAX = 8.0, 16.0
MEDIUM_RMS, MEDIUM_MAX = 16.0, 32.0
# Holdout / validation thresholds (PDF points).
VALIDATION_RMS_MAX, VALIDATION_MAX_MAX = 8.0, 16.0
MIN_PAIRS = 3

DIAGNOSTIC_NOTE = (
    "Auto extent calibration is diagnostic only; use real shared grid/anchor points for MATCH."
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Transform math
# ---------------------------------------------------------------------------
def _is_collinear(points: list[tuple[float, float]]) -> bool:
    """True if all source points lie (near) on a single line (rank-deficient)."""
    n = len(points)
    if n < 3:
        return True
    cx = sum(p[0] for p in points) / n
    cy = sum(p[1] for p in points) / n
    sxx = sxy = syy = 0.0
    for x, y in points:
        dx, dy = x - cx, y - cy
        sxx += dx * dx
        sxy += dx * dy
        syy += dy * dy
    trace = sxx + syy
    if trace <= 0:
        return True  # all identical points
    det = sxx * syy - sxy * sxy
    # Normalised smallest-spread metric; ~0 means collinear.
    return (det / (trace * trace)) < 1e-6


def _fit_variant(src: list[tuple[float, float]], dst: list[tuple[float, float]], reflect: bool):
    """Least-squares 2D similarity using complex numbers.

    Maps src (Revit) -> dst (PDF) as  t = a * s + b  (no reflection), or
    t = a * conj(s) + b  (reflection). Returns (matrix6, scale, rot_deg, residuals).
    matrix6 = [a,b,c,d,e,f] with  X = a*x + b*y + e ;  Y = c*x + d*y + f.
    """
    n = len(src)
    s = [complex(x, y) for x, y in src]
    t = [complex(x, y) for x, y in dst]
    s_mean = sum(s) / n
    t_mean = sum(t) / n
    sp = [v - s_mean for v in s]
    tp = [v - t_mean for v in t]

    denom = sum((v.real * v.real + v.imag * v.imag) for v in sp)
    if denom == 0:
        return None
    if reflect:
        # minimize |t' - a*conj(s')|^2  ->  a = Σ t' * s' / Σ|s'|^2
        a = sum(tp[i] * sp[i] for i in range(n)) / denom
    else:
        # minimize |t' - a*s'|^2  ->  a = Σ t' * conj(s') / Σ|s'|^2
        a = sum(tp[i] * sp[i].conjugate() for i in range(n)) / denom

    p, q = a.real, a.imag
    if reflect:
        b_complex = t_mean - a * s_mean.conjugate()
        matrix = [p, q, q, -p, b_complex.real, b_complex.imag]
    else:
        b_complex = t_mean - a * s_mean
        matrix = [p, -q, q, p, b_complex.real, b_complex.imag]

    scale = abs(a)
    rot_deg = math.degrees(math.atan2(q, p))

    residuals = []
    for i in range(n):
        X, Y = apply_transform(matrix, src[i][0], src[i][1])
        residuals.append(math.hypot(X - dst[i][0], Y - dst[i][1]))
    return matrix, scale, rot_deg, residuals


def apply_transform(matrix: list[float], x: float, y: float) -> tuple[float, float]:
    """Apply a 6-element affine [a,b,c,d,e,f]: X=a*x+b*y+e, Y=c*x+d*y+f."""
    a, b, c, d, e, f = matrix
    return a * x + b * y + e, c * x + d * y + f


def _invert_matrix(matrix: list[float]) -> list[float] | None:
    a, b, c, d, e, f = matrix
    det = a * d - b * c
    if abs(det) < 1e-12:
        return None
    ia = d / det
    ib = -b / det
    ic = -c / det
    id_ = a / det
    ie = -(ia * e + ib * f)
    if_ = -(ic * e + id_ * f)
    return [ia, ib, ic, id_, ie, if_]


def _classify_quality(rms: float, max_res: float, used: int) -> str:
    if used < MIN_PAIRS:
        return "failed"
    if rms <= HIGH_RMS and max_res <= HIGH_MAX:
        return "high"
    if rms <= MEDIUM_RMS and max_res <= MEDIUM_MAX:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Point-pair parsing
# ---------------------------------------------------------------------------
def _clean_pairs(point_pairs: list[dict[str, Any]] | None, prefix: str) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for i, pair in enumerate(point_pairs or []):
        try:
            pdf = pair["pdf_point"]
            rev = pair["revit_point"]
            px, py = float(pdf["x"]), float(pdf["y"])
            rx, ry = float(rev["x"]), float(rev["y"])
        except (KeyError, TypeError, ValueError):
            continue
        cleaned.append(
            {
                "id": pair.get("id", f"{prefix}_{i + 1}"),
                "label": pair.get("label"),
                "pdf_point": {"x": px, "y": py, "space": "pdf_points"},
                "revit_point": {"x": rx, "y": ry, "space": "revit_internal_feet"},
            }
        )
    return cleaned


def _residuals_for(matrix: list[float], pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for pair in pairs:
        rx = pair["revit_point"]["x"]
        ry = pair["revit_point"]["y"]
        px = pair["pdf_point"]["x"]
        py = pair["pdf_point"]["y"]
        X, Y = apply_transform(matrix, rx, ry)
        out.append({"id": pair["id"], "residual_pt": round(math.hypot(X - px, Y - py), 4)})
    return out


# ---------------------------------------------------------------------------
# Public: compute calibration from point pairs
# ---------------------------------------------------------------------------
def compute_calibration(
    point_pairs: list[dict[str, Any]],
    calibration_source: str | None = None,
    validation_pairs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compute a Revit->PDF similarity transform from manual point pairs.

    Each pair: {"id":.., "label":.., "pdf_point":{"x","y"}, "revit_point":{"x","y"}}.

    ``calibration_source`` provenance gates whether a production MATCH is permitted:
      - auto_extent_estimate -> diagnostic only, MATCH never allowed.
      - manual_verified / grid_verified / anchor_verified -> may allow MATCH when
        solve quality is high/medium and validation (if supplied) passes.

    ``validation_pairs`` (optional holdout) are NOT used to solve the transform; they
    are scored against the solved transform. Failing holdout residuals force
    match_allowed = False even when the solve RMS is low.
    """
    source = (calibration_source or DEFAULT_SOURCE).strip()
    source_recognized = source in VALID_SOURCES
    source_verified = source in VERIFIED_SOURCES

    cleaned = _clean_pairs(point_pairs, "pair")
    cleaned_val = _clean_pairs(validation_pairs, "check")
    src = [(p["revit_point"]["x"], p["revit_point"]["y"]) for p in cleaned]
    dst = [(p["pdf_point"]["x"], p["pdf_point"]["y"]) for p in cleaned]

    base = {
        "schema_version": SCHEMA_VERSION,
        "method": "manual_point_pairs",
        "calibration_source": source,
        "source_recognized": source_recognized,
        "created_at": _now_iso(),
        "transform_direction": TRANSFORM_DIRECTION,
        "point_pairs": cleaned,
        "validation_pairs": cleaned_val,
    }

    def _fail(reason: str) -> dict[str, Any]:
        base["transform"] = None
        base["quality"] = {
            "confidence": "failed",
            "match_allowed": False,
            "solve_rms_residual_pt": None,
            "solve_max_residual_pt": None,
            "validation_rms_residual_pt": None,
            "validation_max_residual_pt": None,
            "used_pair_count": len(cleaned),
            "validation_pair_count": len(cleaned_val),
            "validation_failed": False,
            "confidence_reason": reason,
            # Legacy aliases (kept for older readers / UI).
            "rms_residual_pt": None,
            "max_residual_pt": None,
            "reason": reason,
        }
        return base

    if len(cleaned) < MIN_PAIRS:
        return _fail(f"Need at least {MIN_PAIRS} valid point pairs; got {len(cleaned)}.")
    if _is_collinear(src):
        return _fail("Source (Revit) calibration points are collinear; cannot solve a 2D transform.")

    best = None
    for reflect in (False, True):
        fit = _fit_variant(src, dst, reflect)
        if fit is None:
            continue
        matrix, scale, rot_deg, residuals = fit
        rms = math.sqrt(sum(r * r for r in residuals) / len(residuals))
        max_res = max(residuals)
        if best is None or rms < best["rms"]:
            best = {"reflect": reflect, "matrix": matrix, "scale": scale,
                    "rot_deg": rot_deg, "rms": rms, "max_res": max_res, "residuals": residuals}

    if best is None:
        return _fail("Least-squares solve failed (degenerate point configuration).")

    matrix = best["matrix"]
    inverse = _invert_matrix(matrix)
    confidence = _classify_quality(best["rms"], best["max_res"], len(cleaned))

    # Validation / holdout scoring (does not affect the solve).
    val_rms = val_max = None
    val_residuals: list[dict[str, Any]] = []
    validation_failed = False
    if cleaned_val:
        val_residuals = _residuals_for(matrix, cleaned_val)
        vr = [r["residual_pt"] for r in val_residuals]
        val_rms = round(math.sqrt(sum(v * v for v in vr) / len(vr)), 4)
        val_max = round(max(vr), 4)
        validation_failed = val_rms > VALIDATION_RMS_MAX or val_max > VALIDATION_MAX_MAX

    # match_allowed gate: verified source + high/medium confidence + validation OK (or absent).
    match_allowed = source_verified and confidence in ("high", "medium")
    reasons: list[str] = []
    if not source_recognized:
        reasons.append(f"Unrecognized calibration_source '{source}'.")
    if source == DIAGNOSTIC_SOURCE:
        match_allowed = False
        reasons.append(DIAGNOSTIC_NOTE)
    elif not source_verified:
        match_allowed = False
        reasons.append("calibration_source is not a verified source; MATCH withheld.")
    if confidence == "low":
        match_allowed = False
        reasons.append(
            f"Solve RMS={round(best['rms'], 2)}pt / max={round(best['max_res'], 2)}pt exceeds "
            "medium thresholds (RMS<=16, max<=32)."
        )
    if validation_failed:
        match_allowed = False
        reasons.append(
            f"Holdout validation RMS={val_rms}pt / max={val_max}pt exceeds limits "
            f"(RMS<={VALIDATION_RMS_MAX:.0f}, max<={VALIDATION_MAX_MAX:.0f})."
        )
    if match_allowed and not cleaned_val:
        reasons.append("No holdout validation supplied; calibration is unvalidated.")
    if match_allowed and cleaned_val and not validation_failed:
        reasons.append("Verified source, good solve, holdout validation passed.")
    if not reasons:
        reasons.append("Calibration computed.")

    base["transform"] = {
        "type": "similarity_2d",
        "direction": TRANSFORM_DIRECTION,
        "scale": round(best["scale"], 8),
        "rotation_degrees": round(best["rot_deg"], 6),
        "translation": {"x": round(matrix[4], 6), "y": round(matrix[5], 6)},
        "reflection": bool(best["reflect"]),
        "matrix": [round(v, 10) for v in matrix],
        "matrix_form": "X = a*x + b*y + e ; Y = c*x + d*y + f  (x,y in revit feet -> X,Y in pdf points)",
        "inverse_matrix": [round(v, 10) for v in inverse] if inverse else None,
        "inverse_direction": "pdf_points->revit_internal_feet" if inverse else None,
    }
    base["quality"] = {
        "confidence": confidence,
        "match_allowed": bool(match_allowed),
        "solve_rms_residual_pt": round(best["rms"], 4),
        "solve_max_residual_pt": round(best["max_res"], 4),
        "validation_rms_residual_pt": val_rms,
        "validation_max_residual_pt": val_max,
        "used_pair_count": len(cleaned),
        "validation_pair_count": len(cleaned_val),
        "validation_failed": validation_failed,
        "confidence_reason": " ".join(reasons),
        "per_pair_residual_pt": [
            {"id": cleaned[i]["id"], "residual_pt": round(best["residuals"][i], 4)}
            for i in range(len(cleaned))
        ],
        "per_validation_residual_pt": val_residuals,
        # Legacy aliases (kept for older readers / UI).
        "rms_residual_pt": round(best["rms"], 4),
        "max_residual_pt": round(best["max_res"], 4),
        "reason": " ".join(reasons),
    }
    return base


# ---------------------------------------------------------------------------
# Public: 2-benchmark calibration (additive — manual path above is untouched)
# ---------------------------------------------------------------------------
BENCHMARK_MIN_SEP_PT = 200.0      # PDF-side minimum benchmark separation
BENCHMARK_MIN_SEP_FT = 10.0       # Revit-side minimum benchmark separation
BENCHMARK_SCALE_OK = 0.005        # <=0.5% drift vs title-block scale: clean
BENCHMARK_SCALE_WARN = 0.02       # <=2%: warning, confidence capped medium
CHIRALITY_DECISIVE_RATIO = 0.5    # other variant decisively better => conflict


def compute_calibration_from_benchmarks(
    pdf_benchmarks: list[dict[str, Any]],
    revit_benchmarks: list[dict[str, Any]],
    expected_scale_pt_per_ft: float | None = None,
    assume_reflection: bool = True,
    validation_pairs: list[dict[str, Any]] | None = None,
    chirality_evidence: dict[str, Any] | None = None,
    marks: tuple[str, str] = ("BM-1", "BM-2"),
) -> dict[str, Any]:
    """Exact 2-point similarity from stamped benchmarks (BM-1/BM-2).

    n=2 specifics this handles (see docs/BENCHMARK-REGISTRATION-PLAN.md):
    - reflection is undecidable from 2 points -> pinned by convention
      (PDF y-down vs Revit y-up => reflected is the physical truth), with a
      chirality cross-check against detection clouds as EVIDENCE (blocker,
      never a silent flip);
    - RMS is ~0 by construction -> quality comes from benchmark separation,
      derived-scale agreement with the title block, chirality consistency
      and optional holdout validation pairs.

    pdf_benchmarks:  [{"mark":"BM-1","point_pt":{"x":..,"y":..}}, ...]
    revit_benchmarks:[{"mark":"BM-1","point_ft":{"x":..,"y":..}}, ...]
    chirality_evidence (optional): {"revit_points":[[x,y]..],
                                    "pdf_points":[[x,y]..]}
    """
    # Resolve expected scale from env var if not explicitly provided.
    if expected_scale_pt_per_ft is None:
        _env_scale = os.environ.get("QAQC_EXPECTED_SCALE_PT_PER_FT", "18.0")
        try:
            expected_scale_pt_per_ft = float(_env_scale)
        except (ValueError, TypeError):
            expected_scale_pt_per_ft = 18.0
    want = tuple(m.upper() for m in marks)
    pdf_by = {}
    for b in pdf_benchmarks or []:
        m = str(b.get("mark", "")).upper()
        if m in pdf_by:
            return _benchmark_fail(f"Duplicate PDF benchmark mark '{m}'.", [])
        pdf_by[m] = b
    rev_by = {}
    for b in revit_benchmarks or []:
        m = str(b.get("mark", "")).upper()
        if m in rev_by:
            return _benchmark_fail(f"Duplicate Revit benchmark mark '{m}'.", [])
        rev_by[m] = b
    missing = [m for m in want if m not in pdf_by or m not in rev_by]
    if missing:
        return _benchmark_fail(
            f"Benchmark mark(s) missing on one side: {', '.join(missing)}. "
            f"PDF has {sorted(pdf_by)}, Revit has {sorted(rev_by)}.", [])

    pairs = []
    for m in want:
        p, r = pdf_by[m], rev_by[m]
        try:
            pairs.append({
                "id": m, "label": "benchmark",
                "pdf_point": {"x": float(p["point_pt"]["x"]),
                              "y": float(p["point_pt"]["y"]),
                              "space": "pdf_points"},
                "revit_point": {"x": float(r["point_ft"]["x"]),
                                "y": float(r["point_ft"]["y"]),
                                "space": "revit_internal_feet"},
            })
        except (KeyError, TypeError, ValueError):
            return _benchmark_fail(f"Benchmark '{m}' has malformed coordinates.", [])

    sep_pt = math.hypot(pairs[0]["pdf_point"]["x"] - pairs[1]["pdf_point"]["x"],
                        pairs[0]["pdf_point"]["y"] - pairs[1]["pdf_point"]["y"])
    sep_ft = math.hypot(pairs[0]["revit_point"]["x"] - pairs[1]["revit_point"]["x"],
                        pairs[0]["revit_point"]["y"] - pairs[1]["revit_point"]["y"])
    if sep_pt < BENCHMARK_MIN_SEP_PT or sep_ft < BENCHMARK_MIN_SEP_FT:
        return _benchmark_fail(
            f"Benchmarks too close (PDF {sep_pt:.1f}pt / Revit {sep_ft:.1f}ft; "
            f"need >= {BENCHMARK_MIN_SEP_PT:.0f}pt / {BENCHMARK_MIN_SEP_FT:.0f}ft) "
            "— place them at DIAGONAL grid intersections.", pairs)

    src = [(p["revit_point"]["x"], p["revit_point"]["y"]) for p in pairs]
    dst = [(p["pdf_point"]["x"], p["pdf_point"]["y"]) for p in pairs]
    fit = _fit_variant(src, dst, reflect=bool(assume_reflection))
    if fit is None:
        return _benchmark_fail("Degenerate benchmark configuration.", pairs)
    matrix, scale, rot_deg, residuals = fit
    rms = math.sqrt(sum(r * r for r in residuals) / len(residuals))

    warnings: list[str] = []
    blockers: list[str] = []

    # Scale cross-check vs the title-block scale.
    drift = None
    if expected_scale_pt_per_ft:
        drift = abs(scale - expected_scale_pt_per_ft) / expected_scale_pt_per_ft
        if drift > BENCHMARK_SCALE_WARN:
            blockers.append(
                f"BENCHMARK_SCALE_MISMATCH: derived scale {scale:.4f}pt/ft is "
                f"{drift * 100:.1f}% off the expected {expected_scale_pt_per_ft}pt/ft "
                "— stamp on wrong sheet, wrong sheet scale, or misplaced benchmark.")
        elif drift > BENCHMARK_SCALE_OK:
            warnings.append(
                f"Derived scale drifts {drift * 100:.2f}% from expected "
                f"{expected_scale_pt_per_ft}pt/ft (warn band).")

    # Rotation sanity: plans are drawn orthogonal; anything else is unusual.
    rot_mod = abs(rot_deg) % 90.0
    if min(rot_mod, 90.0 - rot_mod) > 0.5:
        warnings.append(
            f"Rotation {rot_deg:.2f} deg is not within 0.5 deg of 0/90/180/270 "
            "(legal but unusual — rotated viewport?).")

    # Chirality cross-check: evidence only, never a silent flip.
    chirality = None
    if chirality_evidence:
        rev_pts = chirality_evidence.get("revit_points") or []
        pdf_pts = chirality_evidence.get("pdf_points") or []
        if len(rev_pts) >= 3 and len(pdf_pts) >= 3:
            other_fit = _fit_variant(src, dst, reflect=not assume_reflection)

            def _mean_nn_cost(mx):
                total = 0.0
                for rx, ry in rev_pts:
                    X, Y = apply_transform(mx, rx, ry)
                    total += min(math.hypot(X - px, Y - py) for px, py in pdf_pts)
                return total / len(rev_pts)

            cost_assumed = _mean_nn_cost(matrix)
            cost_other = _mean_nn_cost(other_fit[0]) if other_fit else None
            chirality = {"cost_assumed_pt": round(cost_assumed, 2),
                         "cost_other_pt": (round(cost_other, 2)
                                           if cost_other is not None else None)}
            if (cost_other is not None and cost_assumed > 0
                    and cost_other / cost_assumed < CHIRALITY_DECISIVE_RATIO):
                blockers.append(
                    "BENCHMARK_CHIRALITY_CONFLICT: the non-assumed reflection "
                    f"fits the detections decisively better ({cost_other:.1f}pt vs "
                    f"{cost_assumed:.1f}pt mean NN) — re-run with assume_reflection="
                    f"{not assume_reflection}.")

    # Optional holdout validation (reuses the existing residual gates).
    cleaned_val = _clean_pairs(validation_pairs, "check")
    val_rms = val_max = None
    val_residuals: list[dict[str, Any]] = []
    validation_failed = False
    if cleaned_val:
        val_residuals = _residuals_for(matrix, cleaned_val)
        vr = [r["residual_pt"] for r in val_residuals]
        val_rms = round(math.sqrt(sum(v * v for v in vr) / len(vr)), 4)
        val_max = round(max(vr), 4)
        validation_failed = val_rms > VALIDATION_RMS_MAX or val_max > VALIDATION_MAX_MAX
        if validation_failed:
            blockers.append(
                f"Holdout validation RMS={val_rms}pt / max={val_max}pt exceeds "
                f"limits (RMS<={VALIDATION_RMS_MAX:.0f}, max<={VALIDATION_MAX_MAX:.0f}).")

    # Quality: separation+scale+chirality+validation all clean -> high;
    # warn-band scale or unvalidated -> medium; any blocker -> failed.
    if blockers:
        confidence = "failed"
    elif warnings or not cleaned_val:
        confidence = "medium"
    else:
        confidence = "high"
    match_allowed = confidence in ("high", "medium")

    reasons = blockers + warnings
    if match_allowed and not cleaned_val:
        reasons.append("No holdout validation supplied; benchmark calibration unvalidated.")
    if not reasons:
        reasons.append("Two-benchmark calibration: separation, scale, chirality and validation all clean.")

    inverse = _invert_matrix(matrix)
    base = {
        "schema_version": SCHEMA_VERSION,
        "method": "benchmark_2pt",
        "calibration_source": "benchmark_verified",
        "source_recognized": True,
        "created_at": _now_iso(),
        "transform_direction": TRANSFORM_DIRECTION,
        "point_pairs": pairs,
        "validation_pairs": cleaned_val,
        "transform": {
            "type": "similarity_2d",
            "direction": TRANSFORM_DIRECTION,
            "scale": round(scale, 8),
            "rotation_degrees": round(rot_deg, 6),
            "translation": {"x": round(matrix[4], 6), "y": round(matrix[5], 6)},
            "reflection": bool(assume_reflection),
            "matrix": [round(v, 10) for v in matrix],
            "matrix_form": "X = a*x + b*y + e ; Y = c*x + d*y + f  (x,y in revit feet -> X,Y in pdf points)",
            "inverse_matrix": [round(v, 10) for v in inverse] if inverse else None,
            "inverse_direction": "pdf_points->revit_internal_feet" if inverse else None,
        },
        "quality": {
            "confidence": confidence,
            "match_allowed": bool(match_allowed),
            "solve_rms_residual_pt": round(rms, 4),
            "solve_max_residual_pt": round(max(residuals), 4),
            "validation_rms_residual_pt": val_rms,
            "validation_max_residual_pt": val_max,
            "used_pair_count": len(pairs),
            "validation_pair_count": len(cleaned_val),
            "validation_failed": validation_failed,
            "confidence_reason": " ".join(reasons),
            "per_pair_residual_pt": [
                {"id": pairs[i]["id"], "residual_pt": round(residuals[i], 4)}
                for i in range(len(pairs))
            ],
            "per_validation_residual_pt": val_residuals,
            "rms_residual_pt": round(rms, 4),
            "max_residual_pt": round(max(residuals), 4),
            "reason": " ".join(reasons),
        },
        "benchmark": {
            "marks": list(want),
            "separation_pt": round(sep_pt, 2),
            "separation_ft": round(sep_ft, 2),
            "expected_scale_pt_per_ft": expected_scale_pt_per_ft,
            "derived_scale_pt_per_ft": round(scale, 6),
            "scale_drift_pct": round(drift * 100, 3) if drift is not None else None,
            "assume_reflection": bool(assume_reflection),
            "chirality": chirality,
            "blockers": blockers,
            "warnings": warnings,
        },
    }
    return base


def _benchmark_fail(reason: str, pairs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "method": "benchmark_2pt",
        "calibration_source": "benchmark_verified",
        "source_recognized": True,
        "created_at": _now_iso(),
        "transform_direction": TRANSFORM_DIRECTION,
        "point_pairs": pairs,
        "validation_pairs": [],
        "transform": None,
        "quality": {
            "confidence": "failed", "match_allowed": False,
            "solve_rms_residual_pt": None, "solve_max_residual_pt": None,
            "validation_rms_residual_pt": None, "validation_max_residual_pt": None,
            "used_pair_count": len(pairs), "validation_pair_count": 0,
            "validation_failed": False,
            "confidence_reason": reason,
            "rms_residual_pt": None, "max_residual_pt": None, "reason": reason,
        },
        "benchmark": {"blockers": [reason], "warnings": []},
    }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def save_calibration(calibration: dict[str, Any]) -> None:
    config.artifact_path("registration").write_text(
        json.dumps(calibration, indent=2), encoding="utf-8"
    )


def load_calibration() -> dict[str, Any] | None:
    path = config.artifact_path("registration")
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def delete_calibration() -> bool:
    path = config.artifact_path("registration")
    if path.exists():
        path.unlink()
        return True
    return False


def calibration_source(calibration: dict[str, Any] | None) -> str | None:
    return calibration.get("calibration_source") if calibration else None


def registration_usable(calibration: dict[str, Any] | None) -> bool:
    """MATCH is only allowed when the stored quality.match_allowed gate is true.

    That gate already requires a verified calibration_source, high/medium solve
    confidence, and (if supplied) passing holdout validation.
    """
    if not calibration or not calibration.get("transform"):
        return False
    return bool(calibration.get("quality", {}).get("match_allowed"))


def registration_status(calibration: dict[str, Any] | None) -> str:
    """Coarse, unambiguous status. match_allowed remains the true MATCH gate."""
    if not calibration:
        return "missing"
    quality = calibration.get("quality", {})
    conf = quality.get("confidence")
    if conf == "failed" or not calibration.get("transform"):
        return "failed"
    if calibration.get("calibration_source") == DIAGNOSTIC_SOURCE:
        return "diagnostic_only"
    if conf == "low":
        return "low_confidence"
    if not quality.get("match_allowed"):
        # Verified source + acceptable solve but blocked (e.g. failed validation).
        return "low_confidence"
    return "available"  # high or medium, verified, validation ok/absent


# ---------------------------------------------------------------------------
# coordinate_registration_report.json
# ---------------------------------------------------------------------------
def build_registration_report(calibration: dict[str, Any] | None) -> dict[str, Any]:
    status = registration_status(calibration)
    usable = registration_usable(calibration)
    quality = (calibration or {}).get("quality", {}) if calibration else {}
    source = calibration_source(calibration)

    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    required_inputs: list[str] = []

    if status == "missing":
        blockers.append({
            "code": "REGISTRATION_MISSING", "severity": "blocking",
            "message": "No Revit->PDF coordinate registration exists.",
            "recommended_fix": "POST /api/registration/manual with >=3 verified matching point pairs.",
        })
        required_inputs = [
            "At least 3 non-collinear matching point pairs (pdf_point + revit_point), "
            "e.g. shared grid intersections on S-201.",
        ]
    elif status == "failed":
        blockers.append({
            "code": "REGISTRATION_FAILED", "severity": "blocking",
            "message": quality.get("confidence_reason") or quality.get("reason")
            or "Registration could not be solved.",
            "recommended_fix": "Provide 3+ non-collinear, correctly matched point pairs.",
        })
        required_inputs = ["3+ non-collinear correctly matched point pairs."]
    elif status == "diagnostic_only":
        blockers.append({
            "code": "AUTO_EXTENT_CALIBRATION_DIAGNOSTIC_ONLY", "severity": "blocking",
            "message": DIAGNOSTIC_NOTE,
            "recommended_fix": "Submit manual_verified / grid_verified / anchor_verified "
                               "point pairs at real shared features.",
        })
        required_inputs = ["Verified shared grid/anchor point pairs (>=3, prefer 4+)."]
    elif status == "low_confidence":
        if quality.get("validation_failed"):
            blockers.append({
                "code": "REGISTRATION_VALIDATION_FAILED", "severity": "blocking",
                "message": (
                    f"Holdout validation RMS={quality.get('validation_rms_residual_pt')}pt / "
                    f"max={quality.get('validation_max_residual_pt')}pt exceeds limits."
                ),
                "recommended_fix": "Re-pick calibration/validation points; ensure correct correspondences.",
            })
            required_inputs = ["More accurate calibration points; independent validation pairs that pass."]
        else:
            blockers.append({
                "code": "REGISTRATION_LOW_CONFIDENCE", "severity": "blocking",
                "message": (
                    f"Solve RMS={quality.get('solve_rms_residual_pt')}pt / "
                    f"max={quality.get('solve_max_residual_pt')}pt exceeds acceptable thresholds."
                ),
                "recommended_fix": "Re-pick calibration points more precisely or add more pairs.",
            })
            required_inputs = ["More precise / additional point pairs to reach medium or high confidence."]

    # Unvalidated warning when usable but no holdout supplied.
    if usable and not quality.get("validation_pair_count"):
        warnings.append({
            "code": "REGISTRATION_UNVALIDATED", "severity": "warning",
            "message": "Calibration is accepted but has no independent holdout validation.",
            "recommended_fix": "Add validation_pairs (known hold-downs not used in the solve) to confirm interior alignment.",
        })

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "registration_status": status,
        "calibration_source": source,
        "transform_direction": TRANSFORM_DIRECTION,
        "method": (calibration or {}).get("method") if calibration else None,
        "quality": quality or None,
        "solve_rms_residual_pt": quality.get("solve_rms_residual_pt") if quality else None,
        "solve_max_residual_pt": quality.get("solve_max_residual_pt") if quality else None,
        "validation_rms_residual_pt": quality.get("validation_rms_residual_pt") if quality else None,
        "validation_max_residual_pt": quality.get("validation_max_residual_pt") if quality else None,
        "match_allowed": usable,
        "blockers": blockers,
        "warnings": warnings,
        "required_user_inputs": required_inputs,
        "notes": [
            "Comparison transforms Revit coordinates (feet) into PDF page points; raw "
            "feet are never compared directly to PDF points.",
            "Only verified calibration sources (manual_verified/grid_verified/anchor_verified) "
            "may permit a MATCH. auto_extent_estimate is diagnostic only.",
            "The inverse transform (pdf_points->revit_internal_feet) is stored in the "
            "calibration artifact for reference but is not used by comparison.",
        ],
    }


def save_registration_report(calibration: dict[str, Any] | None) -> dict[str, Any]:
    report = build_registration_report(calibration)
    config.artifact_path("registration_report").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return report
