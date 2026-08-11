"""Revit-live Phase 1: selection / current-selection / element-location bridge
ops and the highlight + paste-an-ElementId lookup endpoints.

Same discipline as test_revit_bridge.py — a fake async ``call`` stands in for
the Nonica MCP (``_run`` monkeypatched), so nothing spawns a subprocess and the
connector-off behaviour is exercised exactly as the live one reports it.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from app import config, revit_bridge as rb, revit_ids
from app.routers import revit as revit_router

TIMEOUT_TEXT = ("The request timeout. The AI Connector for Revit by Nonica "
                "must be kept open and was not enabled.")


@pytest.fixture()
def tmp_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path)
    monkeypatch.setattr(config, "EVIDENCE_DIR", tmp_path / "evidence")
    return tmp_path


def _bridge(monkeypatch: pytest.MonkeyPatch, call) -> None:
    """Route every bridge op through a fake MCP instead of the exe."""
    monkeypatch.setattr(rb, "_run", lambda fn: asyncio.run(fn(call)))


def _fake_revit(select_ok: bool = True):
    async def call(name: str, args: dict) -> str:
        if name == "set_user_selection_in_revit":
            ids = args["list_elementIds"]
            good = [i for i in ids if i > 0] if select_ok else []
            bad = [i for i in ids if i <= 0] if select_ok else ids
            status = ("status: Element ids selected successfully.\n" if good
                      else "status: No valid element ids to select.\n")
            return (status
                    + f"selected_ids[{len(good)}]: {', '.join(str(i) for i in good)}\n"
                    f"invalid_ids[{len(bad)}]: {', '.join(str(i) for i in bad)}")
        if name == "get_user_selection_in_revit":
            return "selected_ids[2]: 1254, 1070039"
        if name == "get_location_for_element_ids":
            eid = args["list_elementIds"][0]
            return f'{eid},LocationPoint,"(38.05, 32.52, 1.50)"'
        return ""
    return call


def _dead_revit():
    async def call(name: str, args: dict) -> str:
        return TIMEOUT_TEXT
    return call


# ---------------------------------------------------------------------------
# bridge ops
# ---------------------------------------------------------------------------
def test_select_elements_ok(monkeypatch) -> None:
    _bridge(monkeypatch, _fake_revit())
    out = rb.select_elements([1254, 1070039])
    assert out == {"ok": True, "selected_ids": [1254, 1070039],
                   "invalid_ids": [], "selected_count": 2, "reason": None}


def test_select_elements_subset_compressed_response(monkeypatch) -> None:
    """Large batches come back COMPRESSED (the real bug seen live 2026-07-27:
    28 ids -> 'selected_ids[28]{SubsetId,IdsCount,SampleElementId}' and the old
    parser reported 'selected none' for a selection that succeeded)."""
    async def call(name: str, args: dict) -> str:
        return ("status: Element ids selected successfully.\n"
                "selected_ids[28]{SubsetId,IdsCount,SampleElementId}:\n"
                "    -9000017,28,2804799\n"
                "invalid_ids[0]:")
    _bridge(monkeypatch, call)
    out = rb.select_elements(list(range(1000000, 1000028)))
    assert out["ok"] is True
    assert out["selected_count"] == 28
    assert out["selected_ids"] == [2804799]   # sample id — the batch is a subset


def test_select_elements_reports_invalid_ids(monkeypatch) -> None:
    _bridge(monkeypatch, _fake_revit())
    out = rb.select_elements([1254, -7])
    assert out["ok"] is True
    assert out["selected_ids"] == [1254] and out["invalid_ids"] == [-7]


def test_select_elements_none_selected(monkeypatch) -> None:
    _bridge(monkeypatch, _fake_revit(select_ok=False))
    out = rb.select_elements([1254])
    assert out["ok"] is False and out["invalid_ids"] == [1254]
    assert "selected none" in out["reason"]


def test_select_elements_disconnected(monkeypatch) -> None:
    _bridge(monkeypatch, _dead_revit())
    out = rb.select_elements([1254])
    assert out["ok"] is False and out["selected_ids"] == []
    assert "Connector" in out["reason"]


def test_select_elements_bridge_unavailable(monkeypatch) -> None:
    def _boom(fn):
        raise FileNotFoundError("RevitMCPConnection.exe")
    monkeypatch.setattr(rb, "_run", _boom)
    out = rb.select_elements([1254])
    assert out["ok"] is False and "bridge unavailable" in out["reason"]


def test_get_selection_ok(monkeypatch) -> None:
    _bridge(monkeypatch, _fake_revit())
    assert rb.get_selection() == {"ok": True, "element_ids": [1254, 1070039], "reason": None}


def test_selection_reads_blocked_ui_as_error(monkeypatch) -> None:
    """A modal dialog in Revit blocks every tool. That must surface as an
    error with the unblock hint — NOT as 'nothing selected' (live finding
    2026-07-28: the revitMCP 'Open Server' dialog made an active selection
    read back as empty)."""
    async def call(name, args):
        return ("The tool was attempted to be run, but it couldn´t. The "
                "connection with Revit is active, but Revit UI was blocked by "
                "another command/tool or window.")
    _bridge(monkeypatch, call)
    sel = rb.get_selection()
    assert sel["ok"] is False and "blocked" in sel["reason"].lower()
    out = rb.select_elements([1254])
    assert out["ok"] is False and "blocked" in out["reason"].lower()


def test_get_selection_disconnected(monkeypatch) -> None:
    _bridge(monkeypatch, _dead_revit())
    out = rb.get_selection()
    assert out["ok"] is False and out["element_ids"] == []


def test_element_location_ok(monkeypatch) -> None:
    _bridge(monkeypatch, _fake_revit())
    out = rb.element_location(2897203)
    assert out["ok"] is True and (out["x"], out["y"]) == (38.05, 32.52)


def test_element_location_short_id(monkeypatch) -> None:
    """4-digit ids never match the id-prefixed line regex — the xyz fallback
    must still read the point."""
    _bridge(monkeypatch, _fake_revit())
    out = rb.element_location(1254)
    assert out["ok"] is True and out["y"] == 32.52


def test_element_location_missing(monkeypatch) -> None:
    async def call(name, args):
        return "no geometry"
    _bridge(monkeypatch, call)
    out = rb.element_location(1254)
    assert out["ok"] is False and "No location" in out["reason"]


def test_element_location_disconnected(monkeypatch) -> None:
    _bridge(monkeypatch, _dead_revit())
    out = rb.element_location(1254)
    assert out["ok"] is False and out["x"] is None


def test_labelled_ids_empty_list() -> None:
    assert rb._labelled_ids("invalid_ids[0]:", "invalid_ids") == []
    assert rb._labelled_ids("nothing here", "selected_ids") == []


# ---------------------------------------------------------------------------
# artifacts + endpoints
# ---------------------------------------------------------------------------
MEMBER_UID = revit_ids._make_unique_id("bcb941f0c3f9", 2897203)


def _seed(tmp: Path, *, status: str = "MATCH", distance_ft: float = 0.64,
          with_registry: bool = True) -> None:
    (tmp / "AIConvert_revit.json").write_text(json.dumps({
        "canonical_holdown_assemblies": [{
            "id": "rev_asm_011", "pdf_mark_candidate": "H1",
            "member_element_ids": [MEMBER_UID],
            "center_point": {"x": 38.049, "y": 32.524, "z": 1.5},
        }]
    }), encoding="utf-8")
    if not with_registry:
        return
    (tmp / "device_registry.json").write_text(json.dumps({"categories": {"holdown": {
        "devices": [{
            "id": "holdown_dev_001", "mark": "H1", "x": 38.5, "y": 32.9,
            "status": status, "target_id": "rev_asm_011",
            "target_point": [38.049, 32.524], "distance_ft": distance_ft,
            "appearances": ["r1"], "sheets": ["S-201"],
            "reason": "paired by mark and proximity",
        }]}}}), encoding="utf-8")
    (tmp / "element_list.json").write_text(json.dumps({"elements": [
        {"id": "r1", "device_id": "holdown_dev_001", "category": "holdown",
         "status": status, "mark": "H1", "distance_ft": distance_ft},
    ]}), encoding="utf-8")


def _live(monkeypatch, *, connected: bool = True, locations: dict | None = None,
          reason: str | None = None) -> None:
    monkeypatch.setattr(rb, "live_connection_locations", lambda force=False: {
        "connected": connected, "reason": reason,
        "locations": locations if locations is not None else {2897203: (38.05, 32.52)}})


def test_unique_id_decode_fix_regression(tmp_artifacts: Path, monkeypatch) -> None:
    """BUG-05: the endpoint must XOR-decode UniqueIds. The old naive hex-suffix
    decode gives a different (wrong) element for this non-zero-XOR id."""
    _seed(tmp_artifacts)
    _live(monkeypatch, connected=False, reason="off")
    out = revit_router.revit_element_ids("rev_asm_011")
    assert out["export"]["creation_element_ids"] == [2897203]
    assert int(MEMBER_UID.split("-")[-1], 16) != 2897203   # the bug this replaced


def test_highlight_by_assembly_selects_all_hits(tmp_artifacts: Path, monkeypatch) -> None:
    _seed(tmp_artifacts)
    _live(monkeypatch, locations={2897203: (38.05, 32.52), 1131834: (38.05, 33.07),
                                  999999: (90.0, 90.0)})
    _bridge(monkeypatch, _fake_revit())
    out = revit_router.revit_highlight({"assembly_id": "rev_asm_011"}, radius_ft=0.75)
    assert out["ok"] is True
    assert sorted(out["selected_ids"]) == [1131834, 2897203]   # both hits, not just nearest
    assert out["resolved_via"] == "live_coordinate_match"
    assert out["distance_ft"] < 0.01
    assert out["note"] == revit_router.ZOOM_NOTE


def test_highlight_by_element_ids(tmp_artifacts: Path, monkeypatch) -> None:
    _seed(tmp_artifacts)
    _bridge(monkeypatch, _fake_revit())
    out = revit_router.revit_highlight({"element_ids": [1254]})
    assert out["ok"] is True and out["selected_ids"] == [1254]
    assert out["resolved_via"] == "element_ids"


def test_highlight_disconnected_is_honest(tmp_artifacts: Path, monkeypatch) -> None:
    _seed(tmp_artifacts)
    _live(monkeypatch, connected=False, reason="Nonica connector is off", locations={})
    out = revit_router.revit_highlight({"assembly_id": "rev_asm_011"})
    assert out["ok"] is False and out["selected_ids"] == []
    assert "connector is off" in out["reason"]
    assert out["note"] == revit_router.ZOOM_NOTE   # no 500, still tells you what to do


def test_highlight_unknown_assembly(tmp_artifacts: Path) -> None:
    _seed(tmp_artifacts)
    with pytest.raises(HTTPException) as exc:
        revit_router.revit_highlight({"assembly_id": "rev_asm_nope"})
    assert exc.value.status_code == 404


def test_highlight_empty_body(tmp_artifacts: Path) -> None:
    _seed(tmp_artifacts)
    out = revit_router.revit_highlight({})
    assert out["ok"] is False and "assembly_id" in out["reason"]


def test_selection_endpoint(monkeypatch) -> None:
    _bridge(monkeypatch, _fake_revit())
    assert revit_router.revit_selection()["element_ids"] == [1254, 1070039]


def test_lookup_live_match(tmp_artifacts: Path, monkeypatch) -> None:
    _seed(tmp_artifacts)
    _live(monkeypatch)
    out = revit_router.revit_lookup(2897203)
    assert out["found"] is True and out["connected"] is True
    assert out["live_point"] == [38.05, 32.52]
    assert out["assembly"]["id"] == "rev_asm_011"
    assert out["device"]["id"] == "holdown_dev_001"
    assert "rev_asm_011" in out["plain_english"] and "MATCH" in out["plain_english"]
    assert "0.64 ft" in out["plain_english"]


def test_lookup_uses_element_location_when_not_cached(tmp_artifacts, monkeypatch) -> None:
    _seed(tmp_artifacts)
    _live(monkeypatch, locations={})          # connected, but this id isn't a connection
    _bridge(monkeypatch, _fake_revit())       # element_location answers (38.05, 32.52)
    out = revit_router.revit_lookup(1254)
    assert out["found"] is True and out["assembly"]["id"] == "rev_asm_011"


def test_lookup_offline_falls_back_to_member_decode(tmp_artifacts, monkeypatch) -> None:
    _seed(tmp_artifacts)
    _live(monkeypatch, connected=False, reason="connector off", locations={})
    out = revit_router.revit_lookup(2897203)
    assert out["found"] is True and out["connected"] is False
    assert out["live_point"] is None
    assert out["reason"] == "connector off"
    assert "not connected" in out["plain_english"]


def test_lookup_unknown_id(tmp_artifacts: Path, monkeypatch) -> None:
    _seed(tmp_artifacts)
    _live(monkeypatch, locations={555555: (900.0, 900.0)})
    out = revit_router.revit_lookup(555555)
    assert out["found"] is False and out["assembly"] is None
    assert "not a member of any holdown assembly" in out["plain_english"]


def test_lookup_mismatch_explains_direction(tmp_artifacts: Path, monkeypatch) -> None:
    _seed(tmp_artifacts, status="LOCATION_MISMATCH", distance_ft=2.4)
    _live(monkeypatch)
    out = revit_router.revit_lookup(2897203)
    assert out["analysis"]["analysis_available"] is True
    assert out["analysis"]["direction"] == "NE"
    assert out["analysis"]["suggestion"] in out["plain_english"]
    assert "2.40 ft NE" in out["plain_english"]


# ---------------------------------------------------------------------------
# full selected element (open-source revit-mcp primary, Nonica fallback)
# ---------------------------------------------------------------------------
# Real payload shape, captured live 2026-07-27 from the mcp-servers-for-revit
# add-in socket on 127.0.0.1:8080.
RMCP_SELECTION = {"jsonrpc": "2.0", "id": "1", "result": [
    {"Id": 2897203, "UniqueId": "1539e145-a725-4226-9a69-daa468294ac6-00245350",
     "Name": "HDU5-SDS2.5", "Category": "Structural Connections",
     "Properties": {"Mark": "H1", "Level": "Level 1"}},
]}


def _rmcp(monkeypatch, response) -> None:
    """Fake the open-source revit-mcp socket. ``response`` may be an exception
    instance to simulate the add-in's server not being started."""
    def _call(method, params, timeout=10.0):
        if isinstance(response, BaseException):
            raise response
        return response
    monkeypatch.setattr(rb, "_revit_mcp_call", _call)


