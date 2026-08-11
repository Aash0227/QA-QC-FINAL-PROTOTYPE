# -*- coding: utf-8 -*-
"""Export ONLY the QA-QC categories visible in the ACTIVE view as clean JSON.

WYSIWYG scoping: collectors run through the active view, so V/G overrides,
filters, phases and design options all apply. 18 walls visible = 18 walls
exported. Works on any Revit model.
"""
__title__ = "Export\nQA-QC JSON"
__doc__ = ("Exports ONLY Columns, Stairs, Structural Columns/Connections/"
           "Foundation/Framing and Walls that are VISIBLE in the active view "
           "as clean schema-v3.1 JSON, plus grids and levels for PDF-model "
           "alignment. Curate the view first - what you see is what exports.")

import io
import json
import os
import traceback
from datetime import datetime

from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    FamilyInstance,
    FilteredElementCollector,
    Grid,
    Level,
    LocationCurve,
    LocationPoint,
    StorageType,
    Wall,
)
from pyrevit import forms, revit

import qaqc_export_core as core

QAQC_BICS = [
    (BuiltInCategory.OST_Columns, "Columns"),
    (BuiltInCategory.OST_Stairs, "Stairs"),
    (BuiltInCategory.OST_StructuralColumns, "Structural Columns"),
    (BuiltInCategory.OST_StructConnections, "Structural Connections"),
    (BuiltInCategory.OST_StructuralFoundation, "Structural Foundation"),
    (BuiltInCategory.OST_StructuralFraming, "Structural Framing"),
]

# Type-level whitelist: looked up ONCE per family type, cached.
TYPE_PARAM_WHITELIST = ["Type Mark", "Type Comments", "Model", "Description"]

PROGRESS_EVERY = 250


def xyz(p):
    return [p.X, p.Y, p.Z]


def bbox3(box):
    if box is None:
        return None
    return [[box.Min.X, box.Min.Y, box.Min.Z],
            [box.Max.X, box.Max.Y, box.Max.Z]]


def safe_location(element):
    """(point_xyz, curve_or_None) or None. Never a blind cast."""
    try:
        loc = element.Location
        if isinstance(loc, LocationPoint):
            return xyz(loc.Point), None
        if isinstance(loc, LocationCurve):
            c = loc.Curve
            mid = c.Evaluate(0.5, True)
            return xyz(mid), [xyz(c.GetEndPoint(0)), xyz(c.GetEndPoint(1))]
    except Exception:
        pass
    try:
        box = element.get_BoundingBox(None)
        if box is not None:
            return [(box.Min.X + box.Max.X) / 2.0,
                    (box.Min.Y + box.Max.Y) / 2.0,
                    (box.Min.Z + box.Max.Z) / 2.0], None
    except Exception:
        pass
    return None


class Caches(object):
    """Per-run caches: type params/names and level names are shared by
    thousands of instances - resolve each exactly once."""

    def __init__(self, doc):
        self.doc = doc
        self.type_info = {}    # type_id_str -> (type_name, family, params)
        self.level_names = {}  # level_id_str -> name or None

    def type_of(self, element):
        try:
            tid = element.GetTypeId()
            key = tid.ToString()
        except Exception:
            return "", "", {}
        if key in self.type_info:
            return self.type_info[key]
        name, family, params = "", "", {}
        try:
            etype = self.doc.GetElement(tid)
            if etype is not None:
                # ElementType.Name can raise (hide-by-name API quirk); a bare
                # access here used to abort family/params resolution too.
                try:
                    name = etype.Name or ""
                except Exception:
                    name = ""
                if not name:
                    for bip in ("SYMBOL_NAME_PARAM", "ALL_MODEL_TYPE_NAME"):
                        try:
                            p = etype.get_Parameter(
                                getattr(BuiltInParameter, bip))
                            name = (p.AsString() if p is not None else "") or ""
                        except Exception:
                            name = ""
                        if name:
                            break
                try:
                    fam_param = etype.get_Parameter(
                        BuiltInParameter.ALL_MODEL_FAMILY_NAME)
                    family = fam_param.AsValueString() if fam_param else ""
                except Exception:
                    family = ""
                for pname in TYPE_PARAM_WHITELIST:
                    try:
                        p = etype.LookupParameter(pname)
                        if p is not None:
                            value = p.AsValueString() or p.AsString()
                            if value:
                                params[pname] = value.strip()
                    except Exception:
                        pass
        except Exception:
            pass
        self.type_info[key] = (name, family or "", params)
        return self.type_info[key]

    def level_of(self, element):
        try:
            lid = element.LevelId
            key = lid.ToString()
        except Exception:
            return None
        if key not in self.level_names:
            try:
                el = self.doc.GetElement(lid)
                self.level_names[key] = el.Name if el is not None else None
            except Exception:
                self.level_names[key] = None
        return self.level_names[key]


def mark_of(element):
    try:
        p = element.get_Parameter(BuiltInParameter.ALL_MODEL_MARK)
        if p is not None:
            value = p.AsString()
            if value:
                return value.strip()
    except Exception:
        pass
    return ""


