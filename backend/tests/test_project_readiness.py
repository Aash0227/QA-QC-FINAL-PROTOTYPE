"""A project must state whether it can actually produce an answer.

Three of six real projects were permanently unable to produce results while
every card was badged ACTIVE, and each layer inferred the situation
differently: the card listed "no Revit export" as one fact among several, the
pipeline reported "completed", and the AI agent said "run the pipeline first".
Readiness is computed once, on the backend, so every surface tells the user
the same story.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import config
from app.routers import projects as pr


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path)
    return tmp_path


def _make(root: Path, slug: str, *, pdf: bool, revit: bool, elements: int = 0) -> Path:
    d = root / slug
    d.mkdir(parents=True, exist_ok=True)
    manifest = {}
    if pdf:
        (d / "in.pdf").write_bytes(b"%PDF-1.4")
        manifest["pdf_path"] = str(d / "in.pdf")
    if revit:
        (d / "revit.json").write_text("{}", encoding="utf-8")
        manifest["revit_path"] = str(d / "revit.json")
    (d / config.ARTIFACT_FILES["project_manifest"]).write_text(
        json.dumps(manifest), encoding="utf-8")
    if elements:
        (d / config.ARTIFACT_FILES["element_list"]).write_text(
            json.dumps({"elements": [{"id": f"e{i}"} for i in range(elements)],
                        "sheets": ["S-1"]}), encoding="utf-8")
    return d


def test_missing_revit_export_is_incomplete_and_names_what_is_missing(workspace):
    """The real `madera` shape: PDF uploaded, Revit never supplied."""
    d = _make(workspace, "madera", pdf=True, revit=False)
    s = pr._summary(d, active=None)
    assert s["readiness"] == "incomplete"
    assert s["missing_inputs"] == ["revit"]


def test_missing_both_inputs_names_both(workspace):
    d = _make(workspace, "empty", pdf=False, revit=False)
    s = pr._summary(d, active=None)
    assert s["readiness"] == "incomplete"
    assert s["missing_inputs"] == ["pdf", "revit"]


def test_revit_only_project_is_incomplete_on_the_pdf(workspace):
    d = _make(workspace, "revit-only", pdf=False, revit=True)
    s = pr._summary(d, active=None)
    assert s["missing_inputs"] == ["pdf"]


def test_both_inputs_present_but_no_results_is_runnable(workspace):
    """Distinct from "ready": the pipeline CAN run, it just has not yet."""
    d = _make(workspace, "fresh", pdf=True, revit=True)
    s = pr._summary(d, active=None)
    assert s["readiness"] == "runnable"
    assert s["missing_inputs"] == []


def test_results_present_is_ready(workspace):
    d = _make(workspace, "done", pdf=True, revit=True, elements=3)
    s = pr._summary(d, active=None)
    assert s["readiness"] == "ready"
    assert s["missing_inputs"] == []


def test_results_win_even_if_an_input_file_was_since_removed(workspace):
    """A project that already produced results is ready to REVIEW, whatever
    happened to the source files afterwards -- the answers still exist."""
    d = _make(workspace, "archived", pdf=False, revit=False, elements=2)
    s = pr._summary(d, active=None)
    assert s["readiness"] == "ready"
