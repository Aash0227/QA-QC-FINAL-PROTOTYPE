"""Design A2 — zero-upload auto-ingest: the watcher, the shared ingest path,
and the polled /api/revit/export-status contract.

Same discipline as test_revit_live.py: the Nonica bridge is monkeypatched at
``revit_bridge.status`` so nothing spawns RevitMCPConnection.exe, and the heavy
v3 adapter is monkeypatched the way the upload path's consumers are — the point
under test is the plumbing, not adapt_raw.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app import config, export_watch, revit_bridge as rb, revit_v3_adapter
from app.routers import projects
from app.routers import revit as revit_router

V3_EXPORT = {"schema_version": "3.1", "source_file": "10510 Madera Dr_LGS model.rvt",
             "walls": [], "grids": [], "holdowns": [], "v3_elements": []}


@pytest.fixture()
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An isolated project workspace whose uploads/ dir is the watch dir."""
    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path)
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(config, "EXPORT_INBOX_DIR", tmp_path / "incoming")
    monkeypatch.delenv(config.EXPORT_WATCH_DIR_ENV, raising=False)
    (tmp_path / "uploads").mkdir()
    # No live Revit in unit tests: the bridge answers "off" without spawning.
    monkeypatch.setattr(rb, "status", lambda: {
        "connected": False, "reason": "connector off", "model_title": None})
    rb._STATUS_CACHE.update(ts=0.0, status=None)
    # The verdict math is not under test here; adapt_raw is exercised by its own
    # suite and by the Madera baseline.
    monkeypatch.setattr(revit_v3_adapter, "adapt_raw", lambda raw: {**raw, "adapted": True})
    monkeypatch.setattr(projects, "_maybe_auto_advance_export", lambda raw: None)
    return tmp_path


def _drop(project: Path, name: str = "revit_export.json",
          payload: dict | None = None) -> Path:
    p = project / "uploads" / name
    p.write_text(json.dumps(payload if payload is not None else V3_EXPORT), encoding="utf-8")
    return p


