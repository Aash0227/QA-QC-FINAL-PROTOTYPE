"""Revit bridge — drives Nonica's RevitMCPConnection.exe directly from the
backend (production-plan §2, "the critical challenge"). No Claude in the loop:
the placement procedure is a deterministic MCP tool sequence.

Feasibility proven 2026-07-20: the backend can spawn the exe, complete the MCP
handshake, and list all 52 Revit tools. A tool CALL only succeeds while the
Revit-side "AI Connector for Revit by Nonica" is open+enabled; when it is off,
every client (Claude's registered one included) gets the same timeout text —
so there is no single-client contention, just a live-connection requirement
surfaced via status().

The app's FastAPI endpoints are sync, so each public function runs the async
MCP client to completion via asyncio.run() — one fresh session per operation
(placements are rare; a persistent process/loop is a later optimization). The
placement SEQUENCE is factored behind an injected async ``call`` so its logic
is unit-tested with a fake harness without a live Revit.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import socket
from typing import Any, Awaitable, Callable

_LOG = logging.getLogger("qaqc.revit_bridge")

NONICA_EXE = os.environ.get(
    "NONICA_MCP_EXE",
    r"C:\NONICAPRO\OtherFiles\System\Core\net8.0-windows\RevitMCPConnection.exe",
)
MARK_PARAM_ID = -1001203        # built-in Revit "Mark" parameter
READBACK_TOLERANCE_FT = 0.05    # placed marker must land within this of intent
DEFAULT_BENCHMARK_FAMILY = "mwfBenchmark"
BENCHMARK_FAMILY_ENV = "QAQC_BENCHMARK_FAMILY"
BENCHMARK_OVERRIDE_HINT = (
    f"set {BENCHMARK_FAMILY_ENV} or pass 'family' in the place-markers payload")


def benchmark_family(override: str | None = None) -> str:
    """Which family the benchmark markers are copied from: an explicit request
    wins, then ``QAQC_BENCHMARK_FAMILY``, then the built-in default. Read at
    call time so the env var takes effect without a backend restart."""
    env = os.environ.get(BENCHMARK_FAMILY_ENV) or ""
    return (override or "").strip() or env.strip() or DEFAULT_BENCHMARK_FAMILY


CallFn = Callable[[str, dict], Awaitable[str]]

_DISCONNECTED_MARKERS = (
    "request timeout", "not be enabled", "must be kept open", "was not enabled",
)
# A healthy Nonica answer carries ContextUpdate framing, even when the payload
# it wraps is empty. Its ABSENCE next to an empty parse means the transport
# gave us something we don't understand — not that the model is empty.
_CONTEXT_MARKERS = ("type:", "source:", "context[", "context:", "model_title")


def _looks_disconnected(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in _DISCONNECTED_MARKERS)


def _looks_blocked(text: str) -> bool:
    """Revit UI is blocked by a modal dialog / active command. The connector
    answers, but no tool can run — reads must NOT be reported as facts
    ('nothing selected') while this is true (live finding 2026-07-28)."""
    low = (text or "").lower()
    return "ui was blocked" in low or "blocked by another" in low


_BLOCKED_REASON = ("Revit UI is blocked by an open dialog or active command — "
                   "press Esc in Revit / close the pop-up (keep the A.I. "
                   "Connector window open), then retry.")


def _looks_connected_payload(text: str) -> bool:
    """True when a response carries the structural markers of a real Nonica
    reply. Only consulted when a parse came back EMPTY — a response that
    yielded data is self-evidently understood (R-30)."""
    low = (text or "").lower()
    return any(m in low for m in _CONTEXT_MARKERS)


def _unrecognized(text: str) -> "BridgeError":
    """Empty parse + no structural markers = transport failure. Say that,
    rather than reporting a fact about the model we never actually read."""
    head = " ".join((text or "").split())[:120]
    return BridgeError(
        f"Unrecognized connector response — treating as disconnected: {head}")


def _first_xyz(text: str) -> tuple[float, float, float] | None:
    """First (x, y, z) triple in a Revit response, e.g. '(17.30, 62.17, 1.50)'."""
    m = re.search(r"\(\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*\)", text or "")
    return (float(m.group(1)), float(m.group(2)), float(m.group(3))) if m else None


_META_PREFIXES = ("model_title", "timestamp", "source", "type:", "language",
                  "is_linked_doc", "note:", "units")


def _element_ids(text: str) -> list[int]:
    """Every standalone integer that reads like a Revit ElementId (>= 5 digits),
    IGNORING metadata lines — the model title ('10510 Madera Dr…') and timestamp
    otherwise leak false ids (a real live bug this guards against)."""
    lines = [
        ln for ln in (text or "").splitlines()
        if not any(ln.strip().lower().startswith(p) for p in _META_PREFIXES)
    ]
    return [int(n) for n in re.findall(r"\b(\d{5,})\b", "\n".join(lines))]


# ---------------------------------------------------------------------------
# Deterministic placement sequence (pure over an injected async ``call``)
# ---------------------------------------------------------------------------
async def _benchmark_family_suggestions(call: CallFn, needle: str = "benchmark") -> list[str]:
    """Family names in the OPEN model containing ``needle`` (case-insensitive),
    for honest guidance when the configured family is missing. Best effort: an
    unreachable/unparseable listing yields [] and the caller just says less.
    Never auto-picks — naming the candidates is the operator's decision."""
    try:
        text = await call("get_all_families_in_model", {})
    except Exception:                       # tool absent on this connector build
        return []
    if _looks_disconnected(text):
        return []
    seen: dict[str, None] = {}
    for chunk in re.findall(rf"[\w.\- ]*{needle}[\w.\- ]*", text or "", re.I):
        name = chunk.strip()
        if name:
            seen.setdefault(name, None)
    return list(seen)[:10]


