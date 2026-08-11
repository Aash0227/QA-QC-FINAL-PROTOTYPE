"""Benchmark Autopilot state machine tests (AUTOPILOT_PLAN.md P3)."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from fastapi import HTTPException

from app import benchmark_workflow as bw
from app import config, main


@pytest.fixture()
def tmp_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path)
    monkeypatch.setattr(config, "EVIDENCE_DIR", tmp_path / "evidence")
    return tmp_path


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------
def test_happy_path_walks_every_state() -> None:
    wf = bw.default_state()
    path = [
        "proposing", "awaiting_pdf_approval", "stamping", "awaiting_revit",
        "placing_markers", "awaiting_revit_approval", "awaiting_export",
        "calibrating", "done",
    ]
    for state in path:
        bw.transition(wf, state, actor="test")
    assert wf["state"] == "done"
    assert [h["to"] for h in wf["history"]] == path
    # audit trail: every entry carries ts + actor + from
    assert all(h["ts"] and h["actor"] == "test" and h["from"] for h in wf["history"])


def test_invalid_transitions_rejected() -> None:
    wf = bw.default_state()
    with pytest.raises(ValueError):
        bw.transition(wf, "done", actor="test")          # idle -> done
    with pytest.raises(ValueError):
        bw.transition(wf, "stamping", actor="test")      # skip approval gate
    with pytest.raises(ValueError):
        bw.transition(wf, "nonsense", actor="test")      # unknown state
    assert wf["state"] == "idle" and wf["history"] == []  # nothing recorded


def test_approve_required_before_advance() -> None:
    """From awaiting_pdf_approval the ONLY ways forward are the approval gate
    (-> stamping) or failure. The agent's post-approval step is illegal."""
    wf = bw.default_state()
    bw.transition(wf, "proposing", "agent")
    bw.transition(wf, "awaiting_pdf_approval", "agent")
    required, to_state = bw.ADVANCE_STEPS["stamped"]
    assert wf["state"] != required                      # endpoint 409s on this
    with pytest.raises(ValueError):
        bw.transition(wf, to_state, "agent")            # and the edge is illegal
    # approval gate points where the plan says
    assert bw.APPROVAL_GATES["awaiting_pdf_approval"] == "stamping"
    assert bw.APPROVAL_GATES["awaiting_revit_approval"] == "awaiting_export"


def test_reject_fails_and_can_restart() -> None:
    wf = bw.default_state()
    bw.transition(wf, "proposing", "agent")
    bw.transition(wf, "awaiting_pdf_approval", "agent")
    bw.transition(wf, "failed", "human", note="Wrong intersections.")
    assert wf["state"] == "failed"
    bw.transition(wf, "proposing", "agent")             # restart allowed
    assert wf["state"] == "proposing"


def test_persistence_round_trip(tmp_artifacts: Path) -> None:
    wf = bw.default_state()
    bw.transition(wf, "proposing", "agent", payload={"k": 1})
    bw.save(wf)
    loaded = bw.load()
    assert loaded["state"] == "proposing"
    assert loaded["history"][0]["payload"] == {"k": 1}
    assert (tmp_artifacts / "benchmark_workflow.json").exists()


def test_load_defaults_to_idle(tmp_artifacts: Path) -> None:
    assert bw.load()["state"] == "idle"


# ---------------------------------------------------------------------------
# Proposal geometry
# ---------------------------------------------------------------------------
def _pt(pid: str, x: float, y: float) -> dict:
    return {"id": pid, "label": pid, "point": {"x": x, "y": y}}


def test_pick_max_diagonal_pair() -> None:
    pts = [_pt("a", 0, 0), _pt("b", 10, 0), _pt("c", 0, 10), _pt("d", 7, 7)]
    a, b, d = bw.pick_max_diagonal_pair(pts)
    assert {a["id"], b["id"]} == {"b", "c"}
    assert abs(d - math.hypot(10, 10)) < 1e-9
    assert bw.pick_max_diagonal_pair([_pt("a", 0, 0)]) is None


