from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from . import config

# Standardised "LLM was not called" message required by the prototype spec.
NOT_CALLED_MESSAGE = "LLM was not called. Running deterministic/demo mode."


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_log(entry: dict[str, Any]) -> None:
    log_path = config.artifact_path("openrouter_log")
    existing: list[dict[str, Any]] = []
    if log_path.exists():
        try:
            existing = json.loads(log_path.read_text(encoding="utf-8"))
            if not isinstance(existing, list):
                existing = []
        except json.JSONDecodeError:
            existing = []
    existing.append(entry)
    log_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def call_llm(
    *,
    system_prompt: str,
    user_prompt: str,
    purpose: str,
    json_mode: bool = True,
    max_tokens: int = 4000,
    temperature: float = 0.1,
    timeout: float = 90.0,
) -> dict[str, Any]:
    """Make a single OpenRouter chat-completion call and log the outcome.

    Returns a status dict consumed by the AI conversion/compare layers. The dict
    always contains: called, ok, model, timestamp, purpose, error, usage, content.
    A log entry is appended to openrouter_call_log.json for every attempt, so the
    UI/API can prove whether the LLM was actually contacted.
    """
    timestamp = _now_iso()
    base = {
        "called": False,
        "ok": False,
        "model": config.OPENROUTER_REASONING_MODEL,
        "timestamp": timestamp,
        "purpose": purpose,
        "error": None,
        "usage": None,
        "content": None,
        "latency_ms": None,
        "status_code": None,
    }

    if not config.OPENROUTER_API_KEY:
        base["error"] = "OPENROUTER_API_KEY missing from environment."
        base["message"] = NOT_CALLED_MESSAGE
        _append_log(base)
        return base

    payload: dict[str, Any] = {
        "model": config.OPENROUTER_REASONING_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{config.OPENROUTER_BASE_URL}/chat/completions",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://localhost/qa-qc-final-prototype",
            "X-Title": config.PROTOTYPE_NAME,
        },
    )

    base["called"] = True
    start = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            base["status_code"] = response.status
        body = json.loads(raw)
        choices = body.get("choices") or []
        content = choices[0]["message"]["content"] if choices else None
        base["ok"] = bool(content)
        base["content"] = content
        base["usage"] = body.get("usage")
        if not content:
            base["error"] = "OpenRouter returned no message content."
    except urllib.error.HTTPError as exc:  # noqa: PERF203
        detail = ""
        try:
            detail = exc.read().decode("utf-8")[:600]
        except Exception:  # pragma: no cover - best effort
            detail = ""
        base["status_code"] = exc.code
        base["error"] = f"HTTP {exc.code}: {detail or exc.reason}"
    except urllib.error.URLError as exc:
        base["error"] = f"Network error: {exc.reason}"
    except (TimeoutError, json.JSONDecodeError, KeyError, IndexError) as exc:
        base["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        base["latency_ms"] = round((time.monotonic() - start) * 1000, 1)

    _append_log(base)
    return base


def call_chat(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    purpose: str,
    max_tokens: int = 1200,
    temperature: float = 0.2,
    timeout: float = 90.0,
) -> dict[str, Any]:
    """Multi-turn chat-completion with optional function-calling ``tools``.

    Powers chat_agent's tool loop (production-plan §5). Reuses this module's
    call-logging so every chatbot turn is provable in openrouter_call_log.json.
    Returns a dict with the assistant ``message`` (content + any ``tool_calls``);
    ``ok`` is False when the key is missing or the request failed.
    """
    timestamp = _now_iso()
    base: dict[str, Any] = {
        "called": False,
        "ok": False,
        "model": config.OPENROUTER_REASONING_MODEL,
        "timestamp": timestamp,
        "purpose": purpose,
        "error": None,
        "usage": None,
        "message": None,
        "latency_ms": None,
        "status_code": None,
    }
    if not config.OPENROUTER_API_KEY:
        base["error"] = "OPENROUTER_API_KEY missing from environment."
        base["note"] = NOT_CALLED_MESSAGE
        _append_log(base)
        return base

    payload: dict[str, Any] = {
        "model": config.OPENROUTER_REASONING_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools

    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{config.OPENROUTER_BASE_URL}/chat/completions",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://localhost/qa-qc-final-prototype",
            "X-Title": config.PROTOTYPE_NAME,
        },
    )

    base["called"] = True
    start = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            base["status_code"] = response.status
        body = json.loads(raw)
        choices = body.get("choices") or []
        message = choices[0]["message"] if choices else None
        base["ok"] = bool(message)
        base["message"] = message
        base["usage"] = body.get("usage")
        if not message:
            base["error"] = "OpenRouter returned no message."
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")[:600]
        except Exception:  # pragma: no cover - best effort
            detail = ""
        base["status_code"] = exc.code
        base["error"] = f"HTTP {exc.code}: {detail or exc.reason}"
    except urllib.error.URLError as exc:
        base["error"] = f"Network error: {exc.reason}"
    except (TimeoutError, json.JSONDecodeError, KeyError, IndexError) as exc:
        base["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        base["latency_ms"] = round((time.monotonic() - start) * 1000, 1)

    _append_log(base)
    return base


def read_call_log() -> list[dict[str, Any]]:
    log_path = config.artifact_path("openrouter_log")
    if not log_path.exists():
        return []
    try:
        data = json.loads(log_path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def call_status_summary() -> dict[str, Any]:
    """Aggregate view used by /api/health and the UI OpenRouter status panel."""
    log = read_call_log()
    successful = [e for e in log if e.get("ok")]
    attempted = [e for e in log if e.get("called")]
    total_tokens = 0
    for entry in successful:
        usage = entry.get("usage") or {}
        total_tokens += int(usage.get("total_tokens") or 0)
    return {
        "config": config.openrouter_config_status(),
        "total_log_entries": len(log),
        "calls_attempted": len(attempted),
        "calls_successful": len(successful),
        "total_tokens_used": total_tokens,
        "llm_was_called": len(attempted) > 0,
        "llm_succeeded_at_least_once": len(successful) > 0,
        "message": (
            None
            if len(attempted) > 0
            else NOT_CALLED_MESSAGE
        ),
        "last_call": log[-1] if log else None,
    }
