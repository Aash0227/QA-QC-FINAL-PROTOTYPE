"""Zero-upload auto-ingest watcher (Design A2, UI_DEPLOY_PLAN_PIPELINE §2).

The operator opens the model in Revit and presses **Export QAQC**; the pyRevit
add-in drops a ``revit_export*.json`` on disk. This module answers one question
— *is there an export this project has not ingested yet?* — and nothing else.
The math source stays byte-for-byte the stored export, so the 106-MATCH Madera
baseline holds by construction.

No thread, no watchdog: the UI already polls ``/api/revit/export-status``, so
``scan()`` is called on the poll. A file-system poll of two directories is
cheaper than the process that would watch them.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config

# The pyRevit exporter's filename, plus the artifact name people hand-copy.
_DEFAULT_PATTERNS = ("revit_export*.json", "raw_revit_export*.json")
_env_pats = os.environ.get("QAQC_EXPORT_PATTERNS", "")
PATTERNS = tuple(p.strip() for p in _env_pats.split(os.pathsep) if p.strip()) if _env_pats.strip() else _DEFAULT_PATTERNS


def watch_dirs() -> list[Path]:
    """Directories scanned for a fresh export. ``QAQC_EXPORT_WATCH_DIR``
    (os.pathsep-joined) replaces the default of *this project's* uploads/ dir
    plus the global ``artifacts/incoming`` inbox. Read at call time so the env
    var takes effect without a backend restart."""
    env = os.environ.get(config.EXPORT_WATCH_DIR_ENV, "").strip()
    if env:
        return [Path(p) for p in env.split(os.pathsep) if p.strip()]
    return [config.UPLOAD_DIR, config.EXPORT_INBOX_DIR]


def candidates(dirs: list[Path] | None = None) -> list[Path]:
    """Every export-shaped file in the watch dirs, newest mtime first."""
    found: dict[Path, float] = {}
    for d in dirs if dirs is not None else watch_dirs():
        for pattern in PATTERNS:
            try:
                for p in d.glob(pattern):
                    if p.is_file():
                        found[p.resolve()] = p.stat().st_mtime
            except OSError:            # dir missing / unreadable is not an error
                continue
    return sorted(found, key=lambda p: found[p], reverse=True)


def newest(dirs: list[Path] | None = None) -> Path | None:
    found = candidates(dirs)
    return found[0] if found else None


def file_sha(path: Path) -> str:
    """SHA-256 of the file's bytes — mtime alone lies after a copy or a re-save
    that produced identical content."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest() -> dict[str, Any]:
    """The active project's manifest, or {} — a project with no manifest yet has
    simply never ingested anything."""
    path = config.artifact_path("project_manifest")
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def scan(manifest: dict[str, Any] | None = None,
         dirs: list[Path] | None = None) -> dict[str, Any]:
    """{pending, path, mtime, sha, reason} for the newest export on disk.

    ``pending`` is True when a file exists whose sha differs from the one this
    project last ingested (``manifest.last_ingested_export.sha``). An unreadable
    file reads as "not pending" with a reason — never an exception; this runs
    under a polled endpoint."""
    if manifest is None:
        manifest = load_manifest()
    path = newest(dirs)
    if path is None:
        return {"pending": False, "path": None, "mtime": None, "sha": None,
                "reason": "no new export found"}
    try:
        mtime = path.stat().st_mtime
        sha = file_sha(path)
    except OSError as exc:
        return {"pending": False, "path": str(path), "mtime": None, "sha": None,
                "reason": f"export unreadable: {exc}"}
    last = manifest.get("last_ingested_export") or {}
    pending = sha != last.get("sha")
    return {"pending": pending, "path": str(path), "mtime": mtime, "sha": sha,
            "reason": None if pending else "already ingested"}


def export_model_title(raw: dict[str, Any]) -> str | None:
    """The model an export came from. Schema 3.1 carries ``source_file``
    ('10510 Madera Dr_LGS model_08052026.rvt'); ``source_model`` is accepted as
    the newer spelling. Extension stripped so it compares against the live
    Revit ``model_title``, which carries none."""
    name = str(raw.get("source_model") or raw.get("source_file") or "").strip()
    return Path(name).stem or None


def titles_match(a: str | None, b: str | None) -> bool | None:
    """Case-insensitive substring compare of two model titles (Revit's live
    title and the export's filename stem differ in decoration, not identity).
    ``None`` on either side is *unknown*, not a mismatch (§5.2)."""
    if not a or not b:
        return None
    lo_a, lo_b = a.strip().lower(), b.strip().lower()
    return lo_a in lo_b or lo_b in lo_a


def iso(ts: float | None) -> str | None:
    """POSIX timestamp -> UTC ISO-8601, or None."""
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def exported_at(raw: dict[str, Any] | None, mtime: float | None) -> str | None:
    """R-14: when the model was actually exported. The payload's own
    ``exported_at`` wins; the file's mtime is the honest fallback (schema 3.1
    does not emit the field)."""
    stamped = (raw or {}).get("exported_at")
    return str(stamped) if stamped else iso(mtime)


def age_s(exported_iso: str | None) -> float | None:
    """Seconds since ``exported_iso``. Unparseable stamps read as unknown."""
    if not exported_iso:
        return None
    try:
        dt = datetime.fromisoformat(str(exported_iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - dt).total_seconds(), 1)


def ingest_record(sha: str, mtime: float | None, model_title: str | None) -> dict[str, Any]:
    """The manifest stamp written on a successful ingest."""
    return {"sha": sha, "mtime": mtime,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "model_title": model_title}


if __name__ == "__main__":                       # ponytail: one runnable check
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "revit_export.json").write_text('{"schema_version": "3.1"}', encoding="utf-8")
        first = scan({}, [d])
        assert first["pending"] is True, first
        assert scan({"last_ingested_export": {"sha": first["sha"]}}, [d])["pending"] is False
        assert scan({}, [d / "nope"])["pending"] is False
    assert export_model_title({"source_file": "A.rvt"}) == "A"
    assert titles_match("madera dr", "10510 MADERA DR_LGS") is True
    assert titles_match("madera", None) is None
    assert titles_match("madera", "dogwood") is False
    print("export_watch self-check OK")
