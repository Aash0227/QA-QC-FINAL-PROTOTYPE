"""Tests for S-201 manual review overlay generation."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from app import config, review_overlay


@pytest.fixture
def tmp_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect artifact writes to a per-test tmp dir."""
    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path)
    return tmp_path


def _synthetic_report() -> dict:
    """Minimal report with one of each verdict type."""
    return {
        "final_verdicts": [
            {
                "verdict": "LOCATION_MISMATCH",
                "pdf_holdown_id": "pdf_loc_001",
                "revit_assembly_id": "rev_loc_001",
                "mark": "H1",
                "pdf_point": {"x": 500.0, "y": 600.0},
                "revit_point_transformed_to_pdf": {"x": 520.0, "y": 620.0},
                "distance_pdf_points": 28.3,
                "reason": "Location mismatch: 28pt apart",
            },
            {
                "verdict": "PDF_ONLY",
                "pdf_holdown_id": "pdf_only_001",
                "revit_assembly_id": None,
                "mark": "H2",
                "pdf_point": {"x": 800.0, "y": 700.0},
                "reason": "No Revit partner found",
            },
            {
                "verdict": "REVIT_ONLY",
                "pdf_holdown_id": None,
                "revit_assembly_id": "rev_only_001",
                "mark": "H3",
                "revit_point_transformed_to_pdf": {"x": 3000.0, "y": 2000.0},  # Off-sheet
                "reason": "No PDF partner found",
            },
            {
                "verdict": "REVIT_ONLY",
                "pdf_holdown_id": None,
                "revit_assembly_id": "rev_only_002",
                "mark": "H4",
                "revit_point_transformed_to_pdf": {"x": 1200.0, "y": 900.0},  # On-sheet
                "reason": "No PDF partner found",
            },
            {
                "verdict": "MATCH",
                "pdf_holdown_id": "pdf_match_001",
                "revit_assembly_id": "rev_match_001",
                "mark": "H1",
                "pdf_point": {"x": 1000.0, "y": 800.0},
                "revit_point_transformed_to_pdf": {"x": 1005.0, "y": 803.0},
                "distance_pdf_points": 5.8,
                "reason": "Match: 5.8pt apart",
            },
        ]
    }


def test_location_mismatch_red_box_and_connector() -> None:
    """LOCATION_MISMATCH -> red box + red connector."""
    report = _synthetic_report()
    items = review_overlay.build_review_items(report, 2592.0, 1728.0)
    
    loc_mm = next(i for i in items["items"] if i["verdict"] == "LOCATION_MISMATCH")
    assert loc_mm["drawable"] is True
    assert loc_mm["box"]["color"] == "#ef4444"  # RED
    assert loc_mm["box"]["type"] == "rect"
    assert loc_mm["connector"] is not None
    assert loc_mm["connector"]["color"] == "#ef4444"
    assert loc_mm["connector"]["from"]["x"] == 520.0
    assert loc_mm["connector"]["to"]["x"] == 500.0


def test_pdf_only_blue_box() -> None:
    """PDF_ONLY -> blue box at pdf_point."""
    report = _synthetic_report()
    items = review_overlay.build_review_items(report, 2592.0, 1728.0)
    
    pdf_only = next(i for i in items["items"] if i["verdict"] == "PDF_ONLY")
    assert pdf_only["drawable"] is True
    assert pdf_only["box"]["color"] == "#3b82f6"  # BLUE


def test_revit_only_on_sheet_orange() -> None:
    """REVIT_ONLY on-sheet -> orange box."""
    report = _synthetic_report()
    items = review_overlay.build_review_items(report, 2592.0, 1728.0)
    
    on_sheet = next(i for i in items["items"] 
                    if i["id"] == "rev_only_002")
    assert on_sheet["drawable"] is True
    assert on_sheet["box"]["color"] == "#f97316"  # ORANGE


def test_revit_only_off_sheet_undrawable() -> None:
    """REVIT_ONLY off-sheet -> drawable:false, in undrawable_ids."""
    report = _synthetic_report()
    items = review_overlay.build_review_items(report, 2592.0, 1728.0)
    
    off_sheet = next(i for i in items["items"] 
                     if i["id"] == "rev_only_001")
    assert off_sheet["drawable"] is False
    assert off_sheet["id"] in items["undrawable_ids"]


def test_missing_coord_undrawable() -> None:
    """Missing required coordinate -> drawable:false."""
    report = {
        "final_verdicts": [
            {
                "verdict": "PDF_ONLY",
                "pdf_holdown_id": "no_coord",
                "revit_assembly_id": None,
                "mark": "H1",
                "pdf_point": None,  # Missing
                "reason": "Coord missing",
            }
        ]
    }
    items = review_overlay.build_review_items(report, 2592.0, 1728.0)
    
    item = items["items"][0]
    assert item["drawable"] is False
    assert item["id"] in items["undrawable_ids"]


def test_match_hidden_by_default() -> None:
    """MATCH -> drawable:true, default_hidden:true."""
    report = _synthetic_report()
    items = review_overlay.build_review_items(report, 2592.0, 1728.0)
    
    match = next(i for i in items["items"] if i["verdict"] == "MATCH")
    assert match["drawable"] is True
    assert match["default_hidden"] is True