async def place_sequence(
    call: CallFn,
    proposal: dict[str, Any],
    family: str | None = None,
    tolerance_ft: float = READBACK_TOLERANCE_FT,
) -> dict[str, Any]:
    """Copy a benchmark family instance to each proposal point, set its Mark,
    read the placement back, and verify against intent. Returns
    {ok, element_ids, readback, checks}. Coordinates come only from the
    approved proposal's revit_point_ft — never re-derived. ``family`` defaults
    to the env/built-in benchmark family (see benchmark_family())."""
    family = benchmark_family(family)
    fam_res = await call("get_all_elements_of_specific_families", {"familyNames": [family]})
    template_ids = _element_ids(fam_res)
    if not template_ids:
        if not _looks_connected_payload(fam_res):
            raise _unrecognized(fam_res)    # R-30: nothing read != nothing there
        found = await _benchmark_family_suggestions(call)
        hint = (f" Families in this model matching 'benchmark': {', '.join(found)}."
                if found else "")
        raise BridgeError(
            f"No '{family}' family instance to copy in the model.{hint} "
            f"To use a different one, {BENCHMARK_OVERRIDE_HINT}.")
    template_id = template_ids[0]

    loc_res = await call("get_location_for_element_ids", {"list_elementIds": [template_id]})
    tpl = _first_xyz(loc_res)
    if tpl is None:
        raise BridgeError("Could not read the template benchmark's location.")

    element_ids: dict[str, int] = {}
    readback: dict[str, dict[str, float]] = {}
    checks: list[dict[str, Any]] = []
    all_ok = True
    known = set(template_ids)
    for bm in proposal["benchmarks"]:
        tgt = bm["revit_point_ft"]
        dx, dy = tgt["x"] - tpl[0], tgt["y"] - tpl[1]
        # Pinned-copy trick: a zero-vector copy of a pinned element fails, so a
        # target coincident with the template is nudged via a two-hop copy. In
        # practice the proposal points differ from the template, so the direct
        # vector copy is the norm.
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            raise BridgeError(
                f"{bm['mark']} target coincides with the template benchmark; "
                "move the template or pick a different reference."
            )
        copy_res = await call("set_copy_elements", {
            "list_elementIds": [template_id],
            "mov_vect_X": [round(dx, 6)], "mov_vect_Y": [round(dy, 6)], "mov_vect_Z": [0.0],
        })
        # Live finding (2026-07-20): this Nonica version reports pinned templates
        # as InvalidCopy and copies nothing — MCP has no unpin tool, so the
        # operator must unpin the template (or provide a non-pinned benchmark
        # instance) first. Surface that clearly instead of "no new id".
        if "is pinned" in copy_res.lower() or "invalidcopy" in copy_res.lower():
            raise BridgeError(
                f"Benchmark template '{family}' (id {template_id}) is pinned — Revit "
                "won't copy it. Unpin it in Revit (select it, press UP/Unpin) or add "
                "one non-pinned benchmark instance, then retry."
            )
        new_ids = [i for i in _element_ids(copy_res) if i not in known]
        if not new_ids:
            raise BridgeError(f"{bm['mark']}: copy returned no new element id.")
        new_id = new_ids[0]
        known.add(new_id)
        element_ids[bm["mark"]] = new_id

        await call("set_parameter_value_for_elements", {
            "list_elementIds": [new_id], "idParameter": MARK_PARAM_ID,
            "list_newValues": [bm["mark"]],
        })

        rb_res = await call("get_location_for_element_ids", {"list_elementIds": [new_id]})
        got = _first_xyz(rb_res)
        if got is None:
            all_ok = False
            checks.append({"mark": bm["mark"], "ok": False, "delta_ft": None,
                           "reason": "no readback location"})
            continue
        readback[bm["mark"]] = {"x": got[0], "y": got[1]}
        delta = math.hypot(got[0] - tgt["x"], got[1] - tgt["y"])
        ok = delta <= tolerance_ft
        all_ok = all_ok and ok
        checks.append({"mark": bm["mark"], "ok": ok, "delta_ft": round(delta, 4),
                       "element_id": new_id})

    return {"ok": all_ok, "element_ids": element_ids, "readback": readback, "checks": checks}


