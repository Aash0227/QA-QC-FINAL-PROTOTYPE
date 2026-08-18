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


# ------------------------- Shear Wall: level context evidence channel

def _sw_rows(n: int, sheet: str = "S1"):
    """n SW-1 callouts spread far enough apart to stay distinct devices."""
    return [
        {"id": f"{sheet}_sw1_{i}", "sheet": sheet, "category": "shear_wall",
         "mark": "SW-1", "status": "PDF_ONLY",
         "pdf_point": _pdf_point_for(10 + i * 10, 10)}
        for i in range(n)
    ]


def _stacked_walls(unstacked: tuple[int, ...] = ()):
    """Pairs of identical SW-1 walls at the SAME plan coordinates on two
    different levels -- the real Madera ambiguity pattern (a building's
    shear walls stack floor to floor). Indices in `unstacked` get only their
    Level 2 wall, so the matching callout pairs unambiguously and can act as
    a consensus voter."""
    walls = []
    for i in range(4):
        x = 10.0 + i * 10
        levels = ("Level 2",) if i in unstacked else ("Level 1", "Level 2")
        for lvl in levels:
            walls.append({
                "id": f"w_{i}_{lvl.replace(' ', '')}", "type_name": "X SW1",
                "level": lvl, "centerline": [[x, 5.0], [x, 15.0]],
            })
    return walls


def test_level_context_breaks_ambiguity_between_stacked_walls():
    """Stage 9 Shear Wall investigation: the dominant NEEDS_REVIEW cause on
    real Madera was two identical same-mark walls stacked on different
    floors at identical plan coordinates -- distance and mark cannot tell
    them apart, so the ambiguity guard (correctly) refused to pick. But a
    plan sheet draws ONE story, so the sheet's level consensus -- measured
    from the pairings that resolved WITHOUT this channel -- does
    distinguish them."""
    rows = _sw_rows(4)
    # Callouts 0-2 have an unstacked (Level 2 only) wall -> they pair
    # unambiguously and establish the sheet's level; callout 3 faces a real
    # stacked Level 1 / Level 2 tie that only the context channel can break.
    walls = _stacked_walls(unstacked=(0, 1, 2))
    reg = dm.run(rows, CALS, [], walls=walls)
    devices = reg["categories"]["shear_wall"]["devices"]
    resolved = [d for d in devices if d.get("resolved_by") == "level"]
    assert resolved, [(d["status"], d.get("reason")) for d in devices]
    # Every context-resolved pairing must land on the consensus level.
    by_id = {w["id"]: w for w in walls}
    for d in resolved:
        assert by_id[d["target_id"]]["level"] == "Level 2", d
        assert "Level 2" in d["reason"] and "ambiguous" in d["reason"].lower()


def test_level_context_never_fires_without_enough_consensus_evidence():
    """Thin evidence must leave the uncertainty intact: with no unambiguous
    pairing to establish the sheet's level, ambiguous devices stay
    NEEDS_REVIEW rather than guessing a level."""
    rows = _sw_rows(2)
    walls = _stacked_walls()          # every candidate perfectly tied
    reg = dm.run(rows, CALS, [], walls=walls)
    devices = reg["categories"]["shear_wall"]["devices"]
    assert not [d for d in devices if d.get("resolved_by")], devices
    assert any(d["status"] == "NEEDS_REVIEW" for d in devices), devices


def test_level_context_does_not_fire_when_candidates_share_a_level():
    """When the tied candidates agree on the context value there is nothing
    distinguishing about it -- the ambiguity is real and must be kept."""
    rows = _sw_rows(4)
    walls = _stacked_walls(unstacked=(0, 1, 2))
    for w in walls:
        w["level"] = "Level 1"        # all same level -> no discriminating power
    reg = dm.run(rows, CALS, [], walls=walls)
    devices = reg["categories"]["shear_wall"]["devices"]
    assert not [d for d in devices if d.get("resolved_by")], devices


