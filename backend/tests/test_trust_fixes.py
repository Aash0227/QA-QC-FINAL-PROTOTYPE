"""Trust fixes R-18 (REVIT_ONLY cause split), R-07 (export-scope honesty
banner) and R-29 (per-device run diff). All three are metadata/labels — no
test here asserts a verdict, because none of them may change one."""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from app import config, device_match, element_registry
from app.routers import elements as elements_router


# --------------------------------------------------------- R-18: causes
PAIRS = [{"revit_point": {"x": x, "y": y},
          "pdf_point": {"x": 100 + 4 * x, "y": 900 - 4 * y}}
         for x, y in ((0, 0), (50, 0), (0, 30), (25, 60))]
ROWS = [{"id": "s1_h1_a", "sheet": "S1", "category": "holdown", "mark": "H1",
         "status": "MATCH", "pdf_point": {"x": 140, "y": 860}}]   # (10, 10) ft
CALS = {"S1": {"point_pairs": PAIRS}}


def _holdown(assemblies):
    return device_match.run(ROWS, CALS, assemblies, walls=[])["categories"]["holdown"]


def test_revit_only_detail_marks_unmarked_target_unclassified() -> None:
    cat = _holdown([{"id": "rev_asm_009", "pdf_mark_candidate": None,
                     "center_point": {"x": 900.0, "y": 900.0}}])
    assert cat["revit_only_ids"] == ["rev_asm_009"]        # unchanged
    assert cat["revit_only_detail"] == [
        {"id": "rev_asm_009", "mark": None, "cause": "unclassified"}]


def test_revit_only_detail_marks_marked_target_unmatched() -> None:
    cat = _holdown([{"id": "rev_asm_009", "pdf_mark_candidate": "H9",
                     "center_point": {"x": 900.0, "y": 900.0}}])
    assert cat["revit_only_detail"] == [
        {"id": "rev_asm_009", "mark": "H9", "cause": "unmatched"}]


def test_revit_only_detail_empty_when_every_target_is_claimed() -> None:
    cat = _holdown([{"id": "rev_asm_001", "pdf_mark_candidate": "H1",
                     "center_point": {"x": 10.2, "y": 10.1}}])
    assert cat["summary"]["revit_only"] == 0
    assert cat["revit_only_detail"] == []


# ------------------------------------------------------- R-07: scope
RAW = {"comparison_view": {"name": "S-201 Foundation"},
       "export_scope": "active_view_visible"}


def test_scope_warning_when_category_has_callouts_but_no_revit_targets() -> None:
    warnings = element_registry.scope_warnings(
        {"shear_wall": {"callout_rows": 54, "revit_targets": 0}}, RAW)
    assert len(warnings) == 1
    w = warnings[0]
    assert (w["category"], w["pdf_count"], w["revit_count"]) == ("shear_wall", 54, 0)
    assert w["export_view"] == "S-201 Foundation"
    assert "confirm the export view has shear_wall visible" in w["message"]


def test_no_scope_warning_when_revit_targets_exist_or_no_callouts() -> None:
    assert element_registry.scope_warnings(
        {"holdown": {"callout_rows": 122, "revit_targets": 72},
         "shear_wall": {"callout_rows": 0, "revit_targets": 0}}, RAW) == []
    assert element_registry.scope_warnings(None, None) == []


def test_scope_warning_falls_back_to_export_scope_without_a_view() -> None:
    w = element_registry.scope_warnings(
        {"post": {"callout_rows": 3, "revit_targets": 0}},
        {"export_scope": "active_view_visible"})
    assert w[0]["export_view"] == "active_view_visible"


# ------------------------------------------------------- R-29: run diff
REGISTRY = {"categories": {"holdown": {"devices": [
    {"id": "holdown_dev_001", "mark": "H1", "x": 10.0, "y": 10.0,
     "status": "MATCH", "target_id": "rev_asm_001", "distance_ft": 0.4},
    {"id": "holdown_dev_002", "mark": "H2", "x": 50.0, "y": 50.0,
     "status": "PDF_ONLY"},
]}}}
ELEMENT_LIST = {"elements": [{"category": "holdown", "status": "MATCH",
                              "mark": "H1", "sheet": "S-201"}]}


@pytest.fixture()
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path)
    (tmp_path / config.ARTIFACT_FILES["element_list"]).write_text(
        json.dumps(ELEMENT_LIST), encoding="utf-8")
    return tmp_path