def family_of(element, cached_family):
    if cached_family:
        return cached_family
    try:
        if isinstance(element, FamilyInstance) and element.Symbol is not None:
            return element.Symbol.FamilyName or ""
    except Exception:
        pass
    try:
        return element.GetType().Name
    except Exception:
        return ""


def collect_walls(doc, view, caches, skipped):
    walls = []
    collector = (FilteredElementCollector(doc, view.Id)
                 .OfCategory(BuiltInCategory.OST_Walls)
                 .WhereElementIsNotElementType())
    for element in collector:
        try:
            if not isinstance(element, Wall):
                continue
            loc = element.Location
            if not isinstance(loc, LocationCurve):
                continue
            curve = loc.Curve
            height = None
            try:
                hp = element.get_Parameter(
                    BuiltInParameter.WALL_USER_HEIGHT_PARAM)
                if hp is not None and hp.StorageType == StorageType.Double:
                    height = hp.AsDouble()
            except Exception:
                pass
            structural = False
            try:
                sp = element.get_Parameter(
                    BuiltInParameter.WALL_STRUCTURAL_SIGNIFICANT)
                structural = sp is not None and sp.AsInteger() == 1
            except Exception:
                pass
            type_name, _, _ = caches.type_of(element)
            walls.append({
                "id": element.UniqueId,
                "type_name": type_name,
                "mark": mark_of(element),
                "level": caches.level_of(element),
                "base_line": [xyz(curve.GetEndPoint(0)),
                              xyz(curve.GetEndPoint(1))],
                "thickness_ft": element.Width,
                "height_ft": height,
                "is_structural": structural,
            })
        except Exception:
            skipped[0] += 1
    return walls


def collect_category(doc, view, bic, cat_name, caches, skipped, tick):
    out = []
    collector = (FilteredElementCollector(doc, view.Id)
                 .OfCategory(bic)
                 .WhereElementIsNotElementType())
    for element in collector:
        try:
            located = safe_location(element)
            if located is None:
                continue  # no usable geometry - never fake a position
            point, curve = located
            location = {"point": point}
            if curve is not None:
                location["curve"] = curve
            type_name, family, type_params = caches.type_of(element)
            out.append({
                "id": element.UniqueId,
                "category": cat_name,
                "family": family_of(element, family),
                "type_name": type_name,
                "mark": mark_of(element),
                "level": caches.level_of(element),
                "elevation_ft": point[2],
                "location": location,
                "bbox": bbox3(element.get_BoundingBox(None)),
                "params": type_params,
            })
        except Exception:
            skipped[0] += 1
        tick()
    return out


def collect_grids(doc):
    # Document-wide on purpose: the user hides grids for visual clarity, but
    # they are the anchors that align the model to the PDF automatically.
    grids = []
    for element in FilteredElementCollector(doc).OfClass(Grid):
        try:
            curve = element.Curve
            grids.append({
                "id": element.UniqueId,
                "label": element.Name or "",
                "line": [xyz(curve.GetEndPoint(0)),
                         xyz(curve.GetEndPoint(1))],
            })
        except Exception:
            pass
    return grids


def collect_benchmarks(doc, caches):
    # Document-wide on purpose (like grids): benchmark markers are usually
    # hidden in the curated export view but anchor the 2-point registration.
    benchmarks = []
    collector = (FilteredElementCollector(doc)
                 .OfClass(FamilyInstance)
                 .WhereElementIsNotElementType())
    for element in collector:
        try:
            _, family, _ = caches.type_of(element)
            family = family_of(element, family)
            mark = mark_of(element)
            if not core.is_benchmark(family, mark):
                continue
            located = safe_location(element)
            if located is None:
                continue  # no usable geometry - never fake a position
            point = located[0]
            benchmarks.append({
                "id": element.UniqueId,
                "mark": mark,
                "family": family,
                "level": caches.level_of(element),
                "point_ft": {"x": point[0], "y": point[1], "z": point[2]},
            })
        except Exception:
            pass
    return benchmarks


def collect_levels(doc):
    levels = []
    for element in FilteredElementCollector(doc).OfClass(Level):
        try:
            levels.append({"name": element.Name or "",
                           "elevation_ft": element.Elevation})
        except Exception:
            pass
    return levels


def view_info(view):
    level = None
    try:
        gen = getattr(view, "GenLevel", None)
        level = gen.Name if gen is not None else None
    except Exception:
        pass
    return {"id": view.UniqueId, "name": view.Name or "",
            "view_type": str(view.ViewType), "level": level}


def output_path(doc):
    out_dir = None
    try:
        if doc.PathName:
            out_dir = os.path.dirname(doc.PathName)
    except Exception:
        pass
    if not out_dir or not os.path.isdir(out_dir):
        out_dir = os.path.join(os.path.expanduser("~"), "Desktop")
    return os.path.join(out_dir, "revit_export.json")


