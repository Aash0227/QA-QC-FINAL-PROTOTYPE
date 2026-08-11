"""Agentic chatbot endpoint (production-plan §5). POST /api/chat drives the
OpenRouter tool loop against THIS request's project (the make_router() context
dependency binds the artifact dirs first). No streaming — that's phase 2."""

from __future__ import annotations

from typing import Any

from fastapi import Body, HTTPException
from fastapi.responses import JSONResponse

from .. import chat_agent
from .common import make_router

router = make_router()


@router.post("/api/chat")
def chat(payload: dict[str, Any] = Body(...)) -> JSONResponse:
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
