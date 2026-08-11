"""Per-phase AI summaries + the auto-benchmark-on-upload trigger.

The summary builders are pure: dict in, sentence out. The trigger tests fake
the proposal/stamp seams — no real PDF, no real Revit export — so they assert
the DECISION (fire / skip / restore) rather than re-testing the picker.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app import benchmark_workflow as bw
from app import config, phase_summary as ps
from app.routers import workflow as wf_router


@pytest.fixture()
def tmp_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path)
    monkeypatch.setattr(config, "EVIDENCE_DIR", tmp_path / "evidence")
    return tmp_path


PROPOSAL = {
    "sheet_number": "X-100",
    "page_index": 4,
    "separation_revit_ft": 82.12,
    "candidates_considered": 9,
    "benchmarks": [
        {"mark": "BM-1", "grid_id": "grid_A_1", "grid_label": "Grid A/1",
         "pdf_point_pt": {"x": 301.7, "y": 254.6},
         "revit_point_ft": {"x": 17.304, "y": 62.174}},
        {"mark": "BM-2", "grid_id": "grid_F_9", "grid_label": "Grid F/9",
         "pdf_point_pt": {"x": 1354.8, "y": 1287.8},
         "revit_point_ft": {"x": 75.971, "y": 4.716}},
    ],
}


# ---------------------------------------------------------------------------
# Pure builders
# ---------------------------------------------------------------------------
def test_upload_counts_sheets_tables_and_plan_sheet() -> None:
    text = ps.upload(
        {"page_count": 26, "pdf_original_name": "set.pdf"},
        {"summary": {"sheet_count": 19, "marks_by_category": {"holdown": 107, "post": 131}},
         "sheets": [{"tables": [{}, {}]}, {"tables": [{}]}]},
        {"sheet_number": "S-201", "page_index": 4},
    )
    assert "26-page set" in text
    assert "19 sheets indexed" in text
    assert "3 schedule tables found" in text
    assert "238 element marks" in text
    assert "S-201 (page 5)" in text


def test_upload_without_intelligence_says_so() -> None:
    text = ps.upload({"page_count": 3})
    assert "3-page set" in text and "run Extract" in text


def test_auto_benchmark_names_both_grids_and_stamp_state() -> None:
    ok = ps.auto_benchmark(PROPOSAL, stamped=True)
    assert "Grid A/1" in ok and "Grid F/9" in ok
    assert "max diagonal" in ok and "82.12 ft apart" in ok
    assert "PDF stamped" in ok
    unstamped = ps.auto_benchmark(PROPOSAL, stamped=False)
    assert "NOT stamped" in unstamped


def test_auto_benchmark_reports_too_few_intersections() -> None:
    assert "fewer than 2" in ps.auto_benchmark({"benchmarks": []}, stamped=False)


def test_revit_placement_reports_readback_delta() -> None:
    text = ps.revit_placement(PROPOSAL, {"readback": {
        "BM-1": {"x": 17.304, "y": 62.174},
        "BM-2": {"x": 75.981, "y": 4.716},
    }})
    assert "BM-1 at (17.304, 62.174) ft" in text
    assert "0.0100 ft" in text          # BM-2 is 0.01 ft off
    assert "Worst read-back deviation 0.0100 ft" in text


def test_revit_placement_without_readback_is_honest() -> None:
    assert "no read-back" in ps.revit_placement(PROPOSAL, {})


def test_registration_reports_quality_gate_both_ways() -> None:
    allowed = ps.registration({
        "calibration_source": "benchmark_verified",
        "transform": {"scale": 17.9664, "rotation_degrees": 0.0512},
        "quality": {"confidence": "medium", "match_allowed": True,
                    "solve_rms_residual_pt": 0.0},
    })
    assert "17.9664 pt/ft" in allowed and "0.0512° rotation" in allowed
    assert "benchmark_verified" in allowed and "medium" in allowed
    assert "MATCH verdicts allowed" in allowed
    withheld = ps.registration({"quality": {"match_allowed": False,
                                            "confidence_reason": "RMS too high."}})
    assert "MATCH withheld — RMS too high." in withheld


def test_match_breaks_down_by_status_and_systematic_share() -> None:
    element_list = {"counts": {"total": 356, "by_status": {
        "MATCH": 106, "LOCATION_MISMATCH": 37, "PDF_ONLY": 175}}}
    text = ps.match(element_list, systematic=30, sampled=37)
    assert "356 elements" in text
    assert "175 PDF_ONLY, 106 MATCH, 37 LOCATION_MISMATCH" in text  # sorted desc
    assert "30/37 sampled mismatches shift the same direction" in text
    assert "likely drafting offset, not modeling error" in text
    scattered = ps.match(element_list, systematic=0, sampled=12)
    assert "None of 12 sampled mismatches share a direction" in scattered
    assert "shift the same direction" not in scattered


def test_match_without_analysis_omits_the_systematic_sentence() -> None:
    text = ps.match({"counts": {"total": 1, "by_status": {"MATCH": 1}}})
    assert "mismatches" not in text


def test_count_systematic_uses_review_analyze_and_caps(monkeypatch) -> None:
    from app import review

    seen: list[str] = []

    def fake_analyze(element_id, element_list, registry):
        seen.append(element_id)
        return {"analysis_available": True, "systematic": element_id.endswith("0")}

    monkeypatch.setattr(review, "analyze", fake_analyze)
    element_list = {"elements": [
        {"id": f"e{i}", "status": "LOCATION_MISMATCH"} for i in range(50)
    ] + [{"id": "match", "status": "MATCH"}]}
    systematic, sampled = ps.count_systematic(element_list, {}, cap=30)
    assert sampled == 30 and len(seen) == 30      # cap honored
    assert "match" not in seen                    # only mismatches analyzed
    assert systematic == 3                        # e0, e10, e20


def test_count_systematic_survives_analyze_failures(monkeypatch) -> None:
    from app import review

    monkeypatch.setattr(review, "analyze", lambda *a: (_ for _ in ()).throw(ValueError("x")))
    systematic, sampled = ps.count_systematic(
        {"elements": [{"id": "a", "status": "LOCATION_MISMATCH"}]}, {})
    assert (systematic, sampled) == (0, 0)


# ---------------------------------------------------------------------------
# record(): emits on the live log + persists
# ---------------------------------------------------------------------------
def test_record_emits_robot_line_and_persists(tmp_artifacts: Path) -> None:
    from app import progress

    before = progress.events_since(0)
    last = before[-1]["seq"] if before else 0
    ps.record("match", "Match: 2 elements — 1 MATCH.")
    fresh = progress.events_since(last)
    assert any(e["step"] == "match" and e["message"].startswith("🤖 ") for e in fresh)
    stored = json.loads(
        (tmp_artifacts / config.ARTIFACT_FILES["phase_summaries"]).read_text(encoding="utf-8"))
    assert stored["phases"]["match"]["text"].startswith("Match: 2 elements")
    assert stored["phases"]["match"]["ts"]
    # second phase merges, never clobbers
    ps.record("upload", "Upload: 1-page set.")
    stored = ps.load()
    assert set(stored["phases"]) == {"match", "upload"}


def test_record_never_raises(monkeypatch) -> None:
    monkeypatch.setattr(config, "ARTIFACT_DIR", Path("/nonexistent/\0bad"))
    ps.record("match", "still fine")  # must not raise


def test_marker_placement_transition_records_summary(tmp_artifacts: Path) -> None:
    """The placing endpoint lives in a router this module can't call, so the
    transition it reports is where the placement summary is minted."""
    wf = bw.default_state()
    wf["proposal"] = PROPOSAL
    for state in ("proposing", "awaiting_pdf_approval", "stamping",
                  "awaiting_revit", "placing_markers"):
        bw.transition(wf, state, "test")
    bw.transition(wf, "awaiting_revit_approval", "test", payload={
        "readback": {"BM-1": {"x": 17.304, "y": 62.174},
                     "BM-2": {"x": 75.971, "y": 4.716}}})
    assert "Revit placement" in ps.load()["phases"]["revit_placement"]["text"]


def test_transition_without_readback_writes_nothing(tmp_artifacts: Path) -> None:
    wf = bw.default_state()
    bw.transition(wf, "proposing", "test")
    assert not (tmp_artifacts / config.ARTIFACT_FILES["phase_summaries"]).exists()


# ---------------------------------------------------------------------------
# Auto-benchmark trigger
# ---------------------------------------------------------------------------
def test_auto_benchmark_proposes_and_stamps_from_idle(tmp_artifacts, monkeypatch) -> None:
    def fake_propose(body):
        assert body["actor"] == "auto"
        wf = bw.default_state()
        bw.transition(wf, "proposing", "auto")
        bw.transition(wf, "awaiting_pdf_approval", "auto")
        wf["proposal"] = PROPOSAL
        bw.save(wf)
        return wf

    monkeypatch.setattr(wf_router, "_propose", fake_propose)
    monkeypatch.setattr(wf_router, "_stamp_pdf_with_proposal",
                        lambda proposal: {"ok": True, "checks": []})
    out = wf_router.maybe_auto_benchmark()
    assert out is not None
    # left at the normal human gate — nothing auto-approved
    assert bw.load()["state"] == "awaiting_pdf_approval"
    summary = ps.load()["phases"]["auto_benchmark"]["text"]
    assert "Grid A/1" in summary and "PDF stamped" in summary


def test_auto_benchmark_skips_when_workflow_not_idle(tmp_artifacts, monkeypatch) -> None:
    wf = bw.default_state()
    bw.transition(wf, "proposing", "human")
    bw.save(wf)
    monkeypatch.setattr(wf_router, "_propose",
                        lambda body: pytest.fail("must not propose over a live run"))
    assert wf_router.maybe_auto_benchmark() is None
    assert bw.load()["state"] == "proposing"


def test_auto_benchmark_skips_without_grids_and_restores_idle(
    tmp_artifacts, monkeypatch
) -> None:
    """Too few intersections: honest log line, workflow untouched, no raise —
    the manual/RANSAC paths stay available."""
    def failing_propose(body):
        wf = bw.load()
        bw.transition(wf, "proposing", "auto")
        bw.transition(wf, "failed", "backend", note="Only 1 labeled intersection.")
        bw.save(wf)
        raise HTTPException(status_code=409, detail="Only 1 labeled intersection.")

    monkeypatch.setattr(wf_router, "_propose", failing_propose)
    monkeypatch.setattr(wf_router, "_stamp_pdf_with_proposal",
                        lambda p: pytest.fail("must not stamp without a proposal"))
    assert wf_router.maybe_auto_benchmark() is None
    restored = bw.load()
    assert restored["state"] == "idle" and restored["history"] == []
    assert not (tmp_artifacts / config.ARTIFACT_FILES["phase_summaries"]).exists()


def test_auto_benchmark_keeps_proposal_when_stamp_fails(tmp_artifacts, monkeypatch) -> None:
    def fake_propose(body):
        wf = bw.default_state()
        bw.transition(wf, "proposing", "auto")
        bw.transition(wf, "awaiting_pdf_approval", "auto")
        wf["proposal"] = PROPOSAL
        bw.save(wf)
        return wf

    monkeypatch.setattr(wf_router, "_propose", fake_propose)
    monkeypatch.setattr(wf_router, "_stamp_pdf_with_proposal",
                        lambda p: {"ok": False, "reason": "Off-tolerance: BM-2"})
    wf_router.maybe_auto_benchmark()
    assert bw.load()["state"] == "awaiting_pdf_approval"
    assert "NOT stamped" in ps.load()["phases"]["auto_benchmark"]["text"]
