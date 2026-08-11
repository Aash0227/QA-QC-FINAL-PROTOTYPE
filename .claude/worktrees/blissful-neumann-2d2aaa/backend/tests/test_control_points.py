"""Tests for revit/pdf control points, label-pairing, grid-verified calibration,
and standalone Revit scope diagnostics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import compare as compare_mod
from app import config, control_points, registration


@pytest.fixture
def tmp_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect artifact writes to a per-test tmp dir."""
    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path)
    return tmp_path


def _orthogonal_grid_raw() -> dict:
    return {
        "export_scope": "model",
        "grids": [
            {"label": "A", "line": [[0, 0], [0, 100]]},
            {"label": "B", "line": [[50, 0], [50, 100]]},
            {"label": "C", "line": [[100, 0], [100, 100]]},
            {"label": "1", "line": [[-10, 0], [200, 0]]},
            {"label": "2", "line": [[-10, 50], [200, 50]]},
            {"label": "3", "line": [[-10, 100], [200, 100]]},
        ],
    }


def test_extract_revit_control_points_from_grids() -> None:
    cp = control_points.extract_revit_control_points(_orthogonal_grid_raw())
    assert cp["schema_version"].startswith("revit-control-points/")
    ids = sorted(p["id"] for p in cp["points"])
    assert ids == [
        "grid_A_1", "grid_A_2", "grid_A_3",
        "grid_B_1", "grid_B_2", "grid_B_3",
        "grid_C_1", "grid_C_2", "grid_C_3",
    ]
    b2 = next(p for p in cp["points"] if p["id"] == "grid_B_2")
    assert b2["point"]["x"] == 50.0 and b2["point"]["y"] == 50.0


def test_extract_returns_empty_with_warnings_when_no_grids() -> None:
    cp = control_points.extract_revit_control_points({"grids": []})
    assert cp["points"] == []
    assert cp["warnings"]


def test_revit_control_points_artifact_created_even_when_empty(tmp_artifacts: Path) -> None:
    cp = control_points.extract_revit_control_points({"grids": []})
    control_points.save_revit_control_points(cp)
    path = config.artifact_path("revit_control_points")
    assert path.exists()
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["points"] == []
    assert saved["warnings"]


def test_pdf_control_points_round_trip(tmp_artifacts: Path) -> None:
    saved = control_points.save_pdf_control_points(
        [
            {"id": "grid_A_1", "label": "Grid A/1", "point": {"x": 301.22, "y": 1272.96}},
            {"id": "grid_B_2", "label": "Grid B/2", "point": {"x": 838.0, "y": 750.0}},
        ],
        sheet_number="S-201",
        page_index=4,
    )
    assert [p["id"] for p in saved["points"]] == ["grid_A_1", "grid_B_2"]
    loaded = control_points.load_or_init_pdf_control_points()
    assert loaded["sheet_number"] == "S-201"
    assert loaded["page_index"] == 4
    assert loaded["points"][0]["point"]["x"] == 301.22


def test_pdf_control_points_init_empty_with_warning(tmp_artifacts: Path) -> None:
    cp = control_points.load_or_init_pdf_control_points()
    assert cp["points"] == []
    assert cp["warnings"]


def test_pairs_built_from_matching_labels() -> None:
    rev_cp = {"points": [
        {"id": "grid_A_1", "point": {"x": 0, "y": 100}},
        {"id": "grid_B_2", "point": {"x": 50, "y": 50}},
        {"id": "grid_C_3", "point": {"x": 100, "y": 0}},
    ]}
    pdf_cp = {"points": [
        {"id": "grid_A_1", "point": {"x": 301.22, "y": 1272.96}},
        {"id": "grid_B_2", "point": {"x": 838.0, "y": 750.0}},
        {"id": "grid_Z_9", "point": {"x": 0, "y": 0}},
    ]}
    pairs = control_points.build_pairs_from_labels(rev_cp, pdf_cp)
    assert pairs["matched_ids"] == ["grid_A_1", "grid_B_2"]
    assert pairs["revit_only_ids"] == ["grid_C_3"]
    assert pairs["pdf_only_ids"] == ["grid_Z_9"]
    assert pairs["calibration_source"] == "grid_verified"


def test_auto_calibrate_with_too_few_pairs_returns_not_ok(tmp_artifacts: Path) -> None:
    control_points.save_pdf_control_points([
        {"id": "grid_A_1", "point": {"x": 0, "y": 100}},
    ])
    result = control_points.auto_calibrate_from_grids(_orthogonal_grid_raw())
    assert result["ok"] is False
    assert "Need >= 3" in result["reason"]
    assert result["calibration"] is None


