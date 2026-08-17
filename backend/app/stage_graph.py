"""Pipeline stage DAG: definitions, prereqs, outputs, and dependency-aware
invalidation. Single source of truth for what a run is — the orchestrator
(pipeline.py) and the invalidation hook (common.py) both read this module.

No project names, no client data: stages are the generic QA/QC chain.
"""
from __future__ import annotations

from pathlib import Path

from . import config

# (key, human title, prereq artifact keys, output artifact key)
STAGES: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("extract", "Reading drawings", (), "element_intelligence"),
    ("revit_convert", "Reading model", ("raw_revit",), "ai_revit"),
    ("pdf_intelligence", "Locating the plan", ("element_intelligence",), "pdf_page_intelligence"),
    ("pdf_convert", "Preparing drawing data", ("pdf_page_intelligence",), "ai_pdf"),
    ("ransac", "Aligning coordinates", ("ai_revit", "ai_pdf"), "registration"),
    ("compare", "Comparing", ("ai_revit", "ai_pdf", "registration"), "compare"),
    ("match", "Building the review queue", ("element_intelligence", "raw_revit", "ai_revit", "compare"), "element_list"),
)

# Output artifact for each stage, and the artifacts each stage INVALIDATES when
# it reruns (its own output + every downstream output — nothing stale survives).
STAGE_OUTPUT: dict[str, str] = {s[0]: s[3] for s in STAGES}
DOWNSTREAM: dict[str, list[str]] = {}
for i, (key, _title, _prereqs, _out) in enumerate(STAGES):
    DOWNSTREAM[key] = [s[0] for s in STAGES[i + 1:]]


def invalidate_downstream(stage_key: str) -> list[str]:
    """Delete this stage's output and all downstream outputs so a rerun
    recomputes everything that depends on it. Returns removed artifact KEYS
    (e.g. "ai_pdf") — callers map to filenames via config.ARTIFACT_FILES.

    ponytail: file deletion is per-artifact; a proper run-engine rewrite may
    move this to the run graph, but file existence IS the pipeline's truth.
    """
    removed: list[str] = []
    keys = [stage_key, *DOWNSTREAM.get(stage_key, [])]
    for key in keys:
        if key not in STAGE_OUTPUT:
            continue
        path = config.artifact_path(STAGE_OUTPUT[key])
        if path.exists():
            try:
                path.unlink()
                removed.append(STAGE_OUTPUT[key])
            except OSError:
                pass  # racing reader — the artifact stays, next run re-checks
    return removed


def artifact_present(keys: tuple[str, ...]) -> bool:
    return all(config.artifact_path(k).exists() for k in keys)


def stages_payload() -> list[dict]:
    """Initial stage list for a new run (all pending)."""
    return [{"key": k, "title": t, "status": "pending", "started_at": None,
             "completed_at": None, "duration_s": None, "error": None,
             "reason": None} for k, t, _p, _o in STAGES]
