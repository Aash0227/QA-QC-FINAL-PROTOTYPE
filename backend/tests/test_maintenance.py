"""Retention GC (production-plan §10): oldest evidence crops are trimmed per
project until under the size cap; audit artifacts and other projects untouched."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from app import config, maintenance


def _crop(path: Path, kb: int, mtime: float) -> None:
    path.write_bytes(b"\0" * (kb * 1024))
    os.utime(path, (mtime, mtime))


def test_gc_trims_oldest_over_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path)
    ev = tmp_path / "proj" / "evidence"
    ev.mkdir(parents=True)
    now = time.time()
    # 3 crops × 100 KB = 300 KB; cap 0.15 MB should evict the two oldest.
    _crop(ev / "old.png", 100, now - 300)
    _crop(ev / "mid.png", 100, now - 200)
    _crop(ev / "new.png", 100, now - 100)
    # a non-crop artifact must survive regardless of the cap.
    (tmp_path / "proj" / "element_list.json").write_text("{}", encoding="utf-8")

    out = maintenance.gc_evidence_crops(cap_mb=0.15)

    assert out["removed"] == 2
    assert not (ev / "old.png").exists()
    assert not (ev / "mid.png").exists()
    assert (ev / "new.png").exists()               # newest kept
    assert (tmp_path / "proj" / "element_list.json").exists()  # audit untouched


def test_gc_noop_under_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path)
    ev = tmp_path / "p" / "evidence"
    ev.mkdir(parents=True)
    _crop(ev / "a.png", 10, time.time())
    out = maintenance.gc_evidence_crops(cap_mb=512)
    assert out == {"removed": 0, "freed_bytes": 0}
    assert (ev / "a.png").exists()


def test_gc_missing_projects_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "nope")
    assert maintenance.gc_evidence_crops()["removed"] == 0