def test_auto_calibrate_grid_verified_allows_match(tmp_artifacts: Path) -> None:
    raw = _orthogonal_grid_raw()
    rev_cp = control_points.extract_revit_control_points(raw)
    control_points.save_pdf_control_points([
        {"id": p["id"], "label": p["label"], "point": {"x": p["point"]["x"], "y": p["point"]["y"]}}
        for p in rev_cp["points"]
    ])
    result = control_points.auto_calibrate_from_grids(raw)
    assert result["ok"] is True
    cal = result["calibration"]
    assert cal["calibration_source"] == "grid_verified"
    assert cal["quality"]["match_allowed"] is True
    assert config.artifact_path("revit_control_points").exists()
    assert config.artifact_path("manual_registration_points").exists()
    assert config.artifact_path("registration").exists()


def test_failed_validation_blocks_match_in_grid_pipeline(tmp_artifacts: Path) -> None:
    raw = _orthogonal_grid_raw()
    rev_cp = control_points.extract_revit_control_points(raw)
    control_points.save_pdf_control_points([
        {"id": p["id"], "label": p["label"], "point": {"x": p["point"]["x"], "y": p["point"]["y"]}}
        for p in rev_cp["points"]
    ])
    bad_validation = [{
        "id": "holdout_bad",
        "revit_point": {"x": 25, "y": 25},
        "pdf_point": {"x": 80, "y": 25},
    }]
    result = control_points.auto_calibrate_from_grids(raw, validation_pairs=bad_validation)
    assert result["ok"] is True
    cal = result["calibration"]
    assert cal["quality"]["validation_failed"] is True
    assert cal["quality"]["match_allowed"] is False


def _stub_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        compare_mod, "_llm_assessment",
        lambda per_mark, reg_status, blockers: {
            "status": {"called": False, "ok": False, "model": "x"}, "parsed": None,
        },
    )


def test_sample_placeholder_calibration_cannot_emit_match(
    tmp_artifacts: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_llm(monkeypatch)
    cal = registration.compute_calibration(
        [
            {"id": "p1", "pdf_point": {"x": 0, "y": 0}, "revit_point": {"x": 0, "y": 0}},
            {"id": "p2", "pdf_point": {"x": 100, "y": 0}, "revit_point": {"x": 100, "y": 0}},
            {"id": "p3", "pdf_point": {"x": 0, "y": 100}, "revit_point": {"x": 0, "y": 100}},
        ],
        calibration_source="sample",
    )
    assert cal["quality"]["match_allowed"] is False
    ai_revit = {"canonical_holdown_assemblies": [
        {"id": "r1", "pdf_mark_candidate": "H1",
         "center_point": {"x": 50, "y": 50, "z": 1.5, "space": "revit_internal", "unit": "feet"}},
    ]}
    ai_pdf = {"holdowns": [
        {"id": "p1", "normalized_mark": "H1",
         "center_point": {"x": 50, "y": 50, "z": None, "space": "pdf_page", "unit": "points"}},
    ]}
    report = compare_mod.compare(ai_revit, ai_pdf, calibration=cal)
    assert report["summary"]["verdict_counts"]["MATCH"] == 0


def test_scope_diagnostics_flags_missing_metadata() -> None:
    raw = {
        "export_scope": "model",
        "holdowns": [
            {"family": "SHDU6", "scheduled_type": "HDU6", "category": "Structural Connections",
             "level": None, "view": None, "elevation": 1.5},
            {"family": "SHDU11", "scheduled_type": "HDU11", "category": "Structural Connections",
             "level": None, "view": None, "elevation": 1.5},
        ],
    }
    ai = {"canonical_holdown_assemblies": [
        {"pdf_mark_candidate": "H1"}, {"pdf_mark_candidate": "H2"},
    ]}
    diag = control_points.build_scope_diagnostics(raw, ai)
    assert diag["pdf_baseline"]["total"] == 54
    msgs = " ".join(diag["warnings"]).lower()
    assert "level=null" in msgs
    assert "view=null" in msgs
    required = " ".join(diag["required_exporter_fields"]).lower()
    assert "level" in required and "view" in required


def test_scope_diagnostics_artifact_written(tmp_artifacts: Path) -> None:
    raw = {"export_scope": "model", "holdowns": []}
    ai: dict = {"canonical_holdown_assemblies": []}
    control_points.save_scope_diagnostics(raw, ai)
    assert config.artifact_path("revit_scope_diagnostics").exists()