def test_selected_element_full_via_revit_mcp(monkeypatch) -> None:
    _rmcp(monkeypatch, RMCP_SELECTION)
    out = rb.get_selected_element_full()
    assert out["ok"] is True and out["source"] == "revit_mcp"
    assert out["element_id"] == 2897203 and out["type"] == "HDU5-SDS2.5"
    assert out["category"] == "Structural Connections"
    assert out["mark"] == "H1" and out["level"] == "Level 1"
    assert out["point"] is None          # this tool reports no geometry — don't invent it


def test_selected_element_full_falls_back_to_nonica(monkeypatch) -> None:
    """revit-mcp server not started (nothing listening) -> Nonica still answers
    with an id and a point, honestly labelled."""
    _rmcp(monkeypatch, ConnectionRefusedError("no server on 8080"))
    _bridge(monkeypatch, _fake_revit())
    out = rb.get_selected_element_full()
    assert out["ok"] is True and out["source"] == "nonica"
    assert out["element_id"] == 1254 and out["point"] == [38.05, 32.52]
    assert out["type"] is None and out["family"] is None


def test_selected_element_full_both_bridges_down_is_honest(monkeypatch) -> None:
    _rmcp(monkeypatch, ConnectionRefusedError("no server on 8080"))
    _bridge(monkeypatch, _dead_revit())
    out = rb.get_selected_element_full()
    assert out["ok"] is False and out["element_id"] is None
    assert "Connector" in out["reason"]


