"""D1.3: the bearer token arrives as ``?token=`` (EventSource/<img> cannot set a
header) and uvicorn.access logs the full request line, so the rotating file
handler must redact it before anything reaches disk."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from app import maintenance


def _access_record() -> logging.LogRecord:
    """A record shaped like uvicorn.access: message lives in args, not msg."""
    return logging.LogRecord(
        name="uvicorn.access", level=logging.INFO, pathname=__file__, lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:1234", "GET", "/api/health?token=testtoken", "1.1", 200),
        exc_info=None,
    )


def test_filter_redacts_token_in_access_record() -> None:
    record = _access_record()

    assert maintenance.RedactSecretsFilter().filter(record) is True

    message = record.getMessage()
    assert "testtoken" not in message
    assert "token=REDACTED" in message
    assert "GET /api/health" in message  # request line survives — audit trail intact


def test_filter_redacts_key_params_and_leaves_clean_records_alone() -> None:
    log_filter = maintenance.RedactSecretsFilter()
    record = logging.LogRecord(
        name="x", level=logging.INFO, pathname=__file__, lineno=1,
        msg="GET /api/evidence?api_key=sk-abc123&token=zzz&page=3", args=(), exc_info=None,
    )
    log_filter.filter(record)
    assert record.getMessage() == "GET /api/evidence?api_key=REDACTED&token=REDACTED&page=3"

    clean = logging.LogRecord(
        name="x", level=logging.INFO, pathname=__file__, lineno=1,
        msg="pipeline stage %s ok", args=("match",), exc_info=None,
    )
    log_filter.filter(clean)
    assert clean.getMessage() == "pipeline stage match ok"
    assert clean.args == ("match",)  # untouched records keep lazy formatting


def test_setup_logging_writes_redacted_line_to_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_file = tmp_path / "app.log"
    root = logging.getLogger()
    access = logging.getLogger("uvicorn.access")
    monkeypatch.setattr(root, "handlers", [])          # restored by monkeypatch
    monkeypatch.setattr(access, "handlers", [])
    try:
        maintenance.setup_logging(str(log_file))
        access.handle(_access_record())
        for handler in access.handlers:
            handler.flush()
        text = log_file.read_text(encoding="utf-8")
    finally:
        for logger in (root, access, logging.getLogger("uvicorn"),
                       logging.getLogger("uvicorn.error")):
            for handler in list(logger.handlers):
                if getattr(handler, "_qaqc_file", False):
                    logger.removeHandler(handler)
                    handler.close()

    assert "testtoken" not in text
    assert "token=REDACTED" in text