class BridgeError(RuntimeError):
    """A Revit-side failure (family missing, copy failed, connector off)."""


# ---------------------------------------------------------------------------
# Live element-id lookup for holdown assemblies (feature: QA manual verify).
# Export-time UniqueIds embed the CREATION ElementId, which central-model
# operations can change — so the trustworthy id for "Select by ID" in Revit
# must come from the live model, matched by coordinate.
# ---------------------------------------------------------------------------
STRUCT_CONNECTIONS_CAT = -2009030   # OST_StructConnections (holdown hardware)
_CONN_CACHE: dict[str, Any] = {"ts": 0.0, "locations": {}}
_CONN_CACHE_TTL_S = 300.0           # one bridge round-trip serves 5 min of clicks


def _parse_id_locations(text: str) -> dict[int, tuple[float, float]]:
    """Lines like '2897203,LocationPoint,"(38.05, 32.52, 1.50)"' -> {id: (x, y)},
    skipping metadata lines (same false-id hazard as _element_ids)."""
    out: dict[int, tuple[float, float]] = {}
    for ln in (text or "").splitlines():
        if any(ln.strip().lower().startswith(p) for p in _META_PREFIXES):
            continue
        m = re.match(r"\s*(\d{5,})\s*,[^,]*,.*?\(\s*(-?\d+\.?\d*)\s*[,;]\s*(-?\d+\.?\d*)", ln)
        if m:
            out[int(m.group(1))] = (float(m.group(2)), float(m.group(3)))
    return out


async def connection_locations_sequence(call: CallFn) -> dict[int, tuple[float, float]]:
    """All live Structural-Connection ids with (x, y) in model feet."""
    cat_res = await call("get_elements_by_category",
                         {"list_categoryids": [STRUCT_CONNECTIONS_CAT]})
    if _looks_disconnected(cat_res):
        raise BridgeError("Revit AI Connector is off — open Revit and enable "
                          "the NonicaTab PRO AI Connector, then retry.")
    subset = re.search(r"(-9\d{6,})", cat_res)
    ids = [int(subset.group(1))] if subset else _element_ids(cat_res)
    if not ids:
        # R-30: an empty parse only means "the model has none" if the response
        # was a response at all. Otherwise it is a transport failure.
        raise (BridgeError("No Structural Connections found in the live model.")
               if _looks_connected_payload(cat_res) else _unrecognized(cat_res))
    loc_res = await call("get_location_for_element_ids", {"list_elementIds": ids})
    locs = _parse_id_locations(loc_res)
    if not locs:
        raise (BridgeError("Could not read Structural Connection locations.")
               if _looks_connected_payload(loc_res) else _unrecognized(loc_res))
    return locs


def live_connection_locations(force: bool = False) -> dict[str, Any]:
    """Cached {id: (x, y)} of every live Structural Connection. Never raises:
    connector-off reads as connected=False with an honest reason.

    R-15: ``cached``/``age_s`` travel with the answer so callers can say "as of
    N s ago" instead of implying every read is live."""
    import time

    now = time.monotonic()
    if (not force and _CONN_CACHE["locations"]
            and now - _CONN_CACHE["ts"] < _CONN_CACHE_TTL_S):
        return {"connected": True, "cached": True,
                "age_s": round(now - _CONN_CACHE["ts"], 1),
                "locations": _CONN_CACHE["locations"]}

    async def _fn(call: CallFn):
        return await connection_locations_sequence(call)

    try:
        locs = _run(_fn)
    except BridgeError as exc:
        return {"connected": False, "reason": str(exc), "cached": False,
                "age_s": None, "locations": {}}
    except Exception as exc:   # exe missing, spawn failure, init timeout
        return {"connected": False, "reason": f"bridge unavailable: {exc}",
                "cached": False, "age_s": None, "locations": {}}
    _CONN_CACHE.update(ts=now, locations=locs)
    return {"connected": True, "cached": False, "age_s": 0.0, "locations": locs}


# ---------------------------------------------------------------------------
# Live selection / location reads (feature: Revit-live Phase 1).
# The Nonica MCP has NO zoom tool and NO operate_element — selecting the ids
# and telling the operator to press ZS is the whole "show me this" gesture.
# ---------------------------------------------------------------------------
_CONNECTOR_OFF = "Revit AI Connector (NonicaTab PRO) is closed or disabled."


