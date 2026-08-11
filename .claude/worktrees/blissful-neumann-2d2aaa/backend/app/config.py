from __future__ import annotations

import os
import sys
from contextvars import ContextVar
from pathlib import Path

PROTOTYPE_VERSION = "0.1.0"
PROTOTYPE_NAME = "QA-QC Automated System"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
# backend/app/config.py -> backend/app -> backend -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_BASE = PROJECT_ROOT / "artifacts"
PROJECTS_DIR = ARTIFACT_BASE / "projects"
MEMORY_DIR = ARTIFACT_BASE / "memory"
ACTIVE_PROJECT_FILE = ARTIFACT_BASE / "active_project.json"
FRONTEND_DIR = PROJECT_ROOT / "frontend"

# Project-scoped dirs are request-scoped via a ContextVar (BUG-03, full fix).
# ARTIFACT_DIR / EVIDENCE_DIR / UPLOAD_DIR / PAGES_DIR are NOT real module
# attributes: module __getattr__ (below) resolves them per access from the
# bound slug, so two concurrent requests on different projects can't stomp each
# other. Tests monkeypatch config.ARTIFACT_DIR — a real attr that shadows
# __getattr__; the derived dirs follow it because they resolve through this
# module's own attribute lookup (getattr(self, "ARTIFACT_DIR")).
_PROJECT_SLUG: ContextVar[str | None] = ContextVar("qaqc_project", default=None)

_DERIVED = {"EVIDENCE_DIR": "evidence", "UPLOAD_DIR": "uploads", "PAGES_DIR": "pages"}


