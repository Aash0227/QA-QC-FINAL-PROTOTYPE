from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config
from .s201_detector import (
    detect_s201_holdowns,
    locate_s201_page,
    summarize_focused_holdowns,
)

SCHEMA_VERSION = "pdf-page-intelligence/1.0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_page_intelligence(pdf_path: str | Path) -> dict[str, Any]:
    """S-201 focused Page Intelligence.

    Reuses the proven focused detector so that schedule-table H labels are excluded,
    plan marks are treated as physical instances, and `(2)H2` is expanded into two
    instances. Reproduces the Madera baseline H1=10, H2=21, H3=6, H4=17, total=54.
    """
    pdf_path = Path(pdf_path)
    page_index = locate_s201_page(pdf_path)
    if page_index is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at": _now_iso(),
            "source_file": str(pdf_path),
            "sheet_number": "S-201",
            "page_index": None,
            "error": "Could not locate the S-201 foundation-plan page in the PDF.",
            "holdowns": [],
            "summary": {"total": 0, "by_type": {}},
        }

    detections = detect_s201_holdowns(
        pdf_path=pdf_path,
        page_index=page_index,
        sheet_number="S-201",
        evidence_dir=config.EVIDENCE_DIR,
    )
    summary = summarize_focused_holdowns(detections)
    baseline = {"H1": 10, "H2": 21, "H3": 6, "H4": 17}
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "source_file": str(pdf_path),
        "sheet_number": "S-201",
        "page_index": page_index,
        "detector": "s201_focused_holdown_detector",
        "notes": [
            "Schedule-table H labels are excluded via table-region masking.",
            "Each plan H1-H4 label is a physical instance; (2)H2 / 2 H2 expand to two.",
            "PDF coordinates are 2D page points; no true Revit Z is available.",
        ],
        "holdowns": detections,
        "summary": summary,
        "expected_baseline": baseline,
        "matches_expected_baseline": summary.get("by_type") == baseline
        and summary.get("total") == 54,
    }