def _labelled_ids(text: str, label: str) -> list[int]:
    """Ids on a 'selected_ids[2]: 1254, 1070039' / 'invalid_ids[0]:' line.
    Plain int scan (not _element_ids) — real ElementIds can be 4 digits."""
    m = re.search(rf"{label}\s*\[\d+\]\s*:(.*)", text or "")
    return [int(n) for n in re.findall(r"-?\d+", m.group(1))] if m else []


def _subset_ids(text: str, label: str) -> tuple[int, list[int]]:
    """Large batches come back COMPRESSED as a subset, e.g.
    'selected_ids[28]{SubsetId,IdsCount,SampleElementId}:\\n  -9000017,28,2804799'
    -> (count, [sample_id]). Returns (0, []) when the label isn't compressed."""
    m = re.search(rf"{label}\s*\[\d+\]\s*\{{[^}}]*\}}\s*:\s*(-?\d+)\s*,\s*(\d+)\s*,\s*(\d+)",
                  text or "", re.S)
    return (int(m.group(2)), [int(m.group(3))]) if m else (0, [])


def select_elements(element_ids: list[int]) -> dict[str, Any]:
    """Set the Revit user selection. Never raises — connector-off reads as
    ok=False with an honest reason."""
    async def _fn(call: CallFn):
        return await call("set_user_selection_in_revit",
                          {"list_elementIds": [int(i) for i in element_ids]})
    try:
        text = _run(_fn)
    except Exception as exc:   # exe missing, spawn failure, init timeout
        return {"ok": False, "selected_ids": [], "invalid_ids": [],
                "reason": f"bridge unavailable: {exc}"}
    if _looks_disconnected(text):
        return {"ok": False, "selected_ids": [], "invalid_ids": [],
                "selected_count": 0, "reason": _CONNECTOR_OFF}
    if _looks_blocked(text):
        return {"ok": False, "selected_ids": [], "invalid_ids": [],
                "selected_count": 0, "reason": _BLOCKED_REASON}
    selected = _labelled_ids(text, "selected_ids")
    count = len(selected)
    if not selected:
        count, selected = _subset_ids(text, "selected_ids")
    invalid = _labelled_ids(text, "invalid_ids")
    ok = bool(selected) or "selected successfully" in (text or "").lower()
    return {"ok": ok, "selected_ids": selected, "invalid_ids": invalid,
            "selected_count": count,
            "reason": None if ok else "Revit selected none of the requested ids."}


def get_selection() -> dict[str, Any]:
    """What the operator currently has selected in Revit. Never raises."""
    async def _fn(call: CallFn):
        return await call("get_user_selection_in_revit", {})
    try:
        text = _run(_fn)
    except Exception as exc:
        return {"ok": False, "element_ids": [], "reason": f"bridge unavailable: {exc}"}
    if _looks_disconnected(text):
        return {"ok": False, "element_ids": [], "reason": _CONNECTOR_OFF}
    if _looks_blocked(text):
        return {"ok": False, "element_ids": [], "reason": _BLOCKED_REASON}
    ids = _labelled_ids(text, "selected_ids")
    if not ids:
        _, ids = _subset_ids(text, "selected_ids")   # compressed: sample id only
    if not ids:
        ids = _element_ids(text)
    return {"ok": True, "element_ids": ids, "reason": None}


def element_location(element_id: int) -> dict[str, Any]:
    """(x, y) in model feet for one element. Never raises."""
    async def _fn(call: CallFn):
        return await call("get_location_for_element_ids", {"list_elementIds": [int(element_id)]})
    try:
        text = _run(_fn)
    except Exception as exc:
        return {"ok": False, "x": None, "y": None, "reason": f"bridge unavailable: {exc}"}
    if _looks_disconnected(text):
        return {"ok": False, "x": None, "y": None, "reason": _CONNECTOR_OFF}
    pt = _parse_id_locations(text).get(int(element_id))
    if pt is None:
        xyz = _first_xyz(text)          # short (<5-digit) ids never match the id-line regex
        pt = (xyz[0], xyz[1]) if xyz else None
    if pt is None:
        # ponytail: no R-30 structural check here — this read only happens
        # AFTER live_connection_locations() proved the connector answers, so an
        # empty reply really is "Revit knows no location", not noise.
        return {"ok": False, "x": None, "y": None,
                "reason": f"No location reported for element {element_id}."}
    return {"ok": True, "x": pt[0], "y": pt[1], "reason": None}


