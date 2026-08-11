"""Tests 9-10: AIConvert_revit.json and AIConvert_pdf.json schema validation.

OpenRouter is monkeypatched so these tests run offline and deterministically.
"""
import pytest

from app import compare as compare_mod
from app import openrouter, pdf_convert, revit_convert


@pytest.fixture(autouse=True)
def stub_openrouter(monkeypatch):
    def fake_call(**kwargs):
        return {
            "called": False,
            "ok": False,
            "model": "deepseek/deepseek-v4-pro",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "purpose": kwargs.get("purpose"),
            "error": "stubbed offline",
            "usage": None,
            "content": None,
        }

    monkeypatch.setattr(openrouter, "call_llm", fake_call)
    monkeypatch.setattr(revit_convert.openrouter, "call_llm", fake_call)
    monkeypatch.setattr(pdf_convert.openrouter, "call_llm", fake_call)
    monkeypatch.setattr(compare_mod.openrouter, "call_llm", fake_call)


SAMPLE_RAW = {
    "schema_version": 2,
    "units": "revit_internal_feet",
    "grids": [{"name": "A"}],
    "holdowns": [
        {
            "element_id": "body-1",
            "family": "SHDU11-With Bolt",
            "scheduled_type": "HDU11",
            "location": [10.0, 20.0],
            "elevation": 1.5,
            "bbox": [9, 19, 11, 21],
            "level": "L1",
        },
        {
            "element_id": "anchor-1",
            "family": "Anchor_Bolt_SHDU11",
            "scheduled_type": "HDU11",
            "location": [10.05, 20.02],
            "elevation": 0.0,
            "bbox": [9.9, 19.9, 10.1, 20.1],
            "level": "L1",
        },
        {
            "element_id": "body-2",
            "family": "SHDU6-With Bolt",
            "scheduled_type": "HDU6",
            "location": [50.0, 60.0],
            "elevation": 1.5,
            "bbox": [49, 59, 51, 61],
            "level": "L1",
        },
    ],
}

REVIT_REQUIRED = {
    "schema_version", "generated_at", "source_file", "ai_model_used",
    "learned_key_points", "family_type_dictionary", "canonical_holdown_assemblies",
    "unmapped_or_ambiguous_records", "qa_warnings", "openrouter_call_status",
}
ASSEMBLY_REQUIRED = {
    "id", "pdf_mark_candidate", "core_token", "scheduled_type_raw",
    "family_type_summary", "member_element_ids", "primary_element_id",
    "center_point", "bbox", "level", "classification_confidence",
    "classification_reason", "raw_evidence",
}
PDF_HOLDOWN_REQUIRED = {
    "id", "sheet_number", "page_index", "raw_mark", "normalized_mark", "core_token",
    "schedule_type_raw", "center_point", "bbox", "evidence_crop_path", "anchor_bolt",
    "fasteners", "embedment", "confidence", "source",
}


def test_revit_schema_valid():
    """Test 9."""
    result = revit_convert.convert_revit(SAMPLE_RAW, source_file="unit-test.json")
    assert REVIT_REQUIRED <= set(result)
    assert result["canonical_holdown_assemblies"], "expected at least one assembly"
    for asm in result["canonical_holdown_assemblies"]:
        assert ASSEMBLY_REQUIRED <= set(asm)
    # The anchor must be grouped onto its body, not counted as a separate hold-down.
    body1 = next(a for a in result["canonical_holdown_assemblies"] if a["primary_element_id"] == "body-1")
    assert "anchor-1" in body1["member_element_ids"]
    # Deterministic fallback label when LLM not called.
    assert result["ai_model_used"] == "deterministic_fallback"


def _make_page_intel():
    return {
        "sheet_number": "S-201",
        "page_index": 4,
        "holdowns": [
            {
                "id": "s-201_h2_001_1",
                "raw_mark": "H2",
                "normalized_mark": "H2",
                "normalized_core_token": "HDU11",
                "schedule_type_raw": "S/HDU11",
                "center_pdf": [100.0, 200.0],
                "bbox_pdf": [99, 199, 101, 201],
                "evidence_crop_path": "s-201_h2_001_1.png",
                "anchor_bolt": '7/8" (SABR)',
                "fasteners": "(27) #14",
                "embedment": '28"',
                "confidence": 0.9,
                "source": "s201_focused_holdown_detector",
                "multiplicity_index": 1,
                "total_multiplicity": 1,
            }
        ],
    }


def test_pdf_schema_valid():
    """Test 10."""
    result = pdf_convert.convert_pdf(_make_page_intel(), revit_ai_memory=None)
    for h in result["holdowns"]:
        assert PDF_HOLDOWN_REQUIRED <= set(h)
        # PDF Z must be flagged inferred, never a real Revit elevation.
        assert h["center_point"]["z"] is None
        assert h["center_point"]["z_is_inferred"] is True
    assert result["ai_model_used"] == "deterministic_fallback"
