"""Agentic chatbot (production-plan §5) — an OpenRouter function-calling loop
over a read-mostly toolbox. It answers questions about the QA-QC results AND
acts on the UI (select an element, apply a filter, open a view) via ``ui_actions``
the frontend executes. Nothing destructive is in the toolbox by design.

Now unified with teach-the-AI memory: the teach.py logic (rules, overrides,
LLM parsing) is here as internal methods. External surface preserved at module
level: load_memory, save_rule, build_overrides, apply_on_extract, RULE_KINDS,
list_rules, delete_rule.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import HTTPException

from . import config, openrouter
from .schedule_tables import CATEGORY_MARK_RE

# Cap the tool loop so a confused model can never spin forever (production-plan
# §5: "cap the loop, e.g. 6 tool rounds").
MAX_TOOL_ROUNDS = 6

# run_pipeline_step is whitelisted to non-destructive recompute steps only.
PIPELINE_WHITELIST = ("extract", "match", "compare")

LLM = Callable[[list[dict[str, Any]], list[dict[str, Any]] | None], dict[str, Any]]

class ChatUnavailable(RuntimeError):
    """Raised when the LLM cannot be reached (e.g. no OPENROUTER_API_KEY)."""

SYSTEM_PROMPT = (
    "You are the QA-QC copilot for a structural drawing review app. You answer "
    "questions about the compared PDF-vs-Revit element inventory and you ACT on "
    "the UI through tools. Use the tools to fetch real data — never invent counts "
    "or statuses. Categories are: holdown, shear_wall, post, steel_column, "
    "wall_type. Statuses include MATCH, LOCATION_MISMATCH, PDF_ONLY, REVIT_ONLY, "
    "SPEC_ONLY, NO_REVIT_DATA, NOT_EVALUATED. Tool results are rendered as visual "
    "blocks (count cards, tables, status breakdowns) and UI actions (highlighting "
    "an element, filtering the list, opening the table) automatically — so keep "
    "your final reply short and human, and do NOT paste raw JSON. When the user "
    "asks 'how many X', call get_counts and query_elements(category=X). When they "
    "point at a specific element, call focus_element so every pane flies to it. "
    "To record a client's non-standard drawing convention (e.g. 'HD3 means H3'), "
    "or to exclude a mark entirely ('ignore H6'), call save_teach_rule."
)

# Teach-the-AI constants (was in teach.py)
SCHEMA_VERSION = "qa-memory/1.0"
RULE_KINDS = ("mark_alias", "mark_pattern", "category_header", "exclude", "note")
CATEGORIES = ("holdown", "shear_wall", "post", "steel_column", "wall_type")

CATEGORY_WORDS = {
    "holdown": r"hold[- ]?(?:down|own)s?|tie[- ]?downs?|\bhd\b",
    "shear_wall": r"shear[- ]?walls?",
    "post": r"\bposts?\b",
    "steel_column": r"\bsteel columns?\b|\bcolumns?\b",
    "wall_type": r"\bwall types?\b|\bwalls?\b",
}

_TOKEN = r"[A-Za-z]{1,4}[- ]?\d{1,3}"
ALIAS_RE = re.compile(
    rf"[\"\']?({_TOKEN})[\"\']?\s+(?:means|is the same as|maps? to|equals|=|is)\s+[\"\']?({_TOKEN})[\"\']?",
    re.IGNORECASE,
)
IS_CATEGORY_RE = re.compile(
    rf"[\"\']?({_TOKEN})[\"\']?(?:\s+marks?)?\s+(?:is|are|denotes?|represents?)\s+(?:a |an |the )?([a-z][a-z -]+)",
    re.IGNORECASE,
)

LLM_SYSTEM_PROMPT = (
    "You are the QA-QC extraction assistant for structural drawings. The user "
    "explains a NON-STANDARD convention used in this client's PDF. Translate it "
    "into exactly ONE rule as a JSON object with keys: kind (mark_alias | "
    "mark_pattern | category_header | exclude | note), category (holdown | "
    "shear_wall | post | steel_column | wall_type | null), token (the plan text, "
    "or null), maps_to (existing mark it equals, or null), regex (for mark_pattern/"
    "category_header, or null), reply (one short confirmation sentence starting "
    "with 'Got it'). exclude: the user wants a mark ignored/excluded entirely — "
    "kind=exclude, token=the mark, category required. If the explanation is "
    "ambiguous, instead return "
    '{"question": "<ONE clarifying question>"}. Output ONLY the JSON object.'
)

_EXCLUDE_RE = re.compile(
    r"\b(?:ignore|exclude|skip|drop|omit)\b|\b(?:don'?t|do not)\s+(?:extract|include|use|count)\b",
    re.IGNORECASE,
)

# Teach memory store (internal methods, exposed at module level below)
def _load_memory() -> dict[str, Any]:
    path = config.memory_path()
    if not path.exists():
        legacy = config.artifact_path("teach_memory")
        if legacy.exists():
            try:
                memory = json.loads(legacy.read_text(encoding="utf-8"))
                _save_memory(memory)
                return memory
            except json.JSONDecodeError:
                pass
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"schema_version": SCHEMA_VERSION, "entries": []}

def _save_memory(memory: dict[str, Any]) -> None:
    config.memory_path().write_text(json.dumps(memory, indent=2), encoding="utf-8")

def _add_entry(instruction: str, rule: dict[str, Any], reply: str, scope: str = "global") -> dict[str, Any]:
    memory = _load_memory()
    next_num = 1 + max(
        (int(e["id"].rsplit("_", 1)[-1]) for e in memory["entries"]
         if str(e.get("id", "")).rsplit("_", 1)[-1].isdigit()),
        default=0,
    )
    entry = {
        "id": f"mem_{next_num:03d}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "instruction": instruction,
        "rule": rule,
        "reply": reply,
        "source": "human_teach",
        "scope": scope,
        "origin_project": config.active_project(),
    }
    memory["entries"].append(entry)
    _save_memory(memory)
    return entry

def _delete_entry(entry_id: str) -> bool:
    memory = _load_memory()
    before = len(memory["entries"])
    memory["entries"] = [e for e in memory["entries"] if e["id"] != entry_id]
    _save_memory(memory)
    return len(memory["entries"]) < before

def _build_overrides(memory: dict[str, Any] | None = None) -> dict[str, Any]:
    memory = memory or _load_memory()
    active_scope = f"project:{config.active_project()}"
    overrides: dict[str, Any] = {"headers": {}, "mark_patterns": {}, "aliases": {}, "excludes": {}}
    for entry in memory.get("entries", []):
        scope = entry.get("scope", "global")
        if scope not in ("global", active_scope):
            continue
        rule = entry.get("rule") or {}
        kind = rule.get("kind")
        category = rule.get("category")
        if kind == "mark_alias" and rule.get("token") and category in CATEGORIES:
            overrides["aliases"][str(rule["token"]).upper()] = {
                "category": category,
                "mark": str(rule.get("maps_to") or rule["token"]).upper(),
                "taught_by": entry["id"],
            }
        elif kind == "mark_pattern" and rule.get("regex") and category in CATEGORIES:
            try:
                re.compile(rule["regex"])
            except re.error:
                continue
            overrides["mark_patterns"].setdefault(category, []).append(rule["regex"])
        elif kind == "category_header" and rule.get("regex") and category in CATEGORIES:
            try:
                re.compile(rule["regex"])
            except re.error:
                continue
            overrides["headers"].setdefault(category, []).append(rule["regex"])
        elif kind == "exclude" and rule.get("token") and category in CATEGORIES:
            overrides["excludes"][str(rule["token"]).upper()] = {
                "category": category, "taught_by": entry["id"],
            }
    return overrides

def _category_from_words(text: str) -> str | None:
    for category, pattern in CATEGORY_WORDS.items():
        if re.search(pattern, text, re.IGNORECASE):
            return category
    return None

def _category_for_mark(mark: str) -> str | None:
    for category, pattern in CATEGORY_MARK_RE.items():
        if category != "wall_type" and pattern.match(mark):
            return category
    return None

def _fallback_parse(message: str) -> tuple[dict[str, Any] | None, str]:
    if _EXCLUDE_RE.search(message):
        tm = re.search(_TOKEN, message)
        if tm:
            token = tm.group(0).upper().replace(" ", "-")
            category = _category_from_words(message) or _category_for_mark(token)
            if category:
                return (
                    {"kind": "exclude", "category": category, "token": token, "maps_to": None, "regex": None},
                    f"Got it — {token} will be excluded from extraction and comparison. Re-run Extract to apply.",
                )
    m = ALIAS_RE.search(message)
    if m:
        token = m.group(1).upper().replace(" ", "-")
        target = m.group(2).upper().replace(" ", "-")
        category = _category_from_words(message) or _category_for_mark(target)
        if category:
            return (
                {"kind": "mark_alias", "category": category, "token": token, "maps_to": target, "regex": None},
                f"Got it — in this PDF, {token} means {category.replace('_', ' ')} {target}. Saved to memory; re-run Extract to apply.",
            )
    m = IS_CATEGORY_RE.search(message)
    if m:
        token = m.group(1).upper().replace(" ", "-")
        category = _category_from_words(m.group(2))
        if category:
            return (
                {"kind": "mark_alias", "category": category, "token": token, "maps_to": token, "regex": None},
                f"Got it — {token} is a {category.replace('_', ' ')} mark for this client. Saved to memory; re-run Extract to apply.",
            )
    return (
        {"kind": "note", "category": None, "token": None, "maps_to": None, "regex": None},
        "Saved as a note. I couldn't turn that into an extraction rule (try e.g. 'HD3 means H3' or 'TD-1 is a holdown'), so it won't change extraction — but I'll remember it.",
    )

def _llm_parse(message: str) -> tuple[dict[str, Any] | None, str, bool]:
    result = openrouter.call_llm(
        system_prompt=LLM_SYSTEM_PROMPT,
        user_prompt=message,
        purpose="teach.rule_extraction",
    )
    content = (result or {}).get("content") or ""
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not result.get("ok") or not match:
        return None, "", False
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None, "", False
    if parsed.get("question"):
        return None, str(parsed["question"]), True
    kind = parsed.get("kind")
    if kind not in RULE_KINDS:
        return None, "", False
    rule = {
        "kind": kind,
        "category": parsed.get("category") if parsed.get("category") in CATEGORIES else None,
        "token": str(parsed["token"]).upper() if parsed.get("token") else None,
        "maps_to": str(parsed["maps_to"]).upper() if parsed.get("maps_to") else None,
        "regex": parsed.get("regex"),
    }
    if kind != "note" and rule["category"] is None:
        return None, "", False
    reply = parsed.get("reply") or "Got it — saved to memory; re-run Extract to apply."
    return rule, reply, False

def _teach_internal(message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    message = (message or "").strip()
    if not message:
        return {"reply": "Tell me a convention, e.g. 'HD3 means H3'.", "entry": None, "needs_clarification": True}
    rule = reply = None
    if config.OPENROUTER_API_KEY:
        rule, reply, needs_clarification = _llm_parse(message)
        if needs_clarification:
            return {"reply": reply, "entry": None, "needs_clarification": True}
    if rule is None:
        rule, reply = _fallback_parse(message)
    entry = _add_entry(message, rule, reply)
    return {"reply": reply, "entry": entry, "needs_clarification": False, "memory_count": len(_load_memory()["entries"])}

def _unrecognized_report(element_intelligence: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    global_counts: dict[tuple[str, str], int] = {}
    listed: dict[tuple[str, str], bool] = {}
    for sheet in element_intelligence.get("sheets", []):
        for row in sheet.get("count_consistency", []):
            key = (row["category"], row["mark"])
            global_counts[key] = global_counts.get(key, 0) + row["plan_count"]
            listed[key] = listed.get(key, False) or row["schedule_listed"]
    for sheet in element_intelligence.get("sheets", []):
        sheet_no = sheet.get("sheet_number")
        for row in sheet.get("count_consistency", []):
            key = ("mark", row["category"], row["mark"])
            if not row["schedule_listed"] and row["plan_count"] > 0 and key not in seen:
                seen.add(key)
                items.append({
                    "type": "plan_mark_not_in_schedule", "sheet": sheet_no,
                    "category": row["category"], "mark": row["mark"],
                    "plan_count": row["plan_count"],
                    "hint": f"{row['mark']} appears {row['plan_count']}x on {sheet_no} but is missing from every schedule table.",
                })
    for (category, mark), total in sorted(global_counts.items()):
        if category == "wall_type":
            continue
        if listed[(category, mark)] and total == 0:
            items.append({
                "type": "schedule_mark_zero_plan", "sheet": None,
                "category": category, "mark": mark,
                "hint": f"{mark} is in the schedule but never found on any plan sheet — maybe this client labels it differently?",
            })
    unknown_tables: list[dict[str, Any]] = []
    for sheet in element_intelligence.get("sheets", []):
        sheet_no = sheet.get("sheet_number")
        for table in sheet.get("tables", []):
            if table.get("category") == "unknown":
                key = ("table", table.get("header_text"))
                if key not in seen:
                    seen.add(key)
                    unknown_tables.append({"sheet": sheet_no, "header_text": table.get("header_text")})
    if unknown_tables:
        n = len(unknown_tables)
        items.append({
            "type": "unknown_tables", "sheet": None, "count": n, "tables": unknown_tables,
            "hint": f"{n} schedule table{'s' if n != 1 else ''} not recognized as a category I know — teach me one to have me parse it.",
        })
    return items

# Public API (module-level surface for external callers)
def load_memory() -> dict[str, Any]:
    return _load_memory()

def save_rule(instruction: str, rule: dict[str, Any], reply: str, scope: str = "global") -> dict[str, Any]:
    return _add_entry(instruction, rule, reply, scope)

def build_overrides(memory: dict[str, Any] | None = None) -> dict[str, Any]:
    return _build_overrides(memory)

def apply_on_extract(element_intelligence: dict[str, Any]) -> list[dict[str, Any]]:
    return _unrecognized_report(element_intelligence)

def list_rules() -> list[dict[str, Any]]:
    return _load_memory()["entries"]

def delete_rule(entry_id: str) -> bool:
    return _delete_entry(entry_id)



# Cap the tool loop so a confused model can never spin forever (production-plan
# §5: "cap the loop, e.g. 6 tool rounds").
MAX_TOOL_ROUNDS = 6

# run_pipeline_step is whitelisted to non-destructive recompute steps only.
PIPELINE_WHITELIST = ("extract", "match", "compare")

LLM = Callable[[list[dict[str, Any]], list[dict[str, Any]] | None], dict[str, Any]]


class ChatUnavailable(RuntimeError):
    """Raised when the LLM cannot be reached (e.g. no OPENROUTER_API_KEY)."""


SYSTEM_PROMPT = (
    "You are the QA-QC copilot for a structural drawing review app. You answer "
    "questions about the compared PDF-vs-Revit element inventory and you ACT on "
    "the UI through tools. Use the tools to fetch real data — never invent counts "
    "or statuses. Categories are: holdown, shear_wall, post, steel_column, "
    "wall_type. Statuses include MATCH, LOCATION_MISMATCH, PDF_ONLY, REVIT_ONLY, "
    "SPEC_ONLY, NO_REVIT_DATA, NOT_EVALUATED. Tool results are rendered as visual "
    "blocks (count cards, tables, status breakdowns) and UI actions (highlighting "
    "an element, filtering the list, opening the table) automatically — so keep "
    "your final reply short and human, and do NOT paste raw JSON. When the user "
    "asks 'how many X', call get_counts and query_elements(category=X). When they "
    "point at a specific element, call focus_element so every pane flies to it. "
    "To record a client's non-standard drawing convention (e.g. 'HD3 means H3'), "
    "or to exclude a mark entirely ('ignore H6'), call save_teach_rule."
)

# ---------------------------------------------------------------------------
# OpenAI-style tool schemas
# ---------------------------------------------------------------------------
TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_counts",
            "description": "Total element count plus breakdowns by status and by category.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_elements",
            "description": "List elements filtered by any of status, category, sheet, mark.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "category": {"type": "string"},
                    "sheet": {"type": "string"},
                    "mark": {"type": "string"},
                    "limit": {"type": "integer", "default": 25},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_device",
            "description": "The physical-device registry block for a mark or device id.",
            "parameters": {
                "type": "object",
                "properties": {"mark_or_id": {"type": "string"}},
                "required": ["mark_or_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_run_comparison",
            "description": "Baseline run vs current run, totals by status.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_workflow_state",
            "description": "Current benchmark-autopilot workflow state.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_pipeline_step",
            "description": "Re-run a non-destructive pipeline step: extract, match or compare.",
            "parameters": {
                "type": "object",
                "properties": {"step": {"type": "string", "enum": list(PIPELINE_WHITELIST)}},
                "required": ["step"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_teach_rule",
            "description": "Teach the extractor a client convention, e.g. 'HD3 means H3'.",
            "parameters": {
                "type": "object",
                "properties": {"instruction": {"type": "string"}},
                "required": ["instruction"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "focus_element",
            "description": "Highlight one element across every pane (returns a select ui_action).",
            "parameters": {
                "type": "object",
                "properties": {"element_id": {"type": "string"}},
                "required": ["element_id"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Artifact reads (graceful — the chatbot narrates missing data, never 409s)
# ---------------------------------------------------------------------------
def _load(key: str) -> dict[str, Any] | None:
    path = config.artifact_path(key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _elements() -> list[dict[str, Any]]:
    return (_load("element_list") or {}).get("elements", [])


_ROW_COLS = ("mark", "category", "sheet", "status", "distance_ft")


def _row_view(e: dict[str, Any]) -> dict[str, Any]:
    return {c: e.get(c) for c in _ROW_COLS} | {"id": e.get("id")}


# ---------------------------------------------------------------------------
# Tool implementations. Each returns {"data": <json for the LLM>, optional
# "blocks": [...], "ui_actions": [...]}.
# ---------------------------------------------------------------------------
def _tool_get_counts(**_: Any) -> dict[str, Any]:
    counts = (_load("element_list") or {}).get("counts") or {}
    if not counts:
        return {"data": {"error": "No element list yet — run the pipeline first."}}
    by_status = counts.get("by_status", {})
    return {
        "data": {"total": counts.get("total", 0), "by_status": by_status,
                 "by_category": counts.get("by_category", {})},
        "blocks": [
            {"type": "count_card", "label": "Elements",
             "total": counts.get("total", 0), "by_category": counts.get("by_category", {})},
            {"type": "status_breakdown", "by_status": by_status},
        ],
    }


def _tool_query_elements(status: str | None = None, category: str | None = None,
                         sheet: str | None = None, mark: str | None = None,
                         limit: int = 25, **_: Any) -> dict[str, Any]:
    def keep(e: dict[str, Any]) -> bool:
        if status and e.get("status") != status:
            return False
        if category and e.get("category") != category:
            return False
        if sheet and (e.get("sheet") or "") != sheet:
            return False
        if mark and (e.get("mark") or "").upper() != mark.upper():
            return False
        return True

    hits = [e for e in _elements() if keep(e)]
    try:
        limit = max(1, min(int(limit or 25), 100))
    except (TypeError, ValueError):
        limit = 25
    shown = [_row_view(e) for e in hits[:limit]]
    block = {"type": "table", "title": "Matching elements",
             "columns": list(_ROW_COLS), "rows": shown,
             "total": len(hits), "shown": len(shown)}
    ui_actions: list[dict[str, Any]] = []
    filters: dict[str, str] = {}
    if status:
        filters["status"] = status
    if sheet:
        filters["sheet"] = sheet
    if mark or category:
        filters["search"] = mark or category or ""
    if filters:
        ui_actions.append({"type": "filter", "filters": filters})
        ui_actions.append({"type": "open_panel", "panel": "table"})
    return {"data": {"total": len(hits), "rows": shown}, "blocks": [block],
            "ui_actions": ui_actions}


def _tool_get_device(mark_or_id: str | None = None, **_: Any) -> dict[str, Any]:
    key = str(mark_or_id or "").strip()
    reg = _load("device_registry") or {}
    for cat in reg.get("categories", {}).values():
        for d in cat.get("devices", []):
            if d.get("id") == key or (d.get("mark") or "").upper() == key.upper():
                fields = ("id", "mark", "status", "distance_ft", "sheets",
                          "appearances", "reason")
                return {
                    "data": {k: d.get(k) for k in fields},
                    "blocks": [{
                        "type": "table", "title": f"Device {d.get('id')}",
                        "columns": ["field", "value"],
                        "rows": [{"field": k, "value": d.get(k)} for k in fields],
                    }],
                }
    return {"data": {"error": f"No device matching '{key}'."}}


def _tool_get_run_comparison(**_: Any) -> dict[str, Any]:
    base_path = config.ARTIFACT_DIR / "run_baseline.json"
    if not base_path.exists():
        return {"data": {"error": "No saved baseline — save one from the Runs drawer first."}}
    baseline = json.loads(base_path.read_text(encoding="utf-8"))

    def totals(rows: list[dict[str, Any]]) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in rows:
            st = r.get("status") or "?"
            out[st] = out.get(st, 0) + 1
        return out

    base_tot = totals(baseline.get("rows", []))
    cur_tot = totals(_elements())
    statuses = sorted(set(base_tot) | set(cur_tot))
    rows = [{"status": s, "baseline": base_tot.get(s, 0), "current": cur_tot.get(s, 0),
             "delta": cur_tot.get(s, 0) - base_tot.get(s, 0)} for s in statuses]
    return {
        "data": {"baseline_label": baseline.get("label"), "rows": rows},
        "blocks": [{"type": "table", "title": "Baseline vs current run",
                    "columns": ["status", "baseline", "current", "delta"], "rows": rows}],
    }


def _tool_get_workflow_state(**_: Any) -> dict[str, Any]:
    from . import benchmark_workflow

    wf = benchmark_workflow.load()
    history = wf.get("history") or []
    return {"data": {"state": wf.get("state", "idle"),
                     "updated_at": wf.get("updated_at"),
                     "last_note": (history[-1].get("note") if history else None)}}


def _audit_pipeline(step: str) -> None:
    path = config.ARTIFACT_DIR / "chat_pipeline_audit.json"
    log: list[dict[str, Any]] = []
    if path.exists():
        try:
            log = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log = []
    log.append({"ts": datetime.now(timezone.utc).isoformat(), "step": step,
                "actor": "chat_agent"})
    path.write_text(json.dumps(log, indent=2), encoding="utf-8")


def _tool_run_pipeline_step(step: str | None = None, **_: Any) -> dict[str, Any]:
    step = str(step or "").strip().lower()
    if step not in PIPELINE_WHITELIST:
        return {"data": {"error": f"Step '{step}' is not runnable. "
                                  f"Allowed: {list(PIPELINE_WHITELIST)}."}}
    _audit_pipeline(step)
    from .routers import pipeline

    fn = {"extract": pipeline.elements_extract,
          "match": pipeline.elements_match,
          "compare": pipeline.compare_ai}[step]
    try:
        resp = fn()
    except HTTPException as exc:
        return {"data": {"error": f"{step} could not run: {exc.detail}"}}
    body = json.loads(bytes(resp.body).decode("utf-8"))
    return {"data": {"step": step, "counts": body.get("counts"),
                     "summary": body.get("summary")}}



def _tool_save_teach_rule(instruction: str | None = None, **_: Any) -> dict[str, Any]:
    res = _teach_internal(str(instruction or ""))
    entry = res.get("entry")
    return {"data": {"reply": res.get("reply"), "saved": bool(entry), "rule_id": (entry or {}).get("id"), "needs_clarification": res.get("needs_clarification", False)}}


def _tool_focus_element(element_id: str | None = None, **_: Any) -> dict[str, Any]:
    eid = str(element_id or "")
    found = next((e for e in _elements() if e.get("id") == eid), None)
    if not found:
        return {"data": {"error": f"No element with id '{eid}'."}}
    return {
        "data": {"selected": eid, "mark": found.get("mark"),
                 "category": found.get("category"),
                 "status": found.get("status")},
        "ui_actions": [{
            "type": "select",
            "element_id": eid,
        }],
    }


TOOL_IMPLS: dict[str, Callable[..., dict[str, Any]]] = {
    "get_counts": _tool_get_counts,
    "query_elements": _tool_query_elements,
    "get_device": _tool_get_device,
    "get_run_comparison": _tool_get_run_comparison,
    "get_workflow_state": _tool_get_workflow_state,
    "run_pipeline_step": _tool_run_pipeline_step,
    "save_teach_rule": _tool_save_teach_rule,
    "focus_element": _tool_focus_element,
}


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------
def _default_llm(messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]] | None) -> dict[str, Any]:
    res = openrouter.call_chat(messages=messages, tools=tools, purpose="chat_agent")
    if not res.get("ok"):
        raise ChatUnavailable(res.get("error") or "The assistant is not configured.")
    return res["message"]


# ---------------------------------------------------------------------------
# Leaked tool-call markup: some OpenRouter models emit tool calls as PLAIN TEXT
# (Anthropic-style <invoke> XML and/or DeepSeek DSML <｜tool…｜> bar delimiters)
# instead of a structured tool_calls array. We parse what we can and always
# scrub the raw markup so it never reaches the user.
# ---------------------------------------------------------------------------
_INVOKE_RE = re.compile(r'<invoke\s+name="([^"]+)"\s*>(.*?)</invoke>', re.DOTALL | re.IGNORECASE)
_PARAM_RE = re.compile(r'<parameter\s+name="([^"]+)"\s*>(.*?)</parameter>', re.DOTALL | re.IGNORECASE)
# Fullwidth (｜ U+FF5C) or ASCII (|) bar-delimited DSML tokens naming tool/invoke/
# dsml/function, plus any stray invoke/parameter/function_calls/tool_call tags.
_LEAK_TOKEN_RE = re.compile(
    r"<[｜|][^>]*?(?:tool|invoke|dsml|function)[^>]*?[｜|]>"
    r"|</?(?:antml:)?(?:invoke|parameter|function_calls|tool_calls?)\b[^>]*>",
    re.IGNORECASE,
)


def _leaked_tool_calls(content: str) -> tuple[str, list[tuple[str, dict[str, Any]]]]:
    """(scrubbed_text, [(tool_name, args)]) from leaked textual tool-call markup.
    Parses Anthropic-style <invoke>/<parameter> pairs where present; always
    strips DSML bar tokens and orphaned fenced-json arg blobs."""
    content = content or ""
    calls: list[tuple[str, dict[str, Any]]] = []
    for name, body in _INVOKE_RE.findall(content):
        args = {p.strip(): v.strip() for p, v in _PARAM_RE.findall(body)}
        calls.append((name.strip(), args))
    clean = _INVOKE_RE.sub("", content)
    clean = _LEAK_TOKEN_RE.sub("", clean)
    clean = re.sub(r"```(?:json)?\s*\{.*?\}\s*```", "", clean, flags=re.DOTALL)
    return clean.strip(), calls


def _assistant_msg(msg: dict[str, Any]) -> dict[str, Any]:
    """Rebuild the assistant turn to feed back to the API (tool_calls kept)."""
    out: dict[str, Any] = {"role": "assistant", "content": msg.get("content") or ""}
    if msg.get("tool_calls"):
        out["tool_calls"] = msg["tool_calls"]
    return out


def run_chat(message: str, history: list[dict[str, Any]] | None = None, *,
             llm: LLM | None = None) -> dict[str, Any]:
    """One chat turn: user msg -> LLM(tools) -> execute tools -> feed back ->
    final answer. Returns {reply, blocks, ui_actions}."""
    llm = llm or _default_llm
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in history or []:
        role, content = h.get("role"), h.get("content")
        if role in ("user", "assistant") and isinstance(content, str):
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": str(message or "")})

    blocks: list[dict[str, Any]] = []
    ui_actions: list[dict[str, Any]] = []
    reply = ""

    for _ in range(MAX_TOOL_ROUNDS):
        msg = llm(messages, TOOLS)
        calls = msg.get("tool_calls") or []
        if not calls:
            # No structured calls — check for leaked textual tool-call markup and
            # synthesize real calls for any parsed name we implement.
            clean, leaked = _leaked_tool_calls(msg.get("content") or "")
            synth = [(n, a) for n, a in leaked if n in TOOL_IMPLS]
            if not synth:
                messages.append(_assistant_msg(msg))
                reply = clean  # scrubbed even when nothing was parseable
                break
            calls = [
                {"id": f"leak_{i}", "type": "function",
                 "function": {"name": n, "arguments": json.dumps(a)}}
                for i, (n, a) in enumerate(synth)
            ]
            msg = {"role": "assistant", "content": clean, "tool_calls": calls}
        messages.append(_assistant_msg(msg))
        for call in calls:
            fn = call.get("function") or {}
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            impl = TOOL_IMPLS.get(name)
            out = impl(**args) if impl else {"data": {"error": f"Unknown tool '{name}'."}}
            blocks.extend(out.get("blocks") or [])
            ui_actions.extend(out.get("ui_actions") or [])
            messages.append({"role": "tool", "tool_call_id": call.get("id"),
                             "name": name, "content": json.dumps(out.get("data"))})
    else:
        # Round cap hit while still calling tools — force a plain-text wrap-up.
        final = llm(messages, None)
        reply = (final.get("content") or "").strip()

    reply, _ = _leaked_tool_calls(reply)  # last line of defense: never leak markup
    return {"reply": reply or "Done.", "blocks": blocks, "ui_actions": ui_actions}
