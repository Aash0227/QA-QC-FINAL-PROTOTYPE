"""Tests: no fake MATCH without registration (v2.0), clean global blocker, missing key."""
import pytest

from app import compare as compare_mod
from app import config, openrouter


@pytest.fixture
def stub_openrouter(monkeypatch):
    monkeypatch.setattr(
        compare_mod,
        "_llm_assessment",
        lambda per_mark, reg_status, blockers: {
            "status": {"called": False, "ok": False, "model": "x"},
            "parsed": None,
        },
    )


def _ai_revit():
    return {
        "source_file": "r.json",
        "canonical_holdown_assemblies": [
            {"id": "rev_asm_001", "pdf_mark_candidate": "H2", "core_token": "HDU11",
             "center_point": {"x": 10, "y": 20, "z": 1.5, "space": "revit_internal", "unit": "feet"}},
            {"id": "rev_asm_002", "pdf_mark_candidate": "H2", "core_token": "HDU11",
             "center_point": {"x": 30, "y": 40, "z": 1.5, "space": "revit_internal", "unit": "feet"}},
        ],
    }


def _ai_pdf():
    return {
        "source_sheet": "S-201",
        "holdowns": [
            {"id": "p1", "normalized_mark": "H2", "core_token": "HDU11",
             "center_point": {"x": 100, "y": 200, "z": None, "space": "pdf_page", "unit": "points"}},
            {"id": "p2", "normalized_mark": "H2", "core_token": "HDU11",
             "center_point": {"x": 300, "y": 400, "z": None, "space": "pdf_page", "unit": "points"}},
        ],
    }


def test_no_registration_no_match_single_global_blocker(stub_openrouter):
    """Test 7: without registration MATCH=0 and exactly one global registration blocker."""
    report = compare_mod.compare(_ai_revit(), _ai_pdf(), calibration=None)
    counts = report["summary"]["verdict_counts"]
    assert counts["MATCH"] == 0
    assert report["summary"]["full_match_achieved"] is False
    assert report["registration"]["status"] == "missing"
    assert report["registration"]["match_allowed"] is False
    # Exactly one blocking registration blocker (not repeated per item).
    blocking = [b for b in report["blockers"] if b["severity"] == "blocking"]
    assert len(blocking) == 1
    assert blocking[0]["code"] == "REGISTRATION_MISSING"
    # Per-item reasons stay short and do not repeat the global blocker text.
    for row in report["final_verdicts"]:
        assert "registration" not in (row["reason"] or "").lower() or len(row["reason"]) < 120


def test_failed_registration_blocks_match(stub_openrouter):
    from app import registration
    bad = registration.compute_calibration([{"pdf_point": {"x": 0, "y": 0},
                                             "revit_point": {"x": 0, "y": 0}}])  # 1 pair -> failed
    report = compare_mod.compare(_ai_revit(), _ai_pdf(), calibration=bad)
    assert report["summary"]["verdict_counts"]["MATCH"] == 0
    assert report["registration"]["status"] == "failed"


def test_missing_api_key_returns_clear_status(monkeypatch):
    """Missing OPENROUTER_API_KEY yields a clear not-called status."""
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")
    status = openrouter.call_llm(
        system_prompt="s", user_prompt="u", purpose="unit-test.missing-key"
    )
    assert status["called"] is False
    assert status["ok"] is False
    assert "OPENROUTER_API_KEY" in (status["error"] or "")
    assert status["message"] == openrouter.NOT_CALLED_MESSAGE