# ---------------------------------------------------------------------------
# Second bridge: the OPEN-SOURCE revit-mcp plugin (mcp-servers-for-revit).
# Its Revit add-in listens on a plain TCP socket speaking one-shot JSON-RPC;
# the Node MCP server it ships with is only a relay over that same socket, so
# the backend talks to the socket directly — stdlib socket+json, no node, no
# server discovery, no new dep. Verified live 2026-07-27 against the add-in in
# %APPDATA%\Autodesk\Revit\Addins\2023\revit_mcp_plugin (port 8080).
# ponytail: no framing protocol here — the add-in writes exactly one JSON
# object per request, so "json.loads succeeded" IS the frame delimiter.
# ---------------------------------------------------------------------------
REVIT_MCP_ADDR = os.environ.get("REVIT_MCP_ADDR", "127.0.0.1:8080")
_NOTHING_SELECTED = "Nothing selected in Revit — pick an element there first."


def _revit_mcp_call(method: str, params: dict, timeout: float = 10.0) -> dict:
    """One JSON-RPC round trip to the revit-mcp add-in socket. Raises on any
    transport failure (server not started, Revit closed, timeout)."""
    host, _, port = REVIT_MCP_ADDR.partition(":")
    req = {"jsonrpc": "2.0", "method": method, "params": params, "id": "1"}
    with socket.create_connection((host, int(port or 8080)), timeout=timeout) as sock:
        sock.sendall(json.dumps(req).encode("utf-8"))
        buf = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                raise BridgeError("revit-mcp socket closed before a full response.")
            buf += chunk
            try:
                return json.loads(buf.decode("utf-8"))
            except ValueError:
                continue        # partial JSON — keep reading


def _from_revit_mcp(el: dict[str, Any]) -> dict[str, Any]:
    """One get_selected_elements entry -> the public shape. The add-in reports
    Id / UniqueId / Name / Category / Properties; ``Name`` is the Revit element
    name (the TYPE name for a family instance), and there is no point or level
    in this payload — those stay None rather than being invented."""
    props = el.get("Properties") or {}
    return {
        "ok": True, "source": "revit_mcp", "element_id": int(el["Id"]),
        "family": props.get("Family") or props.get("FamilyName"),
        "type": el.get("Name"), "mark": props.get("Mark"),
        "category": el.get("Category"), "point": None,
        "level": props.get("Level"), "parameters": props or None, "reason": None,
    }


def get_selected_element_full() -> dict[str, Any]:
    """Everything the live model will tell us about the operator's CURRENT
    selection, richest source first. Never raises.

    1. Open-source revit-mcp (mcp-servers-for-revit) over its TCP socket at
       ``REVIT_MCP_ADDR`` (default 127.0.0.1:8080) — gives id, type name and
       category. OPERATOR STEP: the add-in's socket server must be started
       from inside Revit (revitMCP ribbon -> "Open Server") or this path is
       simply unreachable and we fall through.
    2. Nonica (get_user_selection_in_revit -> get_location_for_element_ids) —
       gives an id and an (x, y) but no family/type.

    Returns {ok, source, element_id, family, type, mark, category, point,
    level, parameters, reason}.
    """
    try:
        res = _revit_mcp_call("get_selected_elements", {"limit": 1})
        elements = res.get("result") or []
        if elements:
            return _from_revit_mcp(elements[0])
        if not res.get("error"):
            # Server answered and the selection is genuinely empty — that is an
            # answer, not a failure, so don't second-guess it via Nonica.
            return {"ok": False, "source": "revit_mcp", "element_id": None,
                    "family": None, "type": None, "mark": None, "category": None,
                    "point": None, "level": None, "parameters": None,
                    "reason": _NOTHING_SELECTED}
    except Exception:
        pass        # server not started / Revit closed — fall through to Nonica

    sel = get_selection()
    ids = sel.get("element_ids") or []
    out = {"ok": False, "source": "nonica", "element_id": None, "family": None,
           "type": None, "mark": None, "category": None, "point": None,
           "level": None, "parameters": None, "reason": sel.get("reason")}
    if not sel.get("ok"):
        return out
    if not ids:
        return {**out, "reason": _NOTHING_SELECTED}
    eid = int(ids[0])
    loc = element_location(eid)
    return {**out, "ok": True, "element_id": eid,
            "point": [loc["x"], loc["y"]] if loc.get("ok") else None,
            "reason": None if loc.get("ok") else loc.get("reason")}


# ---------------------------------------------------------------------------
# Live 3D massing (feature: hybrid live-Revit viewer).
#
# Bounding boxes are the only geometry the Nonica MCP hands out in bulk, so the
# live "model" is an honest box massing per category — never presented as real
# geometry. Verified live 2026-07-28 against a 28k-element LGS model:
#   * get_elements_by_category returns one block per category, compressing big
#     lists to a subset line (-9000002,28380,2248112);
#   * get_boundingboxes_for_element_ids ACCEPTS a subset id directly and answers
#     with per-element rows, so small categories need no expansion at all;
#   * only oversized categories are expanded (get_element_ids_from_subsets) and
#     chunked, because their raw-id list is what the cap has to slice.
# ---------------------------------------------------------------------------
SCENE_CATEGORIES = (
    # (public name, Revit BuiltInCategory id, OST name in the response)
    ("walls", -2000011, "OST_Walls"),
    ("framing", -2001320, "OST_StructuralFraming"),
    ("columns", -2001330, "OST_StructuralColumns"),
    ("connections", -2009030, "OST_StructConnections"),
)
SCENE_MAX_PER_CATEGORY = 3000   # a 28k-member framing category would stall the pane
SCENE_BBOX_CHUNK = 300          # ids per get_boundingboxes call (response-size guard)
_SCENE_CACHE: dict[str, Any] = {"ts": 0.0, "scene": None}
_SCENE_CACHE_TTL_S = 60.0

