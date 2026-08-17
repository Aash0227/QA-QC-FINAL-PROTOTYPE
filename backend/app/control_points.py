"""Revit grid control points + PDF control points + label-matched calibration.

One small module so the next coordinate-matching phase has somewhere obvious to
live. Pure builders + thin save/load helpers; FastAPI in main.py wires them up.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from . import config, registration

SCHEMA_REVIT_CP = "revit-control-points/1.0"
SCHEMA_PDF_CP = "pdf-control-points/1.0"
SCHEMA_PAIRS = "manual-registration-points/1.0"
SCHEMA_SCOPE = "revit-scope-diagnostics/1.0"


def _pdf_baseline() -> dict[str, int] | None:
    """This project's expected PDF mark counts, plus a derived ``total``.

    R-27, extended: the Madera literal {H1:10,H2:21,H3:6,H4:17,total:54} that
    used to live here scored every project against Madera. Reuses compare.py's
    artifact lookup so there is one definition of "this project's baseline".
    None when the project recorded none — the caller then reports Revit counts
    alone rather than a borrowed yardstick.
    """
    from .compare import _project_pdf_baseline

    base = _project_pdf_baseline()
    if not base:
        return None
    marks = {k: v for k, v in base.items() if k != "total"}
    return {**marks, "total": sum(marks.values())}


def _line_intersection(
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    p4: tuple[float, float],
) -> tuple[float, float] | None:
    (x1, y1), (x2, y2) = p1, p2
    (x3, y3), (x4, y4) = p3, p4
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-9:
        return None
    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / denom
    return x1 + t * (x2 - x1), y1 + t * (y2 - y1)


def _is_letter_label(label: str) -> bool:
    return bool(label) and label[0].isalpha()


# ---------------------------------------------------------------------------
# Revit control points (pure)
# ---------------------------------------------------------------------------
def extract_revit_control_points(raw_revit: dict[str, Any]) -> dict[str, Any]:
    """Compute grid intersections from raw_revit_export.json grids[]."""
    grids = raw_revit.get("grids") or []
    letters: list[tuple[str, tuple[float, float], tuple[float, float]]] = []
    numbers: list[tuple[str, tuple[float, float], tuple[float, float]]] = []
    warnings: list[str] = []

    for g in grids:
        label = str(g.get("label", "")).strip()
        line = g.get("line") or []
        if not label or len(line) < 2:
            warnings.append(f"Grid '{label or '?'}' missing label or line geometry; skipped.")
            continue
        try:
            a = (float(line[0][0]), float(line[0][1]))
            b = (float(line[1][0]), float(line[1][1]))
        except (TypeError, ValueError, IndexError):
            warnings.append(f"Grid '{label}' line endpoints unreadable; skipped.")
            continue
        (letters if _is_letter_label(label) else numbers).append((label, a, b))

    points: list[dict[str, Any]] = []
    for lab_letter, a1, b1 in letters:
        for lab_number, a2, b2 in numbers:
            ip = _line_intersection(a1, b1, a2, b2)
            if ip is None:
                warnings.append(
                    f"Grid {lab_letter}/{lab_number}: lines parallel; no intersection."
                )
                continue
            points.append(
                {
                    "id": f"grid_{lab_letter}_{lab_number}",
                    "label": f"Grid {lab_letter}/{lab_number}",
                    "type": "grid_intersection",
                    "point": {"x": round(ip[0], 6), "y": round(ip[1], 6), "z": None},
                }
            )

    if not points:
        warnings.append(
            "No grid intersections derived. Required Revit exporter fields for verified "
            "registration: grids (label + line endpoints in revit_internal_feet), and per "
            "hold-down record: level, view, sheet, schedule membership."
        )

    return {
        "schema_version": SCHEMA_REVIT_CP,
        "source": "raw_revit_export",
        "coordinate_system": {"space": "revit_internal", "unit": "feet"},
        "letter_grid_count": len(letters),
        "number_grid_count": len(numbers),
        "points": points,
        "warnings": warnings,
    }


def save_revit_control_points(payload: dict[str, Any]) -> None:
    config.artifact_path("revit_control_points").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# PDF control points (persisted manual entry)
# ---------------------------------------------------------------------------
def empty_pdf_control_points(
    sheet_number: str | None = None, page_index: int | None = None
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_PDF_CP,
        "source": "manual_click_or_entry",
        "page_index": page_index,
        "sheet_number": sheet_number,
        "coordinate_system": {"space": "pdf_page", "unit": "points"},
        "points": [],
        "warnings": [
            "No PDF control points entered yet. Provide grid-intersection coordinates "
            "(PDF page points) labeled to match Revit grid ids, e.g. grid_A_1, grid_B_2.",
        ],
    }


def load_or_init_pdf_control_points() -> dict[str, Any]:
    path = config.artifact_path("pdf_control_points")
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return empty_pdf_control_points()


def save_pdf_control_points(
    points: list[dict[str, Any]] | None,
    sheet_number: str | None = None,
    page_index: int | None = None,
) -> dict[str, Any]:
    cleaned: list[dict[str, Any]] = []
    warnings: list[str] = []
    for i, p in enumerate(points or []):
        try:
            pt = p["point"]
            x = float(pt["x"])
            y = float(pt["y"])
        except (KeyError, TypeError, ValueError):
            warnings.append(f"Point #{i}: missing/invalid point.x or point.y; skipped.")
            continue
        cleaned.append(
            {
                "id": p.get("id") or f"pdf_pt_{i + 1}",
                "label": p.get("label"),
                "type": p.get("type", "grid_intersection"),
                "point": {"x": x, "y": y},
            }
        )
    if not cleaned:
        warnings.append("Saved with zero valid points.")
    payload = {
        "schema_version": SCHEMA_PDF_CP,
        "source": "manual_click_or_entry",
        "page_index": page_index,
        "sheet_number": sheet_number,
        "coordinate_system": {"space": "pdf_page", "unit": "points"},
        "points": cleaned,
        "warnings": warnings,
    }
    config.artifact_path("pdf_control_points").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    return payload


# ---------------------------------------------------------------------------
# Label-matched pair builder (pure)
# ---------------------------------------------------------------------------
def build_pairs_from_labels(
    revit_cp: dict[str, Any], pdf_cp: dict[str, Any]
) -> dict[str, Any]:
    rev_by_id = {p["id"]: p for p in (revit_cp.get("points") or [])}
    pdf_by_id = {p["id"]: p for p in (pdf_cp.get("points") or [])}
    matched_ids = sorted(set(rev_by_id) & set(pdf_by_id))
    pairs: list[dict[str, Any]] = []
    for pid in matched_ids:
        r = rev_by_id[pid]
        p = pdf_by_id[pid]
        pairs.append(
            {
                "id": pid,
                "label": r.get("label") or p.get("label"),
                "revit_point": {"x": r["point"]["x"], "y": r["point"]["y"]},
                "pdf_point": {"x": p["point"]["x"], "y": p["point"]["y"]},
            }
        )
    return {
        "schema_version": SCHEMA_PAIRS,
        "calibration_source": "grid_verified",
        "matched_ids": matched_ids,
        "revit_only_ids": sorted(set(rev_by_id) - set(pdf_by_id)),
        "pdf_only_ids": sorted(set(pdf_by_id) - set(rev_by_id)),
        "point_pairs": pairs,
    }


def save_manual_pairs(payload: dict[str, Any]) -> None:
    config.artifact_path("manual_registration_points").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# End-to-end auto-calibration from grid labels
# ---------------------------------------------------------------------------
def auto_calibrate_from_grids(
    raw_revit: dict[str, Any],
    pdf_cp: dict[str, Any] | None = None,
    validation_pairs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rev_cp = extract_revit_control_points(raw_revit or {})
    save_revit_control_points(rev_cp)
    if pdf_cp is None:
        pdf_cp = load_or_init_pdf_control_points()
    pairs = build_pairs_from_labels(rev_cp, pdf_cp)
    save_manual_pairs(pairs)

    if len(pairs["point_pairs"]) < registration.MIN_PAIRS:
        return {
            "ok": False,
            "reason": (
                f"Need >= {registration.MIN_PAIRS} matching grid labels in BOTH Revit and "
                f"PDF control points; have {len(pairs['point_pairs'])} "
                f"(rev_only={pairs['revit_only_ids']}, pdf_only={pairs['pdf_only_ids']})."
            ),
            "revit_control_points": rev_cp,
            "pdf_control_points": pdf_cp,
            "pairs": pairs,
            "calibration": None,
        }

    calibration = registration.compute_calibration(
        pairs["point_pairs"],
        calibration_source="grid_verified",
        validation_pairs=validation_pairs,
    )
    registration.save_calibration(calibration)
    registration.save_registration_report(calibration)
    return {
        "ok": True,
        "revit_control_points": rev_cp,
        "pdf_control_points": pdf_cp,
        "pairs": pairs,
        "calibration": calibration,
    }


# ---------------------------------------------------------------------------
# Revit scope diagnostics (pure)
# ---------------------------------------------------------------------------
def build_scope_diagnostics(
    raw_revit: dict[str, Any], ai_revit: dict[str, Any]
) -> dict[str, Any]:
    records = list(raw_revit.get("holdowns") or [])
    assemblies = ai_revit.get("canonical_holdown_assemblies", [])

    by_mark = Counter(
        a.get("pdf_mark_candidate") for a in assemblies if a.get("pdf_mark_candidate")
    )
    by_family = Counter(r.get("family") for r in records)
    by_sched = Counter(r.get("scheduled_type") for r in records if r.get("scheduled_type"))
    by_category = Counter(r.get("category") for r in records)
    by_level = Counter(str(r.get("level")) for r in records)
    by_view = Counter(str(r.get("view")) for r in records)

    elevations = [
        r.get("elevation") for r in records if isinstance(r.get("elevation"), (int, float))
    ]
    elev_buckets: dict[str, int] = {}
    for e in elevations:
        key = f"{round(float(e)):d}_ft"
        elev_buckets[key] = elev_buckets.get(key, 0) + 1

    pdf_baseline = _pdf_baseline()
    # Marks come from this project's baseline when it has one, else from what
    # Revit actually contains — the old fixed ("H1".."H4") tuple dropped every
    # other mark out of revit_total without saying so.
    marks = tuple(k for k in (pdf_baseline or {}) if k != "total") or tuple(sorted(by_mark))
    revit_by_mark = {m: by_mark.get(m, 0) for m in marks}
    revit_by_mark["total"] = sum(revit_by_mark.values())

    warnings: list[str] = []
    required: list[str] = []
    recommended: list[str] = []

    if records and all(r.get("level") is None for r in records):
        warnings.append(
            "All hold-down records have level=null; cannot filter by floor/level. "
            "Comparison may include hold-downs from other levels, inflating Revit counts."
        )
        required.append("level (Revit Level name per hold-down)")
    if records and all(r.get("view") is None for r in records):
        warnings.append(
            "All hold-down records have view=null; cannot scope to the S-201 source view."
        )
        required.append("view (originating view name/id per hold-down)")
    if raw_revit.get("export_scope") != "active_view":
        warnings.append(
            f"export_scope='{raw_revit.get('export_scope')}'; whole-model export pulls hold-downs "
            "from every level/view. Re-run exporter against the S-201 source view in active_view mode."
        )
        required.append("sheet (sheet number per hold-down, e.g. 'S-201')")
        required.append("schedule_membership (which schedule(s) include this element)")

    revit_total = revit_by_mark["total"]
    if pdf_baseline is not None and revit_total != pdf_baseline["total"]:
        delta = revit_total - pdf_baseline["total"]
        recommended.append(
            f"Filter Revit assemblies to S-201 scope; current delta vs PDF baseline = {delta:+d}."
        )
    if elevations:
        recommended.append(
            "Once level metadata exists, optionally filter by elevation band "
            f"(observed buckets: {elev_buckets})."
        )

    summary = (
        (f"Revit total={revit_total} vs PDF baseline={pdf_baseline['total']} "
         f"(delta {revit_total - pdf_baseline['total']:+d}). "
         if pdf_baseline is not None else
         f"Revit total={revit_total}; no PDF baseline recorded for this project. ")
        + (
            "Cannot reliably filter Revit to S-201 scope until exporter includes "
            "level/view/sheet/schedule/grid metadata."
            if warnings
            else "Scope metadata present; further filtering possible."
        )
    )

    return {
        "schema_version": SCHEMA_SCOPE,
        "raw_holdown_records": len(records),
        "canonical_assemblies": len(assemblies),
        "pdf_baseline": dict(pdf_baseline) if pdf_baseline is not None else None,
        "revit_by_mark": revit_by_mark,
        "family_breakdown": dict(by_family),
        "scheduled_type_breakdown": dict(by_sched),
        "category_breakdown": dict(by_category),
        "level_breakdown": dict(by_level),
        "view_breakdown": dict(by_view),
        "elevation_buckets_ft": elev_buckets,
        "warnings": warnings,
        "recommended_filters": recommended,
        "required_exporter_fields": required,
        "summary": summary,
    }


def save_scope_diagnostics(
    raw_revit: dict[str, Any], ai_revit: dict[str, Any]
) -> dict[str, Any]:
    diag = build_scope_diagnostics(raw_revit, ai_revit)
    config.artifact_path("revit_scope_diagnostics").write_text(
        json.dumps(diag, indent=2), encoding="utf-8"
    )
    return diag


if __name__ == "__main__":  # pragma: no cover
    fake_raw = {
        "grids": [
            {"label": "A", "line": [[0, 0], [0, 10]]},
            {"label": "B", "line": [[5, 0], [5, 10]]},
            {"label": "1", "line": [[-1, 0], [10, 0]]},
            {"label": "2", "line": [[-1, 8], [10, 8]]},
        ]
    }
    cp = extract_revit_control_points(fake_raw)
    assert len(cp["points"]) == 4
    assert sorted(p["id"] for p in cp["points"]) == [
        "grid_A_1", "grid_A_2", "grid_B_1", "grid_B_2",
    ]
    pdf_cp = {
        "points": [
            {"id": "grid_A_1", "point": {"x": 100, "y": 200}},
            {"id": "grid_Z_9", "point": {"x": 0, "y": 0}},
        ]
    }
    pairs = build_pairs_from_labels(cp, pdf_cp)
    assert pairs["matched_ids"] == ["grid_A_1"]
    diag = build_scope_diagnostics(
        {"export_scope": "model", "holdowns": [{"family": "x", "scheduled_type": "HDU6"}]},
        {"canonical_holdown_assemblies": [{"pdf_mark_candidate": "H1"}]},
    )
    # Self-consistent: assert against whatever _pdf_baseline() returns for this
    # project, not a hardcoded Madera total. When no baseline is recorded the
    # pdf_baseline key is None and the assertion is skipped.
    from .control_points import _pdf_baseline as _selfcheck_baseline
    _expected = _selfcheck_baseline()
    if _expected is not None:
        assert diag["pdf_baseline"]["total"] == _expected["total"]
    else:
        assert diag["pdf_baseline"] is None
    assert diag["warnings"]
    import sys
    sys.stdout.write("control_points self-check OK\n")