def test_propose_joins_by_id_and_picks_max_diagonal() -> None:
    # PDF has 3 intersections; Revit only knows 3 (one PDF id unmatched).
    pdf = [_pt("grid_A_1", 100, 100), _pt("grid_A_3", 100, 900),
           _pt("grid_C_1", 800, 100), _pt("grid_X_9", 5000, 5000)]
    rev = [_pt("grid_A_1", 0, 0), _pt("grid_A_3", 0, 40),
           _pt("grid_C_1", 55, 0)]
    prop = bw.propose_from_geometry(pdf, rev, "S-201", 4)
    ids = {b["grid_id"] for b in prop["benchmarks"]}
    assert ids == {"grid_A_3", "grid_C_1"}              # max PDF diagonal, joined only
    assert prop["candidates_considered"] == 3           # grid_X_9 excluded
    # BM-1 deterministic: smaller revit x first
    assert prop["benchmarks"][0]["mark"] == "BM-1"
    assert prop["benchmarks"][0]["grid_id"] == "grid_A_3"
    assert prop["benchmarks"][0]["revit_point_ft"] == {"x": 0, "y": 40}
    assert prop["separation_revit_ft"] == round(math.hypot(55, 40), 2)


# ---------------------------------------------------------------------------
# §3 "Pick manually": propose_from_points (user-picked pair)
# ---------------------------------------------------------------------------
def _manual_setup() -> tuple[list[dict], list[dict]]:
    pdf = [_pt("grid_A_1", 100, 100), _pt("grid_A_3", 100, 900),
           _pt("grid_C_1", 800, 100)]
    rev = [_pt("grid_A_1", 0, 0), _pt("grid_A_3", 0, 40),
           _pt("grid_C_1", 55, 0)]
    return pdf, rev


def test_propose_from_points_honors_user_marks() -> None:
    pdf, rev = _manual_setup()
    # User picks the near pair (NOT the max diagonal) and names them explicitly.
    prop = bw.propose_from_points(
        pdf, rev,
        [{"grid_id": "grid_A_1", "mark": "BM-1"},
         {"grid_id": "grid_C_1", "mark": "BM-2"}],
        "S-201", 4,
    )
    assert [b["grid_id"] for b in prop["benchmarks"]] == ["grid_A_1", "grid_C_1"]
    assert prop["benchmarks"][0]["mark"] == "BM-1"       # user order preserved
    assert prop["benchmarks"][0]["pdf_point_pt"] == {"x": 100, "y": 100}
    assert prop["benchmarks"][1]["revit_point_ft"] == {"x": 55, "y": 0}
    assert prop["separation_revit_ft"] == round(math.hypot(55, 0), 2)
    assert prop["candidates_considered"] == 3


def test_propose_from_points_rejects_unknown_grid() -> None:
    pdf, rev = _manual_setup()
    with pytest.raises(ValueError, match="grid_Z_9"):
        bw.propose_from_points(
            pdf, rev,
            [{"grid_id": "grid_A_1", "mark": "BM-1"},
             {"grid_id": "grid_Z_9", "mark": "BM-2"}],
            "S-201", 4,
        )


def test_propose_from_points_rejects_bad_marks_and_count() -> None:
    pdf, rev = _manual_setup()
    with pytest.raises(ValueError, match="exactly 2"):
        bw.propose_from_points(
            pdf, rev, [{"grid_id": "grid_A_1", "mark": "BM-1"}], "S-201", 4
        )
    with pytest.raises(ValueError, match="BM-1 and BM-2"):
        bw.propose_from_points(
            pdf, rev,
            [{"grid_id": "grid_A_1", "mark": "BM-1"},
             {"grid_id": "grid_C_1", "mark": "BM-9"}],
            "S-201", 4,
        )
    with pytest.raises(ValueError, match="different"):
        bw.propose_from_points(
            pdf, rev,
            [{"grid_id": "grid_A_1", "mark": "BM-1"},
             {"grid_id": "grid_A_1", "mark": "BM-2"}],
            "S-201", 4,
        )


