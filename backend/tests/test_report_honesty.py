"""Report-honesty fixes: R-22 (CSV distance unit), R-21 (accuracy
denominator), R-25 (reasons name the PDF callout), R-03/Gate-2 (cross-level
pairing gate) and R-10 (hold-down category sweep).

R-10/R-25 are additive — the statuses they touch must come out the same, so
each test that could move a verdict asserts the verdict too. R-03 was
additive-only (note, status untouched); Gate 2 (Stage 9 accuracy program)
promoted it to an actual gate — see test_cross_level_pairing_is_flagged.
"""

from __future__ import annotations

import csv
import json

import pytest

from app import config, device_match, revit_v3_adapter
from app.routers import elements as elements_router


def _json(response):
    return json.loads(response.body)


# --------------------------------------------------- shared device fixtures
PAIRS = [{"revit_point": {"x": x, "y": y},
          "pdf_point": {"x": 100 + 4 * x, "y": 900 - 4 * y}}
         for x, y in ((0, 0), (50, 0), (0, 30), (25, 60))]
CALS = {"S-201": {"point_pairs": PAIRS}}
ROW = {"id": "s-201_h1_007_1", "sheet": "S-201", "category": "holdown",
       "mark": "H1", "status": "MATCH", "pdf_point": {"x": 140, "y": 860}}


def _devices(rows, assemblies):
    reg = device_match.run(rows, CALS, assemblies, walls=[])
    return reg, reg["categories"]["holdown"]["devices"]


# ------------------------------------------- R-25: reasons name the callout
def test_reason_names_the_pdf_callout_and_its_sheet() -> None:
    _, devices = _devices([ROW], [{"id": "rev_asm_011",
                                   "pdf_mark_candidate": "H1",
                                   "center_point": {"x": 10.2, "y": 10.1}}])
    assert devices[0]["status"] == "MATCH"
    assert "rev_asm_011" in devices[0]["reason"]          # Revit side kept
    assert "(callout s-201_h1_007_1 on S-201)" in devices[0]["reason"]


def test_unmatched_and_mark_mismatch_reasons_also_name_the_callout() -> None:
    _, devices = _devices([ROW], [])                       # nothing to pair
    assert devices[0]["status"] == "PDF_ONLY"
    assert "(callout s-201_h1_007_1 on S-201)" in devices[0]["reason"]

    _, devices = _devices([ROW], [{"id": "rev_asm_012",
                                   "pdf_mark_candidate": "H9",
                                   "center_point": {"x": 10.2, "y": 10.1}}])
    assert devices[0]["status"] == "MARK_MISMATCH"
    assert "(callout s-201_h1_007_1 on S-201)" in devices[0]["reason"]


def test_row_override_reason_carries_the_callout_tag() -> None:
    reg, _ = _devices([ROW], [])
    assert "(callout s-201_h1_007_1 on S-201)" in (
        reg["row_overrides"]["s-201_h1_007_1"]["reason"])


# ------------------------------------------------ R-03: cross-level pairing
def test_cross_level_pairing_is_flagged() -> None:
    """Gate 2 (Stage 9): good XY, wrong floor is neither a confident MATCH
    nor a confident MISMATCH -- the horizontal and vertical evidence
    disagree, so it's NEEDS_REVIEW and nothing is claimed, not a MATCH with
    a note attached (the pre-Gate-2 behavior)."""
    row = dict(ROW, elevation_ft=0.0)
    _, devices = _devices([row], [{"id": "rev_asm_011",
                                   "pdf_mark_candidate": "H1",
                                   "center_point": {"x": 10.2, "y": 10.1,
                                                    "z": 30.0}}])
    assert devices[0]["status"] == "NEEDS_REVIEW"
    assert devices[0].get("target_id") is None              # nothing claimed
    assert "different level" in devices[0]["reason"]
    assert "Δz≈30 ft" in devices[0]["reason"]


def test_same_level_pairing_gets_no_note() -> None:
    row = dict(ROW, elevation_ft=0.0)
    _, devices = _devices([row], [{"id": "rev_asm_011",
                                   "pdf_mark_candidate": "H1",
                                   "center_point": {"x": 10.2, "y": 10.1,
                                                    "z": 1.5}}])
    assert "different level" not in devices[0]["reason"]


def test_note_stays_dormant_when_the_row_has_no_elevation() -> None:
    """Today's element rows carry no Z (the inverse transform is 2D), so the
    check must never fire on a guess — only on a real elevation."""
    assert device_match.row_z_ft(ROW) is None
    _, devices = _devices([ROW], [{"id": "rev_asm_011",
                                   "pdf_mark_candidate": "H1",
                                   "center_point": {"x": 10.2, "y": 10.1,
                                                    "z": 900.0}}])
    assert devices[0]["status"] == "MATCH"
    assert "different level" not in devices[0]["reason"]


def test_row_z_reads_the_level_elevation_shapes_it_may_arrive_in() -> None:
    assert device_match.row_z_ft({"elevation_ft": 12.5}) == 12.5
    assert device_match.row_z_ft({"level_elevation_ft": 9}) == 9.0
    assert device_match.row_z_ft({"level": {"elevation_ft": 3.0}}) == 3.0
    assert device_match.row_z_ft({"level": "Level 2"}) is None


