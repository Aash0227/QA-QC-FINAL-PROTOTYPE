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
from . import teach
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
    "You are the QBC QA/QC Agent. You help a structural QA/QC engineer verify "
    "that a Revit model matches the structural drawings, and you act on the UI "
    "through tools. "
    "THE VERDICTS a reviewer sees are LOCATION_MATCH (drawing and model agree "
    "on where this element is), LOCATION_MISMATCH (an established discrepancy: "
    "wrong place, wrong mark, drawn-but-not-modelled, or modelled-but-not-"
    "drawn), NEEDS_REVIEW (the engine tried and could not settle it, usually "
    "two candidates it refused to guess between), and NOT_APPLICABLE (out of "
    "scope: the model export never included that category, so no verdict is "
    "possible). Categories: holdown, shear_wall, post, steel_column, wall_type. "
    "HOW TO ANSWER: never invent counts, statuses, distances or element ids. "
    "Always call a tool and answer from what it returns. When the user asks WHY "
    "a result is what it is, call explain_element: it returns the actual "
    "evidence, the Revit element chosen, the distance, which evidence channel "
    "decided it, candidates that were ruled out, and the registration quality "
    "that gated the decision. When they ask what happened during the run, call "
    "get_pipeline_story. For how many X, call get_counts and "
    "query_elements(category=X). When they point at a specific element, call "
    "focus_element so every pane flies to it. To record a client non-standard "
    "drawing convention (HD3 means H3) or to exclude a mark (ignore H6), call "
    "save_teach_rule. "
    "STYLE: lead with the answer in one sentence, in plain engineering language "
    "a QA reviewer would use. Add detail only when it helps them act: which "
    "sheet to open, which element to check, what to look for. Tool results "
    "render as visual blocks and UI actions automatically, so keep the reply "
    "short and never paste raw JSON. If the evidence genuinely does not settle "
    "something, say so plainly and say what would settle it; never manufacture "
    "confidence."
)


# ---------------------------------------------------------------------------
# Teach-the-AI public API (delegates to teach module — no duplication)
# ---------------------------------------------------------------------------
SCHEMA_VERSION = teach.SCHEMA_VERSION
RULE_KINDS = teach.RULE_KINDS
CATEGORIES = teach.CATEGORIES


def load_memory() -> dict[str, Any]:
    return teach.load_memory()


def save_rule(instruction: str, rule: dict[str, Any], reply: str, scope: str = "global") -> dict[str, Any]:
    return teach.add_entry(instruction, rule, reply, scope)


def build_overrides(memory: dict[str, Any] | None = None) -> dict[str, Any]:
    return teach.build_overrides(memory)


def apply_on_extract(element_intelligence: dict[str, Any]) -> list[dict[str, Any]]:
    return teach.unrecognized_report(element_intelligence)


def list_rules() -> list[dict[str, Any]]:
    return teach.load_memory()["entries"]


def delete_rule(entry_id: str) -> bool:
    return teach.delete_entry(entry_id)

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
            "name": "explain_element",
            "description": (
                "Full evidence behind ONE element's verdict: why it is "
                "LOCATION_MATCH / LOCATION_MISMATCH / NEEDS_REVIEW, which "
                "Revit element was chosen, the distance, which evidence "
                "channel decided it, competing candidates that were ruled "
                "out, the registration quality that gated it, and any "
                "recorded evidence conflict. Call this whenever the user "
                "asks WHY a result is what it is."),
            "parameters": {"type": "object", "properties": {
                "element_id": {"type": "string",
                               "description": "Element id, or a mark like H2/SW-1."}},
                "required": ["element_id"]},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pipeline_story",
            "description": (
                "What each pipeline stage actually did on this project, in "
                "plain English, from the recorded per-stage summaries. Call "
                "this when the user asks what happened during the run, or "
                "why there is no result yet."),
            "parameters": {"type": "object", "properties": {}},
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
    view = {c: e.get(c) for c in _ROW_COLS} | {"id": e.get("id")}
    # The product verdict is what the reviewer sees on screen, so the agent
    # must reason in the same vocabulary, not only the internal status.
    product = e.get("product") or {}
    if product.get("verdict"):
        view["verdict"] = product["verdict"]
    return view


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
    try:
        baseline = json.loads(base_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"data": {"error": "Saved baseline is corrupt — re-save from the Runs drawer."}}

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
    res = teach.teach(str(instruction or ""))
    entry = res.get("entry")
    return {"data": {"reply": res.get("reply"), "saved": bool(entry), "rule_id": (entry or {}).get("id"), "needs_clarification": res.get("needs_clarification", False)}}


def _tool_explain_element(element_id: str | None = None, **_: Any) -> dict[str, Any]:
    """Everything behind one verdict, assembled from artifacts only.

    The agent must never speculate about why a match happened; this hands it
    the evidence the engine actually recorded, including the candidates it
    refused and the registration that gated the decision."""
    if not element_id:
        return {"data": {"error": "Provide an element id or mark."}}
    rows = _elements()
    needle = str(element_id).strip().lower()
    row = next((e for e in rows if str(e.get("id", "")).lower() == needle), None)
    if row is None:
        hits = [e for e in rows if str(e.get("mark", "")).lower() == needle]
        if not hits:
            return {"data": {"error": f"No element matching {element_id!r}."}}
        if len(hits) > 1:
            return {"data": {
                "ambiguous_reference": element_id,
                "candidates": [_row_view(e) for e in hits[:10]],
                "note": ("That mark covers several elements - ask about a "
                         "specific id from this list.")}}
        row = hits[0]

    product = row.get("product") or {}
    out: dict[str, Any] = {
        "id": row.get("id"),
        "verdict": product.get("verdict"),
        "certain": product.get("is_certain"),
        "in_scope": product.get("in_scope"),
        "evidence": product.get("evidence") or {
            "internal_status": row.get("status"), "reason": row.get("reason")},
    }
    cal = _load("registration") or {}
    quality = cal.get("quality") or {}
    out["registration"] = {
        "source": cal.get("calibration_source"),
        "confidence": quality.get("confidence"),
        "rms_residual_pt": quality.get("solve_rms_residual_pt"),
        "match_allowed": quality.get("match_allowed"),
    }
    for key in ("nearest_revit_candidates", "nearest_pdf_candidates"):
        if row.get(key):
            out.setdefault("rejected_candidates", {})[key] = row[key]
    if row.get("sheet_status") and row.get("sheet_status") != row.get("status"):
        out["per_sheet_status_before_device_pass"] = row["sheet_status"]
    return {"data": out,
            "ui_actions": [{"action": "focus_element", "element_id": row.get("id")}]}


def _tool_get_pipeline_story(**_: Any) -> dict[str, Any]:
    """The recorded per-stage summaries - real text written by the stages."""
    summaries = _load("phase_summaries") or {}
    phases = summaries.get("phases") or summaries
    if not phases:
        return {"data": {"error": "No pipeline summaries recorded yet."}}
    return {"data": {"stages": phases}}


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
    "explain_element": _tool_explain_element,
    "get_pipeline_story": _tool_get_pipeline_story,
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
        try:
            msg = llm(messages, TOOLS)
        except ChatUnavailable:
            raise
        except Exception as exc:
            raise ChatUnavailable(f"LLM call failed: {exc}") from exc
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
            if impl:
                try:
                    out = impl(**args)
                except Exception as exc:
                    out = {"data": {"error": f"Tool '{name}' raised: {exc}"}}
            else:
                out = {"data": {"error": f"Unknown tool '{name}'."}}
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