def _write_registry(path, registry):
    (path / config.ARTIFACT_FILES["device_registry"]).write_text(
        json.dumps(registry), encoding="utf-8")


def _json(response):
    return json.loads(response.body)


def test_baseline_snapshots_devices_and_compare_reports_status_flips(project) -> None:
    _write_registry(project, REGISTRY)
    saved = _json(elements_router.runs_baseline_save(label="b1"))
    assert saved["saved"] is True
    baseline = json.loads((project / "run_baseline.json").read_text(encoding="utf-8"))
    assert baseline["devices"] == [
        {"key": "holdown:H1:rev_asm_001", "status": "MATCH", "distance_ft": 0.4},
        {"key": "holdown:H2:@50,50", "status": "PDF_ONLY", "distance_ft": None},
    ]

    # Same devices, one flipped and one new -> exactly one change, one added.
    moved = json.loads(json.dumps(REGISTRY))
    moved["categories"]["holdown"]["devices"][0].update(
        status="LOCATION_MISMATCH", distance_ft=3.9)
    moved["categories"]["holdown"]["devices"].append(
        {"id": "holdown_dev_003", "mark": "H3", "x": 5.0, "y": 5.0,
         "status": "PDF_ONLY"})
    _write_registry(project, moved)

    out = _json(elements_router.runs_compare())
    assert out["device_note"] is None
    assert out["device_changes"] == [{
        "key": "holdown:H1:rev_asm_001", "old_status": "MATCH",
        "new_status": "LOCATION_MISMATCH",
        "old_distance_ft": 0.4, "new_distance_ft": 3.9}]
    assert out["device_added"] == ["holdown:H3:@5,5"]
    assert out["device_removed"] == []
    assert out["baseline"]["totals"] == {"MATCH": 1}   # counts table untouched


def test_compare_is_honest_about_a_baseline_saved_before_device_tracking(project) -> None:
    _write_registry(project, REGISTRY)
    (project / "run_baseline.json").write_text(
        json.dumps({"label": "old", "rows": [{"category": "holdown",
                                              "status": "MATCH"}]}),
        encoding="utf-8")
    out = _json(elements_router.runs_compare())
    assert out["device_changes"] is None
    assert out["device_added"] is None
    assert "save a new baseline" in out["device_note"]


def test_baseline_without_a_device_registry_snapshots_none(project) -> None:
    _json(elements_router.runs_baseline_save(label="no-registry"))
    baseline = json.loads((project / "run_baseline.json").read_text(encoding="utf-8"))
    assert baseline["devices"] is None
    out = _json(elements_router.runs_compare())
    assert out["device_changes"] is None and out["device_note"]


def test_compare_without_any_baseline_is_a_409(project) -> None:
    with pytest.raises(HTTPException) as exc:
        elements_router.runs_compare()
    assert exc.value.status_code == 404


# ------------------------------------------- R-27: no borrowed PDF baseline
def _diag(tmp_path, page_intelligence):
    """revit_count_diagnostics for a project whose page-intelligence artifact
    is (or is not) present. Display-only block — never a verdict."""
    from app import compare as compare_mod

    if page_intelligence is not None:
        (tmp_path / config.ARTIFACT_FILES["pdf_page_intelligence"]).write_text(
            json.dumps(page_intelligence), encoding="utf-8")
    ai_revit = {"canonical_holdown_assemblies": [
        {"id": "r1", "pdf_mark_candidate": "HD2", "center_point": {"x": 0, "y": 0}}]}
    return compare_mod.compare(ai_revit, {"holdowns": []}, calibration=None)[
        "revit_count_diagnostics"]


def test_diagnostics_never_uses_the_observed_counts_as_their_own_baseline(project) -> None:
    """No expected_baseline recorded (generic detector) -> no baseline at all.

    The old fallback took the baseline from ``summary.by_type`` — the very
    counts the baseline is supposed to check — so the comparison could never
    disagree with itself, yet still emitted likely_issue/required_next_fix.
    """
    diag = _diag(project, {"summary": {"by_type": {"HD1": 14, "HD2": 17}}})
    assert diag["pdf_baseline"] is None
    assert "likely_issue" not in diag and "required_next_fix" not in diag
    assert "No PDF baseline available" in diag["note"]
    assert diag["by_mark"] == {"HD2": 1}    # still reports what Revit holds


