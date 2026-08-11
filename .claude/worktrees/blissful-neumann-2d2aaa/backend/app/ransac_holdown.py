"""Mark-constrained RANSAC similarity registration using hold-down centers.

Problem: PDF S-201 has 54 hold-downs (locked), Revit model has 72 (over-counts
by 18 because the exporter pulls every level). No manual PDF grid bubble
coordinates have been collected. But same-mark hold-downs on both sides
correspond to the same physical hardware, so the hold-downs ARE the
correspondences.

Approach (textbook RANSAC for similarity transform):
  1. Build candidate correspondences: every (revit, pdf) pair within the same
     mark.
  2. Repeatedly sample 3 non-collinear pairs, fit similarity transform, count
     inliers under one-to-one greedy assignment within each mark.
  3. Refit on inliers, keep the transform with most inliers (tie-break by RMS).
  4. Hand the resulting inlier pairs to registration.compute_calibration() with
     calibration_source='holdown_ransac' (must be in VERIFIED_SOURCES). MATCH
     gating is still the existing 16pt threshold from compare.py.

This does NOT fake matches. Hold-downs that don't have a real partner remain
REVIT_ONLY/PDF_ONLY after compare runs.
"""

from __future__ import annotations

import math
import random
from typing import Any

from . import registration

SCALE_MIN = 1.0
SCALE_MAX = 200.0


def _gather(
    records: list[dict[str, Any]], mark_key: str
) -> dict[str, list[tuple[float, float]]]:
    by_mark: dict[str, list[tuple[float, float]]] = {}
    for r in records:
        m = r.get(mark_key)
        c = r.get("center_point") or {}
        if not m:
            continue
        x, y = c.get("x"), c.get("y")
        if x is None or y is None:
            continue
        try:
            by_mark.setdefault(str(m), []).append((float(x), float(y)))
        except (TypeError, ValueError):
            continue
    return by_mark


def _score(
    matrix: list[float],
    rev_by_mark: dict[str, list[tuple[float, float]]],
    pdf_by_mark: dict[str, list[tuple[float, float]]],
    threshold: float,
) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    inliers: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for mark in rev_by_mark.keys() & pdf_by_mark.keys():
        rev = rev_by_mark[mark]
        pdf = pdf_by_mark[mark]
        rev_transformed = [registration.apply_transform(matrix, r[0], r[1]) for r in rev]
        candidates: list[tuple[float, int, int]] = []
        for ri, (Xr, Yr) in enumerate(rev_transformed):
            for pi, (Xp, Yp) in enumerate(pdf):
                d = math.hypot(Xr - Xp, Yr - Yp)
                if d <= threshold:
                    candidates.append((d, ri, pi))
        candidates.sort(key=lambda c: c[0])
        used_r: set[int] = set()
        used_p: set[int] = set()
        for d, ri, pi in candidates:
            if ri in used_r or pi in used_p:
                continue
            used_r.add(ri)
            used_p.add(pi)
            inliers.append((rev[ri], pdf[pi]))
    return inliers


