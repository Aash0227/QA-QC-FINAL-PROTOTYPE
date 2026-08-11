"""Tests for the teach-the-AI memory engine and its effect on extraction."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import config, element_detector, schedule_tables, teach


@pytest.fixture(autouse=True)
def tmp_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path)
    monkeypatch.setattr(config, "MEMORY_DIR", tmp_path / "memory")
    active_project_file = tmp_path / "active_project.json"
    active_project_file.write_text('{"slug": "test-project"}', encoding="utf-8")
    monkeypatch.setattr(config, "ACTIVE_PROJECT_FILE", active_project_file)
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")  # force fallback path
    return tmp_path


def w(x0: float, y: float, text: str, width: float = 20.0, h: float = 8.0) -> tuple:
    return (x0, y, x0 + width, y + h, text, 0, 0, 0)


def test_fallback_alias_rule_saved_and_round_trips() -> None:
    result = teach.teach("in this pdf HD3 means H3")
    assert result["entry"]["rule"] == {
        "kind": "mark_alias", "category": "holdown", "token": "HD3",
        "maps_to": "H3", "regex": None,
    }
    assert "Got it" in result["reply"]
    memory = teach.load_memory()
    assert len(memory["entries"]) == 1
    assert memory["entries"][0]["instruction"] == "in this pdf HD3 means H3"


def test_unparseable_message_becomes_honest_note() -> None:
    result = teach.teach("the client uses a weird legend")
    assert result["entry"]["rule"]["kind"] == "note"
    assert "won't change extraction" in result["reply"]
    # notes produce no overrides
    assert teach.build_overrides() == {"headers": {}, "mark_patterns": {}, "aliases": {},
                                       "excludes": {}}


def test_delete_entry() -> None:
    entry = teach.teach("HD3 means H3")["entry"]
    assert teach.delete_entry(entry["id"]) is True
    assert teach.load_memory()["entries"] == []
    assert teach.delete_entry("mem_999") is False


def test_taught_alias_changes_mark_detection() -> None:
    teach.teach("HD3 means H3")
    overrides = teach.build_overrides()
    vocab = {"holdown": {"H3": {}}}
    marks = element_detector.detect_marks(
        [w(400, 300, "HD3")], vocab, [], 2592, 1728, "S-201", overrides
    )
    assert len(marks) == 1
    m = marks[0]
    assert m["category"] == "holdown" and m["mark"] == "H3"
    assert m["schedule_listed"] is True          # H3 is in the learned vocab
    assert m["taught_by"] == teach.load_memory()["entries"][0]["id"]
    # Without overrides the HD family is still recognized as a holdown (built-in
    # families now include HD/HDU/HTT/TD) but honestly NOT schedule-listed and
    # NOT aliased to H3 — the teaching is what maps it into the vocabulary.
    untaught = element_detector.detect_marks([w(400, 300, "HD3")], vocab, [], 2592, 1728, "S-201")
    assert len(untaught) == 1
    assert untaught[0]["mark"] == "HD3" and untaught[0]["schedule_listed"] is False
    assert untaught[0]["taught_by"] is None


def test_exclude_fallback_parse_and_reply() -> None:
    result = teach.teach("exclude H6, it's a dummy placement")
    assert result["entry"]["rule"] == {
        "kind": "exclude", "category": "holdown", "token": "H6",
        "maps_to": None, "regex": None,
    }
    assert "excluded from extraction and comparison" in result["reply"]


def test_build_overrides_emits_excludes() -> None:
    teach.teach("ignore H6")
    ov = teach.build_overrides()
    assert ov["excludes"]["H6"]["category"] == "holdown"
    assert ov["excludes"]["H6"]["taught_by"] == teach.load_memory()["entries"][0]["id"]


def test_excluded_mark_dropped_from_detection() -> None:
    teach.teach("exclude H6 holdowns, they are dummy placements")
    overrides = teach.build_overrides()
    vocab = {"holdown": {"H3": {}, "H6": {}}}
    marks = element_detector.detect_marks(
        [w(400, 300, "H6"), w(450, 300, "H3")], vocab, [], 2592, 1728, "S-201", overrides
    )
    # H6 is dropped entirely; H3 still detected and schedule-listed.
    assert [m["mark"] for m in marks] == ["H3"]
    assert marks[0]["schedule_listed"] is True


def test_taught_header_classifies_unknown_table() -> None:
    teach.add_entry(
        "stud schedule is the post table",
        {"kind": "category_header", "category": "post",
         "token": None, "maps_to": None, "regex": r"STUD\s+SCHEDULE"},
        "ok",
    )
    words = [
        w(1800, 100, "STUD"), w(1845, 100, "SCHEDULE"),
        w(1760, 120, "MARK"), w(1830, 120, "SIZE"),
        w(1760, 140, "P-1"), w(1830, 140, "600S162"),
    ]
    tables = schedule_tables.discover_tables(words, teach.build_overrides())
    assert tables[0]["category"] == "post"
    assert schedule_tables.learned_vocabulary(tables) == {"post": {"P-1": tables[0]["rows"][0]["cells"]}}
    # untaught, the same table is 'unknown' and teaches nothing
    plain = schedule_tables.discover_tables(words)
    assert plain[0]["category"] == "unknown"


def test_unrecognized_report() -> None:
    ei = {
        "sheets": [
            {
                "sheet_number": "S-202",
                "count_consistency": [
                    {"category": "steel_column", "mark": "C-4", "plan_count": 5,
                     "schedule_listed": False},
                    {"category": "post", "mark": "P-9", "plan_count": 0,
                     "schedule_listed": True},
                    {"category": "holdown", "mark": "H1", "plan_count": 10,
                     "schedule_listed": True},
                ],
                "tables": [{"category": "unknown", "header_text": "FOUNDATION SCHEDULE"}],
            }
        ]
    }
    items = teach.unrecognized_report(ei)
    types = {i["type"] for i in items}
    # BUG-10: unknown tables aggregate into ONE item, not one-per-table.
    assert types == {"plan_mark_not_in_schedule", "schedule_mark_zero_plan", "unknown_tables"}
    agg = next(i for i in items if i["type"] == "unknown_tables")
    assert agg["count"] == len(agg["tables"]) >= 1
    c4 = next(i for i in items if i.get("mark") == "C-4")
    assert "missing from every schedule" in c4["hint"]
