"""Startup hardening (production-plan §10): a rotating structured log file and
an artifact-retention GC. Both are best-effort and env-tunable; neither ever
touches audit artifacts — only the regenerable evidence-crop cache is trimmed."""

from __future__ import annotations

import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import config

# Evidence crops are regenerable from the source PDFs, so this cap trims a
# disposable cache — generous by default; lower it on small disks.
EVIDENCE_CAP_MB = float(os.environ.get("QAQC_EVIDENCE_CAP_MB", "512"))
LOG_FILE = os.environ.get("QAQC_LOG_FILE", str(config.PROJECT_ROOT / "logs" / "app.log"))
LOG_MAX_BYTES = int(os.environ.get("QAQC_LOG_MAX_BYTES", str(5 * 1024 * 1024)))
LOG_BACKUPS = int(os.environ.get("QAQC_LOG_BACKUPS", "5"))


def gc_evidence_crops(cap_mb: float = EVIDENCE_CAP_MB) -> dict:
    """Per project, delete the oldest evidence-crop PNGs until the crop folder
    is under ``cap_mb``. Returns a small summary. Missing dirs are a no-op."""
    cap = cap_mb * 1024 * 1024
    removed = 0
    freed = 0
    if not config.PROJECTS_DIR.exists():
        return {"removed": 0, "freed_bytes": 0}
    for proj in config.PROJECTS_DIR.iterdir():
        evidence = proj / "evidence"
        if not evidence.is_dir():
            continue
        pngs = sorted(evidence.glob("*.png"), key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in pngs)
        for png in pngs:
            if total <= cap:
                break
            size = png.stat().st_size
            try:
                png.unlink()
            except OSError:
                continue
            removed += 1
            freed += size
            total -= size
    return {"removed": removed, "freed_bytes": freed}


#: ``?token=`` is a real credential (EventSource/<img>/window.open cannot send an
#: Authorization header), and uvicorn.access logs the whole request line — so the
#: bearer token would otherwise land in logs/app.log in cleartext and survive
#: rotation. Value ends at the next query separator or whitespace/quote.
_SECRET_QS_RE = re.compile(r"((?:api_key|token|key)=)[^&\s\"'\\]+", re.IGNORECASE)


class RedactSecretsFilter(logging.Filter):
    """Rewrite ``token=``/``key=``/``api_key=`` values to ``REDACTED``.

    Attached to the file handler rather than to ``uvicorn.access``, so it covers
    every logger that ever formats a URL — present and future."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # a record we cannot format is not one we can redact
            return True
        redacted = _SECRET_QS_RE.sub(r"\1REDACTED", message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def setup_logging(log_file: str = LOG_FILE) -> None:
    """Route the root logger + uvicorn to a rotating file (idempotent)."""
    path = Path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if any(getattr(h, "_qaqc_file", False) for h in root.handlers):
        return
    handler = RotatingFileHandler(path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS,
                                  encoding="utf-8")
    handler._qaqc_file = True  # type: ignore[attr-defined]
    handler.addFilter(RedactSecretsFilter())
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)
    # uvicorn keeps its own loggers; attach the same file sink so requests land
    # in one place without silencing the console.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).addHandler(handler)


def run_startup() -> None:
    """Called once from create_app()."""
    setup_logging()
    summary = gc_evidence_crops()
    if summary["removed"]:
        logging.getLogger("qaqc.maintenance").info(
            "evidence GC: removed %d crops, freed %d bytes",
            summary["removed"], summary["freed_bytes"])