def __getattr__(name: str) -> Path:  # PEP 562
    if name == "ARTIFACT_DIR":
        return PROJECTS_DIR / (_PROJECT_SLUG.get() or active_project())
    if name in _DERIVED:
        return getattr(sys.modules[__name__], "ARTIFACT_DIR") / _DERIVED[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _dir(name: str) -> Path:
    """Effective project dir — honors a monkeypatched real attr if a test set one,
    otherwise falls through to __getattr__'s ContextVar resolution."""
    return getattr(sys.modules[__name__], name)


def slugify(name: str) -> str:
    out = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
    while "--" in out:
        out = out.replace("--", "-")
    return out[:48] or "project"


def active_project() -> str:
    import json

    if ACTIVE_PROJECT_FILE.exists():
        try:
            return json.loads(ACTIVE_PROJECT_FILE.read_text(encoding="utf-8"))["slug"]
        except Exception:
            pass
    return "madera"


import threading

# BUG-03 (full fix, production-plan §1): artifact dirs are request-scoped via the
# _PROJECT_SLUG ContextVar above, so concurrent clients bound to different
# projects can't redirect each other's writes. This lock now guards only
# set_active_project's read-modify-write of ACTIVE_PROJECT_FILE (the persisted UI
# preference); binding itself needs no lock — a ContextVar is per-context.
_ACTIVE_LOCK = threading.RLock()


def bind_project(slug: str) -> Path:
    """Bind this context (request/thread) to artifacts/projects/<slug>/ via the
    _PROJECT_SLUG ContextVar and ensure its dirs exist. No preference persisted:
    any client can target a workspace via the X-Project header / ?project= query
    without /activate. Per-context, so concurrent requests never stomp."""
    slug = slugify(slug)
    _PROJECT_SLUG.set(slug)
    for name in ("ARTIFACT_DIR", "EVIDENCE_DIR", "UPLOAD_DIR", "PAGES_DIR"):
        _dir(name).mkdir(parents=True, exist_ok=True)
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    return _dir("ARTIFACT_DIR")


def set_active_project(slug: str) -> Path:
    """Bind the project for this context AND persist it as the UI's active-project
    preference (the /activate endpoint + the startup default)."""
    import json

    slug = slugify(slug)
    result = bind_project(slug)
    with _ACTIVE_LOCK:
        ACTIVE_PROJECT_FILE.write_text(json.dumps({"slug": slug}), encoding="utf-8")
    return result


def _migrate_legacy_layout() -> None:
    """One-time: move flat artifacts/* into artifacts/projects/madera/."""
    legacy_marker = ARTIFACT_BASE / "element_list.json"
    if not legacy_marker.exists() or (PROJECTS_DIR / "madera").exists():
        return
    target = PROJECTS_DIR / "madera"
    target.mkdir(parents=True, exist_ok=True)
    for item in ARTIFACT_BASE.iterdir():
        if item.name in ("projects", "memory", "active_project.json"):
            continue
        item.rename(target / item.name)


_migrate_legacy_layout()
set_active_project(active_project())

# Canonical artifact file names (saved in ARTIFACT_DIR).
ARTIFACT_FILES = {
    "raw_revit": "raw_revit_export.json",
    "ai_revit": "AIConvert_revit.json",
    "pdf_page_intelligence": "pdf_page_intelligence.json",
    "ai_pdf": "AIConvert_pdf.json",
    "compare": "ai_compare_report.json",
    "openrouter_log": "openrouter_call_log.json",
    "registration": "registration_calibration.json",
    "registration_report": "coordinate_registration_report.json",
    "revit_control_points": "revit_control_points.json",
    "pdf_control_points": "pdf_control_points.json",
    "manual_registration_points": "manual_registration_points.json",
    "revit_scope_diagnostics": "revit_scope_diagnostics.json",
    "review_page": "s201_review_page.png",
    "review_overlay_png": "s201_review_overlay.png",
    "review_overlay_svg": "s201_review_overlay.svg",
    "review_items": "s201_review_items.json",
    # Generalized multi-element pipeline (any PDF + Revit export).
    "project_manifest": "project_manifest.json",
    "element_intelligence": "element_intelligence.json",
    "element_list": "element_list.json",
    "scene3d": "scene3d.json",
    "teach_memory": "ai_teach_memory.json",
    "review_comments": "review_comments.json",
    "device_registry": "device_registry.json",
    "pdf_benchmarks": "pdf_benchmarks.json",
    "benchmark_workflow": "benchmark_workflow.json",
    "phase_summaries": "phase_summaries.json",
}

# ---------------------------------------------------------------------------
# Zero-upload auto-ingest (Design A2). The pyRevit "Export QAQC" button writes a
# revit_export*.json; the backend watches for it instead of making a human carry
# it through an upload form.
# ---------------------------------------------------------------------------
EXPORT_WATCH_DIR_ENV = "QAQC_EXPORT_WATCH_DIR"      # os.pathsep-joined
EXPORT_INBOX_DIR = ARTIFACT_BASE / "incoming"       # global drop-anywhere inbox
# Manifest keys written by the auto-ingest (both additive; absent = never
# ingested, which every reader treats as a normal state):
#   last_ingested_export: {sha, mtime, ingested_at, model_title}
#   revit_model_title:    the Revit model this workspace is bound to (§5.2)


def memory_path() -> Path:
    """Cross-project teach memory (survives project switches)."""
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    return MEMORY_DIR / "global.json"


def sheet_calibration_path(sheet_number: str) -> Path:
    """Per-sheet RANSAC calibration artifact (S-201 keeps the legacy
    registration_calibration.json untouched)."""
    safe = "".join(c for c in sheet_number.upper() if c.isalnum() or c == "-")
    return _dir("ARTIFACT_DIR") / f"registration_calibration_{safe}.json"


def _load_dotenv() -> None:
    """Minimal .env loader so OPENROUTER_API_KEY can be supplied locally without
    being hardcoded in source. Values already in the environment win."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


# ---------------------------------------------------------------------------
# OpenRouter configuration (read from environment, never hardcoded)
# ---------------------------------------------------------------------------
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
OPENROUTER_REASONING_MODEL = os.environ.get(
    "OPENROUTER_REASONING_MODEL", "deepseek/deepseek-v4-pro"
).strip()
OPENROUTER_BASE_URL = os.environ.get(
    "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
).strip()


def openrouter_config_status() -> dict:
    return {
        # No key preview: this dict is served unauthenticated on /api/health.
        "api_key_present": bool(OPENROUTER_API_KEY),
        "model": OPENROUTER_REASONING_MODEL,
        "base_url": OPENROUTER_BASE_URL,
    }


def artifact_path(key: str) -> Path:
    return _dir("ARTIFACT_DIR") / ARTIFACT_FILES[key]
