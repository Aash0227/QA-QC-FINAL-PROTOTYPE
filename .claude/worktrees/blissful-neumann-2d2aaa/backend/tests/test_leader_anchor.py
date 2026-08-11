"""Leader-dot anchor snap tests: a holdown callout re-anchors to the dot its
leader points at; without a proven leader the label point never moves."""

from __future__ import annotations

import math
from pathlib import Path

import fitz
import pytest

from app import leader_anchor


@pytest.fixture()
def leader_pdf(tmp_path: Path) -> Path:
    """One page: 'H1' label at (100,100), leader to a filled dot at (135,129),
    plus an orphan label at (300,300) with no leader."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((100, 100), "H1", fontsize=10)
    shape = page.new_shape()
    shape.draw_line(fitz.Point(108, 104), fitz.Point(133, 127))
    shape.finish(width=0.5)
    shape.draw_circle(fitz.Point(135, 129), 2.0)
    shape.finish(fill=(0, 0, 0))
    shape.commit()
    out = tmp_path / "leader.pdf"
    doc.save(out)
    doc.close()
    return out


def test_snap_holdowns_moves_to_dot(leader_pdf: Path) -> None:
    ai = {"holdowns": [{"id": "t1", "page_index": 0,
                        "center_point": {"x": 105.0, "y": 103.0, "space": "pdf_page"}}]}
    out = leader_anchor.snap_holdowns(ai, leader_pdf)
    h = out["holdowns"][0]
    assert h["anchor"] == "leader_dot"
    assert math.hypot(h["center_point"]["x"] - 135, h["center_point"]["y"] - 129) < 3
    assert h["label_point"] == {"x": 105.0, "y": 103.0}
    assert h["center_point"]["space"] == "pdf_page"  # extra keys preserved
    assert out["leader_anchor"]["snapped"] == 1


def test_no_leader_no_move(leader_pdf: Path) -> None:
    ai = {"holdowns": [{"id": "t2", "page_index": 0,
                        "center_point": {"x": 300.0, "y": 300.0}}]}
    out = leader_anchor.snap_holdowns(ai, leader_pdf)
    assert "anchor" not in out["holdowns"][0]
    assert out["holdowns"][0]["center_point"]["x"] == 300.0
    assert out["leader_anchor"]["kept"] == 1


def test_snap_element_marks_generic_shape(leader_pdf: Path) -> None:
    intel = {"sheets": [{"sheet_number": "S-205", "page_index": 0, "marks": [
        {"id": "m1", "category": "holdown", "center_pdf": [105.0, 103.0]},
        {"id": "m2", "category": "post", "center_pdf": [105.0, 103.0]},   # not holdown
    ]}]}
    out = leader_anchor.snap_element_marks(intel, leader_pdf)
    m1, m2 = out["sheets"][0]["marks"]
    assert m1["anchor"] == "leader_dot"
    assert math.hypot(m1["center_pdf"][0] - 135, m1["center_pdf"][1] - 129) < 3
    assert m1["label_point"] == [105.0, 103.0]
    assert "anchor" not in m2                       # non-holdown untouched
    assert out["leader_anchor"]["snapped"] == 1


def test_missing_pdf_is_honest(tmp_path: Path) -> None:
    ai = {"holdowns": [{"id": "t", "page_index": 0, "center_point": {"x": 1, "y": 1}}]}
    out = leader_anchor.snap_holdowns(ai, tmp_path / "nope.pdf")
    assert out["leader_anchor"]["note"]
    assert "anchor" not in out["holdowns"][0]
