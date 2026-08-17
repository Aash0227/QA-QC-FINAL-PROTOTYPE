"""
S-201 Manual-Review Overlay Generator

Renders the actual S-201 drawing with discrepancy overlays:
- Red boxes + connectors: LOCATION_MISMATCH
- Blue boxes: PDF_ONLY
- Orange markers: REVIT_ONLY (on-sheet only)
- Green dots: MATCH (hidden by default)

All coordinates are in PDF points (no rotation, no transform needed).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import fitz
from PIL import Image, ImageDraw

# Constants
BOX_HALF_PT = 20  # 40pt square centered on point
RENDER_DPI = 150

# Colors
RED = "#ef4444"      # LOCATION_MISMATCH
BLUE = "#3b82f6"     # PDF_ONLY
ORANGE = "#f97316"   # REVIT_ONLY
GREEN = "#22c55e"    # MATCH


def render_s201_page_png(
    pdf_path: Path,
    page_index: int,
    out_path: Path,
    dpi: int = RENDER_DPI,
) -> tuple[Path, float, float]:
    """Render full S-201 page to PNG. Returns (path, width_pt, height_pt)."""
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[page_index]
        # Render at specified DPI
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(out_path))
        # Return page dimensions in PDF points
        rect = page.rect
        return out_path, rect.width, rect.height
    finally:
        doc.close()


def _is_on_sheet(x: float, y: float, w: float, h: float) -> bool:
    """Check if point is within page bounds."""
    return 0 <= x <= w and 0 <= y <= h


def build_review_items(
    compare_report: dict[str, Any],
    page_w: float,
    page_h: float,
) -> dict[str, Any]:
    """
    Build review items from comparison report.
    
    Returns dict with:
    - schema_version
    - page: {w, h, image_png, dpi}
    - counts: {total, drawable, undrawable, by_verdict}
    - items: list of per-verdict overlay specs
    - undrawable_ids: list of IDs that couldn't be drawn
    """
    verdicts = compare_report.get("final_verdicts", [])
    
    items = []
    undrawable_ids = []
    counts = {
        "total": len(verdicts),
        "drawable": 0,
        "undrawable": 0,
        "by_verdict": {},
    }
    
    for row in verdicts:
        verdict = row.get("verdict", "UNKNOWN")
        row_id = row.get("pdf_holdown_id") or row.get("revit_assembly_id") or "unknown"
        
        # Count by verdict
        counts["by_verdict"][verdict] = counts["by_verdict"].get(verdict, 0) + 1
        
        # Extract coordinates
        pdf_pt = row.get("pdf_point")
        rev_pt_t = row.get("revit_point_transformed_to_pdf")
        
        # Build item spec
        item = {
            "id": row_id,
            "verdict": verdict,
            "mark": row.get("mark"),
            "pdf_id": row.get("pdf_holdown_id"),
            "revit_id": row.get("revit_assembly_id"),
            "distance_pt": row.get("distance_pdf_points"),
            "confidence": row.get("confidence"),
            "reason": row.get("reason"),
            "nearest": _extract_nearest(row, verdict),
            "drawable": False,
            "box": None,
            "connector": None,
            "default_hidden": False,
        }
        
        # Verdict-specific rendering
        if verdict == "LOCATION_MISMATCH":
            # Red box + connector
            if pdf_pt and _is_on_sheet(pdf_pt["x"], pdf_pt["y"], page_w, page_h):
                item["drawable"] = True
                item["box"] = _make_box(pdf_pt["x"], pdf_pt["y"], RED)
                if rev_pt_t and _is_on_sheet(rev_pt_t["x"], rev_pt_t["y"], page_w, page_h):
                    item["connector"] = {
                        "from": {"x": rev_pt_t["x"], "y": rev_pt_t["y"]},
                        "to": {"x": pdf_pt["x"], "y": pdf_pt["y"]},
                        "color": RED,
                    }
        
        elif verdict == "PDF_ONLY":
            # Blue box at pdf_point
            if pdf_pt and _is_on_sheet(pdf_pt["x"], pdf_pt["y"], page_w, page_h):
                item["drawable"] = True
                item["box"] = _make_box(pdf_pt["x"], pdf_pt["y"], BLUE)
        
        elif verdict == "REVIT_ONLY":
            # Orange box at rev_pt_t (only if on-sheet)
            if rev_pt_t and _is_on_sheet(rev_pt_t["x"], rev_pt_t["y"], page_w, page_h):
                item["drawable"] = True
                item["box"] = _make_box(rev_pt_t["x"], rev_pt_t["y"], ORANGE)
        
        elif verdict == "MATCH":
            # Green dot (hidden by default)
            if pdf_pt and _is_on_sheet(pdf_pt["x"], pdf_pt["y"], page_w, page_h):
                item["drawable"] = True
                item["box"] = {
                    "type": "circle",
                    "cx": pdf_pt["x"],
                    "cy": pdf_pt["y"],
                    "r": 4,
                    "color": GREEN,
                    "opacity": 0.3,
                }
                item["default_hidden"] = True
        
        # Track drawable/undrawable
        if item["drawable"]:
            counts["drawable"] += 1
        else:
            counts["undrawable"] += 1
            undrawable_ids.append(item["id"])
        
        items.append(item)
    
    return {
        "schema_version": "s201-review-items/1.0",
        "page": {
            "w": page_w,
            "h": page_h,
            "image_png": "review_page.png",
            "dpi": RENDER_DPI,
        },
        "counts": counts,
        "items": items,
        "undrawable_ids": undrawable_ids,
    }


def _extract_nearest(row: dict, verdict: str) -> list[dict] | None:
    """Extract nearest candidates from row based on verdict."""
    if verdict == "PDF_ONLY":
        return row.get("nearest_revit_candidates")
    elif verdict == "REVIT_ONLY":
        return row.get("nearest_pdf_candidates")
    return None


def _make_box(x: float, y: float, color: str) -> dict:
    """Make a box spec centered on (x, y)."""
    return {
        "type": "rect",
        "x0": x - BOX_HALF_PT,
        "y0": y - BOX_HALF_PT,
        "x1": x + BOX_HALF_PT,
        "y1": y + BOX_HALF_PT,
        "color": color,
        "dashed": True,
    }


def build_overlay_svg(
    items_payload: dict[str, Any],
    show_match: bool = False,
) -> str:
    """
    Build SVG overlay with boxes, connectors, and labels.
    
    Args:
        items_payload: output from build_review_items
        show_match: if False, skip MATCH items (default_hidden=True)
    
    Returns SVG string with viewBox in PDF points.
    """
    page = items_payload["page"]
    w, h = page["w"], page["h"]
    
    svg_parts = [
        f'<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" ',
        f'     viewBox="0 0 {w} {h}" ',
        f'     preserveAspectRatio="xMidYMid meet" ',
        f'     width="{w}" height="{h}">',
        f'  <defs>',
        f'    <style>',
        f'      .box {{ fill: none; stroke-width: 3; }}',
        f'      .dashed {{ stroke-dasharray: 8 5; }}',
        f'      .label {{ font-family: monospace; font-size: 12px; font-weight: bold; }}',
        f'      .connector {{ stroke-width: 2; }}',
        f'    </style>',
        f'  </defs>',
    ]
    
    for item in items_payload["items"]:
        if not item["drawable"]:
            continue  # Skip undrawable items (no faked boxes)
        
        # Skip MATCH if show_match=False
        if item["default_hidden"] and not show_match:
            continue
        
        verdict = item["verdict"]
        box = item["box"]
        
        if not box:
            continue
        
        # Draw connector first (so it's behind the box)
        if item.get("connector"):
            conn = item["connector"]
            x1, y1 = conn["from"]["x"], conn["from"]["y"]
            x2, y2 = conn["to"]["x"], conn["to"]["y"]
            svg_parts.append(
                f'  <line class="connector" '
                f'x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
                f'stroke="{conn["color"]}" />'
            )
        
        # Draw box/circle
        if box["type"] == "rect":
            dash_class = " dashed" if box.get("dashed") else ""
            svg_parts.append(
                f'  <rect class="box{dash_class}" '
                f'x="{box["x0"]:.2f}" y="{box["y0"]:.2f}" '
                f'width="{box["x1"] - box["x0"]:.2f}" height="{box["y1"] - box["y0"]:.2f}" '
                f'stroke="{box["color"]}" />'
            )
            
            # Add label above box
            label_x = box["x0"]
            label_y = box["y0"] - 8
            if verdict == "LOCATION_MISMATCH" and item.get("distance_pt") is not None:
                label_text = f"LOCATION MISMATCH · distance: {item['distance_pt']:.1f} pt"
            else:
                label_text = f"{verdict.replace('_', ' ')}"
            svg_parts.append(
                f'  <text class="label" '
                f'x="{label_x:.2f}" y="{label_y:.2f}" '
                f'fill="{box["color"]}">{label_text}</text>'
            )
        
        elif box["type"] == "circle":
            opacity = box.get("opacity", 1.0)
            svg_parts.append(
                f'  <circle cx="{box["cx"]:.2f}" cy="{box["cy"]:.2f}" r="{box["r"]}" '
                f'fill="{box["color"]}" opacity="{opacity}" />'
            )
    
    svg_parts.append('</svg>')
    return '\n'.join(svg_parts)


def render_annotated_png(
    page_png_path: Path,
    items_payload: dict[str, Any],
    out_path: Path,
    dpi: int = RENDER_DPI,
    show_match: bool = False,
) -> None:
    """
    Burn boxes/lines/labels onto the PNG with PIL.
    
    This creates a static, exportable artifact.
    """
    img = Image.open(page_png_path)
    draw = ImageDraw.Draw(img)
    
    # Scale factor: PDF points -> pixels
    scale = dpi / 72.0
    
    for item in items_payload["items"]:
        if not item["drawable"]:
            continue
        if item["default_hidden"] and not show_match:
            continue
        
        box = item["box"]
        if not box:
            continue
        
        # Draw connector
        if item.get("connector"):
            conn = item["connector"]
            x1 = conn["from"]["x"] * scale
            y1 = conn["from"]["y"] * scale
            x2 = conn["to"]["x"] * scale
            y2 = conn["to"]["y"] * scale
            draw.line([(x1, y1), (x2, y2)], fill=conn["color"], width=2)
        
        # Draw box/circle
        if box["type"] == "rect":
            x0 = box["x0"] * scale
            y0 = box["y0"] * scale
            x1 = box["x1"] * scale
            y1 = box["y1"] * scale
            draw.rectangle([x0, y0, x1, y1], outline=box["color"], width=3)
        
        elif box["type"] == "circle":
            cx = box["cx"] * scale
            cy = box["cy"] * scale
            r = box["r"] * scale
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=box["color"])
    
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)


def build_and_save(
    compare_report: dict[str, Any],
    pdf_path: Path,
    page_index: int,
    artifact_dir: Path,
) -> dict[str, Any]:
    """
    Full orchestrator: render page, build items, build SVG, render annotated PNG.
    
    Writes:
    - review_page.png
    - review_overlay.svg
    - review_overlay.png
    - review_items.json
    
    Returns items dict.
    """
    # ponytail: filenames below duplicate config.ARTIFACT_FILES["review_*"] —
    # if they drift the served artifacts 404. Sync manually or import config.
    # 1. Render page PNG
    page_png = artifact_dir / "review_page.png"
    page_png, w, h = render_s201_page_png(pdf_path, page_index, page_png)
    
    # 2. Build review items
    items_payload = build_review_items(compare_report, w, h)
    items_payload["page"]["w"] = w
    items_payload["page"]["h"] = h
    
    # 3. Build SVG (no MATCH by default)
    svg_content = build_overlay_svg(items_payload, show_match=False)
    svg_path = artifact_dir / "review_overlay.svg"
    svg_path.write_text(svg_content, encoding="utf-8")
    
    # 4. Render annotated PNG (no MATCH by default)
    overlay_png = artifact_dir / "review_overlay.png"
    render_annotated_png(page_png, items_payload, overlay_png, show_match=False)
    
    # 5. Write items JSON
    items_json = artifact_dir / "review_items.json"
    items_json.write_text(json.dumps(items_payload, indent=2), encoding="utf-8")
    
    return items_payload


if __name__ == "__main__":
    # Self-check with synthetic report
    synthetic_report = {
        "final_verdicts": [
            {
                "verdict": "LOCATION_MISMATCH",
                "pdf_holdown_id": "pdf_001",
                "revit_assembly_id": "rev_001",
                "mark": "H1",
                "pdf_point": {"x": 500, "y": 600},
                "revit_point_transformed_to_pdf": {"x": 520, "y": 620},
                "distance_pdf_points": 28.3,
                "reason": "Location mismatch: 28pt apart",
            },
            {
                "verdict": "PDF_ONLY",
                "pdf_holdown_id": "pdf_002",
                "revit_assembly_id": None,
                "mark": "H2",
                "pdf_point": {"x": 800, "y": 700},
                "reason": "No Revit partner found",
            },
            {
                "verdict": "REVIT_ONLY",
                "pdf_holdown_id": None,
                "revit_assembly_id": "rev_002",
                "mark": "H3",
                "revit_point_transformed_to_pdf": {"x": 3000, "y": 2000},  # Off-sheet
                "reason": "No PDF partner found",
            },
            {
                "verdict": "MATCH",
                "pdf_holdown_id": "pdf_003",
                "revit_assembly_id": "rev_003",
                "mark": "H1",
                "pdf_point": {"x": 1000, "y": 800},
                "revit_point_transformed_to_pdf": {"x": 1005, "y": 803},
                "distance_pdf_points": 5.8,
                "reason": "Match: 5.8pt apart",
            },
        ]
    }
    
    page_w, page_h = 2592.0, 1728.0  # S-201 dimensions
    items = build_review_items(synthetic_report, page_w, page_h)
    
    print("Self-check results:")
    print(f"  Total items: {items['counts']['total']}")
    print(f"  Drawable: {items['counts']['drawable']}")
    print(f"  Undrawable: {items['counts']['undrawable']}")
    print(f"  Undrawable IDs: {items['undrawable_ids']}")
    print(f"  By verdict: {items['counts']['by_verdict']}")
    
    # Verify specific cases
    loc_mm = next(i for i in items["items"] if i["verdict"] == "LOCATION_MISMATCH")
    assert loc_mm["drawable"], "LOC_MM should be drawable"
    assert loc_mm["box"]["color"] == RED, "LOC_MM should be red"
    assert loc_mm["connector"] is not None, "LOC_MM should have connector"
    
    pdf_only = next(i for i in items["items"] if i["verdict"] == "PDF_ONLY")
    assert pdf_only["drawable"], "PDF_ONLY should be drawable"
    assert pdf_only["box"]["color"] == BLUE, "PDF_ONLY should be blue"
    
    revit_only = next(i for i in items["items"] if i["verdict"] == "REVIT_ONLY")
    assert not revit_only["drawable"], "Off-sheet REVIT_ONLY should NOT be drawable"
    assert revit_only["id"] in items["undrawable_ids"], "Off-sheet should be in undrawable_ids"
    
    match = next(i for i in items["items"] if i["verdict"] == "MATCH")
    assert match["drawable"], "MATCH should be drawable"
    assert match["default_hidden"], "MATCH should be default_hidden"
    
    # Test SVG generation
    svg = build_overlay_svg(items, show_match=False)
    assert f'viewBox="0 0 {page_w} {page_h}"' in svg, "SVG viewBox should match page size"
    assert RED in svg, "SVG should contain red (LOC_MM)"
    assert BLUE in svg, "SVG should contain blue (PDF_ONLY)"
    assert "distance:" in svg, "SVG should contain distance labels"
    assert ORANGE not in svg, "Off-sheet REVIT_ONLY should not appear in SVG"
    assert GREEN not in svg, "MATCH should not appear when show_match=False"
    
    svg_with_match = build_overlay_svg(items, show_match=True)
    assert GREEN in svg_with_match, "MATCH should appear when show_match=True"
    
    print("✓ All self-check assertions passed")
