"""Agentic chatbot endpoint (production-plan §5). POST /api/chat drives the
OpenRouter tool loop against THIS request's project (the make_router() context
dependency binds the artifact dirs first). No streaming — that's phase 2."""

from __future__ import annotations

import time
from typing import Any

from fastapi import Body, HTTPException, Request
from fastapi.responses import JSONResponse

from .. import chat_agent
from .common import make_router

router = make_router()

# ---------------------------------------------------------------------------
# Simple in-memory rate limiter: track last-N timestamps per client IP.
# Reject if > 10 requests/minute. Module-level dict with periodic cleanup.
# ---------------------------------------------------------------------------
_RATE_LIMIT_MAX = 10  # max requests per window
_RATE_LIMIT_WINDOW_S = 60  # 1 minute window
_rate_limit_store: dict[str, list[float]] = {}
_last_cleanup = time.monotonic()


def _check_rate_limit(client_ip: str) -> None:
    """Raise HTTPException 429 if client has exceeded the rate limit."""
    global _last_cleanup
    now = time.monotonic()
    # Periodic cleanup: purge entries older than the window every 5 minutes.
    if now - _last_cleanup > 300:
        cutoff = now - _RATE_LIMIT_WINDOW_S
        _rate_limit_store.clear()
        _last_cleanup = now
    timestamps = _rate_limit_store.setdefault(client_ip, [])
    # Remove timestamps outside the window.
    cutoff = now - _RATE_LIMIT_WINDOW_S
    timestamps[:] = [t for t in timestamps if t > cutoff]
    if len(timestamps) >= _RATE_LIMIT_MAX:
        raise HTTPException(status_code=429, detail="Rate limit exceeded. Try again later.")
    timestamps.append(now)


@router.post("/api/chat")
def chat(request: Request, payload: dict[str, Any] = Body(...)) -> JSONResponse:
    # Rate limiting per client IP.
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)
    message = payload.get("message") if isinstance(payload, dict) else None
    if not isinstance(message, str) or not message.strip():
        raise HTTPException(status_code=400, detail='Body must be {"message": "..."}')
    history = payload.get("history") if isinstance(payload, dict) else None
    if history is not None and not isinstance(history, list):
        history = None
    try:
        result = chat_agent.run_chat(message, history=history)
    except chat_agent.ChatUnavailable as exc:
        # Honest, non-fatal: the UI renders this as a normal assistant reply.
        return JSONResponse({
            "reply": f"The assistant is unavailable: {exc}. "
                     "Set OPENROUTER_API_KEY in backend/.env to enable chat.",
            "blocks": [], "ui_actions": [],
        })
    return JSONResponse(result)
