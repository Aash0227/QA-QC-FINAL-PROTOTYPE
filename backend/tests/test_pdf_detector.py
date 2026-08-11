"""Tests 6-8: PDF S-201 detection — baseline count, schedule exclusion, (2)H2 expansion."""
from pathlib import Path

import pytest

from app.s201_detector import (
    S201_TABLE_BBOXES,
    detect_s201_holdowns,
    locate_s201_page,
    summarize_focused_holdowns,
)

SAMPLE_PDF = Path(
    r"C:\Users\aashd\Downloads\wetransfer_madera-model-and-permit-sets_2026-05-13_1004"
    r"\STAMPED_10510 Madera Dr-DWG-20260122-D1.pdf"
)

pytestmark = pytest.mark.skipif(
    not SAMPLE_PDF.exists(), reason="Sample Madera STAMPED PDF not available."
)


@pytest.fixture(scope="module")
def detections():
    page_index = locate_s201_page(SAMPLE_PDF)
    assert page_index is not None
    return detect_s201_holdowns(pdf_path=SAMPLE_PDF, page_index=page_index)


def test_baseline_total_54(detections):
    """Test 8: Page Intelligence returns the known Madera baseline."""
    summary = summarize_focused_holdowns(detections)
    assert summary["total"] == 54
    assert summary["by_type"] == {"H1": 10, "H2": 21, "H3": 6, "H4": 17}


def _center(bbox):
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def _inside(bbox, region):
    cx, cy = _center(bbox)
    return region[0] <= cx <= region[2] and region[1] <= cy <= region[3]


def test_schedule_table_labels_excluded(detections):
    """Test 6: no detection originates from inside the S-201 schedule table regions."""
    for det in detections:
        bbox = det["bbox_pdf"]
        assert not any(_inside(bbox, region) for region in S201_TABLE_BBOXES), (
            f"Detection {det['id']} came from a schedule table region: {bbox}"
        )


def test_dual_holdown_expansion(detections):
    """Test 7: (2)H2 / 2 H2 style callouts expand into multiple physical instances."""
    dual = [d for d in detections if d["total_multiplicity"] == 2]
    assert dual, "Expected at least one dual hold-down case expanded into 2 instances."
    # Each dual group must contribute exactly two instances (indices 1 and 2).
    groups = {}
    for d in dual:
        groups.setdefault((d["raw_mark"], tuple(d["bbox_pdf"])), []).append(d["multiplicity_index"])
    for key, indices in groups.items():
        assert sorted(indices) == [1, 2], f"Dual group {key} did not expand to 2: {indices}"
