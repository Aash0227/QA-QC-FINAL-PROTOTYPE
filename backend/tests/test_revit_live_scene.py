"""Hybrid live-Revit 3D viewer: the live box-massing read and its endpoints.

Same fake-MCP discipline as test_revit_live.py — ``_run`` is monkeypatched so
nothing spawns RevitMCPConnection.exe. The fake responses are copies of the
real 2026-07-28 shapes captured from the open LGS model (subset-compressed
category lists, inline id lists, quoted bbox rows).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app import config, revit_bridge as rb
from app.routers import revit as revit_router

TIMEOUT_TEXT = ("The request timeout. The AI Connector for Revit by Nonica "
                "must be kept open and was not enabled.")

VIEW = """type: ContextUpdate
source: RevitModel
timestamp: "2026-07-28T06:41:56.26Z"
model_title: TEST TOWER LGS MODEL V01
is_linked_doc: false
context[6]:
  current_view_id: 8485796
  units: Coord. in ft.
"""

# Walls/framing/connections compress to subsets; columns are small enough to
# come back inline (exactly how OST_Levels answered live).
CATEGORIES = """type: ContextUpdate
source: RevitModel
model_title: TEST TOWER LGS MODEL V01
context[1]:
  ids_per_category[4]:
    - Category: OST_Walls
    ElementIdsOfCategory[2]{SubsetId,IdsCount,SampleElementId}:
      -9000001,2,500001
    - Category: OST_StructuralFraming
    ElementIdsOfCategory[5]{SubsetId,IdsCount,SampleElementId}:
      -9000002,5,600001
    - Category: OST_StructuralColumns
    ElementIdsOfCategory[2]: 700001,700002
    - Category: OST_StructConnections
    ElementIdsOfCategory[2]{SubsetId,IdsCount,SampleElementId}:
      -9000004,2,800001
