"""Tests for the unified element list and the 3D scene payload."""

from __future__ import annotations

from app import element_registry, scene3d

EI = {
    "sheets": [
        {
            "sheet_number": "S-201",
            "page_index": 4,
            "page_size_pt": [2592, 1728],
            "tables": [
                {
                    "category": "holdown",
                    "rows": [{"mark": "H1", "cells": {"row_text": "1 H1 S/HDU6"}}],
                }
            ],
            "marks": [
                {"id": "s-201_holdown_h1_001", "category": "holdown", "mark": "H1",
                 "center_pdf": [300, 700], "bbox_pdf": [295, 695, 305, 705],
                 "schedule_listed": True},
            ],
            "count_consistency": [],
        },
        {
            "sheet_number": "S-202",
            "page_index": 5,
            "page_size_pt": [2592, 1728],
            "tables": [
                {"category": "post", "rows": [{"mark": "P-1", "cells": {"row_text": "P-1 spec"}}]},
                {"category": "wall_type", "rows": [{"mark": "2", "cells": {"row_text": "6in wall"}}]},
            ],
            "marks": [
                {"id": "sw1", "category": "shear_wall", "mark": "SW-1",
                 "center_pdf": [800, 400], "bbox_pdf": None, "schedule_listed": True},
                {"id": "p1", "category": "post", "mark": "P-1",
                 "center_pdf": [500, 500], "bbox_pdf": None, "schedule_listed": True},
                {"id": "c4", "category": "steel_column", "mark": "C-4",
                 "center_pdf": [600, 600], "bbox_pdf": None, "schedule_listed": False},
                {"id": "h_extra", "category": "holdown", "mark": "H2",
                 "center_pdf": [700, 700], "bbox_pdf": None, "schedule_listed": True},
            ],
            "count_consistency": [],
        },
    ]
}

COMPARE = {
    "final_verdicts": [
        {"pdf_holdown_id": "s-201_h1_022_2", "revit_assembly_id": "asm1", "mark": "H1",
         "pdf_point": {"x": 307.0, "y": 702.7},
         "revit_point_transformed_to_pdf": {"x": 311.2, "y": 700.1},
         "distance_pdf_points": 4.15, "verdict": "MATCH", "reason": "ok", "confidence": 0.82},
        {"pdf_holdown_id": None, "revit_assembly_id": "asm2", "mark": "H2",
         "pdf_point": None, "revit_point_transformed_to_pdf": {"x": 900.0, "y": 900.0},
         "distance_pdf_points": None, "verdict": "REVIT_ONLY", "reason": "no partner"},
    ]
}

WALL_REPORTS = {
    "S-202": {
        "rows": [
            {"pdf_mark_id": "sw1", "mark": "SW-1", "pdf_point": {"x": 800, "y": 400},
             "revit_wall_id": "w1", "revit_wall_type": 'X SW1',
             "wall_segment_pdf": [[790, 390], [810, 390]],
             "distance_pdf_points": 12.0, "verdict": "MATCH", "reason": "ok"},
        ],
        "unmatched_revit_walls": [
            {"revit_wall_id": "w9", "token": "SW-2", "type_name": "Y SW2", "verdict": "REVIT_ONLY"},
        ],
        "summary": {},
    }
}


def _build():
    return element_registry.build_element_list(EI, COMPARE, WALL_REPORTS, compare_sheet="S-201")


def test_statuses_join_honestly() -> None:
    el = _build()
    by_id = {e["id"]: e for e in el["elements"]}
    # holdown verdicts pass through from compare.py untouched
    assert by_id["s-201_h1_022_2"]["status"] == "MATCH"
    assert by_id["revit_only_asm2"]["status"] == "REVIT_ONLY"
    # shear wall from wall report with revit_ref
    assert by_id["sw1"]["status"] == "MATCH"
    assert by_id["sw1"]["revit_ref"]["id"] == "w1"
    # posts: no Revit data, never a match
    assert by_id["p1"]["status"] == "NO_REVIT_DATA"
    # plan mark missing from every schedule
    assert by_id["c4"]["status"] == "NOT_IN_SCHEDULE"
    # holdown callout on a non-compare sheet: extraction only
    assert by_id["h_extra"]["status"] == "NOT_EVALUATED"
    # unmatched Revit wall listed once
    assert by_id["revit_wall_w9"]["status"] == "REVIT_ONLY"
    assert by_id["revit_wall_w9"]["drawable"] is False
    # wall types are spec-only
    assert by_id["wall_type_2"]["status"] == "SPEC_ONLY"


def test_no_duplicate_holdowns_on_compare_sheet() -> None:
    el = _build()
    # the generic S-201 holdown mark must be skipped (compare rows are authoritative)
    assert all(e["id"] != "s-201_holdown_h1_001" for e in el["elements"])


def test_counts_add_up() -> None:
    el = _build()
    assert el["counts"]["total"] == len(el["elements"])
    assert sum(el["counts"]["by_status"].values()) == el["counts"]["total"]


def test_scene3d_honest_geometry() -> None:
    raw = {
        "walls": [
            {"id": "w1", "type_name": 'X SW1', "centerline": [[0, 0], [10, 0]],
             "thickness": 0.5, "level": "Level 1"},
            {"id": "w2", "type_name": "plain", "centerline": [[0, 5], [10, 5]],
             "thickness": 0.5, "level": "Level 1"},
        ],
        "grids": [{"id": "g1", "label": "A", "line": [[0, 0], [0, 60]]}],
    }
    ai_revit = {
        "canonical_holdown_assemblies": [
            {"id": "asm1", "pdf_mark_candidate": "H1",
             "center_point": {"x": 1.0, "y": 2.0, "z": 1.5}},
        ]
    }
    scene = scene3d.build_scene(raw, _build(), ai_revit)
    w1 = next(w for w in scene["walls"] if w["id"] == "w1")
    assert w1["status"] == "MATCH"           # joined from element list
    assert w1["height_assumed"] is True      # never presented as model truth
    assert w1["is_shear_wall"] is True
    w2 = next(w for w in scene["walls"] if w["id"] == "w2")
    assert w2["status"] == "NOT_EVALUATED" and w2["is_shear_wall"] is False
    h = scene["holdowns"][0]
    assert h["status"] == "MATCH" and h["elevation_ft"] == 1.5
    assert scene["bounds"]["max_y"] == 60.0