_BBOX_RE = re.compile(
    r'^\s*(\d+)\s*,\s*"?\[\s*\(([^)]*)\)\s*,\s*\(([^)]*)\)\s*\]')


def _parse_category_blocks(text: str) -> dict[str, dict[str, Any]]:
    """'- Category: OST_Walls' blocks -> {ost_name: {count, ids, subset_id}}.
    Big categories compress to a subset triple, small ones list ids inline."""
    out: dict[str, dict[str, Any]] = {}
    for block in re.split(r"-\s*Category\s*:\s*", text or "")[1:]:
        name = block.splitlines()[0].strip()
        sub = re.search(
            r"ElementIdsOfCategory\s*\[\d+\]\s*\{[^}]*\}\s*:\s*(-?\d+)\s*,\s*(\d+)\s*,\s*(\d+)",
            block, re.S)
        if sub:
            out[name] = {"count": int(sub.group(2)), "ids": [], "subset_id": int(sub.group(1))}
            continue
        inline = re.search(r"ElementIdsOfCategory\s*\[\d+\]\s*:([^\n]*)", block)
        if inline:
            ids = [int(n) for n in re.findall(r"\d+", inline.group(1))]
            out[name] = {"count": len(ids), "ids": ids, "subset_id": None}
    return out


def _parse_bboxes(text: str) -> dict[int, list[float]]:
    """Rows like '1029591,"[(82.50, 55.75, -0.27), (83.00, 56.25, 12.48)]"'
    -> {id: [minx, miny, minz, maxx, maxy, maxz]}."""
    out: dict[int, list[float]] = {}
    for ln in (text or "").splitlines():
        m = _BBOX_RE.match(ln)
        if not m:
            continue
        try:
            lo = [float(v) for v in m.group(2).split(",")]
            hi = [float(v) for v in m.group(3).split(",")]
        except ValueError:
            continue
        if len(lo) == 3 and len(hi) == 3:
            out[int(m.group(1))] = lo + hi
    return out


def _parse_subset_ids(text: str) -> list[int]:
    """'ElementIds[22]: 981860,981861,…' -> [ids]."""
    m = re.search(r"ElementIds\s*\[\d+\]\s*:([^\n]*)", text or "")
    return [int(n) for n in re.findall(r"\d+", m.group(1))] if m else []


