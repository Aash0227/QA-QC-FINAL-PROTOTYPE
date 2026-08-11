"""Generic hold-down page intelligence for non-Madera drawing sets.

The frozen S-201 path (pdf_intelligence.run_page_intelligence) stays the
default. When it can't find an S-201 foundation plan (a different client's
sheet numbering / mark family), this module derives everything the frozen
detector needs from the generalized extraction artifact instead:

  - which sheet is the hold-down-densest foundation plan
  - the mark alternation (learned vocabulary + plan-detected holdown marks)
  - the schedule-table bboxes to mask (discovered, not hardcoded)

and calls s201_detector with its additive parameters. Same artifact schema as
the frozen path, so RANSAC/compare consume it unchanged. No fake data: if no
sheet has hold-down marks, the error artifact says so.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config
from .s201_detector import detect_s201_holdowns, summarize_focused_holdowns

SCHEMA_VERSION = "pdf-page-intelligence/1.0"
TITLE_STRIP_FRACTION = 0.12  # keep in sync with element_detector


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def choose_foundation_sheet(element_intelligence: dict[str, Any]) -> dict[str, Any] | None:
    """Sheet with the most plan hold-down marks (ties: lowest page index)."""
    best = None
    for sheet in element_intelligence.get("sheets", []):
        n = sum(1 for m in sheet.get("marks", []) if m["category"] == "holdown")
        if n and (best is None or n > best[0]):
            best = (n, sheet)
    return best[1] if best else None


def _mark_alternation(element_intelligence: dict[str, Any], sheet: dict[str, Any]) -> str:
    marks: set[str] = set(element_intelligence.get("vocabulary", {}).get("holdown", []))
    marks.update(
        m["mark"] for m in sheet.get("marks", []) if m["category"] == "holdown"
    )
    return "|".join(re.escape(m) for m in sorted(marks))


def run_generic_page_intelligence(
    pdf_path: str | Path, element_intelligence: dict[str, Any]
) -> dict[str, Any]:
    pdf_path = Path(pdf_path)
    sheet = choose_foundation_sheet(element_intelligence)
    if sheet is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": _now_iso(),
            "source_file": str(pdf_path),
            "sheet_number": None,
            "page_index": None,
            "detector": "generic_holdown_detector",
            "error": "No sheet with hold-down plan marks found by extraction. "
                     "Teach the AI this client's hold-down convention, then re-run Extract.",
            "holdowns": [],
            "summary": {"total": 0, "by_type": {}},
        }

    mark_pattern = _mark_alternation(element_intelligence, sheet)
    page_index = sheet["page_index"]
    width, height = sheet["page_size_pt"]
    plan_bbox = (0.0, 0.0, width * (1.0 - TITLE_STRIP_FRACTION), height)
    table_bboxes = [tuple(t["bbox"]) for t in sheet.get("tables", []) if t.get("bbox")]

    detections = detect_s201_holdowns(
        pdf_path=pdf_path,
        page_index=page_index,
        sheet_number=sheet["sheet_number"],
        evidence_dir=config.EVIDENCE_DIR,
        mark_pattern=mark_pattern,
        table_bboxes=table_bboxes,
        plan_bbox=plan_bbox,
    )
    summary = summarize_focused_holdowns(detections)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "source_file": str(pdf_path),
        "sheet_number": sheet["sheet_number"],
        "page_index": page_index,
        "detector": "generic_holdown_detector",
        "mark_pattern": mark_pattern,
        "notes": [
            "Sheet + mark family derived from generalized extraction (schedule vocabulary).",
            "Schedule-table regions discovered by header text and masked.",
            "Each plan mark is a physical instance; (2)HD2 expands to two.",
        ],
        "holdowns": detections,
        "summary": summary,
    }


if __name__ == "__main__":
    ei = {
        "vocabulary": {"holdown": ["HD1", "HD2"]},
        "sheets": [
            {"sheet_number": "S7", "page_index": 85, "page_size_pt": [2592, 1728],
             "tables": [{"bbox": [100, 100, 300, 300]}],
             "marks": [{"category": "holdown", "mark": "HD3"},
                       {"category": "holdown", "mark": "HD1"},
                       {"category": "steel_column", "mark": "C-1"}]},
            {"sheet_number": "S3", "page_index": 81, "page_size_pt": [2592, 1728],
             "tables": [], "marks": [{"category": "holdown", "mark": "HD1"}]},
        ],
    }
    s = choose_foundation_sheet(ei)
    assert s["sheet_number"] == "S7", s
    alt = _mark_alternation(ei, s)
    assert alt == "HD1|HD2|HD3", alt
    assert choose_foundation_sheet({"sheets": []}) is None
    print("generic_page_intelligence self-check OK:", alt)
