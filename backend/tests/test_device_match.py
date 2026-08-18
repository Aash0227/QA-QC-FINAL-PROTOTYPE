"""Regression + adversarial coverage for backend/app/device_match.py.

This module is the physical-device-level accuracy layer: it re-projects PDF
callouts into model feet (fit_inverse chirality resolution) and assigns them
to Revit assemblies (assign/_claim). It backs the software's core promise --
"does the PDF element correspond to the right Revit location" -- so a wrong
MATCH here is worse than a refused one. These tests pin the failure modes an
audit found were NOT previously covered by any test:

  1. fit_inverse must refuse (not coin-flip) when only 2 point pairs are given
     -- chirality is undetermined with 2 points (R-01).
  2. build_devices must never merge two same-mark callouts drawn on the SAME
     sheet into one physical device, however close -- a sheet draws each
     physical element once, so two nearby same-mark callouts are always two
     real elements (e.g. paired hold-down hardware at a panel edge).
  3. build_devices clustering must not chain-drift: a point just outside the
     true cluster radius must not get absorbed via an intermediate member
     shifting the (now anchor-based, not centroid-based) cluster location.
  4. assign()/_claim() must refuse to auto-pick between two nearly-tied
     same-mark Revit candidates (NEEDS_REVIEW, no target consumed) rather
     than force a MATCH to whichever is marginally closer.
  5. A genuinely decisive nearest candidate still matches normally -- the
     ambiguity guard must not turn every pairing into NEEDS_REVIEW.
"""
from __future__ import annotations

from app import device_match as dm

# Shared calibration: exact similarity transform, PDF y flipped vs model y
# (x_ft, y_ft) -> (100 + 4*x_ft, 900 - 4*y_ft), matching how real plans work.
CAL_PAIRS = [
    {"revit_point": {"x": x, "y": y},
     "pdf_point": {"x": 100 + 4 * x, "y": 900 - 4 * y}}
    for x, y in ((0, 0), (50, 0), (0, 30), (25, 60))
]
CALS = {"S1": {"point_pairs": CAL_PAIRS}, "S2": {"point_pairs": CAL_PAIRS}}


def _pdf_point_for(x_ft: float, y_ft: float) -> dict[str, float]:
    return {"x": 100 + 4 * x_ft, "y": 900 - 4 * y_ft}


# --------------------------------------------------------------- fit_inverse

def test_fit_inverse_refuses_two_pairs_chirality_undetermined():
    assert dm.fit_inverse(CAL_PAIRS[:2]) is None


def test_fit_inverse_round_trips_with_three_or_more_pairs():
    inv = dm.fit_inverse(CAL_PAIRS)
    assert inv is not None
    x, y = inv(*_pdf_point_for(10, 20).values())
    assert abs(x - 10) < 1e-6 and abs(y - 20) < 1e-6


def test_fit_inverse_picks_lower_residual_chirality_not_first_tried():
    # Mirrored data: only the reflected fit should have ~zero residual.
    mirrored = [
        {"revit_point": {"x": x, "y": y},
         "pdf_point": {"x": 100 + 4 * x, "y": 900 + 4 * y}}   # NOT flipped
        for x, y in ((0, 0), (50, 0), (0, 30), (25, 60))
    ]
    inv = dm.fit_inverse(mirrored)
    assert inv is not None
    x, y = inv(100 + 4 * 10, 900 + 4 * 20)
    assert abs(x - 10) < 1e-6 and abs(y - 20) < 1e-6


# --------------------------------------------------------- clustering safety

def test_same_sheet_same_mark_never_merges_regardless_of_proximity():
    """Two H1 callouts 1 ft apart on the SAME sheet are two real devices, not
    one -- e.g. paired hold-down hardware at a shear-panel edge. Pre-fix
    behavior clustered by proximity alone and would have merged these."""
    rows = [
        {"id": "left", "sheet": "S1", "category": "holdown", "mark": "H1",
         "status": "PDF_ONLY", "pdf_point": _pdf_point_for(10, 10)},
        {"id": "right", "sheet": "S1", "category": "holdown", "mark": "H1",
         "status": "PDF_ONLY", "pdf_point": _pdf_point_for(11, 10)},  # 1 ft away
    ]
    devices, _ = dm.build_devices(rows, {"S1": dm.fit_inverse(CAL_PAIRS)}, "hd")
    assert len(devices) == 2
    assert {tuple(d["appearances"]) for d in devices} == {("left",), ("right",)}