def _word(x: float, y: float, t: str) -> tuple:
    return (x - 4, y - 4, x + 4, y + 4, t, 0, 0, 0)


def test_bubble_row_fallback_beats_band_noise() -> None:
    """Madera S-201 pattern: real bubbles 1/2/3 share one top row; noise
    '1'/'2'/'3' words scatter through the bands. The row wins; the noise
    never forms a >=2-unique-label cluster."""
    words = [
        _word(300, 125, "1"), _word(667, 125, "2"), _word(922, 125, "3"),
        # noise in bands, scattered ys/xs
        _word(810, 222, "1"), _word(1815, 1515, "1"), _word(1983, 1573, "3"),
        _word(1816, 1534, "2"), _word(1815, 1554, "3"),
        # letters: one bubble each in the left column
        _word(95, 255, "A"), _word(94, 319, "B"), _word(95, 520, "C"),
    ]
    v, h = bw.bubble_row_positions(words, 2592, 1728, {"1", "2", "3", "A", "B", "C"})
    assert v == {"1": 300, "2": 667, "3": 922}
    assert h == {"A": 255, "B": 319, "C": 520}


def test_bubble_row_fallback_honest_when_ambiguous() -> None:
    # A row where label '1' appears twice -> '1' not unique, cluster is only
    # {'2'} -> below the >=2 minimum, nothing detected.
    words = [_word(100, 50, "1"), _word(300, 52, "1"), _word(500, 51, "2")]
    v, h = bw.bubble_row_positions(words, 2592, 1728, {"1", "2"})
    assert v == {} and h == {}


def test_propose_needs_two_joined_points() -> None:
    with pytest.raises(ValueError):
        bw.propose_from_geometry(
            [_pt("grid_A_1", 0, 0)], [_pt("grid_A_1", 0, 0)], "S-201", 4
        )
    with pytest.raises(ValueError):
        bw.propose_from_geometry(
            [_pt("grid_A_1", 0, 0), _pt("grid_B_2", 9, 9)],
            [_pt("grid_Z_9", 1, 1)], "S-201", 4,
        )


# ---------------------------------------------------------------------------
# BUG-01: axis-agnostic grid resolver
# ---------------------------------------------------------------------------
def _rev(gid: str) -> dict:
    return {"id": gid, "label": gid, "point": {"x": 0.0, "y": 0.0}}


def test_resolve_grid_points_letters_vertical():
    """Madera-style: letters share x (a left column), numbers share y (top row)."""
    rev = [_rev(f"grid_{L}_{N}") for L in "AC" for N in "12"]
    words = [
        _word(100, 100, "A"), _word(100, 300, "C"),   # column: horizontal lines -> y
        _word(200, 50, "1"), _word(400, 50, "2"),     # row: vertical lines -> x
    ]
    pts = bw.resolve_pdf_grid_points(words, rev)
    got = {p["id"]: (p["point"]["x"], p["point"]["y"]) for p in pts}
    assert got == {
        "grid_A_1": (200, 100), "grid_A_2": (400, 100),
        "grid_C_1": (200, 300), "grid_C_2": (400, 300),
    }


def test_resolve_grid_points_axis_inverted():
    """Dogwood-style INVERTED: numbers share x (column), letters share y (row).
    The resolver must not care which is which — same intersections result."""
    rev = [_rev(f"grid_{L}_{N}") for L in "AB" for N in "12"]
    words = [
        _word(500, 100, "1"), _word(500, 400, "2"),   # numbers column -> y
        _word(700, 60, "A"), _word(900, 60, "B"),     # letters row -> x
    ]
    pts = bw.resolve_pdf_grid_points(words, rev)
    ids = {p["id"] for p in pts}
    assert ids == {"grid_A_1", "grid_A_2", "grid_B_1", "grid_B_2"}