def test_diagnostics_says_so_when_no_pdf_baseline_exists(project) -> None:
    """R-27: silence beats another project's numbers."""
    diag = _diag(project, None)
    assert diag["pdf_baseline"] is None
    assert "No PDF baseline available" in diag["note"]
    assert "likely_issue" not in diag       # no recommendation without evidence
    assert diag["by_mark"] == {"HD2": 1}    # still reports what Revit holds


def test_diagnostics_ignores_unusable_baseline(project) -> None:
    diag = _diag(project, {"expected_baseline": {"HD1": "not-a-number"}})
    assert diag["pdf_baseline"] is None


# --------------------------- phantom route: GET /api/registration/sheet/{s}
def _write_sheet_cal(sheet, source="grid_verified"):
    config.sheet_calibration_path(sheet).write_text(json.dumps({
        "calibration_source": source, "sheet_number": sheet,
        "confidence": "high", "transform": {"scale": 12.0},
    }), encoding="utf-8")


def test_registration_sheet_route_returns_per_sheet_calibration(project) -> None:
    from app.routers import registration as reg_router

    _write_sheet_cal("S-202")
    out = _json(reg_router.registration_sheet_get("S-202"))
    assert out["present"] is True and out["sheet"] == "S-202"
    assert out["calibration"]["transform"]["scale"] == 12.0
    assert set(out) >= {"present", "status", "calibration_source",
                        "match_allowed", "calibration"}   # same shape as /api/registration


def test_registration_sheet_route_uses_global_for_primary_sheet(project) -> None:
    from app import registration as registration_mod
    from app.routers import registration as reg_router

    (project / config.ARTIFACT_FILES["pdf_page_intelligence"]).write_text(
        json.dumps({"sheet_number": "S-05"}), encoding="utf-8")
    registration_mod.save_calibration({
        "calibration_source": "grid_verified", "confidence": "high",
        "transform": {"scale": 18.0}})
    out = _json(reg_router.registration_sheet_get("s-05"))   # case-insensitive
    assert out["calibration"]["transform"]["scale"] == 18.0


def test_registration_sheet_route_404s_honestly(project) -> None:
    from app.routers import registration as reg_router

    with pytest.raises(HTTPException) as exc:
        reg_router.registration_sheet_get("S-999")
    assert exc.value.status_code == 404
    assert "S-999" in exc.value.detail


# ------------------------ Doc-21 #4: which intelligence path actually ran
def _run_page_intelligence(monkeypatch, s201_result, generic_result=None):
    from app import generic_page_intelligence, pdf_intelligence
    from app import profile as profile_mod
    from app.routers import pipeline as pipeline_router

    monkeypatch.setattr(pdf_intelligence, "run_page_intelligence",
                        lambda *_a, **_k: dict(s201_result))
    monkeypatch.setattr(generic_page_intelligence, "run_generic_page_intelligence",
                        lambda *_a, **_k: dict(generic_result or {}))
    monkeypatch.setattr(pipeline_router, "project_pdf_path", lambda: "unused.pdf")
    # handler is now sync (def) — call it directly, not via asyncio.run
    return _json(pipeline_router.pdf_page_intelligence(use_saved=True))


def test_intelligence_source_marks_the_s201_path_only_with_madera_profile(
    project, monkeypatch,
) -> None:
    """Generic-first: the frozen S-201 detector runs ONLY when the project
    manifest declares the madera profile."""
    import app.profile as profile_mod
    monkeypatch.setattr(profile_mod, "detection_profile", lambda: "madera")
    out = _run_page_intelligence(monkeypatch, {"sheet_number": "S-201"})
    assert out["intelligence_source"] == "s201_focused"
    saved = json.loads(
        (project / config.ARTIFACT_FILES["pdf_page_intelligence"]).read_text(encoding="utf-8"))
    assert saved["intelligence_source"] == "s201_focused"


def test_intelligence_source_marks_the_generic_path_as_default(project, monkeypatch) -> None:
    (project / config.ARTIFACT_FILES["element_intelligence"]).write_text(
        json.dumps({"sheets": []}), encoding="utf-8")
    out = _run_page_intelligence(monkeypatch, {"sheet_number": "S-201"},
                                 {"sheet_number": "S7"})
    assert out["intelligence_source"] == "generic"
    assert out["sheet_number"] == "S7"


def test_intelligence_source_marks_missing_element_intelligence_honestly(
    project, monkeypatch,
) -> None:
    """Generic first but no element_intelligence — report the error instead of
    pretending the frozen detector ran."""
    out = _run_page_intelligence(monkeypatch, {"sheet_number": "S-201"})
    assert out["intelligence_source"] == "generic" and out["error"]
