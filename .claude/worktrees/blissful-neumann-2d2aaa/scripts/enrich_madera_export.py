"""Enrich the v3.1 Madera export with real model data recovered from the
prior v2 export of the SAME model (identity verified live via Revit MCP:
19 structural columns + identical SHDU family set).

Deterministic, provenance-tagged. Two enrichments:
1. Wall type_name backfill by stable UniqueId join (exporter bug left all
   type_name empty; fixed in the exporter for future runs).
2. Merge shear walls (type_name contains 'SW') that the curated 3D export
   view hides but the drawings reference. Tagged source=v2_export_merge.
"""
import json

V3 = r"C:\Users\aashd\Downloads\wetransfer_madera-model-and-permit-sets_2026-05-13_1004\revit_export.json"
V2 = r"C:\QA-QC-FINAL-PROTOTYPE-bkp\artifacts\projects\madera_prev_v2_run\raw_revit_export.json"
OUT = r"C:\Users\aashd\Downloads\wetransfer_madera-model-and-permit-sets_2026-05-13_1004\revit_export_enriched.json"

new = json.load(open(V3, encoding="utf-8"))
old = json.load(open(V2, encoding="utf-8"))

levels = {l["name"]: l["elevation_ft"] for l in new["levels"]}
elevs = sorted(levels.values())


def level_height(name):
    z = levels.get(name)
    if z is None:
        return None
    above = [e for e in elevs if e > z + 0.01]
    return round(above[0] - z, 2) if above else None


v2_by_id = {w["id"]: w for w in old["walls"]}

# 1. type_name backfill on the 50 view-visible walls
filled = 0
for w in new["walls"]:
    src = v2_by_id.get(w["id"])
    if src and not w.get("type_name") and src.get("type_name"):
        w["type_name"] = src["type_name"]
        w["type_name_source"] = "v2_export_id_join"
        filled += 1

# 2. merge hidden SW walls
present = {w["id"] for w in new["walls"]}
merged = 0
for src in old["walls"]:
    tn = (src.get("type_name") or "").upper()
    if "SW" not in tn or src["id"] in present:
        continue
    z = levels.get(src.get("level") or "", 0.0)
    cl = src.get("centerline") or []
    if len(cl) != 2:
        continue
    new["walls"].append({
        "id": src["id"],
        "type_name": src.get("type_name") or "",
        "mark": "",
        "level": src.get("level"),
        "base_line": [[cl[0][0], cl[0][1], z], [cl[1][0], cl[1][1], z]],
        "thickness_ft": src.get("thickness"),
        "height_ft": level_height(src.get("level") or ""),
        "is_structural": True,
        "source": "v2_export_merge",
    })
    merged += 1

# 3. merge holdown elements hidden in the export view (same id join)
el_ids = {e["id"] for e in new["elements"]}
hd_merged = 0
for src in old.get("holdowns", []):
    eid = src.get("element_id")
    loc = src.get("location")
    if not eid or eid in el_ids or not loc:
        continue
    z = src.get("elevation") or 0.0
    new["elements"].append({
        "id": eid,
        "category": src.get("category") or "Structural Connections",
        "family": src.get("family") or "",
        "type_name": "",
        "mark": src.get("mark") or "",
        "level": src.get("level"),
        "elevation_ft": z,
        "location": {"point": [loc[0], loc[1], z]},
        # v2 bbox is flat [x1,y1,x2,y2]; v3 expects [[min...],[max...]]
        "bbox": ([[src["bbox"][0], src["bbox"][1]],
                  [src["bbox"][2], src["bbox"][3]]]
                 if src.get("bbox") and len(src["bbox"]) == 4 else None),
        "params": {},
        "source": "v2_export_merge",
    })
    hd_merged += 1

new["scoping_note"] = (new.get("scoping_note") or "") + (
    " | ENRICHED: wall type_name backfilled from v2 export by UniqueId "
    "(%d walls); %d shear walls hidden in the export view merged from the "
    "v2 doc-wide export (source=v2_export_merge); %d holdown elements "
    "hidden in the export view merged likewise. Model identity verified "
    "via live Revit MCP." % (filled, merged, hd_merged))

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(new, f, ensure_ascii=True, default=str)

sw = sum(1 for w in new["walls"] if "SW" in (w.get("type_name") or "").upper())
print("type_name filled:", filled, "| SW walls merged:", merged,
      "| holdown elements merged:", hd_merged,
      "| total walls:", len(new["walls"]), "| SW-typed:", sw)
assert merged > 0 and sw >= merged and hd_merged > 0