# ---------------------------------------------------------------------------
# BUG-05: UniqueId decode
# ---------------------------------------------------------------------------
def test_unique_id_decode_roundtrip():
    from app import revit_ids
    uid = revit_ids._make_unique_id("bcb941f0c3f9", 1048191)
    assert revit_ids.unique_id_to_element_id(uid) == 1048191
    assert int(uid.split("-")[-1], 16) != 1048191   # naive decode is wrong


# ---------------------------------------------------------------------------
# BUG-08 reset + BUG-07 unverified flag (endpoint-level)
# ---------------------------------------------------------------------------
def test_reset_endpoint_returns_to_idle(tmp_artifacts: Path) -> None:
    wf = bw.default_state()
    bw.transition(wf, "proposing", "agent")
    bw.transition(wf, "awaiting_pdf_approval", "agent")
    bw.save(wf)
    resp = main.benchmark_workflow_reset({"actor": "test"})
    body = __import__("json").loads(resp.body)
    assert body["state"] == "idle"
    assert body["history"][-1]["from"] == "awaiting_pdf_approval"
    assert bw.load()["state"] == "idle"


def test_stamp_failure_restores_entry_bytes_not_stale_backup(wf_project: Path) -> None:
    """Review fix: a failed verify must restore THIS call's entry state. A
    stale .bak from an earlier run must never be copied over the PDF — that
    would wipe every legitimate change made since."""
    import fitz

    # Stale backup from a hypothetical earlier run (different content).
    bak = wf_project.with_suffix(".pre_benchmarks.bak.pdf")
    stale = fitz.open(); stale.new_page(width=100, height=100)
    stale.save(str(bak)); stale.close()
    stale_bytes = bak.read_bytes()
    # Poison the PDF so verification fails: BM-1 at the wrong position.
    with fitz.open(str(wf_project)) as doc:
        a = doc[0].add_circle_annot(fitz.Rect(0, 0, 20, 20))
        a.set_info(subject="BM-1", title="Livio QA-QC benchmark")
        a.update()
        doc.saveIncr()
    entry_bytes = wf_project.read_bytes()

    verification = main._stamp_pdf_with_proposal(_proposal())
    assert verification["ok"] is False
    after = wf_project.read_bytes()
    assert after == entry_bytes          # exact entry state restored
    assert after != stale_bytes          # and NOT the stale backup


def test_reset_archives_prior_history(tmp_artifacts: Path) -> None:
    wf = bw.default_state()
    bw.transition(wf, "proposing", "agent")
    bw.save(wf)
    main.benchmark_workflow_reset({"actor": "test"})
    archive = tmp_artifacts / "benchmark_workflow.prev.json"
    assert archive.exists()
    prior = __import__("json").loads(archive.read_text(encoding="utf-8"))
    assert prior["state"] == "proposing" and prior["history"]


def test_advance_markers_placed_flagged_unverified(tmp_artifacts: Path) -> None:
    wf = bw.default_state()
    for s in ("proposing", "awaiting_pdf_approval", "stamping", "awaiting_revit",
              "placing_markers"):
        bw.transition(wf, s, "agent")
    wf["proposal"] = {"benchmarks": [{"mark": "BM-1"}, {"mark": "BM-2"}]}
    bw.save(wf)
    resp = main.benchmark_workflow_advance({"step": "markers_placed", "data": {"x": 1}})
    body = __import__("json").loads(resp.body)
    assert body["state"] == "awaiting_revit_approval"
    assert body["history"][-1]["payload"]["verified"] is False


# ---------------------------------------------------------------------------
# Stamp verification (pure)
# ---------------------------------------------------------------------------
def _proposal(page_index: int = 0) -> dict:
    return {
        "sheet_number": "S-201",
        "page_index": page_index,
        "benchmarks": [
            {"mark": "BM-1", "grid_id": "grid_A_1", "grid_label": "Grid A/1",
             "pdf_point_pt": {"x": 300.0, "y": 300.0},
             "revit_point_ft": {"x": 0.0, "y": 0.0}},
            {"mark": "BM-2", "grid_id": "grid_C_3", "grid_label": "Grid C/3",
             "pdf_point_pt": {"x": 2200.0, "y": 1400.0},
             "revit_point_ft": {"x": 100.0, "y": 60.0}},
        ],
    }