# ------------------------------------------------- R-10: category sweep
def _v3(elements):
    return {"elements": elements}


def test_generic_model_holdowns_are_found() -> None:
    out = revit_v3_adapter.build_ai_revit(
        _v3([{"id": "g1", "category": "Generic Models", "family": "S/HD15S",
              "location": {"point": [0.0, 0.0, 0.0]}}]),
        {"HD15S": "HD3"})
    asm = out["canonical_holdown_assemblies"]
    assert [a["primary_element_id"] for a in asm] == ["g1"]
    assert asm[0]["pdf_mark_candidate"] == "HD3"


def test_structural_framing_is_swept_only_for_holdown_families() -> None:
    """The regex gate is what makes the extra categories safe — a model has
    tens of thousands of framing members and none of them may leak in."""
    out = revit_v3_adapter.build_ai_revit(
        _v3([{"id": "f1", "category": "Structural Framing", "family": "SHDU9",
              "location": {"point": [0.0, 0.0, 0.0]}}]
            + [{"id": f"j{i}", "category": "Structural Framing",
                "family": "2x6 Stud", "location": {"point": [float(i), 0.0, 0.0]}}
               for i in range(50)]),
        {"HD9": "HD2"})
    assert [a["primary_element_id"]
            for a in out["canonical_holdown_assemblies"]] == ["f1"]


def test_unsearched_categories_are_still_ignored() -> None:
    out = revit_v3_adapter.build_ai_revit(
        _v3([{"id": "x1", "category": "Casework", "family": "S/HD15S",
              "location": {"point": [0.0, 0.0, 0.0]}}]),
        {"HD15S": "HD3"})
    assert out["canonical_holdown_assemblies"] == []


def test_searched_categories_are_reported() -> None:
    out = revit_v3_adapter.build_ai_revit(_v3([]), {})
    assert out["searched_categories"] == list(
        revit_v3_adapter.HOLDOWN_CATEGORIES)
    assert "Generic Models" in out["searched_categories"]


# ------------------------------------------------------- R-21 / R-22 / #5
ELEMENTS = {
    "counts": {"total": 10,
               "by_status": {"MATCH": 4, "LOCATION_MISMATCH": 1,
                             "PDF_ONLY": 1, "REVIT_ONLY": 1,
                             "MARK_MISMATCH": 2, "SPEC_ONLY": 1}},
    "elements": [
        {"id": "e1", "sheet": "S-201", "category": "holdown", "mark": "H1",
         "status": "LOCATION_MISMATCH", "distance_ft": 3.42,
         "distance_pdf_points": 61.5, "pdf_point": {"x": 140.0, "y": 860.0},
         "revit_ref": {"id": "rev_asm_011"}, "reason": "paired"},
        {"id": "e2", "sheet": "S-202", "category": "shear_wall", "mark": "SW-1",
         "status": "PDF_ONLY", "reason": "no target"},
        {"id": "e3", "sheet": "S-201", "category": "holdown", "mark": "H2",
         "status": "MATCH", "distance_ft": 0.4},
    ],
}


@pytest.fixture()
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path)
    (tmp_path / config.ARTIFACT_FILES["element_list"]).write_text(
        json.dumps(ELEMENTS), encoding="utf-8")
    return tmp_path


def test_accuracy_counts_mark_mismatch_as_evaluable(project) -> None:
    out = _json(elements_router.metrics_accuracy())
    # 4 + 1 + 1 + 1 + 2 = 9 (SPEC_ONLY is an honesty flag, still excluded)
    assert out["evaluable"] == 9
    assert out["accuracy"] == round(4 / 9, 4)
    assert "MARK_MISMATCH" in out["definition"]


def _punch_rows(project):
    elements_router.export_punch_list()
    with (project / "punch_list.csv").open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_punch_list_exports_feet_as_the_primary_distance(project) -> None:
    rows = _punch_rows(project)
    assert list(rows[0])[:6] == [
        "sheet", "category", "mark", "status", "distance_ft",
        "distance_pdf_points"]
    by_id = {r["mark"]: r for r in rows}
    assert by_id["H1"]["distance_ft"] == "3.42"
    assert by_id["H1"]["distance_pdf_points"] == "61.5"


def test_punch_list_leaves_the_points_column_blank_when_absent(project) -> None:
    """The foot-based status is the live one; a missing points number must
    read as absent, not as 0 or as the reason for the verdict."""
    row = next(r for r in _punch_rows(project) if r["mark"] == "SW-1")
    assert row["distance_pdf_points"] == ""
    assert row["distance_ft"] == ""
    assert row["status"] == "PDF_ONLY"


def test_punch_list_still_skips_matches(project) -> None:
    assert [r["mark"] for r in _punch_rows(project)] == ["H1", "SW-1"]


def test_primary_sheet_comes_from_the_page_intelligence_artifact(project) -> None:
    (project / config.ARTIFACT_FILES["pdf_page_intelligence"]).write_text(
        json.dumps({"sheet_number": "S-05"}), encoding="utf-8")
    assert _json(elements_router.sheets_primary()) == {"sheet": "S-05"}


def test_primary_sheet_is_null_before_page_intelligence_runs(project) -> None:
    assert _json(elements_router.sheets_primary()) == {"sheet": None}
