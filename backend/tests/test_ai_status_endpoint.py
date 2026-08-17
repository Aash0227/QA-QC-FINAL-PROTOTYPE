"""POST /api/pipeline/ai-status: AI path, missing-key fallback, and the
never-fail deterministic fallback when the LLM raises."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, openrouter
from app.main import app  # noqa: F401
from app.routers.pipeline import _deterministic_status


@pytest.fixture()
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path)
    active = tmp_path / "active_project.json"
    active.write_text(json.dumps({"slug": "scratch"}), encoding="utf-8")
    monkeypatch.setattr(config, "ACTIVE_PROJECT_FILE", active)
    return tmp_path


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _post_ai_status(client: TestClient, stage: str, title: str):
    return client.post("/api/pipeline/ai-status",
                       json={"stage": stage, "title": title})


def test_ai_status_returns_text_and_source(workspace, monkeypatch, client):
    """A healthy LLM answer → 200 with the AI text and source 'ai'."""
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(
        openrouter, "call_llm",
        lambda **kwargs: {"ok": True, "content": "Plan located on S-201."},
    )
    resp = _post_ai_status(client, "pdf_intelligence", "Locating the plan")
    assert resp.status_code == 200
    body = resp.json()
    assert body["text"] == "Plan located on S-201."
    assert body["source"] == "ai"


def test_ai_status_without_key_is_deterministic(workspace, monkeypatch, client):
    """Empty OpenRouter key → deterministic fallback, no network call."""
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")
    resp = _post_ai_status(client, "ransac", "Aligning coordinates")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "deterministic"
    assert body["text"] == _deterministic_status("ransac", "Aligning coordinates")
    assert "complete" in body["text"]


def test_ai_status_llm_failure_still_200_deterministic(workspace, monkeypatch, client):
    """LLM raises → still 200 with the deterministic fallback (never fails)."""
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    def _boom(**kwargs):
        raise RuntimeError("openrouter down")

    monkeypatch.setattr(openrouter, "call_llm", _boom)
    resp = _post_ai_status(client, "compare", "Comparing")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "deterministic"
    assert body["text"] == _deterministic_status("compare", "Comparing")