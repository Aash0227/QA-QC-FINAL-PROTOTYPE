"""Product-facing verdict layer.

The engine reasons in a rich internal vocabulary (MATCH, PDF_ONLY,
REVIT_ONLY, MARK_MISMATCH, NEEDS_REVIEW, NO_REVIT_DATA, ...). The product
speaks two assertions -- LOCATION_MATCH / LOCATION_MISMATCH -- plus an honest
"could not tell". These tests pin that the collapse is (a) honest, (b)
lossless, and (c) defined in exactly one place.
"""
from __future__ import annotations

from app import matching_engine as me


def test_confident_pairing_is_a_match():
    assert me.product_verdict("MATCH") == me.LOCATION_MATCH


def test_established_discrepancies_collapse_to_mismatch():
    """PDF_ONLY / REVIT_ONLY are NOT product categories of their own -- to a
    reviewer, 'the drawing shows a hold-down the model lacks' is a
    discrepancy, not a third kind of answer. Which kind it was survives in
    the internal status and reason."""
    for status in ("LOCATION_MISMATCH", "MARK_MISMATCH", "PDF_ONLY", "REVIT_ONLY"):
        assert me.product_verdict(status) == me.LOCATION_MISMATCH, status


def test_uncertainty_is_never_promoted_to_a_verdict():
    """The whole point of the ambiguity guard is refusing to guess; the
    product layer must not undo that."""
    assert me.product_verdict("NEEDS_REVIEW") == me.NEEDS_REVIEW
    assert me.product_verdict(None) == me.NEEDS_REVIEW


def test_structurally_unevaluable_rows_are_not_dumped_in_the_review_queue():
    """A category the exporter never shipped is out of scope, not something a
    human should adjudicate. Mixing them makes the review queue useless."""
    for status in ("NO_REVIT_DATA", "SPEC_ONLY", "NOT_IN_SCHEDULE", "NOT_EVALUATED"):
        assert me.product_verdict(status) == me.NOT_APPLICABLE, status


def test_product_result_preserves_evidence():
    """Simplifying the verdict must not destroy the explanation behind it."""
    row = {
        "status": "MATCH", "reason": "paired with w_1 at 0.14 ft",
        "distance_ft": 0.14, "mark": "SW-1", "sheet": "S-205",
        "category": "shear_wall", "resolved_by": "level",
        "revit_ref": {"id": "w_1", "kind": "wall"},
    }
    out = me.product_result(row)
    assert out["verdict"] == me.LOCATION_MATCH
    assert out["is_certain"] is True and out["in_scope"] is True
    ev = out["evidence"]
    assert ev["internal_status"] == "MATCH"          # internal state survives
    for key in ("reason", "distance_ft", "mark", "sheet", "resolved_by", "revit_ref"):
        assert ev[key] == row[key], key


def test_needs_review_row_is_flagged_uncertain_but_still_explained():
    row = {"status": "NEEDS_REVIEW", "mark": "SW-1", "sheet": "S-202",
           "reason": "Ambiguous: two candidates...",
           "evidence_conflict": "drawn_orientation_matches_no_candidate"}
    out = me.product_result(row)
    assert out["verdict"] == me.NEEDS_REVIEW
    assert out["is_certain"] is False and out["in_scope"] is True
    assert out["evidence"]["evidence_conflict"] == "drawn_orientation_matches_no_candidate"
    assert out["evidence"]["reason"] == row["reason"]


def test_summary_counts_every_row_exactly_once():
    rows = [{"status": s} for s in
            ("MATCH", "MATCH", "PDF_ONLY", "NEEDS_REVIEW", "NO_REVIT_DATA")]
    counts = me.summarize_product_verdicts(rows)
    assert counts == {me.LOCATION_MATCH: 2, me.LOCATION_MISMATCH: 1,
                      me.NEEDS_REVIEW: 1, me.NOT_APPLICABLE: 1}
    assert sum(counts.values()) == len(rows)


# --------------------------------------------- per-stage pipeline narration

