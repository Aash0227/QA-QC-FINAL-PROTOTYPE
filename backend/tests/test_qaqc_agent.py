"""The QBC QA/QC Agent's evidence tools.

The agent's value is answering "why is this a mismatch?" for a QA engineer.
That only works if it reads real recorded evidence instead of speculating,
so these tests pin that the tools are wired, degrade honestly with no data,
and never fabricate.
"""
from __future__ import annotations

from app import chat_agent as ca


def test_every_declared_tool_has_an_implementation():
    """A declared-but-unimplemented tool makes the model call into a hole."""
    for tool in ca.TOOLS:
        name = tool["function"]["name"]
        assert name in ca.TOOL_IMPLS, name


def test_evidence_tools_are_available_to_the_agent():
    names = {t["function"]["name"] for t in ca.TOOLS}
    assert {"explain_element", "get_pipeline_story"} <= names


def test_explain_element_requires_a_target():
    assert "error" in ca._tool_explain_element()["data"]


def test_explain_element_reports_missing_rather_than_guessing(monkeypatch):
    monkeypatch.setattr(ca, "_elements", lambda: [])
    out = ca._tool_explain_element(element_id="H99")["data"]
    assert "error" in out and "H99" in out["error"]


def test_explain_element_returns_evidence_and_registration(monkeypatch):
    row = {
        "id": "s-205_sw-1_002", "mark": "SW-1", "category": "shear_wall",
        "sheet": "S-205", "status": "MATCH", "distance_ft": 0.14,
        "product": {"verdict": "LOCATION_MATCH", "is_certain": True,
                    "in_scope": True,
                    "evidence": {"internal_status": "MATCH",
                                 "reason": "paired with w_1 at 0.14 ft",
                                 "resolved_by": "level"}},
    }
    monkeypatch.setattr(ca, "_elements", lambda: [row])
    monkeypatch.setattr(ca, "_load", lambda key: {
        "calibration_source": "holdown_ransac",
        "quality": {"confidence": "high", "solve_rms_residual_pt": 6.2,
                    "match_allowed": True},
    } if key == "registration" else None)
    out = ca._tool_explain_element(element_id="s-205_sw-1_002")
    data = out["data"]
    assert data["verdict"] == "LOCATION_MATCH" and data["certain"] is True
    assert data["evidence"]["resolved_by"] == "level"
    # the reviewer must be able to see what gated the decision
    assert data["registration"]["confidence"] == "high"
    assert data["registration"]["match_allowed"] is True
    # and the UI should fly to the element they asked about
    assert out["ui_actions"][0]["element_id"] == "s-205_sw-1_002"


def test_ambiguous_mark_reference_lists_options_instead_of_picking_one(monkeypatch):
    rows = [{"id": "a", "mark": "H2", "product": {"verdict": "LOCATION_MATCH"}},
            {"id": "b", "mark": "H2", "product": {"verdict": "NEEDS_REVIEW"}}]
    monkeypatch.setattr(ca, "_elements", lambda: rows)
    data = ca._tool_explain_element(element_id="H2")["data"]
    assert data["ambiguous_reference"] == "H2"
    assert len(data["candidates"]) == 2


def test_pipeline_story_is_honest_when_nothing_has_run(monkeypatch):
    monkeypatch.setattr(ca, "_load", lambda key: None)
    assert "error" in ca._tool_get_pipeline_story()["data"]


def test_row_view_exposes_the_product_verdict():
    """The agent must reason in the vocabulary the reviewer sees."""
    view = ca._row_view({"id": "x", "mark": "SW-1", "status": "MATCH",
                         "product": {"verdict": "LOCATION_MATCH"}})
    assert view["verdict"] == "LOCATION_MATCH"
    assert view["status"] == "MATCH"          # internal state still available


def test_system_prompt_forbids_fabrication_and_names_the_verdicts():
    p = ca.SYSTEM_PROMPT
    assert "never invent" in p.lower()
    for verdict in ("LOCATION_MATCH", "LOCATION_MISMATCH",
                    "NEEDS_REVIEW", "NOT_APPLICABLE"):
        assert verdict in p, verdict
    assert "explain_element" in p and "get_pipeline_story" in p
