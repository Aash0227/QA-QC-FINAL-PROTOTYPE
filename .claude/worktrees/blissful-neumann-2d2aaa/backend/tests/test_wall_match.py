"""Tests for shear-wall matching geometry and MATCH gating."""

from __future__ import annotations

import math

from app import wall_match

IDENTITY_CAL = {
    "calibration_source": "manual_verified",
    "transform": {"matrix": [1, 0, 0, 1, 0, 0]},
    "quality": {"match_allowed": True, "confidence": "high"},
}

MARKS = [
    {"id": "m1", "category": "shear_wall", "mark": "SW-1", "center_pdf": [5, 3]},
    {"id": "m2", "category": "shear_wall", "mark": "SW-2", "center_pdf": [100, 100]},
    {"id": "m3", "category": "shear_wall", "mark": "SW-1", "center_pdf": [900, 900]},
]
WALLS = [
    {"id": "w1", "type_name": 'N-INT-LB-54-SO-6" SW1', "centerline": [[0, 0], [10, 0]]},
    {"id": "w2", "type_name": 'N-EXT-LB-54-SO-6" SW-2', "centerline": [[95, 95], [105, 95]]},
]


def test_sw_token_normalization() -> None:
    assert wall_match.sw_token('N-INT-LB-54-SO-6" SW1') == "SW-1"
    assert wall_match.sw_token('N-EXT-LB-54-SO-6" SW-2') == "SW-2"
    assert wall_match.sw_token("plain interior wall") is None
    assert wall_match.sw_token(None) is None


def test_point_to_segment_distance() -> None:
    assert wall_match.point_to_segment_distance((0, 5), (0, 0), (10, 0)) == 5.0
    # clamp to endpoint
    assert wall_match.point_to_segment_distance((-3, 4), (0, 0), (10, 0)) == 5.0
    # degenerate zero-length segment
    assert wall_match.point_to_segment_distance((1, 1), (2, 2), (2, 2)) == math.hypot(1, 1)


def test_greedy_one_to_one_match() -> None:
    rep = wall_match.match_shear_walls(MARKS, WALLS, IDENTITY_CAL)
    verdicts = {r["pdf_mark_id"]: r["verdict"] for r in rep["rows"]}
    assert verdicts == {"m1": "MATCH", "m2": "MATCH", "m3": "PDF_ONLY"}
    assert rep["summary"]["REVIT_ONLY"] == 0
    m1 = next(r for r in rep["rows"] if r["pdf_mark_id"] == "m1")
    assert m1["revit_wall_id"] == "w1"
    assert m1["distance_pdf_points"] == 3.0  # point (5,3) above segment y=0


def test_no_calibration_means_needs_review_never_match() -> None:
    rep = wall_match.match_shear_walls(MARKS, WALLS, None)
    assert rep["usable_calibration"] is False
    assert all(r["verdict"] == "NEEDS_REVIEW" for r in rep["rows"])


def test_unverified_calibration_blocks_match() -> None:
    bad = {**IDENTITY_CAL, "quality": {"match_allowed": False, "confidence": "low"}}
    rep = wall_match.match_shear_walls(MARKS, WALLS, bad)
    assert all(r["verdict"] in ("NEEDS_REVIEW", "PDF_ONLY") for r in rep["rows"])
    assert "MATCH" not in rep["summary"]


def test_mark_token_constraint() -> None:
    # SW-2 callout must never match an SW-1 wall even if it is closest.
    marks = [{"id": "x", "category": "shear_wall", "mark": "SW-2", "center_pdf": [5, 3]}]
    rep = wall_match.match_shear_walls(marks, [WALLS[0]], IDENTITY_CAL)
    assert rep["rows"][0]["verdict"] == "PDF_ONLY"
    assert rep["summary"]["REVIT_ONLY"] == 1
