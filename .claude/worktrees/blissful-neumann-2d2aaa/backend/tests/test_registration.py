"""Phase 5 tests for coordinate registration + location-aware comparison."""
import math

import pytest

from app import compare as compare_mod
from app import registration


@pytest.fixture(autouse=True)
def stub_compare_llm(monkeypatch):
    monkeypatch.setattr(
        compare_mod,
        "_llm_assessment",
        lambda per_mark, reg_status, blockers: {
            "status": {"called": False, "ok": False, "model": "x"},
            "parsed": None,
        },
    )


def _pairs(mapping):
    return [
        {"id": f"p{i}", "pdf_point": {"x": px, "y": py}, "revit_point": {"x": rx, "y": ry}}
        for i, (px, py, rx, ry) in enumerate(mapping)
    ]


def _identity_calibration():
    # pdf == revit for 3 non-collinear points -> identity transform, RMS 0.
    return registration.compute_calibration(
        _pairs([(0, 0, 0, 0), (100, 0, 100, 0), (0, 100, 0, 100)])
    )


# --- Test 1: transform recovers a known mapping ---------------------------
def test_transform_recovers_known_mapping():
    # Revit -> PDF with scale 2, translation (10,5): pdf = 2*revit + (10,5).
    mapping = [
        (10, 5, 0, 0),
        (210, 5, 100, 0),
        (10, 205, 0, 100),
        (210, 205, 100, 100),
    ]
    cal = registration.compute_calibration(_pairs(mapping))
    assert cal["quality"]["confidence"] == "high"
    assert cal["transform"]["reflection"] is False
    assert math.isclose(cal["transform"]["scale"], 2.0, rel_tol=1e-6)
    X, Y = registration.apply_transform(cal["transform"]["matrix"], 50, 50)
    assert math.isclose(X, 110, abs_tol=1e-3) and math.isclose(Y, 105, abs_tol=1e-3)


# --- Test 2: fewer than 3 pairs fails -------------------------------------
def test_fails_with_fewer_than_three_pairs():
    cal = registration.compute_calibration(_pairs([(0, 0, 0, 0), (10, 0, 5, 0)]))
    assert cal["quality"]["confidence"] == "failed"
    assert cal["transform"] is None
    assert registration.registration_usable(cal) is False


# --- Test 3: collinear pairs fail -----------------------------------------
def test_fails_on_collinear_points():
    cal = registration.compute_calibration(
        _pairs([(0, 0, 0, 0), (10, 0, 5, 0), (20, 0, 10, 0), (30, 0, 15, 0)])
    )
    assert cal["quality"]["confidence"] == "failed"
    assert "collinear" in cal["quality"]["reason"].lower()


# --- Test 4: high confidence when RMS <= 8 --------------------------------
def test_high_confidence_low_rms():
    cal = _identity_calibration()
    assert cal["quality"]["rms_residual_pt"] <= 8
    assert cal["quality"]["confidence"] == "high"
    assert registration.registration_usable(cal) is True


def _revit(mark, x, y, _id):
    return {"id": _id, "pdf_mark_candidate": mark,
            "center_point": {"x": x, "y": y, "z": 1.5, "space": "revit_internal", "unit": "feet"}}


def _pdf(mark, x, y, _id):
    return {"id": _id, "normalized_mark": mark,
            "center_point": {"x": x, "y": y, "z": None, "space": "pdf_page", "unit": "points"}}


# --- Test 5: same-type nearby -> MATCH ------------------------------------
def test_nearby_same_type_becomes_match():
    cal = _identity_calibration()
    ai_revit = {"canonical_holdown_assemblies": [_revit("H1", 50, 50, "r1")]}
    ai_pdf = {"holdowns": [_pdf("H1", 53, 54, "p1")]}  # distance 5pt
    report = compare_mod.compare(ai_revit, ai_pdf, calibration=cal)
    counts = report["summary"]["verdict_counts"]
    assert counts["MATCH"] == 1
    match_rows = [r for r in report["final_verdicts"] if r["verdict"] == "MATCH"]
    assert match_rows and match_rows[0]["distance_pdf_points"] <= 16
    assert match_rows[0]["revit_point_transformed_to_pdf"] is not None