async def scene_geometry_sequence(
    call: CallFn,
    max_per_category: int = SCENE_MAX_PER_CATEGORY,
    chunk: int = SCENE_BBOX_CHUNK,
) -> dict[str, Any]:
    """Live box massing for every SCENE_CATEGORIES entry in the OPEN model.
    Pure over the injected ``call`` so it is unit-tested without Revit."""
    view = await call("get_active_view_in_revit", {})
    if _looks_disconnected(view):
        raise BridgeError("Revit AI Connector is off — open Revit and enable "
                          "the NonicaTab PRO AI Connector, then retry.")
    mt = re.search(r"model_title:\s*(.+)", view)
    model_title = mt.group(1).strip() if mt else None

    cat_res = await call("get_elements_by_category",
                         {"list_categoryids": [cid for _, cid, _ in SCENE_CATEGORIES]})
    if _looks_disconnected(cat_res):
        raise BridgeError("Revit AI Connector went away mid-read — retry.")
    blocks = _parse_category_blocks(cat_res)
    if not blocks and not _looks_connected_payload(cat_res):
        raise _unrecognized(cat_res)   # R-30: don't render "empty model" from noise

    categories: dict[str, list[dict[str, Any]]] = {}
    truncated: dict[str, dict[str, Any]] = {}
    for name, _cid, ost in SCENE_CATEGORIES:
        blk = blocks.get(ost)
        if not blk or not blk["count"]:
            categories[name] = []
            continue
        boxes: dict[int, list[float]] = {}
        if blk["subset_id"] is not None and blk["count"] <= max_per_category:
            # A subset id IS a valid element id for this tool — one round trip.
            boxes.update(_parse_bboxes(await call(
                "get_boundingboxes_for_element_ids", {"list_elementIds": [blk["subset_id"]]})))
        else:
            ids = blk["ids"]
            if blk["subset_id"] is not None:
                ids = _parse_subset_ids(await call(
                    "get_element_ids_from_subsets", {"list_subsetIds": [blk["subset_id"]]}))
                if len(ids) < blk["count"]:
                    _LOG.warning("live scene: %s subset expanded to %d of %d reported ids",
                                 name, len(ids), blk["count"])
                    truncated[name] = {"reported": blk["count"], "expanded": len(ids)}
            if len(ids) > max_per_category:
                _LOG.warning("live scene: %s capped at %d of %d elements",
                             name, max_per_category, len(ids))
                truncated[name] = {**truncated.get(name, {}),
                                   "total": len(ids), "kept": max_per_category}
                ids = ids[:max_per_category]
            for i in range(0, len(ids), chunk):
                boxes.update(_parse_bboxes(await call(
                    "get_boundingboxes_for_element_ids",
                    {"list_elementIds": ids[i:i + chunk]})))
        if len(boxes) < min(blk["count"], max_per_category):
            _LOG.warning("live scene: %s returned %d boxes for %d requested elements",
                         name, len(boxes), min(blk["count"], max_per_category))
            truncated.setdefault(name, {}).update(
                boxes=len(boxes), requested=min(blk["count"], max_per_category))
        categories[name] = [{"id": eid, "bbox_ft": bb} for eid, bb in sorted(boxes.items())]

    every = [e["bbox_ft"] for els in categories.values() for e in els]
    bounds = None
    if every:
        bounds = {
            "min_x": min(b[0] for b in every), "min_y": min(b[1] for b in every),
            "min_z": min(b[2] for b in every), "max_x": max(b[3] for b in every),
            "max_y": max(b[4] for b in every), "max_z": max(b[5] for b in every),
        }
    return {
        "ok": True, "model_title": model_title, "units": "feet",
        "categories": categories,
        "counts": {k: len(v) for k, v in categories.items()},
        "truncated": truncated, "bounds": bounds, "reason": None,
        "note": "Live massing from Revit bounding boxes — not real geometry.",
    }


def live_scene_geometry(force: bool = False) -> dict[str, Any]:
    """Cached (60 s) live box massing of the open model. Never raises:
    connector-off reads as ok:false with an honest reason."""
    import time

    now = time.monotonic()
    if not force and _SCENE_CACHE["scene"] and now - _SCENE_CACHE["ts"] < _SCENE_CACHE_TTL_S:
        return {**_SCENE_CACHE["scene"], "cached": True}
    offline = {"ok": False, "model_title": None, "categories": {}, "counts": {},
               "truncated": {}, "bounds": None, "cached": False}
    try:
        scene = _run(scene_geometry_sequence)
    except BridgeError as exc:
        return {**offline, "reason": str(exc)}
    except Exception as exc:      # exe missing, spawn failure, init timeout
        return {**offline, "reason": f"bridge unavailable: {exc}"}
    _SCENE_CACHE.update(ts=now, scene=scene)
    return {**scene, "cached": False}


# ---------------------------------------------------------------------------
# Live MCP transport (spawns the exe; each op is one session)
# ---------------------------------------------------------------------------
async def _live_call_factory(session):
    async def call(name: str, args: dict) -> str:
        res = await asyncio.wait_for(session.call_tool(name, args), timeout=30)
        return "".join(getattr(c, "text", "") for c in res.content)
    return call