def test_holdown_adapter_has_no_context_channel():
    """Hold-down assemblies carry no level field in the export, so the
    Hold Down adapter must leave the channel off -- guarding the validated
    Gate 3 hold-down behavior against accidental change."""
    assert dm.HOLDOWN_ADAPTER.context_key is None
    assert dm.SHEAR_WALL_ADAPTER.context_key == "level"


# ------------------- Shear Wall: PDF-side orientation evidence channel

def test_orientation_breaks_ambiguity_when_only_one_candidate_agrees():
    """The drawn wall's direction, measured from the sheet's own vector
    geometry (pdf_wall_geometry), is real PDF<->model evidence: when two
    same-mark candidates are equidistant but run in different directions,
    the one matching the DRAWN direction is the wall the callout refers to."""
    row = {"id": "S1_sw1_a", "sheet": "S1", "category": "shear_wall",
           "mark": "SW-1", "status": "PDF_ONLY",
           "pdf_point": _pdf_point_for(10, 10),
           "orientation_deg": 90.0}          # drawn wall runs vertically
    walls = [
        # equidistant from the callout, but only one runs vertically
        {"id": "w_vert", "type_name": "X SW1", "level": "Level 1",
         "centerline": [[11.0, 5.0], [11.0, 15.0]]},
        {"id": "w_horiz", "type_name": "X SW1", "level": "Level 1",
         "centerline": [[5.0, 11.0], [15.0, 11.0]]},
    ]
    reg = dm.run([row], CALS, [], walls=walls)
    dev = reg["categories"]["shear_wall"]["devices"][0]
    assert dev.get("resolved_by") == "orientation", dev
    assert dev["target_id"] == "w_vert", dev
    assert "90" in dev["reason"]


def test_orientation_refuses_when_both_candidates_share_direction():
    """Two parallel same-mark walls are not distinguishable by direction --
    the channel must stay silent rather than pick arbitrarily."""
    row = {"id": "S1_sw1_a", "sheet": "S1", "category": "shear_wall",
           "mark": "SW-1", "status": "PDF_ONLY",
           "pdf_point": _pdf_point_for(10, 10), "orientation_deg": 90.0}
    walls = [
        {"id": "w_a", "type_name": "X SW1", "level": "Level 1",
         "centerline": [[10.6, 5.0], [10.6, 15.0]]},
        {"id": "w_b", "type_name": "X SW1", "level": "Level 1",
         "centerline": [[9.4, 5.0], [9.4, 15.0]]},
    ]
    reg = dm.run([row], CALS, [], walls=walls)
    dev = reg["categories"]["shear_wall"]["devices"][0]
    assert dev.get("resolved_by") is None, dev
    assert dev["status"] == "NEEDS_REVIEW", dev


def test_orientation_channel_dormant_without_pdf_geometry():
    """A callout whose drawn wall could not be extracted carries no
    orientation, and must behave exactly as before the channel existed."""
    row = {"id": "S1_sw1_a", "sheet": "S1", "category": "shear_wall",
           "mark": "SW-1", "status": "PDF_ONLY",
           "pdf_point": _pdf_point_for(10, 10)}     # no orientation_deg
    walls = [
        {"id": "w_vert", "type_name": "X SW1", "level": "Level 1",
         "centerline": [[11.0, 5.0], [11.0, 15.0]]},
        {"id": "w_horiz", "type_name": "X SW1", "level": "Level 1",
         "centerline": [[5.0, 11.0], [15.0, 11.0]]},
    ]
    reg = dm.run([row], CALS, [], walls=walls)
    dev = reg["categories"]["shear_wall"]["devices"][0]
    assert dev.get("resolved_by") is None, dev
    assert dev["status"] == "NEEDS_REVIEW", dev