# --- Test 6: same-type far -> LOCATION_MISMATCH ---------------------------
def test_far_same_type_becomes_location_mismatch():
    cal = _identity_calibration()
    ai_revit = {"canonical_holdown_assemblies": [_revit("H1", 50, 50, "r1")]}
    ai_pdf = {"holdowns": [_pdf("H1", 75, 70, "p1")]}  # distance ~32pt (16<d<=40)
    report = compare_mod.compare(ai_revit, ai_pdf, calibration=cal)
    counts = report["summary"]["verdict_counts"]
    assert counts["LOCATION_MISMATCH"] == 1
    assert counts["MATCH"] == 0


# --- Test 8: one-to-one prevents duplicate assignment ---------------------
def test_one_to_one_no_duplicate_assignment():
    cal = _identity_calibration()
    ai_revit = {"canonical_holdown_assemblies": [
        _revit("H1", 10, 10, "r1"), _revit("H1", 11, 11, "r2"),
    ]}
    ai_pdf = {"holdowns": [_pdf("H1", 10, 10, "p1")]}  # only one PDF target
    report = compare_mod.compare(ai_revit, ai_pdf, calibration=cal)
    counts = report["summary"]["verdict_counts"]
    assert counts["MATCH"] == 1
    assert counts["REVIT_ONLY"] == 1
    # The single PDF id is used exactly once.
    pdf_ids = [r["pdf_holdown_id"] for r in report["final_verdicts"] if r["pdf_holdown_id"]]
    assert pdf_ids.count("p1") == 1


def test_match_only_possible_with_registration():
    """MATCH cannot appear without a usable registration even if locations are identical."""
    ai_revit = {"canonical_holdown_assemblies": [_revit("H1", 50, 50, "r1")]}
    ai_pdf = {"holdowns": [_pdf("H1", 50, 50, "p1")]}
    report = compare_mod.compare(ai_revit, ai_pdf, calibration=None)
    assert report["summary"]["verdict_counts"]["MATCH"] == 0


# --- calibration_source gating --------------------------------------------
def _verified_identity(source="manual_verified", validation_pairs=None):
    return registration.compute_calibration(
        _pairs([(0, 0, 0, 0), (100, 0, 100, 0), (0, 100, 0, 100)]),
        calibration_source=source,
        validation_pairs=validation_pairs,
    )


def test_auto_extent_source_never_allows_match():
    """auto_extent_estimate: transform solves perfectly but MATCH is forbidden."""
    cal = registration.compute_calibration(
        _pairs([(0, 0, 0, 0), (100, 0, 100, 0), (0, 100, 0, 100)]),
        calibration_source="auto_extent_estimate",
    )
    assert cal["quality"]["confidence"] == "high"          # solve is fine
    assert cal["quality"]["match_allowed"] is False         # but gated off
    assert registration.registration_usable(cal) is False
    assert registration.registration_status(cal) == "diagnostic_only"

    ai_revit = {"canonical_holdown_assemblies": [_revit("H1", 50, 50, "r1")]}
    ai_pdf = {"holdowns": [_pdf("H1", 50, 50, "p1")]}  # identical location
    report = compare_mod.compare(ai_revit, ai_pdf, calibration=cal)
    assert report["summary"]["verdict_counts"]["MATCH"] == 0
    codes = [b["code"] for b in report["blockers"]]
    assert "AUTO_EXTENT_CALIBRATION_DIAGNOSTIC_ONLY" in codes
    assert report["registration"]["calibration_source"] == "auto_extent_estimate"


def test_manual_verified_good_rms_allows_match():
    cal = _verified_identity("manual_verified")
    assert cal["quality"]["match_allowed"] is True
    assert registration.registration_status(cal) == "available"
    ai_revit = {"canonical_holdown_assemblies": [_revit("H1", 50, 50, "r1")]}
    ai_pdf = {"holdowns": [_pdf("H1", 52, 53, "p1")]}  # ~3.6pt
    report = compare_mod.compare(ai_revit, ai_pdf, calibration=cal)
    assert report["summary"]["verdict_counts"]["MATCH"] == 1