"""

SUBSETS = {
    -9000001: [500001, 500002],
    -9000002: [600001, 600002, 600003, 600004, 600005],
    -9000004: [800001, 800002],
}
BOXES = {
    500001: (0.0, 0.0, 0.0, 20.0, 0.5, 9.0),
    500002: (0.0, 0.0, 0.0, 0.5, 30.0, 9.0),
    600001: (1.0, 1.0, 8.0, 9.0, 1.4, 8.5),
    600002: (1.0, 2.0, 8.0, 9.0, 2.4, 8.5),
    600003: (1.0, 3.0, 8.0, 9.0, 3.4, 8.5),
    600004: (1.0, 4.0, 8.0, 9.0, 4.4, 8.5),
    600005: (1.0, 5.0, 8.0, 9.0, 5.4, 8.5),
    700001: (5.0, 5.0, -0.5, 5.5, 5.5, 9.0),
    700002: (15.0, 5.0, -0.5, 15.5, 5.5, 9.0),
    800001: (37.80, 32.30, 1.20, 38.30, 32.80, 1.80),   # ~ the seeded assembly
    800002: (90.00, 90.00, 1.00, 90.50, 90.50, 1.60),   # nowhere near it
}


def _bbox_rows(ids: list[int]) -> str:
    rows = "\n".join(
        f'    {i},"[({BOXES[i][0]:.2f}, {BOXES[i][1]:.2f}, {BOXES[i][2]:.2f}), '
        f'({BOXES[i][3]:.2f}, {BOXES[i][4]:.2f}, {BOXES[i][5]:.2f})]"'
        for i in ids if i in BOXES)
    return ("type: ContextUpdate\nsource: RevitModel\n"
            "model_title: TEST TOWER LGS MODEL V01\n"
            f"context[3]:\n  bounding_boxes[{len(ids)}]{{elementId,bBoxFrame}}:\n"
            f"{rows}\n  invalid_ids_or_subsets[0]:\n  units: Coord. in feet")


def _fake_model(log: list | None = None):
    """A live Revit that answers the four scene tools. Records every call so the
    chunking/caching behaviour can be asserted."""
    async def call(name: str, args: dict) -> str:
        if log is not None:
            log.append((name, args))
        if name == "get_active_view_in_revit":
            return VIEW
        if name == "get_elements_by_category":
            return CATEGORIES
        if name == "get_element_ids_from_subsets":
            sid = args["list_subsetIds"][0]
            ids = SUBSETS[sid]
            return ("context[1]:\n  subsets[1]:\n"
                    f"    - SubsetId: {sid}\n"
                    f"    ElementIds[{len(ids)}]: {','.join(str(i) for i in ids)}")
        if name == "get_boundingboxes_for_element_ids":
            wanted: list[int] = []
            for i in args["list_elementIds"]:
                wanted.extend(SUBSETS[i] if i in SUBSETS else [i])
            return _bbox_rows(wanted)
        return ""
    return call


def _bridge(monkeypatch: pytest.MonkeyPatch, call) -> None:
    monkeypatch.setattr(rb, "_run", lambda fn: asyncio.run(fn(call)))


@pytest.fixture(autouse=True)
def _clear_scene_cache():
    rb._SCENE_CACHE.update(ts=0.0, scene=None)
    yield
    rb._SCENE_CACHE.update(ts=0.0, scene=None)


@pytest.fixture()
def tmp_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path)
    monkeypatch.setattr(config, "EVIDENCE_DIR", tmp_path / "evidence")
    return tmp_path


# ---------------------------------------------------------------------------
# parsers
# ---------------------------------------------------------------------------
def test_parse_category_blocks_handles_subset_and_inline() -> None:
    blocks = rb._parse_category_blocks(CATEGORIES)
    assert blocks["OST_Walls"] == {"count": 2, "ids": [], "subset_id": -9000001}
    assert blocks["OST_StructuralFraming"]["count"] == 5
    assert blocks["OST_StructuralColumns"] == {"count": 2, "ids": [700001, 700002],
                                               "subset_id": None}


def test_parse_bboxes_reads_quoted_rows() -> None:
    got = rb._parse_bboxes(_bbox_rows([800001]))
    assert got == {800001: [37.8, 32.3, 1.2, 38.3, 32.8, 1.8]}
    assert rb._parse_bboxes("model_title: 10510 Madera Dr\nno boxes here") == {}


# ---------------------------------------------------------------------------
# live_scene_geometry
# ---------------------------------------------------------------------------
def test_scene_geometry_parses_every_category(monkeypatch) -> None:
    _bridge(monkeypatch, _fake_model())
    out = rb.live_scene_geometry()
    assert out["ok"] is True
    assert out["model_title"] == "TEST TOWER LGS MODEL V01"
    assert out["counts"] == {"walls": 2, "framing": 5, "columns": 2, "connections": 2}
    assert out["truncated"] == {}
    assert out["bounds"] == {"min_x": 0.0, "min_y": 0.0, "min_z": -0.5,
                             "max_x": 90.5, "max_y": 90.5, "max_z": 9.0}
    assert out["categories"]["connections"][0] == {
        "id": 800001, "bbox_ft": [37.8, 32.3, 1.2, 38.3, 32.8, 1.8]}


def test_scene_geometry_uses_subset_ids_without_expanding(monkeypatch) -> None:
    """A subset id is itself a valid element id for the bbox tool — small
    categories must cost ONE call, not an expansion plus chunks."""
    log: list = []
    _bridge(monkeypatch, _fake_model(log))
    rb.live_scene_geometry()
    assert not [c for c in log if c[0] == "get_element_ids_from_subsets"]
    bbox_calls = [c for c in log if c[0] == "get_boundingboxes_for_element_ids"]
    assert len(bbox_calls) == 4                      # one per category
    assert bbox_calls[0][1]["list_elementIds"] == [-9000001]


def test_scene_geometry_caps_and_chunks_oversized_categories(monkeypatch) -> None:
    """Over the cap: expand the subset, keep the first N, and fetch boxes in
    chunks. The drop is REPORTED, never silent."""
    log: list = []
    call = _fake_model(log)
    out = asyncio.run(rb.scene_geometry_sequence(call, max_per_category=3, chunk=2))
    assert out["counts"]["framing"] == 3
    assert out["truncated"]["framing"] == {"total": 5, "kept": 3}
    assert out["counts"]["walls"] == 2 and "walls" not in out["truncated"]
    expanded = [c for c in log if c[0] == "get_element_ids_from_subsets"]
    assert [c[1]["list_subsetIds"] for c in expanded] == [[-9000002]]
    chunks = [c[1]["list_elementIds"] for c in log
              if c[0] == "get_boundingboxes_for_element_ids"]
    assert [600001, 600002] in chunks and [600003] in chunks


def test_scene_geometry_offline_is_honest(monkeypatch) -> None:
    async def dead(name, args):
        return TIMEOUT_TEXT
    _bridge(monkeypatch, dead)
    out = rb.live_scene_geometry()
    assert out["ok"] is False and out["categories"] == {} and out["bounds"] is None
    assert "AI Connector" in out["reason"]


def test_scene_geometry_bridge_unavailable(monkeypatch) -> None:
    def _boom(fn):
        raise FileNotFoundError("RevitMCPConnection.exe")
    monkeypatch.setattr(rb, "_run", _boom)
    out = rb.live_scene_geometry()
    assert out["ok"] is False and "bridge unavailable" in out["reason"]


def test_scene_geometry_caches_for_60s(monkeypatch) -> None:
    log: list = []
    _bridge(monkeypatch, _fake_model(log))
    rb.live_scene_geometry()
    n = len(log)
    assert rb.live_scene_geometry()["cached"] is True
    assert len(log) == n                      # served from cache, no round trip
    assert rb.live_scene_geometry(force=True)["cached"] is False
    assert len(log) > n


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------
def _seed(tmp: Path, status: str = "LOCATION_MISMATCH") -> None:
    (tmp / "AIConvert_revit.json").write_text(json.dumps({
        "canonical_holdown_assemblies": [{
            "id": "rev_asm_011", "pdf_mark_candidate": "H1",
            "center_point": {"x": 38.05, "y": 32.55, "z": 1.5},
        }]}), encoding="utf-8")
    (tmp / "device_registry.json").write_text(json.dumps({"categories": {"holdown": {
        "devices": [{"id": "holdown_dev_001", "mark": "H1", "status": status,
                     "target_id": "rev_asm_011"}]}}}), encoding="utf-8")


def test_live_scene_endpoint_joins_device_status(tmp_artifacts: Path, monkeypatch) -> None:
    _seed(tmp_artifacts)
    _bridge(monkeypatch, _fake_model())
    out = revit_router.revit_live_scene()
    conns = out["categories"]["connections"]
    near, far = conns[0], conns[1]
    assert near["status"] == "LOCATION_MISMATCH" and near["assembly_id"] == "rev_asm_011"
    assert "status" not in far          # 50 ft away — no status invented for it
    assert out["status_joined"] == 1


def test_live_scene_status_never_leaks_into_the_bridge_cache(tmp_artifacts, monkeypatch) -> None:
    """The joined status is project state; the module-level bridge cache must
    stay clean so the next project doesn't inherit it."""
    _seed(tmp_artifacts)
    _bridge(monkeypatch, _fake_model())
    revit_router.revit_live_scene()
    cached = rb._SCENE_CACHE["scene"]["categories"]["connections"]
    assert all("status" not in e for e in cached)


def test_live_scene_endpoint_without_registry(tmp_artifacts: Path, monkeypatch) -> None:
    """No compare run yet: geometry still renders, just with no statuses."""
    _bridge(monkeypatch, _fake_model())
    out = revit_router.revit_live_scene()
    assert out["ok"] is True and out["counts"]["connections"] == 2
    assert all("status" not in e for e in out["categories"]["connections"])


def test_live_scene_endpoint_offline_is_honest(tmp_artifacts: Path, monkeypatch) -> None:
    async def dead(name, args):
        return TIMEOUT_TEXT
    _bridge(monkeypatch, dead)
    out = revit_router.revit_live_scene()
    assert out["ok"] is False and out["bounds"] is None
    assert "AI Connector" in out["reason"]


def test_refresh_3d_busts_the_cache(tmp_artifacts: Path, monkeypatch) -> None:
    log: list = []
    _bridge(monkeypatch, _fake_model(log))
    revit_router.revit_live_scene()
    n = len(log)
    revit_router.revit_live_scene()
    assert len(log) == n
    out = revit_router.revit_live_refresh_3d()
    assert out["ok"] is True and out["cached"] is False
    assert len(log) > n
