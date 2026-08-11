from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from . import openrouter
from .normalization import (
    CORE_TOKEN_TO_MARK,
    mapped_mark_for_core_token,
    normalize_holdown_type,
)

SCHEMA_VERSION = "revit-aiconvert/1.0"

# Family-name tokens that indicate a record is an *evidence member* of a physical
# hold-down assembly rather than a standalone hold-down. Note: "bolt" is NOT here,
# because body families legitimately carry a "-With Bolt" suffix.
import os as _os

_DEFAULT_MEMBER_KEYWORDS = ("anchor", "offset", "screw", "plate", "nut", "washer", "stud")
_env_kw = _os.environ.get("QAQC_MEMBER_KEYWORDS", "")
MEMBER_KEYWORDS = tuple(k.strip() for k in _env_kw.split(",") if k.strip()) if _env_kw.strip() else _DEFAULT_MEMBER_KEYWORDS

# Maximum 2D distance (Revit internal feet) for attaching an evidence member to a body.
MEMBER_ATTACH_MAX_FT = float(_os.environ.get("QAQC_MEMBER_ATTACH_MAX_FT", "3.0"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _classify_family(family: str) -> str:
    f = (family or "").lower()
    if any(k in f for k in MEMBER_KEYWORDS):
        return "evidence_member"
    return "body"


def _location(record: dict[str, Any]) -> tuple[float, float] | None:
    loc = record.get("location")
    if isinstance(loc, (list, tuple)) and len(loc) >= 2:
        try:
            return float(loc[0]), float(loc[1])
        except (TypeError, ValueError):
            return None
    return None


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _build_family_dictionary(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    dictionary: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in records:
        grouped[rec.get("family") or "<unknown>"].append(rec)
    for family, recs in sorted(grouped.items()):
        scheduled = Counter(r.get("scheduled_type") for r in recs if r.get("scheduled_type"))
        # Prefer the explicit scheduled_type; fall back to normalising the family name.
        core_token = ""
        if scheduled:
            core_token = normalize_holdown_type(scheduled.most_common(1)[0][0]).core_token
        if not core_token:
            core_token = normalize_holdown_type(family).core_token
        dictionary[family] = {
            "family": family,
            "count": len(recs),
            "classification": _classify_family(family),
            "core_token": core_token,
            "mapped_pdf_mark": mapped_mark_for_core_token(core_token),
            "scheduled_types_seen": dict(scheduled),
        }
    return dictionary


def _learned_key_points(
    records: list[dict[str, Any]],
    family_dict: dict[str, dict[str, Any]],
    raw_json: dict[str, Any],
) -> dict[str, Any]:
    bodies = [r for r in records if _classify_family(r.get("family", "")) == "body"]
    members = [r for r in records if _classify_family(r.get("family", "")) == "evidence_member"]
    body_by_token = Counter(
        normalize_holdown_type(r.get("scheduled_type") or r.get("family", "")).core_token
        for r in bodies
    )
    return {
        "raw_record_count": len(records),
        "body_record_count": len(bodies),
        "evidence_member_record_count": len(members),
        "distinct_family_count": len(family_dict),
        "naming_patterns_observed": [
            "Body families carry the structural hold-down token, often with a "
            "'-With Bolt' / '-2 Sided' suffix.",
            "Evidence-member families embed keywords such as 'Anchor_Bolt_*' and "
            "'*offset' and are co-located with a body record.",
            "scheduled_type provides a clean core token and is preferred over the "
            "raw family string for classification.",
        ],
        "core_token_to_pdf_mark": dict(CORE_TOKEN_TO_MARK),
        "body_count_by_core_token": {k: v for k, v in sorted(body_by_token.items()) if k},
        "member_keywords_used": list(MEMBER_KEYWORDS),
        "grid_count": len(raw_json.get("grids") or []),
        "units": raw_json.get("units"),
        "coordinate_space": "revit_internal_feet (x, y, z=elevation)",
    }


def _llm_enrichment(family_dict: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Ask OpenRouter to learn the naming/labeling pattern from the family list.

    Grouping itself stays deterministic; the LLM augments learned_key_points and is
    proof the AI layer was actually invoked. On any failure we degrade gracefully.
    """
    compact = [
        {
            "family": d["family"],
            "count": d["count"],
            "scheduled_types_seen": d["scheduled_types_seen"],
        }
        for d in family_dict.values()
    ]
    system_prompt = (
        "You are a structural QA/QC assistant. You are given raw Revit family names for "
        "hold-down hardware exported from a model. One physical hold-down assembly often "
        "appears as multiple records (body, anchor bolt, offset, plate, screws). Classify "
        "each family as either 'body' (the hold-down itself) or 'evidence_member' "
        "(hardware that is part of an assembly). Also give the canonical core token "
        "from the family name itself when identifiable (illustrative examples ONLY — "
        "e.g. HDU6, HTT4 — do NOT limit yourself to these; report the token actually "
        "present in the name). Reply ONLY with JSON of shape "
        '{"families":[{"family":..,"classification":..,"core_token":..,"reason":..}],'
        '"summary":".."}.'
    )
    user_prompt = json.dumps({"families": compact}, indent=2)
    status = openrouter.call_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        purpose="revit_ai_convert.naming_pattern_learning",
    )
    parsed: dict[str, Any] | None = None
    if status.get("ok") and status.get("content"):
        try:
            parsed = json.loads(status["content"])
        except json.JSONDecodeError:
            status = {**status, "error": "LLM returned non-JSON content; ignored."}
    return {"status": status, "parsed": parsed}


def convert_revit(raw_json: dict[str, Any], source_file: str) -> dict[str, Any]:
    records: list[dict[str, Any]] = list(raw_json.get("holdowns") or [])
    family_dict = _build_family_dictionary(records)

    bodies = [r for r in records if _classify_family(r.get("family", "")) == "body"]
    members = [r for r in records if _classify_family(r.get("family", "")) == "evidence_member"]

    # --- LLM naming-pattern learning (real OpenRouter call) -----------------
    enrichment = _llm_enrichment(family_dict)
    call_status = enrichment["status"]
    llm_ok = bool(call_status.get("ok"))
    ai_model_used = call_status.get("model") if llm_ok else "deterministic_fallback"

    # Merge LLM family classifications as a cross-check (deterministic stays source of truth).
    if enrichment["parsed"]:
        for item in enrichment["parsed"].get("families", []):
            fam = item.get("family")
            if fam in family_dict:
                family_dict[fam]["llm_classification"] = item.get("classification")
                family_dict[fam]["llm_core_token"] = item.get("core_token")
                family_dict[fam]["llm_reason"] = item.get("reason")

    learned = _learned_key_points(records, family_dict, raw_json)
    if enrichment["parsed"] and enrichment["parsed"].get("summary"):
        learned["llm_summary"] = enrichment["parsed"]["summary"]

    # --- Group evidence members onto the nearest compatible body ------------
    assemblies: list[dict[str, Any]] = []
    member_assignment: dict[int, int] = {}  # member index -> assembly index
    body_index_to_asm: dict[int, int] = {}

    for body_i, body in enumerate(bodies):
        core_token = normalize_holdown_type(
            body.get("scheduled_type") or body.get("family", "")
        ).core_token
        center = _location(body) or (None, None)
        asm = {
            "id": f"rev_asm_{len(assemblies) + 1:03d}",
            "pdf_mark_candidate": mapped_mark_for_core_token(core_token),
            "core_token": core_token,
            "scheduled_type_raw": body.get("scheduled_type") or "",
            "family_type_summary": {body.get("family", "<unknown>"): 1},
            "member_element_ids": [body.get("element_id")],
            "primary_element_id": body.get("element_id"),
            "center_point": {
                "x": center[0],
                "y": center[1],
                "z": body.get("elevation"),
                "space": "revit_internal",
                "unit": "feet",
                "has_real_z": True,
                "z_source": "revit_elevation",
            },
            "bbox": body.get("bbox"),
            "level": body.get("level"),
            "classification_confidence": 0.9 if core_token else 0.4,
            "classification_reason": (
                f"Body family {body.get('family')!r} maps to core token "
                f"{core_token or 'UNKNOWN'} via scheduled_type/normalisation."
            ),
            "raw_evidence": [
                {
                    "element_id": body.get("element_id"),
                    "family": body.get("family"),
                    "role": "body",
                    "scheduled_type": body.get("scheduled_type"),
                }
            ],
        }
        body_index_to_asm[body_i] = len(assemblies)
        assemblies.append(asm)

    orphan_members: list[dict[str, Any]] = []
    for m_i, member in enumerate(members):
        m_token = normalize_holdown_type(
            member.get("scheduled_type") or member.get("family", "")
        ).core_token
        m_loc = _location(member)
        best_asm_i: int | None = None
        best_dist = MEMBER_ATTACH_MAX_FT
        for body_i, body in enumerate(bodies):
            b_loc = _location(body)
            if not m_loc or not b_loc:
                continue
            b_token = normalize_holdown_type(
                body.get("scheduled_type") or body.get("family", "")
            ).core_token
            if m_token and b_token and m_token != b_token:
                continue
            dist = _distance(m_loc, b_loc)
            if dist <= best_dist:
                best_dist = dist
                best_asm_i = body_index_to_asm[body_i]
        if best_asm_i is None:
            orphan_members.append(
                {
                    "element_id": member.get("element_id"),
                    "family": member.get("family"),
                    "core_token": m_token,
                    "reason": "No body within attach distance / token mismatch.",
                }
            )
            continue
        member_assignment[m_i] = best_asm_i
        asm = assemblies[best_asm_i]
        asm["member_element_ids"].append(member.get("element_id"))
        fam = member.get("family", "<unknown>")
        asm["family_type_summary"][fam] = asm["family_type_summary"].get(fam, 0) + 1
        asm["raw_evidence"].append(
            {
                "element_id": member.get("element_id"),
                "family": member.get("family"),
                "role": "evidence_member",
                "attach_distance_ft": round(best_dist, 4),
                "scheduled_type": member.get("scheduled_type"),
            }
        )

    # --- QA warnings (honest, no forced matching) ---------------------------
    body_by_mark = Counter(a["pdf_mark_candidate"] for a in assemblies if a["pdf_mark_candidate"])
    from .compare import _project_pdf_baseline
    pdf_baseline = _project_pdf_baseline()
    # Strip the "total" key if present — we only need per-mark counts here.
    if pdf_baseline:
        pdf_baseline = {k: v for k, v in pdf_baseline.items() if k != "total"}
    qa_warnings: list[str] = []
    # Use baseline marks when available, otherwise iterate observed marks.
    marks_to_check = tuple(pdf_baseline) if pdf_baseline else tuple(sorted(body_by_mark))
    if pdf_baseline:
        for mark in marks_to_check:
            rev = body_by_mark.get(mark, 0)
            expected = pdf_baseline.get(mark, 0)
            if rev != expected:
                qa_warnings.append(
                    f"{mark}: Revit body assemblies={rev} vs PDF baseline={expected} "
                    f"(delta {rev - expected}). Do NOT force-match; flag for review."
                )
    if orphan_members:
        qa_warnings.append(
            f"{len(orphan_members)} evidence-member record(s) could not be attached to a body."
        )
    ambiguous_families = [
        f for f, d in family_dict.items() if not d["core_token"]
    ]
    if ambiguous_families:
        qa_warnings.append(
            f"Families without a resolved core token: {ambiguous_families}."
        )

    unmapped = orphan_members + [
        {
            "element_id": r.get("element_id"),
            "family": r.get("family"),
            "reason": "Body family did not resolve to a known core token.",
        }
        for r in bodies
        if not normalize_holdown_type(r.get("scheduled_type") or r.get("family", "")).core_token
    ]

    # --- Revit over-count diagnostics (no exporter fix in this phase) --------
    family_breakdown = {f: d["count"] for f, d in sorted(family_dict.items())}
    schedule_breakdown = dict(
        Counter(r.get("scheduled_type") for r in records if r.get("scheduled_type"))
    )
    levels_seen = dict(Counter(r.get("level") for r in records))
    views_seen = dict(Counter(r.get("view") for r in records))
    all_levels_null = all(r.get("level") is None for r in records) if records else True
    all_views_null = all(r.get("view") is None for r in records) if records else True
    scope_warnings: list[str] = []
    if all_levels_null:
        scope_warnings.append(
            "All records have level=null; cannot scope by level/floor. Comparison may include "
            "assemblies from other levels/views, inflating Revit counts."
        )
    if all_views_null:
        scope_warnings.append(
            "All records have view=null; cannot scope to the comparison view."
        )
    # Dynamic mark keys: use baseline marks if available, else observed marks.
    diag_marks = tuple(pdf_baseline) if pdf_baseline else tuple(sorted(body_by_mark))
    revit_count_diagnostics = {
        "raw_holdown_records": len(records),
        "canonical_assemblies": len(assemblies),
        "by_mark": {m: body_by_mark.get(m, 0) for m in diag_marks},
        "pdf_baseline": dict(pdf_baseline) if pdf_baseline else None,
        "family_breakdown": family_breakdown,
        "schedule_type_breakdown": schedule_breakdown,
        "level_availability": {"all_null": all_levels_null, "values_seen": levels_seen},
        "view_availability": {"all_null": all_views_null, "values_seen": views_seen},
        "evidence_members_orphaned": len(orphan_members),
        "likely_issue": (
            "Revit export/conversion still includes extra assemblies or wrong scope "
            "(no level/view scoping; raw hardware records inflate assembly counts)."
        ),
        "required_next_fix": "Add view/level/schedule/grid scoping before final comparison.",
        "scope_warnings": scope_warnings,
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "source_file": source_file,
        "ai_model_used": ai_model_used,
        "coordinate_system": {
            "space": "revit_internal",
            "unit": "feet",
            "has_real_z": True,
            "axes": "x, y, z=elevation",
        },
        "learned_key_points": learned,
        "family_type_dictionary": family_dict,
        "canonical_holdown_assemblies": assemblies,
        "unmapped_or_ambiguous_records": unmapped,
        "revit_count_diagnostics": revit_count_diagnostics,
        "qa_warnings": qa_warnings,
        "summary": {
            "canonical_assembly_count": len(assemblies),
            "assemblies_by_pdf_mark": {k: v for k, v in sorted(body_by_mark.items()) if k},
            "evidence_members_attached": len(member_assignment),
            "evidence_members_orphaned": len(orphan_members),
        },
        "openrouter_call_status": call_status,
    }