def test_validation_residuals_computed():
    # pdf = 2*revit + (10,5); exact-fitting holdout pair -> ~0 residual.
    cal = registration.compute_calibration(
        _pairs([(10, 5, 0, 0), (210, 5, 100, 0), (10, 205, 0, 100), (210, 205, 100, 100)]),
        calibration_source="grid_verified",
        validation_pairs=_pairs([(110, 105, 50, 50)]),  # 2*50+10=110, 2*50+5=105
    )
    q = cal["quality"]
    assert q["validation_pair_count"] == 1
    assert q["validation_rms_residual_pt"] is not None
    assert q["validation_rms_residual_pt"] < 1.0
    assert q["validation_failed"] is False
    assert q["match_allowed"] is True


def test_failed_validation_blocks_match():
    # Solve is exact, but the holdout pair is deliberately wrong by ~30pt.
    cal = registration.compute_calibration(
        _pairs([(10, 5, 0, 0), (210, 5, 100, 0), (10, 205, 0, 100), (210, 205, 100, 100)]),
        calibration_source="grid_verified",
        validation_pairs=_pairs([(140, 105, 50, 50)]),  # expected (110,105); off by 30pt
    )
    q = cal["quality"]
    assert q["validation_failed"] is True
    assert q["match_allowed"] is False
    assert registration.registration_usable(cal) is False

    ai_revit = {"canonical_holdown_assemblies": [_revit("H1", 50, 50, "r1")]}
    ai_pdf = {"holdowns": [_pdf("H1", 110, 105, "p1")]}
    report = compare_mod.compare(ai_revit, ai_pdf, calibration=cal)
    assert report["summary"]["verdict_counts"]["MATCH"] == 0
    codes = [b["code"] for b in report["blockers"]]
    assert "REGISTRATION_VALIDATION_FAILED" in codes


def test_unverified_source_blocks_match():
    cal = _verified_identity(source="some_random_source")
    assert cal["quality"]["match_allowed"] is False
    assert registration.registration_usable(cal) is False


def test_nearest_candidates_present_for_unmatched():
    """PDF_ONLY rows carry nearest_revit_candidates; REVIT_ONLY rows carry nearest_pdf_candidates."""
    cal = _verified_identity("manual_verified")
    ai_revit = {"canonical_holdown_assemblies": [_revit("H1", 0, 0, "r1")]}
    ai_pdf = {"holdowns": [_pdf("H1", 100, 100, "p1")]}  # ~141pt apart -> no pairing
    report = compare_mod.compare(ai_revit, ai_pdf, calibration=cal)
    rows = report["final_verdicts"]
    pdf_only = [r for r in rows if r["verdict"] == "PDF_ONLY"]
    revit_only = [r for r in rows if r["verdict"] == "REVIT_ONLY"]
    assert pdf_only and pdf_only[0]["nearest_revit_candidates"]
    assert pdf_only[0]["nearest_revit_candidates"][0]["revit_assembly_id"] == "r1"
    assert pdf_only[0]["nearest_revit_candidates"][0]["distance_pdf_points"] > 40
    assert revit_only and revit_only[0]["nearest_pdf_candidates"]
    assert revit_only[0]["nearest_pdf_candidates"][0]["pdf_holdown_id"] == "p1"


def test_revit_count_diagnostics_in_report(tmp_path, monkeypatch):
    """R-27: the PDF baseline comes from THIS project's page-intelligence
    artifact, not a hardcoded Madera {H1:10,H2:21,H3:6,H4:17}."""
    import json as _json

    from app import config

    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path)
    (tmp_path / config.ARTIFACT_FILES["pdf_page_intelligence"]).write_text(
        _json.dumps({"expected_baseline": {"HD1": 3, "HD2": 5}}), encoding="utf-8")
    ai_revit = {
        "canonical_holdown_assemblies": [_revit("HD1", 0, 0, "r1")],
        "learned_key_points": {"raw_record_count": 150},
    }
    ai_pdf = {"holdowns": [_pdf("HD1", 0, 0, "p1")]}
    diag = compare_mod.compare(ai_revit, ai_pdf, calibration=None)["revit_count_diagnostics"]
    assert diag["raw_holdown_records"] == 150
    assert diag["pdf_baseline"] == {"HD1": 3, "HD2": 5}
    assert diag["by_mark"] == {"HD1": 1, "HD2": 0}     # keyed by THIS project's marks
