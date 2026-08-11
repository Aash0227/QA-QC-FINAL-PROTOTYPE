from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from . import openrouter
from .normalization import mapped_mark_for_core_token, normalize_holdown_mark

SCHEMA_VERSION = "pdf-aiconvert/1.0"

# Core token per PDF mark (kept in sync with the Revit-side learned memory).
MARK_TO_CORE_TOKEN = {"H1": "HDU6", "H2": "HDU11", "H3": "HD10S", "H4": "HD15B"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _llm_confirm_mapping(revit_ai_memory: dict[str, Any] | None) -> dict[str, Any]:
    """Real OpenRouter call that uses the format/memory learned on the Revit side.

    The deterministic mark->core-token mapping stays authoritative; the LLM is asked
    to confirm it against the learned Revit memory, which both exercises the AI layer
    and records token usage / call status for the artifact.
    """
    learned = {}
    if revit_ai_memory:
        learned = (revit_ai_memory.get("learned_key_points") or {}).get(
            "core_token_to_pdf_mark", {}
        )
    system_prompt = (
        "You are a structural QA/QC assistant. Using the hold-down naming memory learned "
        "from the Revit model, confirm the mapping between PDF plan marks (H1-H4) and "
        "canonical core tokens (HDU6, HDU11, HD10S, HD15B). Reply ONLY with JSON "
        '{"mapping":{"H1":"..","H2":"..","H3":"..","H4":".."},"agrees_with_revit":true|false,'
        '"note":".."}.'
    )
    user_prompt = json.dumps(
        {
            "revit_learned_core_token_to_pdf_mark": learned,
            "candidate_mark_to_core_token": MARK_TO_CORE_TOKEN,
        },
        indent=2,
    )
    status = openrouter.call_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        purpose="pdf_ai_convert.confirm_mark_mapping",
    )
    parsed = None
    if status.get("ok") and status.get("content"):
        try:
            parsed = json.loads(status["content"])
        except json.JSONDecodeError:
            status = {**status, "error": "LLM returned non-JSON content; ignored."}
    return {"status": status, "parsed": parsed}


def convert_pdf(
    page_intelligence: dict[str, Any],
    revit_ai_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    detections: list[dict[str, Any]] = list(page_intelligence.get("holdowns") or [])
    sheet_number = page_intelligence.get("sheet_number", "S-201")
    page_index = page_intelligence.get("page_index")

    enrichment = _llm_confirm_mapping(revit_ai_memory)
    call_status = enrichment["status"]
    ai_model_used = call_status.get("model") if call_status.get("ok") else "deterministic_fallback"

    holdowns: list[dict[str, Any]] = []
    for det in detections:
        mark = str(det.get("normalized_mark", "")).upper()
        core_token = det.get("normalized_core_token") or MARK_TO_CORE_TOKEN.get(mark, "")
        norm = normalize_holdown_mark(mark)
        center = det.get("center_pdf") or [None, None]
        holdowns.append(
            {
                "id": det.get("id"),
                "sheet_number": sheet_number,
                "page_index": page_index,
                "raw_mark": det.get("raw_mark"),
                "normalized_mark": mark,
                "core_token": core_token,
                "schedule_type_raw": det.get("schedule_type_raw") or det.get("scheduled_type", ""),
                "center_point": {
                    "x": center[0] if len(center) > 0 else None,
                    "y": center[1] if len(center) > 1 else None,
                    "z": None,
                    "space": "pdf_page",
                    "unit": "points",
                    "has_real_z": False,
                    "z_is_inferred": True,
                    "z_source": f"inferred_from_sheet_{sheet_number}_plan_view",
                },
                "bbox": list(det.get("bbox_pdf") or []),
                "evidence_crop_path": det.get("evidence_crop_path") or None,
                "anchor_bolt": det.get("anchor_bolt", ""),
                "fasteners": det.get("fasteners", ""),
                "embedment": det.get("embedment", ""),
                "confidence": det.get("confidence"),
                "source": det.get("source", "s201_focused_holdown_detector"),
                "multiplicity_index": det.get("multiplicity_index"),
                "total_multiplicity": det.get("total_multiplicity"),
                "normalization_known": norm.known,
            }
        )

    by_mark: dict[str, int] = {}
    for h in holdowns:
        by_mark[h["normalized_mark"]] = by_mark.get(h["normalized_mark"], 0) + 1

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "source_sheet": sheet_number,
        "page_index": page_index,
        "ai_model_used": ai_model_used,
        "coordinate_system": {
            "space": "pdf_page",
            "unit": "points",
            "has_real_z": False,
            "z_is_inferred": True,
            "z_note": "Z is inferred only from sheet/level context, never a real Revit elevation.",
        },
        "used_revit_memory": bool(revit_ai_memory),
        "mark_to_core_token": MARK_TO_CORE_TOKEN,
        "llm_mapping_confirmation": enrichment["parsed"],
        "holdowns": holdowns,
        "summary": {
            "total": len(holdowns),
            "by_type": dict(sorted(by_mark.items())),
        },
        "coordinate_note": (
            "PDF center points are 2D page coordinates. Any Z is inferred from the "
            "sheet/plan-view context and flagged z_is_inferred=true; it is NOT a true "
            "Revit elevation."
        ),
        "openrouter_call_status": call_status,
    }
