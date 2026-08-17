"""Unit tests for stage_graph.invalidate_downstream — artifact removal.

``invalidate_downstream`` returns the removed artifact KEYS (e.g. ``"ai_pdf"``),
which map to canonical filenames via ``config.ARTIFACT_FILES``. No HTTP, no
TestClient — only stage_graph + config (ARTIFACT_DIR monkeypatched)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import config, stage_graph

# All 7 output artifact keys (ordered as STAGES).
ALL_OUTPUT_KEYS = [s[3] for s in stage_graph.STAGES]
# Map key → canonical filename.
_FILENAME = {k: config.ARTIFACT_FILES[k] for k in ALL_OUTPUT_KEYS}


def _create_all(tmp: Path) -> list[Path]:
    """Write every stage output artifact as an empty dict, return their paths."""
    paths = []
    for key in ALL_OUTPUT_KEYS:
        p = config.artifact_path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}")
        paths.append(p)
    return paths


# ── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _scratch_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate artifact writes to a temp dir (follows the conftest pattern)."""
    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path)
    return tmp_path


# ── tests ───────────────────────────────────────────────────────────────


def test_invalidate_pdf_convert_removes_downstream_only(monkeypatch, tmp_path):
    """invalidate_downstream('pdf_convert') removes ai_pdf + 3 downstream
    artifacts, but keeps element_intelligence (upstream)."""
    _create_all(tmp_path)

    removed = set(stage_graph.invalidate_downstream("pdf_convert"))

    # pdf_convert's own output + every downstream output.
    assert removed == {"ai_pdf", "registration", "compare", "element_list"}
    # Upstream survivors — file still on disk:
    for key in ("element_intelligence", "ai_revit", "pdf_page_intelligence"):
        assert config.artifact_path(key).exists(), f"{key} should survive"


def test_invalidate_extract_removes_all_seven(monkeypatch, tmp_path):
    """invalidate_downstream('extract') removes every artifact."""
    paths = _create_all(tmp_path)

    removed = stage_graph.invalidate_downstream("extract")

    assert set(removed) == set(ALL_OUTPUT_KEYS)
    assert len(removed) == 7
    for p in paths:
        assert not p.exists(), f"{p.name} should be removed"


def test_returned_list_contains_only_removed_keys(monkeypatch, tmp_path):
    """The returned list names only what was actually on disk (not
    theoretical): element_list is reported only if its file existed."""
    # Create only 4 of 7 artifacts.
    for key in ("element_intelligence", "ai_pdf", "registration", "compare"):
        p = config.artifact_path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}")

    removed = set(stage_graph.invalidate_downstream("pdf_convert"))

    assert removed == {"ai_pdf", "registration", "compare"}
    # element_list was never on disk → not in returned list, and its file
    # (absent) stays absent.
    assert "element_list" not in removed
    assert not config.artifact_path("element_list").exists()


def test_unknown_stage_returns_empty(monkeypatch, tmp_path):
    """An unknown stage key falls off the DOWNSTREAM dict safely."""
    _create_all(tmp_path)
    removed = stage_graph.invalidate_downstream("nonexistent_stage")
    assert removed == []