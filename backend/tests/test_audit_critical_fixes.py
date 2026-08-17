"""Regression tests for the CRITICAL findings in docs/CODEBASE_AUDIT_REPORT.md.

One test per defect, each failing against the pre-fix code:
  C-1  fabricated Simpson specs stamped onto generic (non-Madera) detections
  C-3  OpenRouter key prefix served on the unauthenticated /api/health
  C-4  wall_match AttributeError on a persisted transform:None
  C-5  RANSAC returning ok:true after persisting a failed calibration
  C-2  self-referential PDF baseline on the generic path
  §8-8/9  path traversal via a URL path param / an artifact-supplied path
  §9-6 load_artifact 500 on a truncated JSON artifact
"""

from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest
from fastapi import HTTPException

from app import compare, config, control_points, ransac_holdown, registration, s201_detector, wall_match
from app.routers import common, elements


@pytest.fixture
def tmp_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# CRITICAL-1 — fabricated engineering specs
# ---------------------------------------------------------------------------
def _synthetic_page(doc: fitz.Document) -> fitz.Page:
    page = doc.new_page(width=612, height=792)
    page.insert_text((100, 200), "H2", fontsize=10)
    page.insert_text((300, 400), "H1", fontsize=10)
    return page


def _detect(page: fitz.Page, schedule):
    return s201_detector.detect_holdowns_on_page(
        page, page_index=0, sheet_number="T", schedule=schedule,
        mark_pattern="H[1-4]", table_bboxes=[], plan_bbox=(0.0, 0.0, 612.0, 792.0),
    )


def test_generic_path_never_fabricates_schedule_specs() -> None:
    """schedule={} means 'this project has no schedule', not 'use Madera's'."""
    with fitz.open() as doc:
        detections = _detect(_synthetic_page(doc), {})
    assert detections, "expected the synthetic marks to be detected"
    for d in detections:
        assert d["anchor_bolt"] == ""
        assert d["fasteners"] == ""
        assert d["embedment"] == ""
        assert d["schedule_type_raw"] == ""
        assert d["schedule_source"] == "none"


def test_legacy_path_never_fabricates_without_profile() -> None:
    """schedule=None (the legacy S-201 call) must NOT substitute Madera's
    defaults unless the project opted into the madera profile — honest
    'schedule_not_parsed' + empty specs otherwise."""
    with fitz.open() as doc:
        detections = _detect(_synthetic_page(doc), None)
    by_mark = {d["normalized_mark"]: d for d in detections}
    assert by_mark["H2"]["anchor_bolt"] == ""
    assert by_mark["H2"]["schedule_source"] == "schedule_not_parsed"


def test_madera_profile_opt_in_still_gets_the_default_schedule_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the madera profile active, schedule=None may use the frozen
    defaults — and it is labelled as such, never passed off as detected."""
    import app.profile as profile_mod
    monkeypatch.setattr(profile_mod, "detection_profile", lambda: "madera")
    with fitz.open() as doc:
        detections = _detect(_synthetic_page(doc), None)
    by_mark = {d["normalized_mark"]: d for d in detections}
    assert by_mark["H2"]["anchor_bolt"] == s201_detector.DEFAULT_HOLDOWN_SCHEDULE["H2"]["anchor_bolt"]
    assert by_mark["H2"]["schedule_source"] == "default_madera"


def test_detected_schedule_rows_are_labelled_detected() -> None:
    with fitz.open() as doc:
        detections = _detect(_synthetic_page(doc), {"H1": {"anchor_bolt": '1/2"'}})
    by_mark = {d["normalized_mark"]: d for d in detections}
    assert by_mark["H1"]["anchor_bolt"] == '1/2"'
    assert by_mark["H1"]["schedule_source"] == "detected"
    # A mark the read schedule does not cover is honestly labelled — never
    # passed off as read from the drawing, never given fabricated defaults.
    assert by_mark["H2"]["schedule_source"] == "not_in_schedule"
    assert by_mark["H2"]["anchor_bolt"] == ""


# ---------------------------------------------------------------------------
# CRITICAL-3 — key prefix on /api/health
# ---------------------------------------------------------------------------
def test_openrouter_status_exposes_no_key_material() -> None:
    status = config.openrouter_config_status()
    assert "api_key_preview" not in status
    assert set(status) == {"api_key_present", "model", "base_url"}
    assert isinstance(status["api_key_present"], bool)


# ---------------------------------------------------------------------------
# CRITICAL-4 / CRITICAL-5 — the failed-calibration pair
# ---------------------------------------------------------------------------
def _failed_calibration() -> dict:
    """Collinear pairs — registration refuses to solve and stores transform:None."""
    pairs = [
        {"id": f"p{i}", "revit_point": {"x": float(i), "y": 0.0},
         "pdf_point": {"x": float(i) * 2, "y": 0.0}}
        for i in range(4)
    ]
    cal = registration.compute_calibration(pairs, calibration_source="unit_test")
    assert cal["transform"] is None and cal["quality"]["confidence"] == "failed"
    return cal


def test_wall_match_survives_a_stored_transform_none() -> None:
    report = wall_match.match_shear_walls(
        revit_walls=[], sheet_marks=[
            {"id": "m1", "mark": "SW1", "category": "shear_wall", "center_pdf": [10.0, 20.0]}
        ],
        calibration=_failed_calibration(),
    )
    assert report["usable_calibration"] is False
    assert report["rows"][0]["verdict"] == "NEEDS_REVIEW"


def test_ransac_does_not_persist_a_failed_calibration(
    tmp_artifacts: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RANSAC finds consensus, then the similarity solve degenerates.

    The degenerate solve is injected rather than coaxed out of a point cloud:
    the branch under test is "compute_calibration came back failed", and that is
    the only input that reaches it.
    """
    honest = [(0, 0), (10, 0), (0, 10), (10, 10), (5, 7), (3, 8), (8, 2), (7, 4)]
    rev = [
        {"id": f"r{i}", "pdf_mark_candidate": "H1",
         "center_point": {"x": float(x), "y": float(y), "z": 1.5,
                          "space": "revit_internal", "unit": "feet"}}
        for i, (x, y) in enumerate(honest)
    ]
    pdf = [
        {"id": f"p{i}", "normalized_mark": "H1",
         "center_point": {"x": 2.0 * x + 10.0, "y": 2.0 * y + 5.0, "z": None,
                          "space": "pdf_page", "unit": "points"}}
        for i, (x, y) in enumerate(honest)
    ]
    saved: list[dict] = []
    monkeypatch.setattr(registration, "save_calibration", lambda c: saved.append(c))
    monkeypatch.setattr(registration, "save_registration_report", lambda c: saved.append(c))
    failed = _failed_calibration()
    monkeypatch.setattr(registration, "compute_calibration", lambda *a, **k: dict(failed))

    res = ransac_holdown.ransac_calibrate(
        {"canonical_holdown_assemblies": rev}, {"holdowns": pdf},
        distance_threshold_pt=2.0, iterations=500,
    )
    assert res["ok"] is False
    assert res["saved"] is False
    assert "not saved" in res["reason"].lower()
    assert saved == [], "a failed calibration must never be persisted"