def test_verify_stamped_benchmarks_passes_within_tolerance() -> None:
    extracted = {"benchmarks": [
        {"mark": "BM-1", "point_pt": {"x": 301.0, "y": 300.5}},
        {"mark": "BM-2", "point_pt": {"x": 2200.0, "y": 1400.0}},
    ]}
    v = bw.verify_stamped_benchmarks(_proposal(), extracted)
    assert v["ok"] is True
    assert all(c["ok"] for c in v["checks"])
    assert v["reason"] is None


def test_verify_stamped_benchmarks_fails_off_position() -> None:
    extracted = {"benchmarks": [
        {"mark": "BM-1", "point_pt": {"x": 300.0, "y": 300.0}},
        {"mark": "BM-2", "point_pt": {"x": 2210.0, "y": 1410.0}},  # 14pt off
    ]}
    v = bw.verify_stamped_benchmarks(_proposal(), extracted)
    assert v["ok"] is False
    assert v["checks"][0]["ok"] is True
    assert v["checks"][1]["ok"] is False
    assert "BM-2" in v["reason"] and "BM-1" not in v["reason"]


def test_verify_stamped_benchmarks_fails_when_mark_missing() -> None:
    extracted = {"benchmarks": [{"mark": "BM-1", "point_pt": {"x": 300.0, "y": 300.0}}]}
    v = bw.verify_stamped_benchmarks(_proposal(), extracted)
    assert v["ok"] is False
    assert v["checks"][1]["found"] is None
    assert v["checks"][1]["delta_pt"] is None


# ---------------------------------------------------------------------------
# /stamp: real PyMuPDF write + read-back verify (fixture PDF)
# ---------------------------------------------------------------------------
def _blank_pdf(tmp_path: Path, w: float = 2592.0, h: float = 1728.0) -> Path:
    import fitz

    doc = fitz.open()
    doc.new_page(width=w, height=h)
    out = tmp_path / "input.pdf"
    doc.save(str(out))
    doc.close()
    return out


