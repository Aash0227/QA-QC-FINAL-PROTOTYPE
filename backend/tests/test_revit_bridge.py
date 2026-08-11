"""Revit MCP bridge tests (production-plan §2). The live transport needs Revit
open with the Nonica connector; here the placement SEQUENCE logic is exercised
over a fake async ``call`` and the endpoints over a monkeypatched bridge, so
correctness is verified with no subprocess."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from app import benchmark_workflow as bw
from app import config, main, revit_bridge as rb


@pytest.fixture()
def tmp_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path)
    monkeypatch.setattr(config, "EVIDENCE_DIR", tmp_path / "evidence")
    return tmp_path


def _proposal() -> dict:
    return {"benchmarks": [
        {"mark": "BM-1", "revit_point_ft": {"x": 17.30, "y": 62.17}},
        {"mark": "BM-2", "revit_point_ft": {"x": 75.97, "y": 4.72}},
    ]}


def _fake_call(readback_offset: float = 0.0):
    """A fake Revit that copies the template to each requested vector and reads
    the copy back at (template + vector) + an optional error offset."""
    template = (10.0, 20.0, 1.5)
    state = {"next_id": 900001, "loc": {}}

    async def call(name: str, args: dict) -> str:
        if name == "get_active_view_in_revit":
            return "model_title: TEST MODEL"
        if name == "get_all_elements_of_specific_families":
            return "families count 1: 175646 mwfBenchmark"
        if name == "get_location_for_element_ids":
            eid = args["list_elementIds"][0]
            if eid == 175646:
                return f'175646,LocationPoint,"({template[0]:.2f}, {template[1]:.2f}, 1.50)"'
            x, y = state["loc"][eid]
            return f'{eid},LocationPoint,"({x:.4f}, {y:.4f}, 1.50)"'
        if name == "set_copy_elements":
            nid = state["next_id"]; state["next_id"] += 1
            x = template[0] + args["mov_vect_X"][0] + readback_offset
            y = template[1] + args["mov_vect_Y"][0]
            state["loc"][nid] = (x, y)
            return f"Copied. New element ids: {nid}"
        if name == "set_parameter_value_for_elements":
            return "ok"
        return ""
    return call


def test_place_sequence_success() -> None:
    out = asyncio.run(rb.place_sequence(_fake_call(), _proposal()))
    assert out["ok"] is True
    assert set(out["element_ids"]) == {"BM-1", "BM-2"}
    assert out["element_ids"]["BM-1"] != out["element_ids"]["BM-2"]
    assert all(c["delta_ft"] < 0.01 for c in out["checks"])


def test_place_sequence_off_tolerance_fails() -> None:
    out = asyncio.run(rb.place_sequence(_fake_call(readback_offset=0.5), _proposal()))
    assert out["ok"] is False
    assert all(c["ok"] is False for c in out["checks"])  # every mark 0.5ft off


def test_place_sequence_missing_family() -> None:
    """A recognisable-but-empty family listing = the family really is absent."""
    async def call(name, args):
        if name == "get_all_elements_of_specific_families":
            return "type: ContextUpdate\nfamilies count 0:"
        return "type: ContextUpdate"
    with pytest.raises(rb.BridgeError, match="mwfBenchmark"):
        asyncio.run(rb.place_sequence(call, _proposal()))


def test_parsing_helpers() -> None:
    assert rb._first_xyz('x,LocationPoint,"(17.30, 62.17, 1.50)"') == (17.30, 62.17, 1.50)
    assert rb._element_ids("New ids: 900001 and 3951193") == [900001, 3951193]
    assert rb._looks_disconnected("The request timeout ... AI Connector ... not be enabled")
    assert not rb._looks_disconnected("model_title: Madera")


def test_element_ids_ignores_model_title() -> None:
    """Live-found bug: '10510 Madera Dr…' model title leaked a false id (10510)
    ahead of the real element id."""
    resp = ('model_title: 10510 Madera Dr_LGS model_08052026\n'
            'timestamp: "2026-07-20T11:48:29Z"\n'
            '  mwfBenchmark[1]: 1756546')
    assert rb._element_ids(resp) == [1756546]


def test_place_sequence_pinned_template() -> None:
    """Live-found: a pinned template copies nothing (InvalidCopy) — the bridge
    must say so clearly, not 'no new id'."""
    async def call(name, args):
        if name == "get_all_elements_of_specific_families":
            return "  mwfBenchmark[1]: 1756546"
        if name == "get_location_for_element_ids":
            return '1756546,LocationPoint,"(10.00, 20.00, 1.50)"'
        if name == "set_copy_elements":
            return ('context: CopyToBeConfirmed IdsCopied[0]: InvalidCopy[1]: '
                    '"1756546": Element is Pinned.')
        return ""
    with pytest.raises(rb.BridgeError, match="pinned"):
        asyncio.run(rb.place_sequence(call, _proposal()))


def test_place_markers_endpoint_requires_state(tmp_artifacts: Path) -> None:
    bw.save(bw.default_state())  # idle
    with pytest.raises(HTTPException) as exc:
        main.benchmark_workflow_place_markers({})
    assert exc.value.status_code == 409


def test_place_markers_endpoint_verified_advance(tmp_artifacts, monkeypatch) -> None:
    wf = bw.default_state()
    for s in ("proposing", "awaiting_pdf_approval", "stamping", "awaiting_revit",
              "placing_markers"):
        bw.transition(wf, s, "agent")
    wf["proposal"] = _proposal()
    bw.save(wf)
    monkeypatch.setattr(rb, "place_benchmarks", lambda proposal, family=rb.DEFAULT_BENCHMARK_FAMILY: {
        "ok": True, "element_ids": {"BM-1": 900001, "BM-2": 900002},
        "readback": {"BM-1": {"x": 17.30, "y": 62.17}, "BM-2": {"x": 75.97, "y": 4.72}},
        "checks": [{"mark": "BM-1", "ok": True, "delta_ft": 0.001}],
    })
    resp = main.benchmark_workflow_place_markers({})
    body = __import__("json").loads(resp.body)
    assert body["state"] == "awaiting_revit_approval"
    last = body["history"][-1]["payload"]
    assert last["verified"] is True and last["element_ids"]["BM-1"] == 900001


def test_place_markers_endpoint_bridge_error(tmp_artifacts, monkeypatch) -> None:
    wf = bw.default_state()
    for s in ("proposing", "awaiting_pdf_approval", "stamping", "awaiting_revit",
              "placing_markers"):
        bw.transition(wf, s, "agent")
    wf["proposal"] = _proposal()
    bw.save(wf)

    def _boom(proposal, family=rb.DEFAULT_BENCHMARK_FAMILY):
        raise rb.BridgeError("Revit AI Connector is off")
    monkeypatch.setattr(rb, "place_benchmarks", _boom)
    with pytest.raises(HTTPException) as exc:
        main.benchmark_workflow_place_markers({})
    assert exc.value.status_code == 409
    assert bw.load()["state"] == "placing_markers"  # unchanged


# ---------------------------------------------------------------------------
# Live element-id lookup (QA manual verify feature)
# ---------------------------------------------------------------------------
def test_parse_id_locations_skips_metadata() -> None:
    text = (
        "model_title: 10510 Madera Dr_LGS model_08052026\n"
        "timestamp: 2026-07-21\n"
        '2897203,LocationPoint,"(38.05, 32.52, 1.50)"\n'
        '1131834,LocationPoint,"(38.05, 33.07, 1.50)"\n'
    )
    locs = rb._parse_id_locations(text)
    assert locs == {2897203: (38.05, 32.52), 1131834: (38.05, 33.07)}


def test_connection_locations_sequence_subset() -> None:
    async def call(name: str, args: dict) -> str:
        if name == "get_elements_by_category":
            return "ElementIdsOfCategory[2]{SubsetId,IdsCount,Sample}:\n-9000001,2,1070039"
        assert args["list_elementIds"] == [-9000001]
        return '2897203,LocationPoint,"(38.05, 32.52, 1.50)"'
    locs = asyncio.run(rb.connection_locations_sequence(call))
    assert locs == {2897203: (38.05, 32.52)}


def _seed_ai_revit(tmp: Path) -> None:
    import json
    (tmp / "AIConvert_revit.json").write_text(json.dumps({
        "canonical_holdown_assemblies": [{
            "id": "rev_asm_064", "pdf_mark_candidate": "H4",
            "family_type_summary": {"SHD15B-WITH BOLT": 1},
            "member_element_ids": ["f0d3f875-3934-4876-a9a0-b489e36b08eb-002c1eae"],
            "center_point": {"x": 38.049, "y": 32.524, "z": 1.5},
        }]
    }), encoding="utf-8")


def test_element_ids_endpoint_live_match(tmp_artifacts: Path, monkeypatch) -> None:
    from app.routers import revit as revit_router
    _seed_ai_revit(tmp_artifacts)
    monkeypatch.setattr(rb, "live_connection_locations", lambda force=False: {
        "connected": True, "locations": {2897203: (38.05, 32.52), 999999: (90.0, 90.0)}})
    out = revit_router.revit_element_ids("rev_asm_064")
    assert out["live"]["connected"] is True
    assert out["live"]["element_ids"] == [2897203]
    assert out["live"]["distance_ft"] < 0.01
    # XOR decode (revit_ids), not the naive hex suffix 0x2C1EAE — see BUG-05.
    assert out["export"]["creation_element_ids"] == [0x2C1EAE ^ 0xE36B08EB]
    assert "Select by ID" in out["live"]["note"]


def test_element_ids_endpoint_connector_off(tmp_artifacts: Path, monkeypatch) -> None:
    from app.routers import revit as revit_router
    _seed_ai_revit(tmp_artifacts)
    monkeypatch.setattr(rb, "live_connection_locations", lambda force=False: {
        "connected": False, "reason": "off", "locations": {}})
    out = revit_router.revit_element_ids("rev_asm_064")
    assert out["live"]["connected"] is False
    assert out["live"]["element_ids"] == []
    assert out["export"]["creation_element_ids"] == [0x2C1EAE ^ 0xE36B08EB]


def test_element_ids_endpoint_unknown_assembly(tmp_artifacts: Path) -> None:
    from app.routers import revit as revit_router
    _seed_ai_revit(tmp_artifacts)
    with pytest.raises(HTTPException) as exc:
        revit_router.revit_element_ids("rev_asm_nope")
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Audit blocker #1: the benchmark family must be overridable
# ---------------------------------------------------------------------------
def test_benchmark_family_resolution_order(monkeypatch) -> None:
    monkeypatch.delenv(rb.BENCHMARK_FAMILY_ENV, raising=False)
    assert rb.benchmark_family() == rb.DEFAULT_BENCHMARK_FAMILY
    assert rb.benchmark_family("  ") == rb.DEFAULT_BENCHMARK_FAMILY   # blank ignored
    monkeypatch.setenv(rb.BENCHMARK_FAMILY_ENV, "Acme_Benchmark")
    assert rb.benchmark_family() == "Acme_Benchmark"                  # env beats default
    assert rb.benchmark_family("Payload_BM") == "Payload_BM"          # payload beats env


def test_place_sequence_honours_env_family(monkeypatch) -> None:
    monkeypatch.setenv(rb.BENCHMARK_FAMILY_ENV, "Acme_Benchmark")
    asked: list = []

    async def call(name, args):
        if name == "get_all_elements_of_specific_families":
            asked.append(args["familyNames"])
            return "type: ContextUpdate\nfamilies count 0:"
        return "type: ContextUpdate"
    with pytest.raises(rb.BridgeError, match="Acme_Benchmark"):
        asyncio.run(rb.place_sequence(call, _proposal()))
    assert asked == [["Acme_Benchmark"]]


def test_missing_family_error_says_how_to_override() -> None:
    async def call(name, args):
        if name == "get_all_elements_of_specific_families":
            return "type: ContextUpdate\nfamilies count 0:"
        return "type: ContextUpdate"
    with pytest.raises(rb.BridgeError) as exc:
        asyncio.run(rb.place_sequence(call, _proposal(), family="Acme_BM"))
    msg = str(exc.value)
    assert "Acme_BM" in msg                       # names what it looked for
    assert rb.BENCHMARK_FAMILY_ENV in msg         # and how to change it
    assert "'family'" in msg


def test_missing_family_error_suggests_discovered_families() -> None:
    """Honest guidance, not a silent auto-pick: name what the model DOES have."""
    async def call(name, args):
        if name == "get_all_elements_of_specific_families":
            return "type: ContextUpdate\nfamilies count 0:"
        if name == "get_all_families_in_model":
            return ('type: ContextUpdate\nFamilies[3]:\n  Generic_Wall\n'
                    '  mwfBenchmark\n  Site Benchmark Marker\n')
        return "type: ContextUpdate"
    with pytest.raises(rb.BridgeError) as exc:
        asyncio.run(rb.place_sequence(call, _proposal(), family="Acme_BM"))
    msg = str(exc.value)
    assert "mwfBenchmark" in msg and "Site Benchmark Marker" in msg
    assert "Generic_Wall" not in msg              # only benchmark-ish candidates


def test_place_markers_endpoint_threads_payload_family(tmp_artifacts, monkeypatch) -> None:
    wf = bw.default_state()
    for s in ("proposing", "awaiting_pdf_approval", "stamping", "awaiting_revit",
              "placing_markers"):
        bw.transition(wf, s, "agent")
    wf["proposal"] = _proposal()
    bw.save(wf)
    seen: dict = {}

    def _place(proposal, family=None):
        seen["family"] = family
        return {"ok": True, "element_ids": {"BM-1": 1}, "readback": {}, "checks": []}
    monkeypatch.setattr(rb, "place_benchmarks", _place)
    main.benchmark_workflow_place_markers({"family": "Acme_BM"})
    assert seen["family"] == "Acme_BM"
    assert bw.load()["history"][-1]["payload"]["family"] == "Acme_BM"   # audit trail


# ---------------------------------------------------------------------------
# R-30: an unparseable reply is a transport failure, not a fact about the model
# ---------------------------------------------------------------------------
def test_looks_connected_payload() -> None:
    assert rb._looks_connected_payload("type: ContextUpdate\nsource: Revit")
    assert rb._looks_connected_payload("model_title: 10510 Madera Dr")
    assert not rb._looks_connected_payload("")
    assert not rb._looks_connected_payload("�� binary garbage �")


def test_connection_locations_unrecognized_reply_is_transport_failure() -> None:
    async def call(name, args):
        return "�� garbage �"
    with pytest.raises(rb.BridgeError, match="Unrecognized connector response"):
        asyncio.run(rb.connection_locations_sequence(call))


def test_connection_locations_recognized_but_empty_still_reports_no_connections() -> None:
    """The old message is still correct when the reply IS a reply."""
    async def call(name, args):
        return "type: ContextUpdate\nsource: Revit\nElementIdsOfCategory[0]:"
    with pytest.raises(rb.BridgeError, match="No Structural Connections"):
        asyncio.run(rb.connection_locations_sequence(call))


def test_connection_locations_unreadable_locations_is_transport_failure() -> None:
    async def call(name, args):
        if name == "get_elements_by_category":
            return "ElementIdsOfCategory[1]{SubsetId,IdsCount,Sample}:\n-9000001,1,1070039"
        return "� nonsense �"
    with pytest.raises(rb.BridgeError, match="Unrecognized connector response"):
        asyncio.run(rb.connection_locations_sequence(call))


# ---------------------------------------------------------------------------
# R-15: a cached bridge answer must say it is cached
# ---------------------------------------------------------------------------
def test_live_connection_locations_reports_cache_and_age(monkeypatch) -> None:
    monkeypatch.setattr(rb, "_CONN_CACHE", {"ts": 0.0, "locations": {}})
    monkeypatch.setattr(rb, "_run", lambda fn: {2897203: (38.05, 32.52)})
    fresh = rb.live_connection_locations()
    assert fresh["cached"] is False and fresh["age_s"] == 0.0
    cached = rb.live_connection_locations()
    assert cached["cached"] is True and cached["age_s"] >= 0.0


def test_live_connection_locations_offline_still_carries_cache_keys(monkeypatch) -> None:
    monkeypatch.setattr(rb, "_CONN_CACHE", {"ts": 0.0, "locations": {}})

    def _boom(fn):
        raise rb.BridgeError("connector off")
    monkeypatch.setattr(rb, "_run", _boom)
    out = rb.live_connection_locations()
    assert out["connected"] is False and out["cached"] is False and out["age_s"] is None


def test_element_ids_endpoint_passes_cache_flags(tmp_artifacts: Path, monkeypatch) -> None:
    from app.routers import revit as revit_router
    _seed_ai_revit(tmp_artifacts)
    monkeypatch.setattr(rb, "live_connection_locations", lambda force=False: {
        "connected": True, "cached": True, "age_s": 42.0,
        "locations": {2897203: (38.05, 32.52)}})
    live = revit_router.revit_element_ids("rev_asm_064")["live"]
    assert live["cached"] is True and live["age_s"] == 42.0


def test_highlight_endpoint_carries_live_cache(tmp_artifacts: Path, monkeypatch) -> None:
    from app.routers import revit as revit_router
    _seed_ai_revit(tmp_artifacts)
    monkeypatch.setattr(rb, "live_connection_locations", lambda force=False: {
        "connected": True, "cached": True, "age_s": 7.5,
        "locations": {2897203: (38.05, 32.52)}})
    monkeypatch.setattr(rb, "select_elements", lambda ids: {
        "ok": True, "selected_ids": ids, "invalid_ids": [], "reason": None})
    out = revit_router.revit_highlight({"assembly_id": "rev_asm_064"})
    assert out["live"] == {"connected": True, "cached": True, "age_s": 7.5}
    assert revit_router.revit_highlight({"element_ids": [5]})["live"] is None
