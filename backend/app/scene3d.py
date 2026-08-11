"""3D scene payload for the frontend Three.js view.

Built ONLY from real Revit export geometry (wall centerlines + thickness,
hold-down locations + elevations, grid lines) joined with match statuses from
the element list. Wall height is NOT in the export — it is emitted with
height_assumed=true and must be labeled as assumed in the UI, never presented
as model truth.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

from .wall_match import sw_token

SCHEMA_VERSION = "scene3d/1.0"
ASSUMED_WALL_HEIGHT_FT = float(os.environ.get("QAQC_ASSUMED_WALL_HEIGHT_FT", "10.0"))


def build_scene(
    raw_revit: dict[str, Any],
    element_list: dict[str, Any] | None,
    ai_revit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # Datum from the GEOMETRY itself: Level.Elevation can be in the shared
    # site basis (~346 ft) while element coordinates are internal (~0-16 ft),
    # so levels are useless as a render datum. v2 exports (no v3_elements)
    # keep z0=0 — unchanged behavior.
    elevs = [
        e.get("elevation_ft")
        for e in raw_revit.get("v3_elements", [])
        if isinstance(e.get("elevation_ft"), (int, float))
    ]
    z0 = min(elevs) if elevs else 0.0

    wall_status: dict[str, str] = {}
    holdown_status: dict[str, str] = {}
    for e in (element_list or {}).get("elements", []):
        ref = e.get("revit_ref")
        if not ref or not ref.get("id"):
            continue
        if ref["kind"] == "wall":
            wall_status[ref["id"]] = e["status"]
        elif ref["kind"] == "holdown_assembly":
            holdown_status[ref["id"]] = e["status"]

    walls = []
    xs: list[float] = []
    ys: list[float] = []
    for w in raw_revit.get("walls", []):
        line = w.get("centerline")
        if not line or len(line) != 2:
            continue
        token = sw_token(w.get("type_name"))
        real_height = w.get("height_ft")  # v3 exports carry the real value
        walls.append(
            {
                "id": w.get("id"),
                "centerline_ft": line,
                "thickness_ft": w.get("thickness") or 0.5,
                "height_ft": real_height if real_height is not None else ASSUMED_WALL_HEIGHT_FT,
                "height_assumed": real_height is None,
                "type_name": w.get("type_name"),
                "sw_token": token,
                "is_shear_wall": token is not None,
                "status": wall_status.get(w.get("id"), "NOT_EVALUATED"),
                "level": w.get("level"),
                "base_ft": 0.0,  # level list basis is unreliable; stems sit at grade
            }
        )
        for p in line:
            xs.append(float(p[0]))
            ys.append(float(p[1]))

    holdowns = []
    # Canonical assemblies (with statuses) come from AIConvert_revit.json.
    assemblies = (ai_revit or {}).get("canonical_holdown_assemblies")
    if assemblies:
        for a in assemblies:
            c = a.get("center_point") or {}
            if c.get("x") is None:
                continue
            holdowns.append(
                {
                    "assembly_id": a.get("id"),
                    "x_ft": c["x"],
                    "y_ft": c["y"],
                    "elevation_ft": round(c["z"] - z0, 2) if isinstance(c.get("z"), (int, float)) else 0.0,
                    "mark": a.get("pdf_mark_candidate"),
                    "status": holdown_status.get(a.get("id"), "NOT_EVALUATED"),
                }
            )
            xs.append(float(c["x"]))
            ys.append(float(c["y"]))

    openings = []
    for o in raw_revit.get("openings", []):
        c = o.get("center")
        if not c:
            continue
        openings.append(
            {
                "id": o.get("id"),
                "kind": o.get("kind"),
                "type_name": o.get("type_name"),
                "host_wall_id": o.get("host_wall_id"),
                "center_ft": [float(c[0]), float(c[1])],
            }
        )

    # v3 category elements (posts, columns, framing, stairs …): rendered as
    # category-colored boxes so the 3D model shows ONLY the curated categories.
    status_by_revit_id: dict[str, str] = {}
    for e in (element_list or {}).get("elements", []):
        ref = e.get("revit_ref")
        if ref and ref.get("id"):
            status_by_revit_id.setdefault(ref["id"], e["status"])
    category_elements = []
    framing: list[list[float]] = []
    for e in raw_revit.get("v3_elements", []):
        point = (e.get("location") or {}).get("point")
        bbox = e.get("bbox")
        if e.get("category") == "Structural Framing":
            # The LGS structure itself: compact [cx, cy, cz, sx, sy, sz]
            # boxes rendered as a single InstancedMesh in the frontend.
            if not bbox:
                continue
            (x0, y0, zlo), (x1, y1, zhi) = bbox
            framing.append([
                round((x0 + x1) / 2.0, 2), round((y0 + y1) / 2.0, 2),
                round((zlo + zhi) / 2.0 - z0, 2),
                round(max(x1 - x0, 0.15), 2), round(max(y1 - y0, 0.15), 2),
                round(max(zhi - zlo, 0.15), 2),
            ])
            continue
        if not point:
            continue
        category_elements.append({
            "id": e.get("id"),
            "category": e.get("category"),
            "mark": e.get("mark") or "",
            "center_ft": [float(point[0]), float(point[1])],
            "elevation_ft": round(float(e.get("elevation_ft", 0.0)) - z0, 2),
            "bbox_ft": bbox,
            "status": status_by_revit_id.get(e.get("id"), "NOT_EVALUATED"),
        })
        xs.append(float(point[0]))
        ys.append(float(point[1]))

    benchmarks = []
    for b in raw_revit.get("benchmarks", []):
        p = b.get("point_ft") or {}
        if p.get("x") is None or p.get("y") is None:
            continue
        benchmarks.append(
            {
                "id": b.get("id"),
                "mark": b.get("mark"),
                "x_ft": p["x"],
                "y_ft": p["y"],
                "elevation_ft": round(p["z"] - z0, 2) if p.get("z") is not None else 0.0,
            }
        )
        xs.append(float(p["x"]))
        ys.append(float(p["y"]))

    grids = []
    for g in raw_revit.get("grids", []):
        line = g.get("line")
        if not line or len(line) != 2:
            continue
        grids.append({"id": g.get("id"), "label": g.get("label"), "line_ft": line})
        for p in line:
            xs.append(float(p[0]))
            ys.append(float(p[1]))

    bounds = (
        {"min_x": min(xs), "max_x": max(xs), "min_y": min(ys), "max_y": max(ys)}
        if xs
        else None
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "units": "feet",
        "assumed_wall_height_ft": ASSUMED_WALL_HEIGHT_FT,
        "counts": {
            "walls": len(walls),
            "shear_walls": sum(1 for w in walls if w["is_shear_wall"]),
            "holdowns": len(holdowns),
            "grids": len(grids),
            "openings": len(openings),
            "category_elements": len(category_elements),
            "framing": len(framing),
            "benchmarks": len(benchmarks),
        },
        "datum_elevation_ft": z0,
        "bounds": bounds,
        "walls": walls,
        "holdowns": holdowns,
        "openings": openings,
        "grids": grids,
        "category_elements": category_elements,
        "framing": framing,
        "benchmarks": benchmarks,
    }
