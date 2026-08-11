"""Tests for generic schedule-table discovery + multi-category mark detection."""

from __future__ import annotations

import pytest

from app import element_detector, schedule_tables


def w(x0: float, y: float, text: str, width: float = 40.0, h: float = 8.0) -> tuple:
    return (x0, y, x0 + width, y + h, text, 0, 0, 0)


SYNTH_POST_TABLE = [
    w(1800, 100, "POST"), w(1845, 100, "SCHEDULE"), w(1895, 100, "SPECIFICATION"),
    w(1760, 120, "MARK"), w(1830, 120, "SIZE", 30), w(1865, 120, "&", 8),
    w(1878, 120, "SPACING", 45), w(1960, 120, "GRADE"),
    w(1760, 140, "P-1"), w(1830, 140, "(2)"), w(1855, 140, "600S162-43MIL"),
    w(1960, 140, "50", 15), w(1978, 140, "KSI", 20),
    w(1760, 160, "P-2"), w(1830, 160, "(4)"), w(1855, 160, "600S162-43MIL"),
    w(1960, 160, "50", 15), w(1978, 160, "KSI", 20),
    w(1830, 172, "(BOXED)"), w(1875, 172, "POST"),
    w(1760, 190, "NOTE:"), w(1805, 190, "ignore"),
]


def test_header_found_and_rows_parsed() -> None:
    tables = schedule_tables.discover_tables(SYNTH_POST_TABLE)
    assert len(tables) == 1
    t = tables[0]
    assert t["category"] == "post"
    assert [r["mark"] for r in t["rows"]] == ["P-1", "P-2"]
    # wrapped continuation merged into P-2
    assert "(BOXED) POST" in t["rows"][1]["cells"]["row_text"]
    # bbox spans header to last row
    assert t["bbox"][1] <= 100 and t["bbox"][3] >= 172


def test_vocabulary_learned_from_mark_column() -> None:
    vocab = schedule_tables.learned_vocabulary(
        schedule_tables.discover_tables(SYNTH_POST_TABLE)
    )
    assert set(vocab["post"]) == {"P-1", "P-2"}


def test_unknown_schedule_teaches_no_marks() -> None:
    words = [
        w(100, 100, "FOUNDATION"), w(160, 100, "SCHEDULE"),
        w(100, 120, "MARK"), w(160, 120, "SIZE"),
        w(100, 140, "F-1"), w(160, 140, "4'x4'"),
    ]
    tables = schedule_tables.discover_tables(words)
    assert tables and tables[0]["category"] == "unknown"
    assert schedule_tables.learned_vocabulary(tables) == {}


def test_header_run_does_not_sprawl_over_plan_text() -> None:
    # Plan text at the same y as the header must not widen the header bbox.
    words = [w(100, 100, "GARAGE"), *SYNTH_POST_TABLE]
    headers = schedule_tables.find_schedule_headers(words)
    assert len(headers) == 1
    assert headers[0]["header_bbox"][0] >= 1700


def test_detect_marks_vocab_filters_and_expansion() -> None:
    vocab = {"shear_wall": {"SW-1": {}}, "post": {"P-1": {}}}
    words = [
        w(400, 300, "SW-1"),
        w(600, 500, "(2)"), w(625, 500, "P-1"),
        w(700, 700, "C-4"),
        w(900, 900, "5/S-501"),
        w(2500, 400, "SW-1"),       # title strip
        w(120, 118, "P-1"),         # inside table bbox
    ]
    marks = element_detector.detect_marks(
        words, vocab, [[100, 100, 200, 140]], 2592, 1728, "S-202"
    )
    by_mark: dict[str, list] = {}
    for m in marks:
        by_mark.setdefault(m["mark"], []).append(m)
    assert len(by_mark["SW-1"]) == 1 and by_mark["SW-1"][0]["schedule_listed"]
    assert len(by_mark["P-1"]) == 2 and by_mark["P-1"][1]["expanded_synthetic"]
    assert not by_mark["C-4"][0]["schedule_listed"]  # plan mark not in any schedule
    assert "5/S-501" not in by_mark


def test_count_consistency_surfaces_zero_plan_hits() -> None:
    vocab = {"steel_column": {"C-1": {}}}
    marks = element_detector.detect_marks(
        [w(700, 700, "C-4")], vocab, [], 2592, 1728, "S-202"
    )
    cc = element_detector._count_consistency(marks, vocab)
    zero = next(r for r in cc if r["mark"] == "C-1")
    assert zero["plan_count"] == 0 and zero["schedule_listed"]
    c4 = next(r for r in cc if r["mark"] == "C-4")
    assert c4["plan_count"] == 1 and not c4["schedule_listed"]


def test_sheet_number_prefers_title_block() -> None:
    words = [w(2540, 1700, "S-202", 30, 14), w(2540, 200, "S-501", 20, 8)]
    assert element_detector.detect_sheet_number(words, 2592) == "S-202"
    assert element_detector.detect_sheet_number([w(100, 100, "S-202")], 2592) is None
