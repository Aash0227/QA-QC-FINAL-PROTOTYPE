# -*- coding: utf-8 -*-
"""Pure export-payload builder for the Livio QA-QC exporter (schema v3.1).

No Revit API imports here: the button script converts Revit elements into
plain dicts and this module assembles the final JSON payload. That keeps the
logic unit-testable under plain CPython (tests run outside Revit) and the
Revit glue trivially thin.

Runs under IronPython 2.7 (pyRevit engine) AND CPython 3 — keep syntax
compatible with both (no f-strings).
"""
import re

SCHEMA_VERSION = "3.1"
GENERATOR = "Livio pyRevit exporter v3.1 (view-scoped, category-filtered)"

# The seven curated categories, in display order.
CATEGORIES = [
    "Columns",
    "Stairs",
    "Structural Columns",
    "Structural Connections",
    "Structural Foundation",
    "Structural Framing",
    "Walls",
]


def sanitize_strings(obj):
    """Recursively coerce every byte-string in the payload to unicode.

    Revit parameter values can carry raw cp1252 bytes (e.g. 0xD8 for the
    diameter symbol) that IronPython's json.dumps cannot decode — the whole
    export dies with UnicodeDecodeError. utf-8 first, then latin-1 (which
    maps ALL 256 byte values, so it can never fail)."""
    if isinstance(obj, bytes):
        try:
            return obj.decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            return obj.decode("latin-1")
    if isinstance(obj, dict):
        return dict((sanitize_strings(k), sanitize_strings(v))
                    for k, v in obj.items())
    if isinstance(obj, list):
        return [sanitize_strings(x) for x in obj]
    if isinstance(obj, tuple):
        return [sanitize_strings(x) for x in obj]
    return obj


_BM_MARK_RE = re.compile(r"^BM[-_ ]?\d$", re.IGNORECASE)


def is_benchmark(family, mark):
    """Registration benchmark detection: family name contains 'Benchmark'
    (case-insensitive) OR Mark matches BM-<digit>."""
    if family and "benchmark" in family.lower():
        return True
    return bool(mark and _BM_MARK_RE.match(mark.strip()))


def build_export(source_model, view_info, levels, grids, walls, elements,
                 exported_at, benchmarks=None):
    """Assemble the schema v3.1 payload.

    walls: list of wall dicts (id, type_name, mark, level, base_line,
           thickness_ft, height_ft, is_structural)
    elements: list of element dicts (id, category, family, type_name, mark,
           level, elevation_ft, location{point[,curve]}, bbox, params)
    view_info: dict describing the ACTIVE view the export was scoped to
           (id, name, view_type, level) — the honest provenance of the counts.
    benchmarks: optional list of registration benchmark instances
           (id, mark, family, level, point_ft{x,y,z}) — document-wide,
           coordinates in revit internal feet.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "generator": GENERATOR,
        "exported_at": exported_at,
        "source_model": source_model,
        "units": "revit_internal_feet",
        "export_scope": "active_view_visible",
        "scoping_note": (
            "Only elements VISIBLE in the export view are included - "
            "visibility/graphics overrides, filters, phases and design "
            "options all apply. Curate the view, then export."
        ),
        "categories": list(CATEGORIES),
        "export_view": view_info,
        "levels": sorted(levels, key=lambda l: l.get("elevation_ft", 0.0)),
        "grids": grids,
        "walls": walls,
        "elements": elements,
        "benchmarks": benchmarks or [],
    }


def category_counts(payload):
    """{category: count} for the success dialog — walls have their own list."""
    counts = {}
    for name in CATEGORIES:
        if name == "Walls":
            counts[name] = len(payload.get("walls", []))
        else:
            counts[name] = sum(
                1 for e in payload.get("elements", [])
                if e.get("category") == name
            )
    return counts


def format_counts(counts):
    lines = []
    for name in CATEGORIES:
        lines.append("   {0}:  {1}".format(name, counts.get(name, 0)))
    return "\n".join(lines)


if __name__ == "__main__":
    payload = build_export(
        source_model="model.rvt",
        view_info={"name": "{3D} curated"},
        levels=[{"name": "L2", "elevation_ft": 10.0},
                {"name": "L1", "elevation_ft": 0.0}],
        grids=[{"label": "A", "line": [[0, 0, 0], [0, 100, 0]]}],
        walls=[{"id": "w1"}],
        elements=[{"id": "e1", "category": "Structural Columns"},
                  {"id": "e2", "category": "Structural Columns"},
                  {"id": "e3", "category": "Stairs"}],
        exported_at="2026-01-01T00:00:00Z",
    )
    assert payload["levels"][0]["name"] == "L1"
    counts = category_counts(payload)
    assert counts["Walls"] == 1 and counts["Structural Columns"] == 2
    assert counts["Columns"] == 0 and counts["Stairs"] == 1
    assert "Columns:  0" in format_counts(counts)
    assert payload["export_scope"] == "active_view_visible"
    assert payload["benchmarks"] == []
    assert is_benchmark("Livio Benchmark Marker", "")
    assert is_benchmark("Generic Model", "BM-1")
    assert is_benchmark("Generic Model", "bm 2")
    assert not is_benchmark("Generic Model", "BM-12")   # single digit only
    assert not is_benchmark("Holdown HDU2", "H2")
    with_bm = build_export("m.rvt", {}, [], [], [], [], "t",
                           benchmarks=[{"mark": "BM-1",
                                        "point_ft": {"x": 1, "y": 2, "z": 0}}])
    assert with_bm["benchmarks"][0]["mark"] == "BM-1"
    print("qaqc_export_core self-check OK")