def test_svg_viewbox_matches_page() -> None:
    """SVG viewBox must equal page size."""
    report = _synthetic_report()
    items = review_overlay.build_review_items(report, 2592.0, 1728.0)
    svg = review_overlay.build_overlay_svg(items, show_match=False)
    
    assert 'viewBox="0 0 2592.0 1728.0"' in svg


def test_svg_contains_expected_colors() -> None:
    """SVG contains red/blue/orange but no fake boxes."""
    report = _synthetic_report()
    items = review_overlay.build_review_items(report, 2592.0, 1728.0)
    svg = review_overlay.build_overlay_svg(items, show_match=False)
    
    assert "#ef4444" in svg  # RED (LOC_MM)
    assert "#3b82f6" in svg  # BLUE (PDF_ONLY)
    assert "#f97316" in svg  # ORANGE (on-sheet REVIT_ONLY)
    assert "#22c55e" not in svg  # GREEN (MATCH hidden)


def test_svg_distance_label() -> None:
    """SVG contains distance labels for LOC_MM."""
    report = _synthetic_report()
    items = review_overlay.build_review_items(report, 2592.0, 1728.0)
    svg = review_overlay.build_overlay_svg(items, show_match=False)
    
    assert "distance:" in svg or "28.3" in svg


def test_svg_skips_undrawable() -> None:
    """SVG does not contain off-sheet REVIT_ONLY."""
    report = _synthetic_report()
    items = review_overlay.build_review_items(report, 2592.0, 1728.0)
    svg = review_overlay.build_overlay_svg(items, show_match=False)
    
    # Should not have any element at (3000, 2000) since it's off-sheet
    assert 'x="3000.0"' not in svg
    assert 'y="2000.0"' not in svg


def test_svg_show_match() -> None:
    """SVG includes MATCH when show_match=True."""
    report = _synthetic_report()
    items = review_overlay.build_review_items(report, 2592.0, 1728.0)
    
    svg_no_match = review_overlay.build_overlay_svg(items, show_match=False)
    svg_with_match = review_overlay.build_overlay_svg(items, show_match=True)
    
    assert "#22c55e" not in svg_no_match
    assert "#22c55e" in svg_with_match


def test_coordinate_identity_no_transform() -> None:
    """Known pdf_point appears at raw coords in SVG (no transform)."""
    known_x, known_y = 500.0, 600.0
    report = {
        "final_verdicts": [
            {
                "verdict": "PDF_ONLY",
                "pdf_holdown_id": "known_coord",
                "revit_assembly_id": None,
                "mark": "H1",
                "pdf_point": {"x": known_x, "y": known_y},
                "reason": "Test",
            }
        ]
    }
    items = review_overlay.build_review_items(report, 2592.0, 1728.0)
    svg = review_overlay.build_overlay_svg(items, show_match=False)
    
    # The box should be centered at (500, 600) -> x0 = 500 - 20 = 480
    assert 'x="480.00"' in svg, f"Expected x=480.00 in SVG, got: {svg[:500]}"
    assert 'y="580.00"' in svg, f"Expected y=580.00 in SVG, got: {svg[:500]}"


def test_render_page_png(tmp_artifacts: Path) -> None:
    """Render page PNG (skip if sample PDF absent)."""
    sample_pdf = Path(
        r"C:\Users\aashd\Downloads\wetransfer_madera-model-and-permit-sets_2026-05-13_1004"
        r"\STAMPED_10510 Madera Dr-DWG-20260122-D1.pdf"
    )
    if not sample_pdf.exists():
        pytest.skip("Sample Madera PDF not available")
    
    out_path = tmp_artifacts / "test_page.png"
    page_png, w, h = review_overlay.render_s201_page_png(sample_pdf, 4, out_path)
    
    assert page_png.exists()
    assert w > 0 and h > 0
    # S-201 is 2592 x 1728 pt (or close)
    assert 2500 < w < 2700
    assert 1650 < h < 1800


def test_counts_match_verdicts() -> None:
    """Counts in items match actual verdict counts."""
    report = _synthetic_report()
    items = review_overlay.build_review_items(report, 2592.0, 1728.0)
    
    assert items["counts"]["total"] == 5
    assert items["counts"]["by_verdict"]["LOCATION_MISMATCH"] == 1
    assert items["counts"]["by_verdict"]["PDF_ONLY"] == 1
    assert items["counts"]["by_verdict"]["REVIT_ONLY"] == 2
    assert items["counts"]["by_verdict"]["MATCH"] == 1
    assert items["counts"]["drawable"] == 4  # 1 off-sheet
    assert items["counts"]["undrawable"] == 1


def test_nearest_candidates_included() -> None:
    """PDF_ONLY includes nearest_revit_candidates if present."""
    report = {
        "final_verdicts": [
            {
                "verdict": "PDF_ONLY",
                "pdf_holdown_id": "pdf_with_nearest",
                "revit_assembly_id": None,
                "mark": "H1",
                "pdf_point": {"x": 500.0, "y": 600.0},
                "nearest_revit_candidates": [
                    {"revit_assembly_id": "rev_001", "distance_pdf_points": 45.2}
                ],
                "reason": "No Revit partner found",
            }
        ]
    }
    items = review_overlay.build_review_items(report, 2592.0, 1728.0)
    
    item = items["items"][0]
    assert item["nearest"] is not None
    assert item["nearest"][0]["revit_assembly_id"] == "rev_001"
