"""Tests for mark-constrained RANSAC hold-down registration."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from app import config, ransac_holdown, registration


@pytest.fixture
def tmp_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path)
    return tmp_path


def _rev(mark: str, x: float, y: float, idx: int) -> dict:
    return {
        "id": f"r{idx}", "pdf_mark_candidate": mark,
        "center_point": {"x": x, "y": y, "z": 1.5, "space": "revit_internal", "unit": "feet"},
    }


def _pdf(mark: str, x: float, y: float, idx: int) -> dict:
    return {
        "id": f"p{idx}", "normalized_mark": mark,
        "center_point": {"x": x, "y": y, "z": None, "space": "pdf_page", "unit": "points"},
    }


def _apply_known(rx: float, ry: float) -> tuple[float, float]:
    return 2.0 * rx + 10.0, 2.0 * ry + 5.0


def test_ransac_recovers_known_transform_with_outliers(tmp_artifacts: Path) -> None:
    rev = []
    pdf = []
    honest = [(0, 0), (10, 0), (0, 10), (10, 10), (5, 7), (3, 8), (8, 2), (7, 4)]
    for i, (x, y) in enumerate(honest):
        rev.append(_rev("H1", x, y, i))
        px, py = _apply_known(x, y)
        pdf.append(_pdf("H1", px, py, i))
    for i, (x, y) in enumerate([(50, 50), (60, 60), (70, 70), (80, 80)]):
        rev.append(_rev("H1", x, y, 100 + i))

    res = ransac_holdown.ransac_calibrate(
        {"canonical_holdown_assemblies": rev},
        {"holdowns": pdf},
        distance_threshold_pt=2.0,
        iterations=1000,
        restarts=5,
    )
    assert res["ok"], res
    inliers = res["summary"]["inliers"]
    assert inliers >= 6
    cal = res["calibration"]
    assert cal["calibration_source"] == "holdown_ransac"
    assert cal["quality"]["match_allowed"] is True
    assert math.isclose(cal["transform"]["scale"], 2.0, rel_tol=0.05)
    assert cal["transform"]["reflection"] is False


def test_ransac_too_few_correspondences(tmp_artifacts: Path) -> None:
    res = ransac_holdown.ransac_calibrate(
        {"canonical_holdown_assemblies": [_rev("H1", 0, 0, 0)]},
        {"holdowns": [_pdf("H2", 0, 0, 0)]},
        iterations=10,
        restarts=1,
    )
    assert res["ok"] is False
    assert "3+" in res["reason"]


def test_holdown_ransac_source_in_verified_sources() -> None:
    assert "holdown_ransac" in registration.VERIFIED_SOURCES


def _seed_benchmark_calibration() -> dict:
    """A usable benchmark_verified calibration matching the known 2x+10/2y+5 map."""
    pairs = []
    for i, (x, y) in enumerate([(0, 0), (100, 0), (0, 100), (100, 100)]):
        px, py = _apply_known(x, y)
        pairs.append({"id": f"bm{i}", "revit_point": {"x": x, "y": y},
                      "pdf_point": {"x": px, "y": py}})
    cal = registration.compute_calibration(pairs, calibration_source="benchmark_verified")
    registration.save_calibration(cal)
    return cal


def test_ransac_keeps_benchmark_verified_calibration(tmp_artifacts: Path) -> None:
    seeded = _seed_benchmark_calibration()
    assert registration.registration_usable(seeded)

    rev, pdf = [], []
    honest = [(0, 0), (10, 0), (0, 10), (10, 10), (5, 7), (3, 8), (8, 2), (7, 4)]
    for i, (x, y) in enumerate(honest):
        rev.append(_rev("H1", x, y, i))
        px, py = _apply_known(x, y)
        pdf.append(_pdf("H1", px, py, i))

    res = ransac_holdown.ransac_calibrate(
        {"canonical_holdown_assemblies": rev}, {"holdowns": pdf},
        distance_threshold_pt=2.0, iterations=1000, restarts=5,
    )
    assert res["ok"] is True
    assert res["saved"] is False
    assert res["kept_calibration_source"] == "benchmark_verified"
    assert "note" in res and "retained" in res["note"]
    assert res["drift_report"]["compared_points"] >= 6
    # The saved calibration on disk is UNTOUCHED — still benchmark_verified.
    on_disk = registration.load_calibration()
    assert on_disk["calibration_source"] == "benchmark_verified"
