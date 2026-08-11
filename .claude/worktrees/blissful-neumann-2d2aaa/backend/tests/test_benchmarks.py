"""Tests for 2-benchmark registration (A1 solve + A2 PDF extraction)."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from app import config, registration
from app.benchmark_workflow import extract_pdf_benchmarks

SCALE = 18.0
TX, TY = 100.0, 1500.0


def _pdf_of(x: float, y: float, reflected: bool = True) -> tuple[float, float]:
    """Known ground-truth similarity: scale 18, rotation 0, translation."""
    return SCALE * x + TX, (-SCALE * y if reflected else SCALE * y) + TY


def _pdf_bm(mark: str, x: float, y: float) -> dict:
    return {"mark": mark, "point_pt": {"x": x, "y": y}}


def _rev_bm(mark: str, x: float, y: float) -> dict:
    return {"mark": mark, "point_ft": {"x": x, "y": y}}


def _benchmarks(reflected: bool = True) -> tuple[list[dict], list[dict]]:
    fts = {"BM-1": (10.0, 20.0), "BM-2": (60.0, 55.0)}   # 61ft apart
    pdf, rev = [], []
    for mark, (x, y) in fts.items():
        px, py = _pdf_of(x, y, reflected)
        pdf.append(_pdf_bm(mark, px, py))
        rev.append(_rev_bm(mark, x, y))
    return pdf, rev


def test_round_trip_recovers_exact_transform() -> None:
    pdf, rev = _benchmarks()
    cal = registration.compute_calibration_from_benchmarks(pdf, rev)
    assert cal["method"] == "benchmark_2pt"
    assert cal["calibration_source"] == "benchmark_verified"
    assert cal["quality"]["match_allowed"] is True
    # unvalidated -> capped at medium, never silently "high"
    assert cal["quality"]["confidence"] == "medium"
    assert abs(cal["benchmark"]["derived_scale_pt_per_ft"] - SCALE) < 1e-6
    # a probe point far from both benchmarks maps exactly
    X, Y = registration.apply_transform(cal["transform"]["matrix"], 33.0, 41.0)
    ex, ey = _pdf_of(33.0, 41.0)
    assert math.hypot(X - ex, Y - ey) < 1e-6


def test_holdout_validation_upgrades_to_high() -> None:
    pdf, rev = _benchmarks()
    vx, vy = _pdf_of(25.0, 40.0)
    cal = registration.compute_calibration_from_benchmarks(
        pdf, rev,
        validation_pairs=[{"id": "V1", "pdf_point": {"x": vx, "y": vy},
                           "revit_point": {"x": 25.0, "y": 40.0}}])
    assert cal["quality"]["confidence"] == "high"
    assert cal["quality"]["validation_failed"] is False


def test_bad_holdout_validation_blocks() -> None:
    pdf, rev = _benchmarks()
    vx, vy = _pdf_of(25.0, 40.0)
    cal = registration.compute_calibration_from_benchmarks(
        pdf, rev,
        validation_pairs=[{"id": "V1", "pdf_point": {"x": vx + 500, "y": vy},
                           "revit_point": {"x": 25.0, "y": 40.0}}])
    assert cal["quality"]["confidence"] == "failed"
    assert cal["quality"]["match_allowed"] is False


def test_scale_mismatch_blocker() -> None:
    pdf, rev = _benchmarks()
    cal = registration.compute_calibration_from_benchmarks(
        pdf, rev, expected_scale_pt_per_ft=24.0)   # true scale is 18 -> 25% off
    assert cal["quality"]["confidence"] == "failed"
    assert cal["quality"]["match_allowed"] is False
    assert any("BENCHMARK_SCALE_MISMATCH" in b for b in cal["benchmark"]["blockers"])


def test_chirality_conflict_blocker() -> None:
    # Ground truth here is NON-reflected; solving with assume_reflection=True
    # still fits the 2 benchmarks exactly, but the detection clouds expose it.
    pdf, rev = _benchmarks(reflected=False)
    cloud_ft = [(5.0, 5.0), (15.0, 30.0), (40.0, 12.0), (55.0, 48.0), (28.0, 60.0)]
    evidence = {
        "revit_points": [list(p) for p in cloud_ft],
        "pdf_points": [list(_pdf_of(x, y, reflected=False)) for x, y in cloud_ft],
    }
    cal = registration.compute_calibration_from_benchmarks(
        pdf, rev, assume_reflection=True, chirality_evidence=evidence)
    assert cal["quality"]["match_allowed"] is False
    assert any("BENCHMARK_CHIRALITY_CONFLICT" in b for b in cal["benchmark"]["blockers"])
    # and the honest re-run with the evidence-backed reflection is clean
    cal2 = registration.compute_calibration_from_benchmarks(
        pdf, rev, assume_reflection=False, chirality_evidence=evidence)
    assert cal2["quality"]["match_allowed"] is True


def test_duplicate_mark_is_hard_error() -> None:
    pdf, rev = _benchmarks()
    pdf.append(_pdf_bm("BM-1", 999.0, 999.0))
    cal = registration.compute_calibration_from_benchmarks(pdf, rev)
    assert cal["quality"]["confidence"] == "failed"
    assert "Duplicate" in cal["quality"]["reason"]


def test_missing_mark_is_hard_error() -> None:
    pdf, rev = _benchmarks()
    cal = registration.compute_calibration_from_benchmarks(pdf[:1], rev)
    assert cal["quality"]["match_allowed"] is False
    assert "BM-2" in cal["quality"]["reason"]


def test_benchmarks_too_close_blocked() -> None:
    pdf = [_pdf_bm("BM-1", 100.0, 100.0), _pdf_bm("BM-2", 150.0, 100.0)]
    rev = [_rev_bm("BM-1", 0.0, 0.0), _rev_bm("BM-2", 2.8, 0.0)]
    cal = registration.compute_calibration_from_benchmarks(pdf, rev)
    assert cal["quality"]["match_allowed"] is False
    assert "too close" in cal["quality"]["reason"]


def test_pdf_benchmarks_artifact_registered() -> None:
    assert config.ARTIFACT_FILES["pdf_benchmarks"] == "pdf_benchmarks.json"


# ---------------------------------------------------------------------------
# A2 extraction on generated fixture PDFs
# ---------------------------------------------------------------------------
def _fixture_pdf(tmp_path: Path, with_freetext_decoy: bool = True) -> Path:
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=2592, height=1728)
    a1 = page.add_rect_annot(fitz.Rect(300, 300, 330, 330))
    a1.set_info(subject="BM-1")
    a1.update()
    a2 = page.add_circle_annot(fitz.Rect(2200, 1400, 2230, 1430))
    a2.set_info(subject="BM-2")
    a2.update()
    if with_freetext_decoy:
        ft = page.add_freetext_annot(fitz.Rect(500, 500, 700, 530),
                                     "review comment near BM-1 maybe?")
        ft.update()
    out = tmp_path / "fixture.pdf"
    doc.save(str(out))
    doc.close()
    return out


def test_extract_finds_stamps_and_ignores_freetext(tmp_path: Path) -> None:
    res = extract_pdf_benchmarks(_fixture_pdf(tmp_path))
    got = {b["mark"]: b for b in res["benchmarks"]}
    assert set(got) == {"BM-1", "BM-2"}
    assert all(b["method"] == "annotation_stamp" for b in got.values())
    assert abs(got["BM-1"]["point_pt"]["x"] - 315.0) < 0.5
    assert abs(got["BM-2"]["point_pt"]["y"] - 1415.0) < 0.5


def test_extract_reports_missing_marks(tmp_path: Path) -> None:
    import fitz

    doc = fitz.open()
    doc.new_page(width=612, height=792)
    out = tmp_path / "empty.pdf"
    doc.save(str(out))
    doc.close()
    res = extract_pdf_benchmarks(out)
    assert res["benchmarks"] == []
    assert any("not found" in w for w in res["warnings"])


def test_extract_end_to_end_calibration(tmp_path: Path) -> None:
    """Fixture stamps -> extraction -> exact solve, one flow."""
    res = extract_pdf_benchmarks(_fixture_pdf(tmp_path))
    rev = [_rev_bm("BM-1", (315.0 - TX) / SCALE, -(315.0 - TY) / SCALE),
           _rev_bm("BM-2", (2215.0 - TX) / SCALE, -(1415.0 - TY) / SCALE)]
    cal = registration.compute_calibration_from_benchmarks(res["benchmarks"], rev)
    assert cal["quality"]["match_allowed"] is True
    assert abs(cal["benchmark"]["derived_scale_pt_per_ft"] - SCALE) < 0.01