async def _with_session(fn: Callable[[CallFn], Awaitable[Any]], init_timeout: float = 20):
    """One MCP session = one RevitMCPConnection.exe, spawned and reaped by
    ``stdio_client``.

    Orphan-reaper investigation (2026-07-31): the orphaned RevitMCPConnection.exe
    processes on this box are NOT ours. Measured with Revit closed — one
    status() call, 14.1 s, zero net new processes — and every live orphan's
    ParentProcessId resolves to claude.exe (Claude Desktop's own registered
    Revit MCP server, and claude-code), not to python. mcp 1.26.0's
    stdio_client finally-block does stdin close -> wait(2 s) ->
    _terminate_process_tree, which on Windows terminates a Job Object created
    with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; pywin32 is installed here, so that
    path is live and works.

    So there is deliberately no name-based _reap_orphans(): a taskkill filtered
    to RevitMCPConnection.exe would kill Claude Desktop's live connection, and
    a "created > 10 min ago" guard cannot tell a long-lived healthy session from
    a corpse. The real spawn-hygiene fix for the new polled endpoint is
    status_cached() above — one spawn per 30 s instead of one per poll."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=NONICA_EXE, args=[])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), timeout=init_timeout)
            call = await _live_call_factory(session)
            return await fn(call)


def _run(fn: Callable[[CallFn], Awaitable[Any]]) -> Any:
    return asyncio.run(_with_session(fn))


def status() -> dict[str, Any]:
    """Live connection status via get_active_view_in_revit. Never raises —
    a spawn/transport failure or the connector being off both read as
    disconnected, which is exactly what the wizard needs to show."""
    async def _fn(call: CallFn):
        return await call("get_active_view_in_revit", {})
    try:
        text = _run(_fn)
    except Exception as exc:  # exe missing, spawn failure, init timeout
        return {"connected": False, "reason": f"bridge unavailable: {exc}", "model_title": None}
    if _looks_disconnected(text):
        return {"connected": False,
                "reason": "Revit AI Connector (NonicaTab PRO) is closed or disabled.",
                "model_title": None}
    m = re.search(r"model_title:\s*(.+)", text)
    return {"connected": True, "reason": None,
            "model_title": (m.group(1).strip() if m else None)}


_STATUS_CACHE: dict[str, Any] = {"ts": 0.0, "status": None}
_STATUS_CACHE_TTL_S = 30.0
# Measured 2026-07-31 with Revit closed: one status() costs ~14 s of handshake
# before it can say "disconnected". Re-asking that every 30 s wedges a worker
# thread for half the time a poller is running, and the answer never changes on
# its own — Revit opening is an operator action, and the Connect card's Refresh
# button busts the cache. So the negative answer is held much longer.
_STATUS_CACHE_OFFLINE_TTL_S = 300.0


def status_cached(ttl_s: float | None = None, force: bool = False) -> dict[str, Any]:
    """status() behind a TTL, for endpoints the UI POLLS.

    Spawn hygiene: every _run() spawns a fresh RevitMCPConnection.exe, so a 2 s
    poll calling status() directly would be a process storm. ``cached``/``age_s``
    travel with the answer (R-15) so no caller can pass a 30 s-old read off as
    live. ``force=True`` is the operator's Refresh."""
    import time

    now = time.monotonic()
    hit = _STATUS_CACHE["status"]
    if hit is not None and not force:
        ttl = ttl_s if ttl_s is not None else (
            _STATUS_CACHE_TTL_S if hit.get("connected") else _STATUS_CACHE_OFFLINE_TTL_S)
        if now - _STATUS_CACHE["ts"] < ttl:
            return {**hit, "cached": True, "age_s": round(now - _STATUS_CACHE["ts"], 1)}
    fresh = status()
    _STATUS_CACHE.update(ts=now, status=fresh)
    return {**fresh, "cached": False, "age_s": 0.0}


def place_benchmarks(proposal: dict[str, Any], family: str | None = None) -> dict[str, Any]:
    """Live placement of BM-1/BM-2 using ``family`` (default: env/built-in, see
    benchmark_family()). Raises BridgeError on any Revit-side failure (incl.
    connector off, surfaced as a clear message)."""
    async def _fn(call: CallFn):
        # Fail fast + clearly if the connector is off.
        probe = await call("get_active_view_in_revit", {})
        if _looks_disconnected(probe):
            raise BridgeError("Revit AI Connector is off — open Revit and enable "
                              "the NonicaTab PRO AI Connector, then retry.")
        return await place_sequence(call, proposal, family)
    return _run(_fn)


if __name__ == "__main__":
    # Self-check: the placement sequence logic over a fake Revit.
    async def _fake(name, args):
        if name == "get_all_elements_of_specific_families":
            return "families: 175646 mwfBenchmark"
        if name == "get_location_for_element_ids":
            eid = args["list_elementIds"][0]
            if eid == 175646:
                return '175646,LocationPoint,"(10.00, 20.00, 1.50)"'
            return '900001,LocationPoint,"(75.97, 4.72, 1.50)"'  # readback ~ target
        if name == "set_copy_elements":
            return "Copied. New element ids: 900001"
        if name == "set_parameter_value_for_elements":
            return "ok"
        return ""
    prop = {"benchmarks": [{"mark": "BM-2", "revit_point_ft": {"x": 75.97, "y": 4.72}}]}
    out = asyncio.run(place_sequence(_fake, prop))
    assert out["ok"] is True, out
    assert out["element_ids"]["BM-2"] == 900001
    assert out["checks"][0]["delta_ft"] < 0.05
    assert _looks_disconnected("The request timeout. ... AI Connector ... not be enabled")
    assert not _looks_disconnected("model_title: Madera")
    assert _looks_connected_payload("type: ContextUpdate\nsource: Revit")
    assert not _looks_connected_payload("\x00\x00garbage")
    assert benchmark_family("Acme_BM") == "Acme_BM"
    assert benchmark_family() == DEFAULT_BENCHMARK_FAMILY   # no env set here
    sel = "status: Element ids selected successfully.\nselected_ids[2]: 1254, 1070039\ninvalid_ids[0]:"
    assert _labelled_ids(sel, "selected_ids") == [1254, 1070039]
    assert _labelled_ids(sel, "invalid_ids") == []
    print("revit_bridge self-check OK")
