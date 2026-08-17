"""Revit bridge endpoints (production-plan §2): live connection status and the
backend-driven benchmark marker placement. URL paths are kept exactly as they
were (/api/revit/status, /api/benchmark-workflow/place-markers)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from fastapi import Body, HTTPException
from fastapi.responses import JSONResponse

from .. import (benchmark_workflow, config, device_match, export_watch, progress,
                review, revit_bridge, revit_ids)
from . import projects
from .common import load_artifact, make_router

router = make_router()

# The MCP has no zoom tool. BX (Selection Box) is a DEFAULT Revit shortcut that
# crops + jumps to the selected element; ZS is not mapped by default.
ZOOM_NOTE = ("Press BX in Revit to jump to it (don't click the canvas first — "
             "that clears the selection).")


def _creation_element_ids(unique_ids: list[str]) -> list[int]:
    """Export-time ElementIds embedded in UniqueIds (BUG-05: XOR decode, never
    the naive hex-suffix shortcut)."""
    out: list[int] = []
    for u in unique_ids:
        try:
            out.append(revit_ids.unique_id_to_element_id(str(u)))
        except ValueError:
            pass
    return out


def _assemblies() -> list[dict[str, Any]]:
    return load_artifact("ai_revit").get("canonical_holdown_assemblies", [])


def _optional_artifact(key: str) -> dict[str, Any]:
    """An artifact the lookup can live without (no compare run yet)."""
    try:
        return load_artifact(key)
    except HTTPException:
        return {}


def _live_lookup(center: dict[str, Any], radius_ft: float) -> dict[str, Any]:
    """Live Structural-Connection ids within ``radius_ft`` of an assembly's
    export centre. Shared by /element-ids and /highlight."""
    live: dict[str, Any] = {"connected": False, "element_ids": [], "distance_ft": None,
                            "note": None, "reason": None, "cached": False, "age_s": None}
    cx, cy = (center or {}).get("x"), (center or {}).get("y")
    if cx is None or cy is None:
        return live
    lookup = revit_bridge.live_connection_locations()
    live["connected"] = lookup["connected"]
    live["reason"] = lookup.get("reason")
    # R-15: the bridge answer may be up to 5 min old — say so instead of
    # letting the UI imply every lookup is a fresh read of the model.
    live["cached"] = bool(lookup.get("cached"))
    live["age_s"] = lookup.get("age_s")
    if lookup["connected"]:
        near = sorted(
            ((math.hypot(x - cx, y - cy), eid)
             for eid, (x, y) in lookup["locations"].items()),
            key=lambda t: t[0],
        )
        hits = [(d, eid) for d, eid in near if d <= radius_ft]
        live["element_ids"] = [eid for _, eid in hits]
        live["distance_ft"] = round(hits[0][0], 3) if hits else None
        live["note"] = (
            f"Select in Revit: Manage > Inquiry > Select by ID > {hits[0][1]}"
            if hits else
            f"No live Structural Connection within {radius_ft} ft of the export point."
        )
    else:
        live["note"] = "Nonica connector off — showing export-time IDs only."
    return live


@router.get("/api/revit/status")
def revit_status() -> dict[str, Any]:
    """Live Nonica/Revit connection status for the wizard (production-plan §2).
    Never raises — connector-off reads as disconnected. Cached variant: the UI
    polls this endpoint, and every uncached call spawns the MCP exe (~14 s
    handshake even to learn Revit is closed) — status_cached holds the answer
    30 s connected / 300 s offline (force=True is the operator's Refresh)."""
    return revit_bridge.status_cached()


# ---------------------------------------------------------------------------
# Zero-upload auto-ingest (Design A2). The operator presses Export QAQC in
# Revit; these two endpoints notice the file and pull it in. The math source is
# byte-for-byte the same export the upload form took, because the ingest runs
# projects.ingest_revit_export — the very function /api/upload calls.
# ---------------------------------------------------------------------------
def _write_manifest(manifest: dict[str, Any]) -> None:
    config.artifact_path("project_manifest").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")


@router.post("/api/revit/ingest")
def revit_ingest(payload: dict[str, Any] | None = Body(default=None)) -> JSONResponse:
    """Ingest the newest un-ingested Revit export found in the watch dirs.
    Nothing new on disk is a normal 200 with ingested:false, not an error.

    Refuses (409) an export from a different model than this workspace is bound
    to — §5.2's wrong-model ingest is the most expensive silent failure we have.
    ``{"force": true}`` overrides and re-binds."""
    body = payload if isinstance(payload, dict) else {}
    found = export_watch.scan()
    out: dict[str, Any] = {"ok": True, "ingested": False,
                           "path": found["path"], "reason": found["reason"]}
    if not found["pending"]:
        return JSONResponse(out)

    path = Path(found["path"])
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return JSONResponse({**out, "ok": False,
                             "reason": f"Invalid Revit JSON in {path.name}: {exc}"},
                            status_code=400)

    # Basic JSON schema validation: require at least one of the expected top-level
    # keys that a Revit export should carry. Rejects empty or malformed files
    # before they reach the ingest pipeline.
    required_keys = {"discovery_instances", "holdowns", "v3_elements", "source_file", "schema_version"}
    if not isinstance(raw, dict) or not any(k in raw for k in required_keys):
        return JSONResponse({**out, "ok": False,
                             "reason": f"Revit JSON missing required keys (expected one of: {', '.join(sorted(required_keys))})"},
                            status_code=400)

    manifest = export_watch.load_manifest()
    title = export_watch.export_model_title(raw)
    bound = manifest.get("revit_model_title")
    if (not body.get("force") and bound
            and export_watch.titles_match(bound, title) is False):
        return JSONResponse(
            {**out, "ok": False,
             "reason": f"This project is bound to «{bound}» but {path.name} came "
                       f"from «{title}». Re-send with force:true to re-bind."},
            status_code=409)
    if title is None:
        # Export carries no source_file — the live connector is the only other
        # witness to which model this came from.
        live = revit_bridge.status_cached()
        title = live.get("model_title") if live.get("connected") else None

    projects.ingest_revit_export(manifest, raw, path.name)
    manifest["last_ingested_export"] = export_watch.ingest_record(
        found["sha"], found["mtime"], title)
    if title:
        manifest["revit_model_title"] = title
    manifest["project"] = config.active_project()
    _write_manifest(manifest)
    return JSONResponse({**out, "ingested": True, "reason": None,
                         "model_title": title})


@router.get("/api/revit/export-status")
def revit_export_status(refresh: bool = False) -> dict[str, Any]:
    """Is this workspace looking at the model Revit has open, and how stale is
    it? Polled by the UI — every off state (no export, Revit closed, never
    ingested) is a normal 200, never a 500.

    synced          — an export has been ingested and nothing newer is waiting
    model_title     — the model this workspace is bound to
    exported_at     — the export payload's own stamp, else the file mtime (R-14)
    matches_project — live title vs bound title; null when Revit is offline

    ``?refresh=true`` busts the cached connector read (the Connect card's
    Refresh button); plain polls reuse it so they never spawn an exe per poll.
    """
    manifest = export_watch.load_manifest()
    last = manifest.get("last_ingested_export") or {}
    try:
        found = export_watch.scan(manifest)
    except Exception as exc:                       # a polled endpoint never 500s
        found = {"pending": False, "path": None, "mtime": None, "sha": None,
                 "reason": f"watch failed: {exc}"}

    raw: dict[str, Any] = {}
    mtime = found["mtime"] if found["path"] else last.get("mtime")
    if found["path"]:
        try:
            raw = json.loads(Path(found["path"]).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raw = {}                               # unreadable -> mtime-only answer
    stamp = export_watch.exported_at(raw, mtime)

    title = (manifest.get("revit_model_title") or last.get("model_title")
             or export_watch.export_model_title(raw))
    live = revit_bridge.status_cached(force=refresh)
    matches = (export_watch.titles_match(live.get("model_title"), title)
               if live.get("connected") else None)

    synced = bool(last) and not found["pending"]
    reason = None if synced else (
        "no export ingested yet" if not last else
        found["reason"] or ("newer export pending" if found["pending"] else None))
    return {"synced": synced, "model_title": title, "exported_at": stamp,
            "age_s": export_watch.age_s(stamp), "matches_project": matches,
            "reason": reason,
            # additive, non-contract: what the poller needs to offer "Ingest now"
            "pending": found["pending"], "path": found["path"],
            "live_model_title": live.get("model_title") if live.get("connected") else None,
            "connected": bool(live.get("connected")),
            "status_cached": bool(live.get("cached")), "status_age_s": live.get("age_s")}


LIVE_STATUS_RADIUS_FT = 1.0


def _assembly_status_index() -> list[tuple[float, float, str, str]]:
    """(x, y, status, assembly_id) for each holdown assembly that has a paired
    PDF device in THIS project. Empty when no compare has been run — the live
    scene then simply carries no statuses."""
    registry = _optional_artifact("device_registry")
    if not registry:
        return []
    by_target: dict[str, dict[str, Any]] = {}
    for cat in registry.get("categories", {}).values():
        for d in cat.get("devices", []):
            if d.get("target_id"):
                by_target.setdefault(str(d["target_id"]), d)
    index: list[tuple[float, float, str, str]] = []
    for a in _optional_artifact("ai_revit").get("canonical_holdown_assemblies", []):
        c = a.get("center_point") or {}
        dev = by_target.get(str(a.get("id")))
        if c.get("x") is None or c.get("y") is None or not dev:
            continue
        index.append((float(c["x"]), float(c["y"]),
                      str(dev.get("status") or "NOT_EVALUATED"), str(a.get("id"))))
    return index


def _with_connection_status(scene: dict[str, Any], radius_ft: float) -> dict[str, Any]:
    """Colour live Structural Connections by joining their bbox centre to the
    project's device registry (same nearest-within-radius rule as _live_lookup).
    Returns a NEW scene — the bridge cache must not inherit project state."""
    conns = (scene.get("categories") or {}).get("connections") or []
    index = _assembly_status_index()
    if not conns or not index:
        return scene
    joined = []
    for el in conns:
        b = el["bbox_ft"]
        cx, cy = (b[0] + b[3]) / 2.0, (b[1] + b[4]) / 2.0
        x, y, status, asm_id = min(index, key=lambda t: math.hypot(t[0] - cx, t[1] - cy))
        hit = math.hypot(x - cx, y - cy) <= radius_ft
        joined.append({**el, "status": status, "assembly_id": asm_id} if hit else dict(el))
    cats = {**scene["categories"], "connections": joined}
    return {**scene, "categories": cats,
            "status_joined": sum(1 for e in joined if e.get("status"))}


def _live_scene(force: bool, radius_ft: float) -> dict[str, Any]:
    scene = revit_bridge.live_scene_geometry(force=force)
    return _with_connection_status(scene, radius_ft) if scene.get("ok") else scene


@router.get("/api/revit-live/scene")
def revit_live_scene(radius_ft: float = LIVE_STATUS_RADIUS_FT) -> dict[str, Any]:
    """Box massing of the OPEN Revit model (walls / framing / columns /
    connections) for the 3D pane, with connection statuses joined from this
    project's device registry when one exists. Connector off is an honest
    ok:false — the frontend then falls back to the export snapshot."""
    return _live_scene(force=False, radius_ft=radius_ft)


@router.post("/api/revit-live/refresh-3d")
def revit_live_refresh_3d(radius_ft: float = LIVE_STATUS_RADIUS_FT) -> dict[str, Any]:
    """Bust the 60 s live-scene cache and re-read the model."""
    return _live_scene(force=True, radius_ft=radius_ft)


@router.get("/api/revit/element-ids/{assembly_id}")
def revit_element_ids(assembly_id: str, radius_ft: float = 0.75) -> dict[str, Any]:
    """Live Revit ElementIds for a holdown assembly so a QA reviewer can
    Manage > Inquiry > Select by ID and eyeball the device in Revit. Live ids
    are matched by coordinate (export UniqueIds embed the CREATION id, which
    central-model ops can change); export ids returned as honest fallback."""
    asm = next((a for a in _assemblies() if a.get("id") == assembly_id), None)
    if asm is None:
        raise HTTPException(status_code=404, detail=f"No holdown assembly '{assembly_id}'.")
    center = asm.get("center_point") or {}
    uids = asm.get("member_element_ids") or []
    creation_ids = _creation_element_ids(uids)
    live = _live_lookup(center, radius_ft)

    return {
        "assembly_id": assembly_id,
        "family": next(iter((asm.get("family_type_summary") or {}).keys()), None),
        "mark": asm.get("pdf_mark_candidate"),
        "center_point_ft": center,
        "live": live,
        "export": {
            "unique_ids": uids,
            "creation_element_ids": creation_ids,
            "note": "IDs at export time — may differ from live after central-model operations.",
        },
    }


@router.post("/api/revit/highlight")
def revit_highlight(payload: dict[str, Any] | None = Body(default=None),
                    radius_ft: float = 0.75) -> dict[str, Any]:
    """Select a holdown assembly (or raw ElementIds) in the live Revit model so
    the operator can eyeball it. There is no MCP zoom tool — the response says
    to press ZS. Connector off is an honest ok:false, never a 500."""
    body = payload if isinstance(payload, dict) else {}
    out: dict[str, Any] = {"ok": False, "selected_ids": [], "invalid_ids": [],
                           "resolved_via": "element_ids", "note": ZOOM_NOTE,
                           "reason": None, "live": None}
    ids = [int(i) for i in (body.get("element_ids") or [])]
    assembly_id = body.get("assembly_id")
    if not ids and assembly_id:
        asm = next((a for a in _assemblies() if a.get("id") == str(assembly_id)), None)
        if asm is None:
            raise HTTPException(status_code=404, detail=f"No holdown assembly '{assembly_id}'.")
        live = _live_lookup(asm.get("center_point") or {}, radius_ft)
        out["resolved_via"] = "live_coordinate_match"
        out["distance_ft"] = live["distance_ft"]
        # R-15: the coordinate match may have come from the 5-min bridge cache.
        out["live"] = {"connected": live["connected"], "cached": live["cached"],
                       "age_s": live["age_s"]}
        ids = live["element_ids"]          # ALL coordinate hits, not just the nearest
        if not ids:
            out["reason"] = live["reason"] or live["note"] or "No live match for that assembly."
            return out
    if not ids:
        out["reason"] = "Give an assembly_id or a non-empty element_ids list."
        return out
    result = revit_bridge.select_elements(ids)
    out.update(ok=result["ok"], selected_ids=result["selected_ids"],
               invalid_ids=result["invalid_ids"], reason=result["reason"])
    return out


@router.get("/api/revit/selection")
def revit_selection() -> dict[str, Any]:
    """What the operator has selected in Revit right now."""
    return revit_bridge.get_selection()


def _plain_english(element_id: int, connected: bool, asm: dict[str, Any] | None,
                   device: dict[str, Any] | None, analysis: dict[str, Any] | None) -> str:
    """Deterministic 2-4 sentence explanation — no LLM."""
    offline = "" if connected else (
        " (Revit is not connected, so this is from the export, not the live model.)")
    if asm is None:
        return (f"ElementId {element_id} is not a member of any holdown assembly in this "
                f"project's Revit export, so there is nothing to compare against the "
                f"permit PDF.{offline}")
    mark = asm.get("pdf_mark_candidate")
    head = (f"This element belongs to holdown assembly {asm.get('id')}"
            + (f" (mark {mark})." if mark else "."))
    if device is None:
        return (f"{head} No PDF device is paired with that assembly in the device registry, "
                f"so the drawing either does not call it out or it was not matched.{offline}")
    status = device.get("status")
    dist = device.get("distance_ft")
    if status == "MATCH" and dist is not None:
        return (f"{head} The permit PDF shows this device {dist:.2f} ft from where the Revit "
                f"model places it — within the {device_match.MATCH_FT:g} ft tolerance, so it "
                f"is a MATCH.{offline}")
    if status == "LOCATION_MISMATCH" and analysis and analysis.get("analysis_available"):
        return (f"{head} {analysis['finding']} Deterministic suggestion: "
                f"{analysis['suggestion']}.{offline}")
    return (f"{head} The pipeline status is {status}: "
            f"{device.get('reason') or 'no further detail recorded.'}{offline}")


def _explain_element(element_id: int, radius_ft: float = 2.0,
                     point: tuple[float, float] | None = None) -> dict[str, Any]:
    """Live XY (or the export fallback when Revit is off) -> holdown assembly ->
    paired PDF device -> deterministic mismatch analysis. Shared by the
    paste-an-ElementId lookup and the current-selection endpoint; ``point``
    short-circuits the per-element location read when the caller already has it."""
    assemblies = _assemblies()
    lookup = revit_bridge.live_connection_locations()
    connected = bool(lookup.get("connected"))
    if point is None and connected:
        point = lookup["locations"].get(element_id)
        if point is None:
            loc = revit_bridge.element_location(element_id)
            if loc.get("ok"):
                point = (loc["x"], loc["y"])

    asm = None
    if point is not None:
        sited = [a for a in assemblies if (a.get("center_point") or {}).get("x") is not None]
        if sited:
            near = min(sited, key=lambda a: math.hypot(
                a["center_point"]["x"] - point[0], a["center_point"]["y"] - point[1]))
            d = math.hypot(near["center_point"]["x"] - point[0],
                           near["center_point"]["y"] - point[1])
            asm = near if d <= radius_ft else None
    if asm is None:
        # Offline (or off-grid) fallback: the id may be an export-time member id.
        asm = next((a for a in assemblies
                    if element_id in _creation_element_ids(a.get("member_element_ids") or [])),
                   None)

    device = None
    registry = _optional_artifact("device_registry")
    if asm is not None:
        for cat in registry.get("categories", {}).values():
            device = next((d for d in cat.get("devices", [])
                           if d.get("target_id") == asm.get("id")), None)
            if device:
                break

    analysis = None
    if device and device.get("appearances"):
        try:
            analysis = review.analyze(device["appearances"][0],
                                      _optional_artifact("element_list"), registry)
        except ValueError:
            analysis = None

    return {
        "found": asm is not None,
        "connected": connected,
        "element_id": element_id,
        "live_point": [point[0], point[1]] if point else None,
        "assembly": None if asm is None else {
            "id": asm.get("id"), "mark_candidate": asm.get("pdf_mark_candidate"),
            "center_point": asm.get("center_point"),
            "classification_reason": asm.get("classification_reason"),
            "classification_confidence": asm.get("classification_confidence"),
        },
        "device": device,
        "registration_quality": registry.get("registration_quality"),
        "analysis": analysis,
        "plain_english": _plain_english(element_id, connected, asm, device, analysis),
        "reason": None if connected else lookup.get("reason"),
    }


@router.get("/api/revit/lookup/{element_id}")
def revit_lookup(element_id: int, radius_ft: float = 2.0) -> dict[str, Any]:
    """Paste-an-ElementId explainer: what is this thing, and what does QA say
    about it?"""
    return _explain_element(element_id, radius_ft)


@router.get("/api/revit/selected-element")
def revit_selected_element(radius_ft: float = 2.0) -> dict[str, Any]:
    """One round trip for "explain what I have selected in Revit": the richest
    available read of the current selection (open-source revit-mcp first, Nonica
    fallback) joined with the same assembly/device/analysis explainer as
    /api/revit/lookup. Nothing selected / both bridges down is an honest
    ok:false, never a 500."""
    sel = revit_bridge.get_selected_element_full()
    if not sel.get("ok") or sel.get("element_id") is None:
        return {**sel, "found": False, "connected": False, "live_point": None,
                "assembly": None, "device": None, "analysis": None,
                "plain_english": None}
    pt = sel.get("point")
    out = _explain_element(int(sel["element_id"]), radius_ft,
                           point=(pt[0], pt[1]) if pt else None)
    return {**out, "ok": True, "source": sel["source"], "family": sel["family"],
            "type": sel["type"], "mark": sel["mark"], "category": sel.get("category"),
            "level": sel["level"], "parameters": sel["parameters"]}


@router.post("/api/benchmark-workflow/place-markers")
def benchmark_workflow_place_markers(
    payload: dict[str, Any] | None = Body(default=None),
) -> JSONResponse:
    """Place BM-1/BM-2 in the live Revit model via the backend MCP bridge (no
    Claude in the loop), verify the read-back against the approved proposal,
    and only then advance. Closes BUG-07's trust gap for this step: the
    readback is server-obtained, not self-reported.

    Optional body field ``family`` names the benchmark family to copy; it falls
    back to QAQC_BENCHMARK_FAMILY and then the built-in default, so a client
    whose model has no 'mwfBenchmark' is not stuck (audit blocker #1)."""
    body = payload if isinstance(payload, dict) else {}
    actor = str(body.get("actor", "backend"))
    family = revit_bridge.benchmark_family(body.get("family"))
    wf = benchmark_workflow.load()
    if wf.get("state") != "placing_markers":
        raise HTTPException(
            status_code=409,
            detail=f"Place-markers requires state 'placing_markers', "
            f"current is '{wf.get('state')}'.",
        )
    proposal = wf.get("proposal")
    if not proposal or not proposal.get("benchmarks"):
        raise HTTPException(status_code=409, detail="No approved proposal to place.")
    try:
        result = revit_bridge.place_benchmarks(proposal, family=family)
    except revit_bridge.BridgeError as exc:
        progress.emit("benchmark_workflow", "error", f"Marker placement failed: {exc}")
        raise HTTPException(status_code=409, detail=str(exc))
    if not result["ok"]:
        progress.emit("benchmark_workflow", "error",
                      "Placed markers did not verify against the proposal.")
        raise HTTPException(status_code=409, detail={
            "message": "Markers placed but read-back is off-tolerance — state unchanged.",
            "result": result,
        })
    benchmark_workflow.transition(
        wf, "awaiting_revit_approval", actor,
        note="Markers placed in Revit and read-back verified by the backend bridge.",
        payload={"readback": result["readback"], "element_ids": result["element_ids"],
                 "verified": True, "checks": result["checks"], "family": family},
    )
    benchmark_workflow.save(wf)
    progress.emit("benchmark_workflow", "done", "Markers placed + verified via MCP bridge")
    return JSONResponse({**wf, "result": result})
