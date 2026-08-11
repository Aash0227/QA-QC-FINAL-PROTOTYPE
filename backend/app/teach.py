"""Teach-the-AI memory: humans explain non-standard drawing conventions,
rules persist to ai_teach_memory.json, and the NEXT extraction run applies
them (element_detector/schedule_tables consume build_overrides()).

Client PDFs are not standardized — one client writes "HD3" where the schedule
vocabulary says "H3", another titles a table "TIE-DOWN SCHEDULE". Rules:

  mark_alias      TOKEN on the plan means an existing mark (HD3 -> holdown H3)
  mark_pattern    extra regex that classifies plan tokens into a category
  category_header extra regex that classifies a schedule table's header
  exclude         TOKEN is dropped entirely from extraction (plan + schedule)
  note            free text; honest no-op for extraction (still remembered)

Teaching NEVER fabricates matches: rules only change extraction/classification.
MATCH still requires verified registration + the distance gates.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from . import config, openrouter
from .schedule_tables import CATEGORY_MARK_RE

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
    rf"[\"']?({_TOKEN})[\"']?\s+(?:means|is the same as|maps? to|equals|=|is)\s+[\"']?({_TOKEN})[\"']?",
    re.IGNORECASE,
)
IS_CATEGORY_RE = re.compile(
    rf"[\"']?({_TOKEN})[\"']?(?:\s+marks?)?\s+(?:is|are|denotes?|represents?)\s+(?:a |an |the )?([a-z][a-z -]+)",
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


# ---------------------------------------------------------------------------
# Memory store
# ---------------------------------------------------------------------------
def load_memory() -> dict[str, Any]:
    path = config.memory_path()
    if not path.exists():
        # One-time migration from the old per-project artifact.
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


def add_entry(
    instruction: str, rule: dict[str, Any], reply: str, scope: str = "global"
) -> dict[str, Any]:
    # Validate regex fields at add-time so bad patterns are rejected immediately
    # rather than silently skipped later in build_overrides().
    if rule and rule.get("regex"):
        try:
            re.compile(rule["regex"])
        except re.error as exc:
            raise ValueError(f"Invalid regex in rule: {exc}") from exc
    memory = load_memory()
    # max+1, not len+1: after a delete, len+1 re-issues an existing id and a
    # later delete-by-id would then remove two unrelated rules at once.
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


def delete_entry(entry_id: str) -> bool:
    memory = load_memory()
    before = len(memory["entries"])
    memory["entries"] = [e for e in memory["entries"] if e["id"] != entry_id]
    _save_memory(memory)
    return len(memory["entries"]) < before


# ---------------------------------------------------------------------------
# Overrides consumed by the extraction pipeline
# ---------------------------------------------------------------------------
def build_overrides(memory: dict[str, Any] | None = None) -> dict[str, Any]:
    memory = memory or load_memory()
    active_scope = f"project:{config.active_project()}"
    overrides: dict[str, Any] = {"headers": {}, "mark_patterns": {}, "aliases": {},
                                 "excludes": {}}
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


# ---------------------------------------------------------------------------
# Teaching conversation
# ---------------------------------------------------------------------------
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


_EXCLUDE_RE = re.compile(
    r"\b(?:ignore|exclude|skip|drop|omit)\b|\b(?:don'?t|do not)\s+(?:extract|include|use|count)\b",
    re.IGNORECASE,
)


def _fallback_parse(message: str) -> tuple[dict[str, Any] | None, str]:
    """Deterministic NLU when the LLM is unavailable. Reduced but honest."""
    if _EXCLUDE_RE.search(message):
        tm = re.search(_TOKEN, message)
        if tm:
            token = tm.group(0).upper().replace(" ", "-")
            category = _category_from_words(message) or _category_for_mark(token)
            if category:
                return (
                    {"kind": "exclude", "category": category, "token": token,
                     "maps_to": None, "regex": None},
                    f"Got it — {token} will be excluded from extraction and "
                    "comparison. Re-run Extract to apply.",
                )
    m = ALIAS_RE.search(message)
    if m:
        token, target = m.group(1).upper().replace(" ", "-"), m.group(2).upper().replace(" ", "-")
        category = _category_from_words(message) or _category_for_mark(target)
        if category:
            return (
                {"kind": "mark_alias", "category": category, "token": token,
                 "maps_to": target, "regex": None},
                f"Got it — in this PDF, {token} means {category.replace('_', ' ')} "
                f"{target}. Saved to memory; re-run Extract to apply.",
            )
    m = IS_CATEGORY_RE.search(message)
    if m:
        token = m.group(1).upper().replace(" ", "-")
        category = _category_from_words(m.group(2))
        if category:
            return (
                {"kind": "mark_alias", "category": category, "token": token,
                 "maps_to": token, "regex": None},
                f"Got it — {token} is a {category.replace('_', ' ')} mark for this "
                "client. Saved to memory; re-run Extract to apply.",
            )
    return (
        {"kind": "note", "category": None, "token": None, "maps_to": None, "regex": None},
        "Saved as a note. I couldn't turn that into an extraction rule "
        "(try e.g. 'HD3 means H3' or 'TD-1 is a holdown'), so it won't change "
        "extraction — but I'll remember it.",
    )


def _llm_parse(message: str) -> tuple[dict[str, Any] | None, str, bool]:
    """(rule, reply, needs_clarification) via OpenRouter. rule None => question."""
    result = openrouter.call_llm(
        system_prompt=LLM_SYSTEM_PROMPT,
        user_prompt=message,
        purpose="teach.rule_extraction",
    )
    content = (result or {}).get("content") or ""
    match = re.search(r"\{.*?\}", content, re.DOTALL)
    if not result.get("ok") or not match:
        return None, "", False  # signal caller to use fallback
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
        "token": (str(parsed["token"]).upper() if parsed.get("token") else None),
        "maps_to": (str(parsed["maps_to"]).upper() if parsed.get("maps_to") else None),
        "regex": parsed.get("regex"),
    }
    if kind != "note" and rule["category"] is None:
        return None, "", False
    reply = parsed.get("reply") or "Got it — saved to memory; re-run Extract to apply."
    return rule, reply, False


def teach(message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """One chat turn: parse instruction -> save rule -> confirm."""
    message = (message or "").strip()
    if not message:
        return {"reply": "Tell me a convention, e.g. 'HD3 means H3'.", "entry": None,
                "needs_clarification": True}
    rule = reply = None
    if config.OPENROUTER_API_KEY:
        rule, reply, needs_clarification = _llm_parse(message)
        if needs_clarification:
            return {"reply": reply, "entry": None, "needs_clarification": True}
    if rule is None:
        rule, reply = _fallback_parse(message)
    try:
        entry = add_entry(message, rule, reply)
    except ValueError as exc:
        # Bad regex from LLM — fall back to a note so the user still gets a reply
        rule = {"kind": "note", "category": None, "token": None, "maps_to": None, "regex": None}
        reply = f"Saved as a note (couldn't store as a rule: {exc})"
        entry = add_entry(message, rule, reply)
    return {"reply": reply, "entry": entry, "needs_clarification": False,
            "memory_count": len(load_memory()["entries"])}


# ---------------------------------------------------------------------------
# What should the AI proactively ask about?
# ---------------------------------------------------------------------------
def unrecognized_report(element_intelligence: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    # Aggregate plan counts across ALL sheets first — "H1 missing on the
    # general-notes sheet" is noise; "P-9 missing on EVERY sheet" is signal.
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
                    "hint": f"{row['mark']} appears {row['plan_count']}x on {sheet_no} "
                            "but is missing from every schedule table.",
                })
    for (category, mark), total in sorted(global_counts.items()):
        if category == "wall_type":
            continue  # wall types are spec rows, never plan callouts
        if listed[(category, mark)] and total == 0:
            items.append({
                "type": "schedule_mark_zero_plan", "sheet": None,
                "category": category, "mark": mark,
                "hint": f"{mark} is in the schedule but never found on any plan "
                        "sheet — maybe this client labels it differently?",
            })
    # BUG-10: aggregate unknown-table notices into ONE dismissible item so the
    # real teach rules aren't buried under 20+ repetitive cards.
    unknown_tables: list[dict[str, Any]] = []
    for sheet in element_intelligence.get("sheets", []):
        sheet_no = sheet.get("sheet_number")
        for table in sheet.get("tables", []):
            if table.get("category") == "unknown":
                key = ("table", table.get("header_text"))
                if key not in seen:
                    seen.add(key)
                    unknown_tables.append(
                        {"sheet": sheet_no, "header_text": table.get("header_text")}
                    )
    if unknown_tables:
        n = len(unknown_tables)
        items.append({
            "type": "unknown_tables", "sheet": None, "count": n,
            "tables": unknown_tables,
            "hint": f"{n} schedule table{'s' if n != 1 else ''} not recognized as a "
                    "category I know — teach me one to have me parse it.",
        })
    return items


if __name__ == "__main__":
    rule, reply = _fallback_parse("in this pdf HD3 means H3")
    assert rule["kind"] == "mark_alias" and rule["token"] == "HD3"
    assert rule["maps_to"] == "H3" and rule["category"] == "holdown", rule
    rule2, _ = _fallback_parse("TD-1 is a holdown")
    assert rule2 == {"kind": "mark_alias", "category": "holdown", "token": "TD-1",
                     "maps_to": "TD-1", "regex": None}, rule2
    rule3, _ = _fallback_parse("the weather is nice")
    assert rule3["kind"] == "note"
    rule_ex, reply_ex = _fallback_parse("exclude H6 holdowns, they are dummy placements")
    assert rule_ex == {"kind": "exclude", "category": "holdown", "token": "H6",
                       "maps_to": None, "regex": None}, rule_ex
    assert "excluded" in reply_ex
    ov_ex = build_overrides({"entries": [{"id": "mem_ex", "rule": rule_ex}]})
    assert ov_ex["excludes"]["H6"] == {"category": "holdown", "taught_by": "mem_ex"}, ov_ex
    ov = build_overrides({"entries": [
        {"id": "mem_001", "rule": rule},
        {"id": "mem_002", "rule": {"kind": "category_header", "category": "post",
                                   "regex": r"STUD\s+SCHEDULE"}},
        {"id": "mem_003", "rule": {"kind": "mark_pattern", "category": "holdown",
                                   "regex": "bad(regex"}},
    ]})
    assert ov["aliases"]["HD3"] == {"category": "holdown", "mark": "H3", "taught_by": "mem_001"}
    assert ov["headers"]["post"] == [r"STUD\s+SCHEDULE"]
    assert "holdown" not in ov["mark_patterns"]  # invalid regex rejected
    print("teach self-check OK")