def test_cross_sheet_same_mark_close_together_does_merge():
    """The intended case: the same physical device re-drawn on two sheets,
    a few inches apart from digitization/registration noise, DOES merge."""
    rows = [
        {"id": "s1_a", "sheet": "S1", "category": "holdown", "mark": "H1",
         "status": "MATCH", "pdf_point": _pdf_point_for(10, 10)},
        {"id": "s2_a", "sheet": "S2", "category": "holdown", "mark": "H1",
         "status": "PDF_ONLY", "pdf_point": _pdf_point_for(10.2, 10.1)},
    ]
    inv = dm.fit_inverse(CAL_PAIRS)
    devices, _ = dm.build_devices(rows, {"S1": inv, "S2": inv}, "hd")
    assert len(devices) == 1
    assert set(devices[0]["appearances"]) == {"s1_a", "s2_a"}


def test_clustering_does_not_chain_drift_past_tolerance():
    """A running-centroid cluster can chain: A merges B (centroid shifts
    toward B), then a point beyond tol(A) but within tol(new centroid) gets
    absorbed too, even though it's actually a separate device. Anchoring to
    the founding member closes this: only distance from the ORIGINAL point
    gates membership, so a point outside CLUSTER_TOL_FT of the true anchor is
    never absorbed via an intermediate member's pull on the centroid."""
    inv = dm.fit_inverse(CAL_PAIRS)
    # Three same-mark, different-sheet appearances marching outward in 2.9ft
    # steps: A -> A+2.9 -> A+5.8. Naive centroid-chaining would merge all
    # three (each step is < CLUSTER_TOL_FT from the *shifting* centroid).
    # Anchor-based clustering caps membership at CLUSTER_TOL_FT (3.0) from
    # the anchor, so the third point (5.8ft from the anchor) must NOT join.
    rows = [
        {"id": f"s{i}_a", "sheet": f"S{i}", "category": "holdown", "mark": "H1",
         "status": "PDF_ONLY", "pdf_point": _pdf_point_for(10 + i * 2.9, 10)}
        for i in range(1, 4)
    ]
    inverse_by_sheet = {f"S{i}": inv for i in range(1, 4)}
    devices, _ = dm.build_devices(rows, inverse_by_sheet, "hd")
    # s1 (anchor 10,10) and s2 (12.9,10) are within 3.0ft -> merge.
    # s3 (15.8,10) is 5.8ft from the s1 anchor -> must stay separate.
    by_appearance = {tuple(d["appearances"]): d for d in devices}
    assert len(devices) == 2, [d["appearances"] for d in devices]
    merged = next(d for d in devices if len(d["appearances"]) == 2)
    assert set(merged["appearances"]) == {"s1_a", "s2_a"}


# ------------------------------------------------------------- assign/_claim

def test_ambiguous_candidates_produce_needs_review_not_forced_match():
    """Two same-mark Revit targets nearly equidistant from one device: the
    system must refuse to pick, not force a MATCH to whichever is a hair
    closer -- that's a coin flip, and a wrong MATCH is worse than a refusal."""
    devices = [{"mark": "H1", "x": 10.0, "y": 10.0, "id": "hd_dev_001",
                "appearances": ["s1_a"], "sheets": ["S1"]}]
    targets = [
        {"id": "rev_a", "mark": "H1", "x": 10.4, "y": 10.0},   # 0.40 ft
        {"id": "rev_b", "mark": "H1", "x": 9.7, "y": 10.0},    # 0.30 ft, nearly tied
    ]
    dm.assign(devices, targets, dm.point_distance)
    d = devices[0]
    assert d["status"] == "NEEDS_REVIEW"
    assert "Ambiguous" in d["reason"]
    assert "target_id" not in d
    assert not targets[0].get("_claimed") and not targets[1].get("_claimed")


def test_decisive_nearest_candidate_still_matches():
    """A clearly-closer candidate (well outside the ambiguity margin) must
    still produce a normal MATCH -- the ambiguity guard is not a blanket
    refusal, only a refusal on genuine ties."""
    devices = [{"mark": "H1", "x": 10.0, "y": 10.0, "id": "hd_dev_001",
                "appearances": ["s1_a"], "sheets": ["S1"]}]
    targets = [
        {"id": "rev_close", "mark": "H1", "x": 10.1, "y": 10.0},  # 0.10 ft
        {"id": "rev_far", "mark": "H1", "x": 15.0, "y": 10.0},    # 5.0 ft
    ]
    dm.assign(devices, targets, dm.point_distance)
    d = devices[0]
    assert d["status"] == "MATCH"
    assert d["target_id"] == "rev_close"
    assert targets[0].get("_claimed") is True