def ransac_calibrate(
    ai_revit: dict[str, Any],
    ai_pdf: dict[str, Any],
    distance_threshold_pt: float = 16.0,
    iterations: int = 4000,
    seed: int = 42,
    restarts: int = 20,
) -> dict[str, Any]:
    rev_by_mark = _gather(
        ai_revit.get("canonical_holdown_assemblies", []), "pdf_mark_candidate"
    )
    pdf_by_mark = _gather(ai_pdf.get("holdowns", []), "normalized_mark")

    candidate_pairs: list[tuple[tuple[float, float], tuple[float, float], str]] = []
    for mark in rev_by_mark.keys() & pdf_by_mark.keys():
        for r in rev_by_mark[mark]:
            for p in pdf_by_mark[mark]:
                candidate_pairs.append((r, p, mark))

    if len(candidate_pairs) < 3:
        return {
            "ok": False,
            "reason": (
                f"Need 3+ same-mark correspondences; got {len(candidate_pairs)}. "
                "Check that both AIConvert files carry hold-downs with marks."
            ),
        }

    # Multi-seed restarts: each random.Random seed explores a different sample
    # path; consensus space has many local optima, so we keep the best across
    # all restarts. Total work = restarts * iterations.
    rng_master = random.Random(seed)
    seeds = [rng_master.randint(0, 2**31 - 1) for _ in range(max(1, restarts))]
    best: tuple[int, float, list[float], bool] | None = None
    inspected = 0

    for outer_seed in seeds:
        rng = random.Random(outer_seed)
        for _ in range(iterations):
            sample = rng.sample(candidate_pairs, 3)
            src = [s[0] for s in sample]
            dst = [s[1] for s in sample]
            if registration._is_collinear(src):
                continue
            for reflect in (False, True):
                fit = registration._fit_variant(src, dst, reflect)
                if fit is None:
                    continue
                matrix, scale, _, _ = fit
                if not (SCALE_MIN <= scale <= SCALE_MAX):
                    continue
                inspected += 1
                inliers = _score(matrix, rev_by_mark, pdf_by_mark, distance_threshold_pt)
                n = len(inliers)
                if n < 3:
                    continue
                refit = registration._fit_variant(
                    [p[0] for p in inliers], [p[1] for p in inliers], reflect
                )
                if refit is None:
                    continue
                matrix2, _, _, residuals2 = refit
                rms2 = math.sqrt(sum(r * r for r in residuals2) / len(residuals2))
                inliers2 = _score(matrix2, rev_by_mark, pdf_by_mark, distance_threshold_pt)
                n2 = len(inliers2)
                score = (n2, -rms2)
                if best is None or score > (best[0], -best[1]):
                    best = (n2, rms2, matrix2, reflect)

    if best is None:
        return {
            "ok": False,
            "reason": (
                f"RANSAC found no consensus transform over {iterations} iterations "
                f"({inspected} valid fits inspected). Layouts likely differ between "
                "Revit and PDF (different sheets, units, or scope)."
            ),
        }

    inlier_count, rms, matrix, reflect = best
    final_inliers = _score(matrix, rev_by_mark, pdf_by_mark, distance_threshold_pt)
    point_pairs = [
        {
            "id": f"holdown_pair_{i + 1:03d}",
            "label": "auto_ransac_holdown",
            "revit_point": {"x": r[0], "y": r[1]},
            "pdf_point": {"x": p[0], "y": p[1]},
        }
        for i, (r, p) in enumerate(final_inliers)
    ]

    calibration = registration.compute_calibration(
        point_pairs, calibration_source="holdown_ransac"
    )
    calibration["ransac"] = {
        "candidate_pair_count": len(candidate_pairs),
        "inlier_pair_count": inlier_count,
        "inspected_fits": inspected,
        "iterations": iterations,
        "distance_threshold_pt": distance_threshold_pt,
        "reflection": reflect,
        "score_rms_pt": round(rms, 4),
    }

    # A calibration whose solve failed has transform:None. Persisting it hands
    # every downstream reader (wall_match, device_match) a None to dereference,
    # so it is never saved and the caller is told the run did not succeed.
    if (calibration["quality"]["confidence"] == "failed"
            or not (calibration.get("transform") or {}).get("matrix")):
        return {
            "ok": False,
            "saved": False,
            "reason": (
                f"RANSAC reached consensus on {inlier_count} inlier pairs, but the "
                "similarity solve failed: "
                f"{calibration['quality'].get('confidence_reason') or 'degenerate point set'} "
                "Calibration not saved."
            ),
            "calibration": calibration,
        }

    summary = {
        "candidate_pairs": len(candidate_pairs),
        "inliers": inlier_count,
        "solve_rms_pt": calibration["quality"]["solve_rms_residual_pt"],
        "match_allowed": calibration["quality"]["match_allowed"],
    }

    # Benchmark-verified calibration has higher precedence than a ransac solve —
    # never silently downgrade it. Keep the ransac solve as evidence, report how
    # well the two transforms agree, but do NOT overwrite the saved calibration.
    existing = registration.load_calibration()
    if (registration.calibration_source(existing) == "benchmark_verified"
            and registration.registration_usable(existing)):
        ex_matrix = existing["transform"]["matrix"]
        deltas = []
        for r, _p in final_inliers:
            ax, ay = registration.apply_transform(matrix, r[0], r[1])
            bx, by = registration.apply_transform(ex_matrix, r[0], r[1])
            deltas.append(math.hypot(ax - bx, ay - by))
        max_delta = round(max(deltas), 4) if deltas else None
        mean_delta = round(sum(deltas) / len(deltas), 4) if deltas else None
        return {
            "ok": True,
            "saved": False,
            "kept_calibration_source": "benchmark_verified",
            "calibration": calibration,
            "summary": summary,
            "drift_report": {
                "compared_points": len(final_inliers),
                "max_delta_pt": max_delta,
                "mean_delta_pt": mean_delta,
                "ransac_scale": (calibration["transform"] or {}).get("scale"),
                "benchmark_scale": existing["transform"].get("scale"),
            },
            "note": (
                "Benchmark-verified calibration retained (higher precedence than "
                f"holdown_ransac). The ransac solve agrees with it to mean "
                f"{mean_delta}pt / max {max_delta}pt across {len(final_inliers)} "
                "inlier hold-downs; kept as evidence but not saved."
            ),
        }

    registration.save_calibration(calibration)
    registration.save_registration_report(calibration)

    return {
        "ok": True,
        "saved": True,
        "calibration": calibration,
        "summary": summary,
    }