@pytest.fixture()
def wf_project(tmp_artifacts: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project workspace with a real (blank) PDF wired up via
    project_manifest.pdf_path, exactly like main.py's _project_pdf_path()
    expects — so _stamp_pdf_with_proposal never touches the real Downloads
    sample or a real project PDF."""
    pdf_path = _blank_pdf(tmp_artifacts)
    manifest = {"pdf_path": str(pdf_path), "project": "test"}
    (tmp_artifacts / "project_manifest.json").write_text(
        __import__("json").dumps(manifest), encoding="utf-8"
    )
    return pdf_path


def test_stamp_writes_and_verifies_benchmarks(wf_project: Path) -> None:
    verification = main._stamp_pdf_with_proposal(_proposal())
    assert verification["ok"] is True
    assert all(c["delta_pt"] is not None and c["delta_pt"] < 0.5 for c in verification["checks"])
    bak = wf_project.with_suffix(".pre_benchmarks.bak.pdf")
    assert bak.exists()


def test_stamp_is_idempotent_and_flags_wrong_existing_position(wf_project: Path) -> None:
    import fitz

    # Pre-stamp BM-1 at the WRONG position — _stamp_pdf_with_proposal must
    # skip re-stamping an existing mark (idempotent retry), so the wrong
    # position survives and verification must catch it.
    with fitz.open(str(wf_project)) as doc:
        page = doc[0]
        a = page.add_circle_annot(fitz.Rect(0, 0, 20, 20))
        a.set_info(subject="BM-1", title="Livio QA-QC benchmark")
        a.update()
        doc.saveIncr()

    verification = main._stamp_pdf_with_proposal(_proposal())
    assert verification["ok"] is False
    checks = {c["mark"]: c for c in verification["checks"]}
    assert checks["BM-1"]["ok"] is False        # stale wrong position, not re-stamped
    assert checks["BM-2"]["ok"] is True          # freshly stamped, correct


def test_stamp_endpoint_requires_stamping_state(wf_project: Path) -> None:
    wf = bw.default_state()
    bw.save(wf)
    with pytest.raises(HTTPException) as exc:
        main.benchmark_workflow_stamp({"actor": "test"})
    assert exc.value.status_code == 409
    assert bw.load()["state"] == "idle"


def test_stamp_endpoint_happy_path(wf_project: Path) -> None:
    wf = bw.default_state()
    bw.transition(wf, "proposing", "agent")
    bw.transition(wf, "awaiting_pdf_approval", "agent")
    bw.transition(wf, "stamping", "human")
    wf["proposal"] = _proposal()
    bw.save(wf)

    resp = main.benchmark_workflow_stamp({"actor": "human_ui"})
    body = __import__("json").loads(resp.body)
    assert body["state"] == "awaiting_revit"
    assert body["verification"]["ok"] is True
    assert bw.load()["state"] == "awaiting_revit"


def test_advance_stamped_verifies_against_proposal(wf_project: Path) -> None:
    """The advance{step:'stamped'} fallback must not trust the caller's word
    — it re-reads the PDF. With nothing actually stamped, it must 409."""
    wf = bw.default_state()
    bw.transition(wf, "proposing", "agent")
    bw.transition(wf, "awaiting_pdf_approval", "agent")
    bw.transition(wf, "stamping", "human")
    wf["proposal"] = _proposal()
    bw.save(wf)

    with pytest.raises(HTTPException) as exc:
        main.benchmark_workflow_advance({"step": "stamped", "actor": "agent"})
    assert exc.value.status_code == 409
    assert bw.load()["state"] == "stamping"  # unchanged — nothing was verified

    # Now actually stamp via the real endpoint — the state moves on once the
    # PDF genuinely carries the approved points.
    main.benchmark_workflow_stamp({"actor": "human_ui"})
    assert bw.load()["state"] == "awaiting_revit"


# ---------------------------------------------------------------------------
# awaiting_export auto-detect
# ---------------------------------------------------------------------------
def test_auto_advance_export_when_marks_present(tmp_artifacts: Path) -> None:
    wf = bw.default_state()
    bw.transition(wf, "proposing", "agent")
    bw.transition(wf, "awaiting_pdf_approval", "agent")
    bw.transition(wf, "stamping", "human")
    bw.transition(wf, "awaiting_revit", "agent")
    bw.transition(wf, "placing_markers", "agent")
    bw.transition(wf, "awaiting_revit_approval", "agent")
    bw.transition(wf, "awaiting_export", "human")
    wf["proposal"] = _proposal()
    bw.save(wf)

    raw = {"benchmarks": [{"mark": "BM-1"}, {"mark": "BM-2"}]}
    main._maybe_auto_advance_export(raw)
    assert bw.load()["state"] == "calibrating"


def test_auto_advance_export_noop_outside_that_state(tmp_artifacts: Path) -> None:
    bw.save(bw.default_state())  # idle
    main._maybe_auto_advance_export({"benchmarks": [{"mark": "BM-1"}, {"mark": "BM-2"}]})
    assert bw.load()["state"] == "idle"


def test_auto_advance_export_noop_when_marks_incomplete(tmp_artifacts: Path) -> None:
    wf = bw.default_state()
    bw.transition(wf, "proposing", "agent")
    bw.transition(wf, "awaiting_pdf_approval", "agent")
    bw.transition(wf, "stamping", "human")
    bw.transition(wf, "awaiting_revit", "agent")
    bw.transition(wf, "placing_markers", "agent")
    bw.transition(wf, "awaiting_revit_approval", "agent")
    bw.transition(wf, "awaiting_export", "human")
    wf["proposal"] = _proposal()
    bw.save(wf)

    main._maybe_auto_advance_export({"benchmarks": [{"mark": "BM-1"}]})  # only 1 of 2
    assert bw.load()["state"] == "awaiting_export"
