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
