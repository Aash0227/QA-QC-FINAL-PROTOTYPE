# Revit Exporter Requirements — what the QA-QC tool needs from `revit_export.json`

**Audience:** whoever owns the Revit exporter add-in.
**Why:** every gap below is currently a hard ceiling on automatic match accuracy.
The matching logic on the tool side is already built — it lights up the moment the data arrives.

## 1. Structural posts and steel columns (CRITICAL — 153 elements blocked)

The export contains no post/column instances, so 153 extracted PDF elements can
only be flagged `NO_REVIT_DATA`. Add, per instance:

```json
{
  "category": "post" | "steel_column",
  "element_id": "...",
  "mark": "P-1",              // the schedule mark if present
  "type_name": "600S162-43MIL",
  "location": [x_ft, y_ft],
  "elevation": 1.5,
  "level": "Level 1"
}
```

## 2. Level per element (HIGH — kills REVIT_ONLY noise)

Today every `discovery_instances[]` record has `"level": null`. The whole-model
export therefore stacks hold-downs from all floors onto one comparison, which is
why Revit shows 72 assemblies against 54 on the foundation sheet (REVIT_ONLY
noise). Populate `level` with the Revit Level name per instance. (The tool
already falls back to elevation-band clustering, but real level names are
exact.)

## 3. Export scope per sheet/view (HIGH)

`export_scope` is `"model"`. Either export per active view
(`export_scope: "active_view"`, matching each drawing sheet), or include
`"sheet"` / `"view"` fields per instance so the tool can scope precisely.

## 4. Grids (KEEP — already good)

`grids[]` with `label` + `line` endpoints is what enables automatic
grid-intersection registration on sheets with few hold-downs. Keep exporting
them for every project.

## 5. Wall height (LOW)

Walls carry no height; the 3D view assumes 10 ft and labels it as assumed.
Add `height_ft` per wall when convenient.

---

**Format stability:** everything above is additive to the existing schema —
no existing field needs to change. The tool ignores unknown fields, so the
exporter can ship these incrementally.
