"""Element registry: joins every extraction/matching output into one list.

compare.py stays byte-identical — hold-down verdicts are read from its report.
Statuses are honest by construction:

  MATCH / LOCATION_MISMATCH / PDF_ONLY / REVIT_ONLY / NEEDS_REVIEW
      — real matching outcomes (hold-downs via compare.py, shear walls via
        wall_match.py)
  NO_REVIT_DATA   — category absent from the Revit export (posts, columns);
                    can never be MATCH until the exporter ships that data
  NOT_IN_SCHEDULE — mark seen on the plan but missing from every schedule table
  SPEC_ONLY       — schedule row without plan geometry (wall types)
  NOT_EVALUATED   — extracted mark on a sheet whose category has no matching
                    pipeline run (e.g. hold-down callouts on a wall-plan sheet)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "element-list/1.0"

NO_REVIT_CATEGORIES = ("post", "steel_column")


def _discover_primary_sheet(element_intelligence: dict[str, Any]) -> str | None:
    """Discover the primary holdown comparison sheet dynamically.
    
    Priority:
    1. First sheet with holdown marks in element_intelligence
    2. First sheet with holdown tables
    3. None (no holdown data found)
    """
    sheets = element_intelligence.get("sheets", [])
    
    # First pass: look for sheets with holdown marks
    for sheet in sheets:
        for mark in sheet.get("marks", []):
            if mark.get("category") == "holdown":
                return sheet.get("sheet_number")
    
    # Second pass: look for sheets with holdown tables
    for sheet in sheets:
        for table in sheet.get("tables", []):
            if table.get("category") == "holdown":
                return sheet.get("sheet_number")
    
    # Fallback: first sheet with any marks
    for sheet in sheets:
        if sheet.get("marks"):
            return sheet.get("sheet_number")
    
    return None


def build_element_list(
    element_intelligence: dict[str, Any],
    compare_report: dict[str, Any] | None,
    wall_reports: dict[str, dict[str, Any]] | None,
    compare_sheet: str | None = None,
    holdown_sheet_reports: dict[str, dict[str, Any]] | None = None,
    point_reports: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    # Dynamic discovery of compare_sheet if not provided.
    if compare_sheet is None:
        compare_sheet = _discover_primary_sheet(element_intelligence)
    sheets_meta = {
        s["sheet_number"]: s for s in element_intelligence.get("sheets", [])
    }
    vocab_specs = _vocab_specs(element_intelligence)
    elements: list[dict[str, Any]] = []

    # --- Hold-downs: authoritative rows from the frozen compare pipeline. ----
    if compare_report:
        page_index = sheets_meta.get(compare_sheet, {}).get("page_index")
        for row in compare_report.get("final_verdicts", []):
            elements.append(_holdown_element(row, compare_sheet, page_index, vocab_specs))

    # --- Hold-downs on OTHER registered sheets: the same frozen compare() run
    # per sheet with that sheet's calibration. Only PDF-side rows are taken;
    # Revit assemblies are already represented once by the main report above.
    for sheet_number, report in (holdown_sheet_reports or {}).items():
        page_index = sheets_meta.get(sheet_number, {}).get("page_index")
        for row in report.get("final_verdicts", []):
            if not row.get("pdf_holdown_id"):
                continue
            elements.append(_holdown_element(row, sheet_number, page_index, vocab_specs))

    # --- Posts / steel columns etc. with v3 Revit data: same frozen compare()
    # per (category, sheet). PDF-side rows only (Revit points appear once as
    # matches or stay in the model; no cross-sheet REVIT_ONLY duplication).
    for category, sheet_reports in (point_reports or {}).items():
        for sheet_number, report in sheet_reports.items():
            page_index = sheets_meta.get(sheet_number, {}).get("page_index")
            for row in report.get("final_verdicts", []):
                if not row.get("pdf_holdown_id"):
                    continue
                el = _holdown_element(row, sheet_number, page_index, vocab_specs)
                el["category"] = category
                el["spec"] = vocab_specs.get((category, row.get("mark")))
                if el.get("revit_ref"):
                    el["revit_ref"]["kind"] = category
                elements.append(el)

    # --- Shear walls: per-sheet wall-match reports. ---------------------------
    matched_wall_ids: set[str] = set()
    covered_sw_ids: set[str] = set()
    for sheet_number, report in (wall_reports or {}).items():
        page_index = sheets_meta.get(sheet_number, {}).get("page_index")
        for row in report.get("rows", []):
            covered_sw_ids.add(row["pdf_mark_id"])
            if row.get("revit_wall_id"):
                matched_wall_ids.add(row["revit_wall_id"])
            elements.append(
                {
                    "id": row["pdf_mark_id"],
                    "category": "shear_wall",
                    "mark": row["mark"],
                    "sheet": sheet_number,
                    "page_index": page_index,
                    "pdf_point": row.get("pdf_point"),
                    "bbox_pdf": _mark_bbox(sheets_meta.get(sheet_number), row["pdf_mark_id"]),
                    "spec": vocab_specs.get(("shear_wall", row["mark"])),
                    "status": row["verdict"],
                    "distance_pdf_points": row.get("distance_pdf_points"),
                    "revit_ref": (
                        {"kind": "wall", "id": row["revit_wall_id"],
                         "type_name": row.get("revit_wall_type")}
                        if row.get("revit_wall_id") else None
                    ),
                    "wall_segment_pdf": row.get("wall_segment_pdf"),
                    "drawable": bool(row.get("pdf_point")),
                    "schedule_listed": True,
                    "reason": row.get("reason"),
                }
            )
    # Walls unmatched across ALL sheet reports -> REVIT_ONLY (listed once).
    seen_unmatched: set[str] = set()
    for report in (wall_reports or {}).values():
        for w in report.get("unmatched_revit_walls", []):
            wid = w["revit_wall_id"]
            if wid in matched_wall_ids or wid in seen_unmatched:
                continue
            seen_unmatched.add(wid)
            elements.append(
                {
                    "id": f"revit_wall_{wid}",
                    "category": "shear_wall",
                    "mark": w["token"],
                    "sheet": None,
                    "page_index": None,
                    "pdf_point": None,
                    "bbox_pdf": None,
                    "spec": vocab_specs.get(("shear_wall", w["token"])),
                    "status": "REVIT_ONLY",
                    "distance_pdf_points": None,
                    "revit_ref": {"kind": "wall", "id": wid, "type_name": w.get("type_name")},
                    "drawable": False,
                    "schedule_listed": True,
                    "reason": "Revit shear wall with no PDF callout partner on any matched sheet.",
                }
            )

    # --- Everything else from the generic extraction. -------------------------
    # Iterate the raw sheet list, not sheets_meta: two sheets sharing a
    # sheet_number would collapse in the dict and silently drop that sheet's
    # marks.
    for sheet in element_intelligence.get("sheets", []):
        sheet_number = sheet["sheet_number"]
        for m in sheet.get("marks", []):
            category = m["category"]
            if category == "shear_wall" and m["id"] in covered_sw_ids:
                continue
            if category == "holdown" and compare_report and sheet_number == compare_sheet:
                continue  # authoritative rows already emitted from compare.py
            if (
                category == "holdown"
                and m["schedule_listed"]
                and sheet_number in (holdown_sheet_reports or {})
            ):
                continue  # covered by that sheet's own compare run above
            if (
                m["schedule_listed"]
                and sheet_number in (point_reports or {}).get(category, {})
            ):
                continue  # covered by that category's own compare run above
            if category in NO_REVIT_CATEGORIES:
                status = "NO_REVIT_DATA" if m["schedule_listed"] else "NOT_IN_SCHEDULE"
                reason = (
                    "Category not present in the Revit export — awaiting exporter "
                    "support; extraction + schedule QA only."
                    if m["schedule_listed"]
                    else "Mark appears on the plan but is missing from every schedule table."
                )
            elif not m["schedule_listed"]:
                status, reason = "NOT_IN_SCHEDULE", (
                    "Mark appears on the plan but is missing from every schedule table."
                )
            else:
                status, reason = "NOT_EVALUATED", (
                    f"No {category} matching pipeline ran for sheet {sheet_number}."
                )
            elements.append(
                {
                    "id": m["id"],
                    "category": category,
                    "mark": m["mark"],
                    "sheet": sheet_number,
                    "page_index": sheet["page_index"],
                    "pdf_point": {"x": m["center_pdf"][0], "y": m["center_pdf"][1]},
                    "bbox_pdf": m.get("bbox_pdf"),
                    "spec": vocab_specs.get((category, m["mark"])),
                    "status": status,
                    "distance_pdf_points": None,
                    "revit_ref": None,
                    "drawable": True,
                    "schedule_listed": m["schedule_listed"],
                    "reason": reason,
                }
            )

    # --- Wall types: schedule rows only, no plan geometry. ---------------------
    for (category, mark), spec in sorted(vocab_specs.items()):
        if category != "wall_type":
            continue
        elements.append(
            {
                "id": f"wall_type_{mark}",
                "category": "wall_type",
                "mark": mark,
                "sheet": None,
                "page_index": None,
                "pdf_point": None,
                "bbox_pdf": None,
                "spec": spec,
                "status": "SPEC_ONLY",
                "distance_pdf_points": None,
                "revit_ref": None,
                "drawable": False,
                "schedule_listed": True,
                "reason": "Schedule specification row; wall types are not called out as point marks.",
            }
        )

    counts = _counts(elements)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sheets": [s["sheet_number"] for s in element_intelligence.get("sheets", []) if s.get("marks")],
        "counts": counts,
        "count_consistency": {
            s["sheet_number"]: s.get("count_consistency", [])
            for s in element_intelligence.get("sheets", [])
        },
        "elements": elements,
    }


def scope_warnings(
    device_summary: dict[str, dict[str, Any]] | None,
    raw_revit: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """R-07: PDF callouts but ZERO Revit targets in a category almost always
    means the export view hid the category, not that the modeller omitted it
    (the Dogwood shear-wall bug). Display-only — no status is changed."""
    view = ((raw_revit or {}).get("comparison_view") or {}).get("name")
    export_view = view or (raw_revit or {}).get("export_scope")
    out: list[dict[str, Any]] = []
    for category, summary in sorted((device_summary or {}).items()):
        pdf_count = summary.get("callout_rows") or 0
        revit_count = summary.get("revit_targets") or 0
        if pdf_count > 0 and revit_count == 0:
            out.append({
                "category": category,
                "pdf_count": pdf_count,
                "revit_count": revit_count,
                "export_view": export_view,
                "message": (
                    f"No {category} elements in the Revit export. These "
                    f"PDF_ONLY verdicts may be wrong — confirm the export "
                    f"view has {category} visible."),
            })
    return out


def _holdown_element(
    row: dict[str, Any],
    sheet: str | None,
    page_index: int | None,
    vocab_specs: dict[tuple[str, str], Any],
) -> dict[str, Any]:
    pdf_point = row.get("pdf_point")
    tf = row.get("revit_point_transformed_to_pdf")
    display_point = pdf_point or tf
    elem_id = row.get("pdf_holdown_id") or f"revit_only_{row.get('revit_assembly_id')}"
    return {
        "id": elem_id,
        "category": "holdown",
        "mark": row.get("mark"),
        "sheet": sheet,
        "page_index": page_index,
        "pdf_point": pdf_point,
        "revit_point_transformed_to_pdf": tf,
        "bbox_pdf": None,
        "spec": vocab_specs.get(("holdown", row.get("mark"))),
        "status": row.get("verdict"),
        "distance_pdf_points": row.get("distance_pdf_points"),
        "revit_ref": (
            {"kind": "holdown_assembly", "id": row.get("revit_assembly_id"), "type_name": None}
            if row.get("revit_assembly_id") else None
        ),
        "drawable": bool(display_point),
        "schedule_listed": True,
        "reason": row.get("reason"),
        "confidence": row.get("confidence"),
        "nearest_revit_candidates": row.get("nearest_revit_candidates"),
        "nearest_pdf_candidates": row.get("nearest_pdf_candidates"),
    }


def _vocab_specs(element_intelligence: dict[str, Any]) -> dict[tuple[str, str], Any]:
    specs: dict[tuple[str, str], Any] = {}
    for sheet in element_intelligence.get("sheets", []):
        for table in sheet.get("tables", []):
            category = table.get("category")
            for row in table.get("rows", []):
                mark = row.get("mark")
                if mark:
                    specs.setdefault((category, mark), row.get("cells"))
    return specs


def _mark_bbox(sheet: dict[str, Any] | None, mark_id: str) -> list[float] | None:
    if not sheet:
        return None
    for m in sheet.get("marks", []):
        if m["id"] == mark_id:
            return m.get("bbox_pdf")
    return None


def _counts(elements: list[dict[str, Any]]) -> dict[str, Any]:
    by_category: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_sheet: dict[str, int] = {}
    for e in elements:
        by_category[e["category"]] = by_category.get(e["category"], 0) + 1
        by_status[e["status"]] = by_status.get(e["status"], 0) + 1
        if e.get("sheet"):
            by_sheet[e["sheet"]] = by_sheet.get(e["sheet"], 0) + 1
    return {
        "total": len(elements),
        "by_category": dict(sorted(by_category.items())),
        "by_status": dict(sorted(by_status.items())),
        "by_sheet": dict(sorted(by_sheet.items())),
    }