def count_total(doc, view):
    total = 0
    for bic, _ in QAQC_BICS:
        try:
            total += (FilteredElementCollector(doc, view.Id)
                      .OfCategory(bic)
                      .WhereElementIsNotElementType()
                      .GetElementCount())
        except Exception:
            pass
    return max(total, 1)


def run_export():
    doc = revit.doc
    view = doc.ActiveView
    if view is None or not getattr(view, "CanBePrinted", True):
        forms.alert(
            "Open a graphical view (3D or plan) first - the export uses the "
            "ACTIVE view to decide what is included.",
            title="Livio QA-QC Export", warn_icon=True)
        return

    proceed = forms.alert(
        "This exports ONLY what is VISIBLE in the active view "
        "('{0}'), for these categories:\n\n"
        "  -  Columns\n  -  Stairs\n  -  Structural Columns\n"
        "  -  Structural Connections\n  -  Structural Foundation\n"
        "  -  Structural Framing\n  -  Walls\n\n"
        "What you see is what exports (V/G overrides, filters, phases all "
        "apply).\n\nGrids and levels are also exported - they align the "
        "model to the PDF automatically.\n\nContinue?".format(view.Name),
        title="Before you export - checklist",
        warn_icon=True, ok=False, yes=True, no=True)
    if not proceed:
        return

    skipped = [0]
    caches = Caches(doc)
    total = count_total(doc, view)
    state = {"done": 0}

    with forms.ProgressBar(title="Livio QA-QC export - "
                                 "{value} of {max_value} elements",
                           cancellable=False) as pb:

        def tick():
            state["done"] += 1
            if state["done"] % PROGRESS_EVERY == 0:
                pb.update_progress(state["done"], total)

        walls = collect_walls(doc, view, caches, skipped)
        elements = []
        for bic, cat_name in QAQC_BICS:
            elements.extend(
                collect_category(doc, view, bic, cat_name, caches,
                                 skipped, tick))
        pb.update_progress(total, total)

        payload = core.build_export(
            source_model=os.path.basename(doc.PathName or "unsaved.rvt"),
            view_info=view_info(view),
            levels=collect_levels(doc),
            grids=collect_grids(doc),
            walls=walls,
            elements=elements,
            exported_at=datetime.utcnow().isoformat() + "Z",
            benchmarks=collect_benchmarks(doc, caches),
        )
        # Serialize FULLY in memory, pure-ASCII (symbols like diameter marks
        # crash IronPython streams mid-write) - then write in one shot.
        # A failure here means NO file, never a truncated one.
        # ASCII-fold first: IronPython str==unicode, so decode() tricks pass
        # dirty chars through and json's ASCII encoder still dies on 0xD8
        # (Dogwood diameter marks). Folding every char >127 to a safe ASCII
        # substitute makes ensure_ascii physically unable to fail.
        _SUB = {0xD8: u"dia.", 0xF8: u"dia.", 0x2300: u"dia.",
                0xB1: u"+/-", 0xB0: u"deg", 0xB4: u"'", 0x2019: u"'",
                0x201C: u'"', 0x201D: u'"', 0x2013: u"-", 0x2014: u"-"}
        try:
            _string_types = basestring  # IronPython 2.7
        except NameError:
            _string_types = (str, bytes)  # CPython 3 engine

        def _fold(obj):
            if isinstance(obj, bytes):  # py3 bytes: latin-1 never fails
                obj = obj.decode("latin-1")
            if isinstance(obj, _string_types):
                out = []
                for ch in obj:
                    o = ord(ch)
                    out.append(ch if o < 128 else _SUB.get(o, u"?"))
                return u"".join(out)
            if isinstance(obj, dict):
                return dict((_fold(k), _fold(v)) for k, v in obj.items())
            if isinstance(obj, (list, tuple)):
                return [_fold(x) for x in obj]
            return obj

        text = json.dumps(_fold(payload), ensure_ascii=True, default=str)
        out_path = output_path(doc)
        with io.open(out_path, "w", encoding="utf-8") as fh:
            fh.write(text)

    counts = core.category_counts(payload)
    size_mb = os.path.getsize(out_path) / (1024.0 * 1024.0)
    forms.alert(
        "EXPORT COMPLETE  (schema v3.1, view '{0}')\n\n"
        "Elements per category (as visible in the view):\n{1}\n\n"
        "Grids: {2}   Levels: {3}   Benchmarks: {4}   "
        "Skipped (no geometry): {5}\n"
        "File size: {6:.1f} MB\n\nWritten to:\n{7}".format(
            view.Name, core.format_counts(counts),
            len(payload["grids"]), len(payload["levels"]),
            len(payload.get("benchmarks", [])), skipped[0],
            size_mb, out_path),
        title="Livio QA-QC Export - done")


try:
    run_export()
except Exception:
    forms.alert(
        "Export FAILED - nothing was written.\n\n{0}".format(
            traceback.format_exc()),
        title="Livio QA-QC Export - error", warn_icon=True)
