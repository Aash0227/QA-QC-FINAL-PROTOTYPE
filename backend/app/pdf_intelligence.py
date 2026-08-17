from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz

from . import config
from .s201_detector import (
    detect_s201_holdowns,
    locate_s201_page,
    summarize_focused_holdowns,
)

SCHEMA_VERSION = "pdf-page-intelligence/1.0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _detect_sheet_number(pdf_path: Path, page_index: int) -> str | None:
    """Extract the actual sheet number from the located page text.

    Looks for a sheet-number pattern (e.g. S-201, S-101, A-5) on the page.
    Returns None when no pattern is found — never guesses 'S-201'.
    """
    try:
        doc = fitz.open(str(pdf_path))
        try:
            if page_index < len(doc):
                text = doc[page_index].get_text("text")
                # Match common sheet number patterns: S-201, A-101, M-5, etc.
                match = re.search(r"\b([A-Z]-?\d{2,4})\b", text)
                if match:
                    return match.group(1)
        finally:
            doc.close()
    except Exception:
        pass
    return None


def run_page_intelligence(pdf_path: str | Path) -> dict[str, Any]:
    """S-201 focused Page Intelligence.

    Reuses the proven focused detector so that schedule-table H labels are excluded,
    plan marks are treated as physical instances, and `(2)H2` is expanded into two
    instances. The sheet number is dynamically detected from the page text.
    """
    pdf_path = Path(pdf_path)
    page_index = locate_s201_page(pdf_path)
    if page_index is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": _now_iso(),
            "source_file": str(pdf_path),
            "sheet_number": None,
            "page_index": None,
            "error": "Could not locate the foundation-plan page in the PDF.",
            "holdowns": [],
            "summary": {"total": 0, "by_type": {}},
        }

    # Dynamically detect the actual sheet number from the located page.
    sheet_number = _detect_sheet_number(pdf_path, page_index)

    detections = detect_s201_holdowns(
        pdf_path=pdf_path,
        page_index=page_index,
        sheet_number=sheet_number,
        evidence_dir=config.EVIDENCE_DIR,
    )
    summary = summarize_focused_holdowns(detections)

    # Load project-specific baseline if available; otherwise no baseline check.
    from .compare import _project_pdf_baseline
    project_baseline = _project_pdf_baseline()
    # Strip the "total" key if present for per-mark comparison.
    if project_baseline:
        baseline_marks = {k: v for k, v in project_baseline.items() if k != "total"}
    else:
        baseline_marks = None

    # Generic count consistency: schedule counts vs plan counts (no hardcoded baseline).
    schedule_total = sum(1 for d in detections if d.get("schedule_type_raw"))
    plan_total = summary.get("total", 0)

    result = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "source_file": str(pdf_path),
        "sheet_number": sheet_number,
        "page_index": page_index,
        "detector": "s201_focused_holdown_detector",
        "notes": [
            "Schedule-table H labels are excluded via table-region masking.",
            "Each plan mark is a physical instance; multiplicity markers expand to multiple.",
            "PDF coordinates are 2D page points; no true Revit Z is available.",
        ],
        "holdowns": detections,
        "summary": summary,
        "count_consistency": {
            "schedule_entries": schedule_total,
            "plan_instances": plan_total,
            "note": "Schedule entries vs plan instances (project-specific baseline checked separately).",
        },
    }
    if sheet_number is None:
        # Honest gap: no sheet-number pattern on the page, no S-201 guess.
        result["notes"].append(
            "No sheet-number pattern found on the page; sheet_number is None."
        )

    if baseline_marks:
        result["expected_baseline"] = baseline_marks
        result["matches_expected_baseline"] = (
            summary.get("by_type") == baseline_marks
            and summary.get("total") == sum(baseline_marks.values())
        )

    return result