# ---------------------------------------------------------------------------
# CRITICAL-2 — the generic-path baseline must not be self-referential
# ---------------------------------------------------------------------------
def _write_intel(root: Path, payload: dict) -> None:
    (root / config.ARTIFACT_FILES["pdf_page_intelligence"]).write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_pdf_baseline_is_none_without_an_expected_baseline(tmp_artifacts: Path) -> None:
    _write_intel(tmp_artifacts, {"summary": {"by_type": {"HD2": 7}}})
    assert compare._project_pdf_baseline() is None


def test_pdf_baseline_reads_the_recorded_expectation(tmp_artifacts: Path) -> None:
    _write_intel(tmp_artifacts, {"expected_baseline": {"H1": 2, "H2": 3},
                                 "summary": {"by_type": {"H1": 9}}})
    assert compare._project_pdf_baseline() == {"H1": 2, "H2": 3}


def test_scope_diagnostics_quotes_no_borrowed_baseline(tmp_artifacts: Path) -> None:
    _write_intel(tmp_artifacts, {"summary": {"by_type": {"HD2": 7}}})
    diag = control_points.build_scope_diagnostics({"holdowns": []}, {})
    assert diag["pdf_baseline"] is None
    assert "54" not in diag["summary"] and "delta" not in diag["summary"]
    assert not any("PDF baseline" in r for r in diag["recommended_filters"])


def test_scope_diagnostics_uses_this_projects_baseline(tmp_artifacts: Path) -> None:
    _write_intel(tmp_artifacts, {"expected_baseline": {"H1": 2, "H2": 3}})
    diag = control_points.build_scope_diagnostics({"holdowns": []}, {})
    assert diag["pdf_baseline"] == {"H1": 2, "H2": 3, "total": 5}


# ---------------------------------------------------------------------------
# §8-8 / §8-9 — path traversal
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value",
    ["../secret", "..\\secret", "a/b", "a\\b", "..", "", "C:evil", "S-201/../../x"],
)
def test_sheet_path_param_rejects_traversal(value: str) -> None:
    with pytest.raises(HTTPException) as exc:
        elements.safe_path_param(value, "Sheet")
    assert exc.value.status_code == 404


def test_sheet_path_param_accepts_a_plain_sheet_name() -> None:
    assert elements.safe_path_param("S-201", "Sheet") == "S-201"


def test_artifact_source_file_must_stay_inside_the_project(tmp_artifacts: Path) -> None:
    inside = tmp_artifacts / "uploads" / "input.pdf"
    assert elements.contained_project_pdf(str(inside)) == inside.resolve()
    assert elements.contained_project_pdf("uploads/input.pdf") == inside.resolve()
    for outside in (r"C:\Windows\win.ini", "/etc/passwd", "../../../etc/passwd"):
        with pytest.raises(HTTPException) as exc:
            elements.contained_project_pdf(outside)
        assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# §9-6 — a truncated artifact is a 409, not a 500
# ---------------------------------------------------------------------------
def test_load_artifact_reports_invalid_json_as_409(tmp_artifacts: Path) -> None:
    (tmp_artifacts / config.ARTIFACT_FILES["element_list"]).write_text(
        '{"elements": [', encoding="utf-8"
    )
    with pytest.raises(HTTPException) as exc:
        common.load_artifact("element_list")
    assert exc.value.status_code == 409
    assert "not valid JSON" in exc.value.detail
    assert "re-run the producing step" in exc.value.detail