def test_selected_element_full_empty_selection_is_not_a_fallback(monkeypatch) -> None:
    """revit-mcp answering with an empty list is an ANSWER (nothing selected),
    so it must not be second-guessed by re-asking Nonica."""
    _rmcp(monkeypatch, {"jsonrpc": "2.0", "id": "1", "result": []})
    monkeypatch.setattr(rb, "_run", lambda fn: pytest.fail("Nonica must not be called"))
    out = rb.get_selected_element_full()
    assert out["ok"] is False and out["source"] == "revit_mcp"
    assert "Nothing selected" in out["reason"]


def test_selected_element_endpoint_joins_the_lookup(tmp_artifacts: Path, monkeypatch) -> None:
    _seed(tmp_artifacts)
    _rmcp(monkeypatch, RMCP_SELECTION)
    _live(monkeypatch)
    out = revit_router.revit_selected_element()
    assert out["ok"] is True and out["source"] == "revit_mcp"
    assert out["type"] == "HDU5-SDS2.5" and out["level"] == "Level 1"
    assert out["found"] is True and out["assembly"]["id"] == "rev_asm_011"
    assert out["device"]["id"] == "holdown_dev_001"
    assert "MATCH" in out["plain_english"]


def test_selected_element_endpoint_nothing_selected(tmp_artifacts: Path, monkeypatch) -> None:
    _rmcp(monkeypatch, {"jsonrpc": "2.0", "id": "1", "result": []})
    out = revit_router.revit_selected_element()
    assert out["ok"] is False and out["found"] is False
    assert out["assembly"] is None and "Nothing selected" in out["reason"]


def test_lookup_without_registry(tmp_artifacts: Path, monkeypatch) -> None:
    """No compare run yet: still identifies the assembly, honestly says there
    is no paired device instead of 409-ing."""
    _seed(tmp_artifacts, with_registry=False)
    _live(monkeypatch)
    out = revit_router.revit_lookup(2897203)
    assert out["found"] is True and out["device"] is None
    assert "No PDF device is paired" in out["plain_english"]