def test_holdown_adapter_has_no_orientation_channel():
    """Hold-down assemblies are point hardware with no meaningful direction;
    the validated Gate 3 behavior must stay untouched."""
    assert dm.HOLDOWN_ADAPTER.orientation_tolerance_deg is None
    assert dm.SHEAR_WALL_ADAPTER.orientation_tolerance_deg == 20.0


def test_unpaired_callout_still_carries_drawn_orientation():
    """Coverage fix: drawn orientation is a property of the CALLOUT and the
    drawing, not of a Revit pairing. It was first attached only inside
    wall_match's matched-candidate loop, so unpaired (PDF_ONLY) callouts --
    the majority on a real sheet -- silently carried no orientation at all
    and the evidence channel could never see them."""
    from app import wall_match as wm

    identity_cal = {
        "calibration_source": "manual_verified",
        "transform": {"matrix": [1, 0, 0, 1, 0, 0],
                      "inverse_matrix": [1, 0, 0, 1, 0, 0]},
        "quality": {"match_allowed": True, "confidence": "high"},
    }
    # One callout with NO same-token Revit wall anywhere -> PDF_ONLY.
    marks = [{"id": "m_lonely", "category": "shear_wall", "mark": "SW-9",
              "center_pdf": [100, 100]}]
    # A drawn run right beside it: a vertical band of short hatch ticks.
    runs = [{"segment": ((105.0, 60.0), (105.0, 140.0)),
             "length_pt": 80.0, "angle_deg": 90.0, "tick_count": 40}]
    rep = wm.match_shear_walls(marks, [], identity_cal, wall_runs=runs)
    row = rep["rows"][0]
    assert row["verdict"] == "PDF_ONLY", row
    assert row.get("orientation_deg") is not None, row
    assert abs(row["orientation_deg"] - 90.0) < 1.0, row


# ------------------ Shear Wall: evidence-conflict diagnostics (no verdict change)

def test_drawn_orientation_matching_no_candidate_is_flagged():
    """When the drawn wall disagrees with EVERY candidate, the device is not
    really facing a tie -- the right element is probably out of range or
    missing from the model. That is a finding a reviewer must see, so it is
    named explicitly rather than left as a bare 'ambiguous'."""
    row = {"id": "S1_sw1_a", "sheet": "S1", "category": "shear_wall",
           "mark": "SW-1", "status": "PDF_ONLY",
           "pdf_point": _pdf_point_for(10, 10),
           "orientation_deg": 90.0}              # drawn wall is vertical
    walls = [  # two near-tied candidates, BOTH horizontal
        {"id": "w_a", "type_name": "X SW1", "level": "Level 1",
         "centerline": [[5.0, 10.6], [15.0, 10.6]]},
        {"id": "w_b", "type_name": "X SW1", "level": "Level 1",
         "centerline": [[5.0, 9.4], [15.0, 9.4]]},
    ]
    dev = dm.run([row], CALS, [], walls=walls)["categories"]["shear_wall"]["devices"][0]
    assert dev["status"] == "NEEDS_REVIEW", dev          # verdict unchanged
    assert dev.get("evidence_conflict") == "drawn_orientation_matches_no_candidate"
    assert "absent from the model" in dev["reason"]


def test_evidence_conflict_annotation_never_changes_a_verdict():
    """The diagnostics pass is additive: same statuses with and without it."""
    rows = _sw_rows(4)
    walls = _stacked_walls(unstacked=(0, 1, 2))
    before = {tuple(d["appearances"]): d["status"]
              for d in dm.run(rows, CALS, [], walls=walls)["categories"]["shear_wall"]["devices"]}
    # same input, now with drawn orientations attached to every callout
    rows2 = [dict(r, orientation_deg=90.0) for r in _sw_rows(4)]
    after = {tuple(d["appearances"]): d["status"]
             for d in dm.run(rows2, CALS, [], walls=walls)["categories"]["shear_wall"]["devices"]}
    assert before == after, (before, after)