def _manifest(project: Path) -> dict:
    return json.loads((project / "project_manifest.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# scan()
# ---------------------------------------------------------------------------
def test_scan_no_export_is_a_normal_state(project: Path) -> None:
    out = export_watch.scan({})
    assert out == {"pending": False, "path": None, "mtime": None, "sha": None,
                   "reason": "no new export found"}


def test_scan_detects_a_new_export(project: Path) -> None:
    path = _drop(project)
    out = export_watch.scan({})
    assert out["pending"] is True
    assert Path(out["path"]) == path.resolve()
    assert out["sha"] == export_watch.file_sha(path)


def test_scan_unchanged_export_is_not_pending(project: Path) -> None:
    path = _drop(project)
    sha = export_watch.file_sha(path)
    assert export_watch.scan({"last_ingested_export": {"sha": sha}})["pending"] is False


def test_scan_changed_content_is_pending_again(project: Path) -> None:
    """A re-export with the SAME filename must re-trigger — sha, not name."""
    old_sha = export_watch.file_sha(_drop(project))
    _drop(project, payload={**V3_EXPORT, "v3_elements": [{"id": "x"}]})
    assert export_watch.scan({"last_ingested_export": {"sha": old_sha}})["pending"] is True


def test_scan_picks_the_newest_of_several(project: Path) -> None:
    old = _drop(project, "revit_export_old.json")
    os.utime(old, (1_700_000_000, 1_700_000_000))
    new = _drop(project, "raw_revit_export.json",
                payload={**V3_EXPORT, "v3_elements": [{"id": "n"}]})
    assert Path(export_watch.scan({})["path"]) == new.resolve()


def test_watch_dirs_honors_the_env_override(project: Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(config.EXPORT_WATCH_DIR_ENV,
                       os.pathsep.join(["C:/a", "C:/b"]))
    assert export_watch.watch_dirs() == [Path("C:/a"), Path("C:/b")]


def test_titles_match_is_substring_and_honest_about_unknown() -> None:
    assert export_watch.titles_match("10510 Madera Dr_LGS", "madera dr") is True
    assert export_watch.titles_match("Madera", "Dogwood Lane") is False
    assert export_watch.titles_match(None, "Madera") is None      # §5.2 unknown


# ---------------------------------------------------------------------------
# POST /api/revit/ingest — through the SHARED helper, not a fork
# ---------------------------------------------------------------------------
def test_ingest_nothing_pending(project: Path) -> None:
    body = json.loads(revit_router.revit_ingest(None).body)
    assert body == {"ok": True, "ingested": False, "path": None,
                    "reason": "no new export found"}


def test_ingest_runs_the_same_code_path_as_upload(project: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """Design A2's whole safety claim: auto-ingest calls the very function the
    upload form's revit_json branch calls."""
    seen: list[tuple] = []
    real = projects.ingest_revit_export
    monkeypatch.setattr(projects, "ingest_revit_export",
                        lambda m, raw, name: (seen.append((raw, name)), real(m, raw, name))[1])
    path = _drop(project)
    body = json.loads(revit_router.revit_ingest(None).body)

    assert body["ingested"] is True and body["reason"] is None
    assert seen == [(V3_EXPORT, path.name)]
    # ...and it produced exactly what /api/upload produces.
    saved = json.loads((project / "raw_revit_export.json").read_text(encoding="utf-8"))
    assert saved == {**V3_EXPORT, "adapted": True}
    assert json.loads((project / "uploads" / "input_revit.json").read_text(
        encoding="utf-8")) == V3_EXPORT


def test_ingest_stamps_the_manifest(project: Path) -> None:
    path = _drop(project)
    revit_router.revit_ingest(None)
    m = _manifest(project)
    assert m["revit_model_title"] == "10510 Madera Dr_LGS model"
    assert m["revit_schema"] == "v3"
    assert m["last_ingested_export"]["sha"] == export_watch.file_sha(path)
    assert m["last_ingested_export"]["model_title"] == "10510 Madera Dr_LGS model"
    assert m["last_ingested_export"]["ingested_at"]


def test_ingest_is_idempotent(project: Path) -> None:
    _drop(project)
    revit_router.revit_ingest(None)
    second = json.loads(revit_router.revit_ingest(None).body)
    assert second["ingested"] is False and second["reason"] == "already ingested"


def test_ingest_refuses_a_different_model_then_accepts_force(project: Path) -> None:
    """§5.2: a wrong-model ingest is the most expensive silent failure — 409."""
    _drop(project)
    revit_router.revit_ingest(None)
    _drop(project, "revit_export_other.json",
          payload={**V3_EXPORT, "source_file": "Dogwood Lane_LGS.rvt"})

    blocked = revit_router.revit_ingest(None)
    assert blocked.status_code == 409
    assert json.loads(blocked.body)["ingested"] is False
    assert _manifest(project)["revit_model_title"] == "10510 Madera Dr_LGS model"

    forced = revit_router.revit_ingest({"force": True})
    assert json.loads(forced.body)["ingested"] is True
    assert _manifest(project)["revit_model_title"] == "Dogwood Lane_LGS"


def test_ingest_rejects_invalid_json(project: Path) -> None:
    (project / "uploads" / "revit_export.json").write_text("{not json", encoding="utf-8")
    res = revit_router.revit_ingest(None)
    assert res.status_code == 400
    assert json.loads(res.body)["ok"] is False


# ---------------------------------------------------------------------------
# GET /api/revit/export-status — the contract the frontend polls
# ---------------------------------------------------------------------------
CONTRACT = {"synced", "model_title", "exported_at", "age_s", "matches_project", "reason"}


def test_export_status_never_ingested(project: Path) -> None:
    out = revit_router.revit_export_status()
    assert CONTRACT <= set(out)
    assert out["synced"] is False
    assert out["model_title"] is None and out["exported_at"] is None
    assert out["age_s"] is None
    assert out["matches_project"] is None          # Revit offline
    assert out["reason"] == "no export ingested yet"


def test_export_status_synced_after_ingest(project: Path) -> None:
    _drop(project)
    revit_router.revit_ingest(None)
    out = revit_router.revit_export_status()
    assert out["synced"] is True and out["reason"] is None
    assert out["model_title"] == "10510 Madera Dr_LGS model"
    assert out["exported_at"] and out["age_s"] >= 0     # R-14: mtime fallback
    assert out["matches_project"] is None


def test_export_status_prefers_the_payload_exported_at(project: Path) -> None:
    """R-14: the export's own stamp wins over the file mtime."""
    _drop(project, payload={**V3_EXPORT, "exported_at": "2026-07-31T09:12:44+00:00"})
    revit_router.revit_ingest(None)
    out = revit_router.revit_export_status()
    assert out["exported_at"] == "2026-07-31T09:12:44+00:00"
    assert isinstance(out["age_s"], float)   # derived from the stamp, not the mtime


def test_export_status_pending_newer_export(project: Path) -> None:
    _drop(project)
    revit_router.revit_ingest(None)
    _drop(project, payload={**V3_EXPORT, "v3_elements": [{"id": "new"}]})
    out = revit_router.revit_export_status()
    assert out["synced"] is False and out["pending"] is True
    assert out["reason"] == "newer export pending"


def test_export_status_matches_project_when_revit_is_open(
        project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _drop(project)
    revit_router.revit_ingest(None)
    monkeypatch.setattr(rb, "status", lambda: {
        "connected": True, "reason": None, "model_title": "10510 Madera Dr_LGS model_08052026"})
    rb._STATUS_CACHE.update(ts=0.0, status=None)
    assert revit_router.revit_export_status()["matches_project"] is True

    monkeypatch.setattr(rb, "status", lambda: {
        "connected": True, "reason": None, "model_title": "Dogwood Lane_LGS"})
    rb._STATUS_CACHE.update(ts=0.0, status=None)
    out = revit_router.revit_export_status()
    assert out["matches_project"] is False and out["connected"] is True


def test_export_status_survives_a_corrupt_export_file(project: Path) -> None:
    """Polled endpoint: a half-written export must degrade, never 500."""
    _drop(project)
    revit_router.revit_ingest(None)
    (project / "uploads" / "revit_export.json").write_text("{torn", encoding="utf-8")
    out = revit_router.revit_export_status()
    assert CONTRACT <= set(out)
    assert out["synced"] is False and out["exported_at"] is not None


# ---------------------------------------------------------------------------
# spawn hygiene — the polled endpoint must not start an exe per poll
# ---------------------------------------------------------------------------
def test_status_cached_spawns_once_per_ttl(project: Path,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(rb, "status", lambda: (calls.append(1), {
        "connected": False, "reason": "off", "model_title": None})[1])
    rb._STATUS_CACHE.update(ts=0.0, status=None)
    first = rb.status_cached()
    for _ in range(10):
        rb.status_cached()
    assert len(calls) == 1
    assert first["cached"] is False
    assert rb.status_cached()["cached"] is True
