"""Adapter for schema v3.x exports from the pyRevit category-scoped exporter.

Two jobs, both additive (no frozen module changes):

1. adapt_raw(v3)      -> a raw_revit-compatible dict (walls/grids/openings/
                         comparison_view in the shapes existing consumers
                         read), carrying the full v3 element list under
                         "v3_elements" for the 3D scene and point matching.
2. build_ai_revit(v3, spec_to_mark)
                      -> an AIConvert_revit-compatible dict whose hold-down
                         assemblies are grouped from Structural Connections
                         families (body + anchor bolt + offset variants
                         clustered by plan proximity), with pdf_mark_candidate
                         assigned from the PDF schedule's own spec tokens
                         (e.g. "S/HD15S" -> HD3). Data-driven: no hardcoded
                         client vocabulary. No spec match -> mark None,
                         honestly unmatched.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any

# suffix letter must be ADJACENT to the digits ("HD15S" yes, "HD9 PAB" no)
# Two Simpson product families: HD/HDU/HDB hold-downs (Madera style) and
# HTT tension ties (Dogwood style). The key keeps the family prefix so HD4
# and HTT4 can never collide.
# Also includes MiTek/USP patterns (BHH, SDWB) for broader compatibility.
_DEFAULT_HOLDOWN_FAMILY_RE = r"(HTT|HD[UB]?|BHH|SDWB)\s*_?(\d+)([A-Z]?)"
HOLDOWN_FAMILY_RE = re.compile(
    os.environ.get("QAQC_HOLDOWN_FAMILY_RE", _DEFAULT_HOLDOWN_FAMILY_RE),
    re.IGNORECASE,
)
BOLT_FAMILY_RE = re.compile(
    r"(?:ANCHOR[_\s-]*BOLT|J[\s-]*BOLT|ANCHOR[_\s-]*ROD)", re.IGNORECASE
)
CLUSTER_TOL_FT = float(os.environ.get("QAQC_CLUSTER_TOL_FT", "2.0"))

# Mark normalization for point matching: "P-01" -> "P-1", "C2-01-02" -> "C-2".
_MARK_SIMPLE_RE = re.compile(r"^([A-Z]+)-?0*(\d+)", re.IGNORECASE)
_MARK_TYPENUM_RE = re.compile(r"^([A-Z]+)(\d+)", re.IGNORECASE)


def is_v3(raw: dict[str, Any]) -> bool:
    return str(raw.get("schema_version", "")).startswith("3")


def holdown_variant_key(text: str) -> str | None:
    """'SHDU15S-WITH BOLT' / 'S/HD15S' / 'Anchor_Bolt_SHDU9' -> '15S' / '9'.
    The digits+suffix after HD are what identify the Simpson product across
    the naming noise (SHDU15S vs S/HD15S vs S_HD15S offset).
    Also handles MiTek/USP families (BHH, SDWB)."""
    m = HOLDOWN_FAMILY_RE.search(text or "")
    if not m:
        return None
    fam = m.group(1).upper()
    # Preserve the family prefix: HTT stays HTT, BHH stays BHH, SDWB stays SDWB,
    # HD/HDU/HDB all normalize to HD.
    if fam == "HTT":
        prefix = "HTT"
    elif fam in ("BHH", "SDWB"):
        prefix = fam
    else:
        prefix = "HD"
    return f"{prefix}{int(m.group(2))}{m.group(3).upper()}"


def spec_to_mark_map(element_intelligence: dict[str, Any] | None) -> dict[str, str]:
    """From the PDF hold-down schedule rows: variant key -> plan mark.
    e.g. row HD3 with cells containing 'S/HD15S' -> {'15S': 'HD3'}."""
    mapping: dict[str, str] = {}
    if not element_intelligence:
        return mapping
    for sheet in element_intelligence.get("sheets", []):
        for table in sheet.get("tables", []):
            if table.get("category") != "holdown":
                continue
            for row in table.get("rows", []):
                mark = (row.get("mark") or "").strip().upper()
                if not mark:
                    continue
                row_text = (row.get("cells") or {}).get("row_text", "")
                # skip the mark token itself; look at the spec text after it
                spec_text = row_text.upper().replace(mark, "", 1)
                key = holdown_variant_key(spec_text)
                if key and key not in mapping:
                    mapping[key] = mark
    return mapping


_SCHED_MARK_RE = re.compile(
    os.environ.get("QAQC_SCHED_MARK_RE", r"^(?:H|HD|HDU|HTT|TD)-?\d{1,2}$"),
    re.IGNORECASE,
)


def spec_map_from_pdf_tables(
    element_intelligence: dict[str, Any] | None, pdf_path: Any
) -> dict[str, str]:
    """Fallback spec->mark map read straight from the PDF geometry.

    Some schedule layouts (Dogwood: a 1-row mini HOLDOWN SCHEDULE) defeat
    the row-band parser even though the table bbox + columns are found.
    Re-read the words inside each holdown table's own bbox and pair mark
    tokens (HD2) with product tokens (HTT4) that sit on the same text row.
    Deterministic and document-driven: nothing is invented."""
    if not element_intelligence:
        return {}
    try:
        import fitz
    except ImportError:
        return {}
    mapping: dict[str, str] = {}
    with fitz.open(str(pdf_path)) as doc:
        for sheet in element_intelligence.get("sheets", []):
            page_index = sheet.get("page_index")
            if page_index is None or page_index >= doc.page_count:
                continue
            page = None
            for table in sheet.get("tables", []):
                if table.get("category") != "holdown" or not table.get("bbox"):
                    continue
                if page is None:
                    page = doc[page_index]
                clip = fitz.Rect(*table["bbox"])
                words = page.get_text("words", clip=clip)
                # exact column x-ranges disambiguate mark vs product
                # (HD2 and HTT4 both LOOK like marks by token shape)
                mark_col = next((c for c in table.get("columns", [])
                                 if (c.get("name") or "").strip().upper()
                                 in ("MARK", "SYMBOL", "#")), None)
                type_col = next((c for c in table.get("columns", [])
                                 if "TYPE" in (c.get("name") or "").upper()),
                                None)

                def _in(col, w):
                    xc = (w[0] + w[2]) / 2
                    return col and col["x0"] <= xc <= col["x1"]

                # group words into text rows by y-center
                rows: list[list] = []
                for w in sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0])):
                    yc = (w[1] + w[3]) / 2
                    if rows and abs(rows[-1][0] - yc) <= 4.0:
                        rows[-1][1].append(w)
                    else:
                        rows.append([yc, [w]])
                for _, row_words in rows:
                    if mark_col and type_col:
                        mark = next((w[4].upper() for w in row_words
                                     if _in(mark_col, w)
                                     and _SCHED_MARK_RE.match(w[4])), None)
                        prod = next((w[4] for w in row_words
                                     if _in(type_col, w)), None)
                        key = holdown_variant_key(prod) if prod else None
                        if mark and key and key not in mapping:
                            mapping[key] = mark
                        continue
                    tokens = [w[4] for w in row_words]
                    mark = next((t.upper() for t in tokens
                                 if _SCHED_MARK_RE.match(t)), None)
                    if not mark:
                        continue
                    for t in tokens:
                        if t.upper() == mark:
                            continue
                        key = holdown_variant_key(t)
                        if key and key not in mapping:
                            mapping[key] = mark
                            break
    return mapping


def normalize_point_mark(mark: str) -> str:
    """Revit instance marks -> PDF schedule mark family.
    'P-01' -> 'P-1'; 'BP-02' -> 'BP-2'; 'C2-01-02' -> 'C-2'."""
    mark = (mark or "").strip().upper()
    if not mark:
        return ""
    m = _MARK_SIMPLE_RE.match(mark)
    if m and "-" in mark:
        prefix, num = m.group(1), int(m.group(2))
        return f"{prefix}-{num}"
    m = _MARK_TYPENUM_RE.match(mark)
    if m:
        return f"{m.group(1)}-{int(m.group(2))}"
    return mark


def adapt_raw(v3: dict[str, Any]) -> dict[str, Any]:
    """v3 export -> raw_revit-compatible dict for existing consumers."""
    walls = [
        {
            "id": w.get("id"),
            "level": w.get("level"),
            "centerline": [p[:2] for p in (w.get("base_line") or [])],
            "thickness": w.get("thickness_ft"),
            "type_name": w.get("type_name") or "",
            "mark": w.get("mark") or "",
            "height_ft": w.get("height_ft"),
            # Geometry datum (project-internal z), NOT level elevation — the
            # two can use different datums (site vs project base point).
            "base_z_ft": (
                (w.get("base_line") or [[0, 0, 0]])[0][2]
                if len((w.get("base_line") or [[0, 0]])[0]) > 2 else None
            ),
            "is_structural": w.get("is_structural"),
        }
        for w in v3.get("walls", [])
    ]
    grids = [
        {
            "id": g.get("id"),
            "label": g.get("label") or "",
            "line": [p[:2] for p in (g.get("line") or [])],
            "bbox": None,
            "level": None,
        }
        for g in v3.get("grids", [])
    ]
    view = v3.get("export_view") or {}
    holdown_records = _holdown_records(v3)
    return {
        "schema_version": v3.get("schema_version"),
        "export_scope": v3.get("export_scope", "active_view_visible"),
        "source_file": v3.get("source_model", ""),
        "units": v3.get("units", "revit_internal_feet"),
        "walls": walls,
        "rooms": [],
        "openings": [],  # dropped by design in v3 (category boundary)
        "views": [],
        "comparison_view": {
            "id": view.get("id"),
            "name": view.get("name", ""),
            "view_type": view.get("view_type", ""),
            "level": view.get("level"),
            "scale": None,
            "crop_bbox": None,
        },
        "grids": grids,
        "levels": v3.get("levels", []),
        "discovery_instances": holdown_records,
        "holdowns": holdown_records,
        "benchmarks": v3.get("benchmarks", []),
        "v3_elements": v3.get("elements", []),
        "assumptions": [
            "Schema v3 export: only the seven curated categories, scoped to "
            "elements visible in the export view.",
            v3.get("scoping_note", ""),
        ],
    }


# R-10: hold-downs are not always modelled as Structural Connections. Some
# firms place them as Generic Models or nest them in Structural Framing, and
# searching only the first two silently makes the whole report PDF_ONLY. The
# extra categories are swept ONLY for families the hold-down regex recognises
# (holdown_variant_key != None), so a model's 28k framing members can't leak in.
_DEFAULT_HOLDOWN_CATEGORIES = (
    "Structural Connections",
    "Structural Foundation",
    "Generic Models",
    "Structural Framing",
)
_env_cats = os.environ.get("QAQC_HOLDOWN_CATEGORIES", "").strip()
if _env_cats:
    HOLDOWN_CATEGORIES = tuple(s.strip() for s in _env_cats.split(",") if s.strip())
else:
    HOLDOWN_CATEGORIES = _DEFAULT_HOLDOWN_CATEGORIES


def _holdown_records(v3: dict[str, Any]) -> list[dict[str, Any]]:
    """Hold-down-family records (v2 record shape) from HOLDOWN_CATEGORIES."""
    records = []
    for e in v3.get("elements", []):
        if e.get("category") not in HOLDOWN_CATEGORIES:
            continue
        family = e.get("family") or ""
        if holdown_variant_key(family) is None:
            continue
        point = (e.get("location") or {}).get("point") or [0, 0, 0]
        bbox = e.get("bbox")
        records.append({
            "element_id": e.get("id"),
            "integer_id": 0,
            "category": e.get("category"),
            "family": family,
            "type_name": e.get("type_name") or "",
            "mark": e.get("mark") or "",
            "scheduled_type": "",
            "level": e.get("level"),
            "location": point[:2],
            "elevation": e.get("elevation_ft", point[2] if len(point) > 2 else 0.0),
            "bbox": ([bbox[0][0], bbox[0][1], bbox[1][0], bbox[1][1]] if bbox else None),
            "raw_parameters": e.get("params") or {},
        })
    return records


def build_ai_revit(
    v3: dict[str, Any], spec_to_mark: dict[str, str] | None = None
) -> dict[str, Any]:
    """Cluster hold-down records into assemblies; assign PDF marks from the
    schedule-learned spec map. Same output shape as AIConvert_revit."""
    spec_to_mark = spec_to_mark or {}
    records = _holdown_records(v3)
    clusters: list[dict[str, Any]] = []
    for rec in records:
        x, y = rec["location"]
        placed = False
        for cluster in clusters:
            cx, cy = cluster["xy"]
            if abs(x - cx) <= CLUSTER_TOL_FT and abs(y - cy) <= CLUSTER_TOL_FT:
                cluster["members"].append(rec)
                placed = True
                break
        if not placed:
            clusters.append({"xy": (x, y), "members": [rec]})

    # One assembly per BODY member — a proximity cluster can hold two
    # physically adjacent hold-downs (2 bodies + 2 bolts); emitting one
    # assembly for such a cluster silently halves the Revit side.
    # body = not an anchor bolt and not an 'offset' companion variant.
    def _is_body(m: dict[str, Any]) -> bool:
        fam = m["family"]
        return not BOLT_FAMILY_RE.search(fam) and "offset" not in fam.lower()

    groups: list[list[dict[str, Any]]] = []
    for cluster in clusters:
        members = cluster["members"]
        bodies = [m for m in members if _is_body(m)]
        if len(bodies) <= 1:
            groups.append(members)
            continue
        split: list[list[dict[str, Any]]] = [[b] for b in bodies]
        for m in members:
            if _is_body(m):
                continue
            mx, my = m["location"]
            nearest = min(
                range(len(bodies)),
                key=lambda j: (bodies[j]["location"][0] - mx) ** 2
                + (bodies[j]["location"][1] - my) ** 2,
            )
            split[nearest].append(m)
        groups.extend(split)

    assemblies = []
    for i, members in enumerate(groups, start=1):
        body = next((m for m in members if _is_body(m)), members[0])
        key = holdown_variant_key(body["family"])
        mark = spec_to_mark.get(key or "")
        x, y = body["location"]
        assemblies.append({
            "id": f"rev_asm_{i:03d}",
            "pdf_mark_candidate": mark,
            "core_token": key or "",
            "scheduled_type_raw": body["family"],
            "family_type_summary": {
                fam: sum(1 for m in members if m["family"] == fam)
                for fam in {m["family"] for m in members}
            },
            "member_element_ids": [m["element_id"] for m in members],
            "primary_element_id": body["element_id"],
            "center_point": {"x": x, "y": y, "z": body.get("elevation")},
            "bbox": body.get("bbox"),
            "level": body.get("level"),
            "classification_confidence": 0.9 if mark else 0.5,
            "classification_reason": (
                f"Family {body['family']!r} -> variant '{key}' -> mark "
                f"{mark!r} via the PDF hold-down schedule specs."
                if mark else
                f"Family {body['family']!r} (variant '{key}') has no matching "
                "spec row in the PDF hold-down schedule - mark unassigned."
            ),
        })

    marks = sorted({a["pdf_mark_candidate"] for a in assemblies if a["pdf_mark_candidate"]})
    return {
        "schema_version": "ai-revit-convert/3.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": v3.get("source_model", ""),
        "converter": "revit_v3_adapter (schedule-spec driven, deterministic)",
        "canonical_holdown_assemblies": assemblies,
        # R-10: say which Revit categories were swept, so "0 hold-downs found"
        # can be read as "not in these categories" instead of "none exist".
        "searched_categories": list(HOLDOWN_CATEGORIES),
        "summary": {
            "assembly_count": len(assemblies),
            "marks_assigned": marks,
            "unassigned": sum(1 for a in assemblies if not a["pdf_mark_candidate"]),
        },
    }


if __name__ == "__main__":
    assert holdown_variant_key("SHDU15S-WITH BOLT") == "HD15S"
    assert holdown_variant_key("Anchor_Bolt_SHDU9") == "HD9"
    assert holdown_variant_key("S_HD15S offset") == "HD15S"
    assert holdown_variant_key("S/HDB15") == "HD15"
    assert holdown_variant_key("HTT4") == "HTT4"            # Dogwood ties
    assert holdown_variant_key("HTT4 both side") == "HTT4"
    assert holdown_variant_key("Anchor_Bolt_HTT5") == "HTT5"
    assert holdown_variant_key("J-Anchor Bolt") is None
    assert holdown_variant_key("PanelLocator") is None
    assert normalize_point_mark("P-01") == "P-1"
    assert normalize_point_mark("BP-02") == "BP-2"
    assert normalize_point_mark("C2-01-02") == "C-2"

    ei = {"sheets": [{"tables": [{"category": "holdown", "rows": [
        {"mark": "HD3", "cells": {"row_text": "HD3 S/HD15S PAB6H (30) #14 SCREWS"}},
        {"mark": "HD2", "cells": {"row_text": "HD2 S/HDU9 PAB6H (18) #14 SCREWS"}},
    ]}]}]}
    m = spec_to_mark_map(ei)
    assert m == {"HD15S": "HD3", "HD9": "HD2"}, m

    v3 = {"schema_version": "3.1", "source_model": "m.rvt",
          "walls": [{"id": "w1", "base_line": [[0, 0, 0], [10, 0, 0]],
                     "thickness_ft": 0.5, "level": "L1"}],
          "grids": [{"id": "g", "label": "A", "line": [[0, 0, 0], [0, 9, 0]]}],
          "export_view": {"name": "3D"},
          "elements": [
              {"id": "b1", "category": "Structural Connections",
               "family": "SHDU15S-WITH BOLT", "mark": "",
               "location": {"point": [5.0, 5.0, 1.0]}, "elevation_ft": 1.0},
              {"id": "a1", "category": "Structural Connections",
               "family": "Anchor_Bolt_SHDU15S", "mark": "",
               "location": {"point": [5.4, 5.2, 0.5]}, "elevation_ft": 0.5},
              {"id": "p1", "category": "Structural Connections",
               "family": "PanelLocator", "mark": "P-01",
               "location": {"point": [8, 8, 0]}, "elevation_ft": 0.0},
          ]}
    raw = adapt_raw(v3)
    assert raw["walls"][0]["centerline"] == [[0, 0], [10, 0]]
    assert raw["openings"] == [] and len(raw["v3_elements"]) == 3
    ai = build_ai_revit(v3, m)
    assert ai["summary"]["assembly_count"] == 1  # body+bolt clustered
    asm = ai["canonical_holdown_assemblies"][0]
    assert asm["pdf_mark_candidate"] == "HD3" and asm["primary_element_id"] == "b1"
    assert len(asm["member_element_ids"]) == 2

    # two adjacent hold-downs in ONE proximity cluster must stay 2 assemblies
    v3b = dict(v3)
    v3b["elements"] = [
        {"id": "b1", "category": "Structural Connections",
         "family": "SHDU15S-WITH BOLT", "mark": "",
         "location": {"point": [5.0, 5.0, 1.0]}, "elevation_ft": 1.0},
        {"id": "a1", "category": "Structural Connections",
         "family": "Anchor_Bolt_SHDU15S", "mark": "",
         "location": {"point": [5.1, 5.0, 0.5]}, "elevation_ft": 0.5},
        {"id": "b2", "category": "Structural Connections",
         "family": "SHDU15S-WITH BOLT", "mark": "",
         "location": {"point": [6.2, 5.0, 1.0]}, "elevation_ft": 1.0},
        {"id": "a2", "category": "Structural Connections",
         "family": "Anchor_Bolt_SHDU15S", "mark": "",
         "location": {"point": [6.3, 5.0, 0.5]}, "elevation_ft": 0.5},
    ]
    ai2 = build_ai_revit(v3b, m)
    assert ai2["summary"]["assembly_count"] == 2, ai2["summary"]
    pairs = sorted(tuple(sorted(a["member_element_ids"]))
                   for a in ai2["canonical_holdown_assemblies"])
    assert pairs == [("a1", "b1"), ("a2", "b2")], pairs

    # R-10: a Generic Model / Structural Framing hold-down is found, but only
    # when its family is recognisable — plain framing is never swept in.
    v3c = {"elements": [
        {"id": "g1", "category": "Generic Models", "family": "S/HD15S",
         "location": {"point": [0.0, 0.0, 0.0]}},
        {"id": "f1", "category": "Structural Framing", "family": "SHDU9",
         "location": {"point": [50.0, 0.0, 0.0]}},
        {"id": "f2", "category": "Structural Framing", "family": "2x6 Stud",
         "location": {"point": [51.0, 0.0, 0.0]}},
        {"id": "x1", "category": "Casework", "family": "S/HD15S",
         "location": {"point": [90.0, 0.0, 0.0]}},   # category not searched
    ]}
    ai3 = build_ai_revit(v3c, {"HD15S": "HD3", "HD9": "HD2"})
    got = {a["primary_element_id"]: a["pdf_mark_candidate"]
           for a in ai3["canonical_holdown_assemblies"]}
    assert got == {"g1": "HD3", "f1": "HD2"}, got
    assert "Generic Models" in ai3["searched_categories"]

    print("revit_v3_adapter self-check OK:", ai["summary"], ai2["summary"])