def test_every_pipeline_stage_can_narrate_itself():
    """Phase 3: the user watching the pipeline should be told what each stage
    actually did. Every stage in stage_graph.STAGES must have either its own
    narration hook or a handler that records one."""
    from app import phase_summary, run_engine, stage_graph

    for key, _title, _prereqs, _out in stage_graph.STAGES:
        assert (key in run_engine._STAGE_NARRATION
                or key in phase_summary.PHASE_STEPS
                or key in ("ransac", "match")), key


def test_stage_narration_never_raises():
    """Commentary must not be able to fail a pipeline that otherwise
    succeeded -- including when no project is bound or the stage is unknown."""
    from app import run_engine

    run_engine._narrate_stage("extract")
    run_engine._narrate_stage("compare")
    run_engine._narrate_stage("does_not_exist")


def test_stage_summaries_are_built_from_real_numbers_not_prose():
    """Each summary must reflect its input; a summary that ignores its input
    would be fabrication."""
    from app import phase_summary as ps

    ei = {"sheets": [{"marks": [{"category": "holdown"}, {"category": "holdown"},
                                {"category": "shear_wall"}]}],
          "vocabulary": {"holdown": ["H1", "H2"]}}
    text = ps.extract(ei)
    assert "3 callouts" in text and "1 sheet" in text
    assert "2 holdown" in text and "1 shear wall" in text

    ai = {"canonical_holdown_assemblies": [{"pdf_mark_candidate": "H1"},
                                           {"pdf_mark_candidate": None}]}
    text = ps.revit_convert(ai)
    assert "2 hold-down assemblies" in text and "1 resolved" in text
    assert "1 unresolved" in text

    # a failed intelligence stage must say so, not report success
    assert "FAILED" in ps.pdf_intelligence({"error": "no plan sheet found"})


# ------------------------------------- read-time backfill for old artifacts

def test_elements_endpoint_backfills_verdicts_for_pre_existing_artifacts(monkeypatch):
    """Artifacts written before the product layer existed have no `product`
    block. Requiring a full pipeline re-run just to see a verdict on screen
    would be a bad trade, so the endpoint applies the same pure collapse at
    read time. A backfilled response must be identical to a fresh one."""
    from app.routers import elements as el_router

    stored = {"elements": [{"id": "a", "status": "MATCH", "reason": "ok"},
                           {"id": "b", "status": "PDF_ONLY"},
                           {"id": "c", "status": "NO_REVIT_DATA"}]}
    monkeypatch.setattr(el_router, "load_artifact", lambda key: stored)
    import json as _json
    payload = _json.loads(el_router.elements_get().body)

    assert payload["product_counts"] == {
        "LOCATION_MATCH": 1, "LOCATION_MISMATCH": 1,
        "NEEDS_REVIEW": 0, "NOT_APPLICABLE": 1}
    verdicts = [e["product"]["verdict"] for e in payload["elements"]]
    assert verdicts == ["LOCATION_MATCH", "LOCATION_MISMATCH", "NOT_APPLICABLE"]
    # evidence survives the backfill
    assert payload["elements"][0]["product"]["evidence"]["reason"] == "ok"


def test_backfill_does_not_overwrite_freshly_written_verdicts(monkeypatch):
    from app.routers import elements as el_router

    stored = {"elements": [{"id": "a", "status": "MATCH",
                            "product": {"verdict": "SENTINEL"}}],
              "product_counts": {"LOCATION_MATCH": 1}}
    monkeypatch.setattr(el_router, "load_artifact", lambda key: stored)
    import json as _json
    payload = _json.loads(el_router.elements_get().body)
    assert payload["elements"][0]["product"]["verdict"] == "SENTINEL"
    assert payload["product_counts"] == {"LOCATION_MATCH": 1}


def test_backfill_tolerates_an_empty_or_broken_artifact(monkeypatch):
    from app.routers import elements as el_router
    import json as _json

    for stored in ({}, {"elements": []}, {"elements": None}):
        monkeypatch.setattr(el_router, "load_artifact", lambda key, s=stored: s)
        _json.loads(el_router.elements_get().body)   # must not raise