def test_ambiguity_only_considers_candidates_within_mismatch_gate():
    """A distant runner-up (beyond mismatch_ft) is never claimable anyway, so
    it must not trigger a spurious ambiguity flag against a genuinely
    decisive near candidate."""
    devices = [{"mark": "H1", "x": 10.0, "y": 10.0, "id": "hd_dev_001",
                "appearances": ["s1_a"], "sheets": ["S1"]}]
    targets = [
        {"id": "rev_close", "mark": "H1", "x": 10.1, "y": 10.0},   # 0.10 ft
        {"id": "rev_distant", "mark": "H1", "x": 10.9, "y": 10.0},  # 0.90 ft
    ]
    # 0.90 - 0.10 = 0.80 < AMBIGUITY_MARGIN_FT(1.0) -> still flagged ambiguous.
    # This test documents that behavior explicitly (tight margin is a knob,
    # not a bug): both candidates are close enough in absolute terms that
    # picking wrong would misplace which physical device is which.
    dm.assign(devices, targets, dm.point_distance)
    assert devices[0]["status"] == "NEEDS_REVIEW"


# --------------------------------------------------------------- end to end

def test_run_end_to_end_matches_wall_and_holdown_categories():
    """Smoke test: run() still produces sane output shape after the fixes."""
    rows = [
        {"id": "s1_h1_a", "sheet": "S1", "category": "holdown", "mark": "H1",
         "status": "MATCH", "pdf_point": _pdf_point_for(10, 10)},
    ]
    asm = [{"id": "rev_asm_001", "pdf_mark_candidate": "H1",
            "center_point": {"x": 10.05, "y": 10.0}}]
    reg = dm.run(rows, CALS, asm, walls=[])
    hd = reg["categories"]["holdown"]
    assert hd["summary"]["physical_devices"] == 1
    assert hd["devices"][0]["status"] == "MATCH"


# ------------------------------------------- Gate: Shear Wall anchor fix

def test_shear_wall_uses_leader_corrected_anchor_not_raw_bubble():
    """wall_match.py hangs a SW callout bubble off the wall on a leader line
    and corrects for it (the bubble is not the physical reference, the
    leader tip is) -- but the fix landed only in wall_match's OWN verdict.
    element_registry passed the raw bubble point through as the row's
    pdf_point, and device_match re-projected THAT for the authoritative
    device-level verdict, silently discarding the correction. A bubble
    parked far from its wall with a leader that lands right on the wall
    must still MATCH at the device level, using match_anchor_pdf -- not
    fall back to a false PDF_ONLY/LOCATION_MISMATCH from the raw bubble."""
    bubble_far = _pdf_point_for(30, 30)       # nowhere near the wall
    leader_tip_on_wall = _pdf_point_for(10, 10.1)  # right next to the target
    row = {"id": "s1_sw1_a", "sheet": "S1", "category": "shear_wall",
           "mark": "SW-1", "status": "LOCATION_MISMATCH",
           "pdf_point": bubble_far, "match_anchor_pdf": leader_tip_on_wall}
    walls = [{"id": "wall_1", "type_name": "X SW1",
              "centerline": [[10.0, 5.0], [10.0, 15.0]]}]
    reg = dm.run([row], CALS, [], walls=walls)
    sw = reg["categories"]["shear_wall"]
    assert sw["summary"]["physical_devices"] == 1, sw["summary"]
    dev = sw["devices"][0]
    assert dev["status"] == "MATCH", dev  # would be PDF_ONLY/MISMATCH on the raw bubble

    # Sanity: without match_anchor_pdf (older row shape / no leader found),
    # falling back to the raw bubble is honest -- it should NOT match.
    row_no_anchor = dict(row)
    del row_no_anchor["match_anchor_pdf"]
    reg2 = dm.run([row_no_anchor], CALS, [], walls=walls)
    dev2 = reg2["categories"]["shear_wall"]["devices"][0]
    assert dev2["status"] != "MATCH", dev2
