"""chat_agent tool loop, whitelist, ui_action shape, and teach write-through —
all against a FAKED OpenRouter (no network). Mirrors test_teach.py's fixture."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import chat_agent, config, teach


@pytest.fixture(autouse=True)
def tmp_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(config, "ARTIFACT_DIR", tmp_path)
    monkeypatch.setattr(config, "MEMORY_DIR", tmp_path / "memory")
    monkeypatch.setattr(config, "ACTIVE_PROJECT_FILE", tmp_path / "active_project.json")
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "")  # force teach fallback path
    return tmp_path


def _write_element_list(tmp: Path) -> None:
    data = {
        "counts": {"total": 2, "by_status": {"MATCH": 1, "PDF_ONLY": 1},
                   "by_category": {"holdown": 2}},
        "elements": [
            {"id": "s1_h1", "mark": "H1", "category": "holdown", "sheet": "S-201",
             "status": "MATCH", "distance_ft": 0.1},
            {"id": "s1_h2", "mark": "H2", "category": "holdown", "sheet": "S-201",
             "status": "PDF_ONLY", "distance_ft": None},
        ],
    }
    (tmp / config.ARTIFACT_FILES["element_list"]).write_text(json.dumps(data), encoding="utf-8")


def _tool_call(call_id: str, name: str, args: dict) -> dict:
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": call_id, "type": "function",
         "function": {"name": name, "arguments": json.dumps(args)}}]}


class ScriptedLLM:
    """Replays a queued list of assistant messages; records how it was called."""

    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[int, bool]] = []  # (msg_count, tools_present)

    def __call__(self, messages, tools):
        self.calls.append((len(messages), tools is not None))
        return self._responses.pop(0)


def test_tool_loop_executes_tools_then_terminates(tmp_artifacts: Path) -> None:
    _write_element_list(tmp_artifacts)
    llm = ScriptedLLM([
        _tool_call("c1", "get_counts", {}),
        {"role": "assistant", "content": "There are 2 holdowns."},
    ])
    out = chat_agent.run_chat("how many holdowns?", llm=llm)
    assert out["reply"] == "There are 2 holdowns."
    # get_counts emits a count_card + a status_breakdown block.
    types = {b["type"] for b in out["blocks"]}
    assert {"count_card", "status_breakdown"} <= types
    card = next(b for b in out["blocks"] if b["type"] == "count_card")
    assert card["total"] == 2
    assert len(llm.calls) == 2  # tool round, then final answer — no infinite loop


def test_focus_element_returns_select_ui_action(tmp_artifacts: Path) -> None:
    _write_element_list(tmp_artifacts)
    llm = ScriptedLLM([
        _tool_call("c1", "focus_element", {"element_id": "s1_h2"}),
        {"role": "assistant", "content": "Highlighted H2."},
    ])
    out = chat_agent.run_chat("show me H2", llm=llm)
    assert out["ui_actions"] == [{"type": "select", "element_id": "s1_h2"}]


def test_query_elements_filters_and_opens_table(tmp_artifacts: Path) -> None:
    _write_element_list(tmp_artifacts)
    llm = ScriptedLLM([
        _tool_call("c1", "query_elements", {"status": "PDF_ONLY"}),
        {"role": "assistant", "content": "One PDF-only element."},
    ])
    out = chat_agent.run_chat("what's PDF only?", llm=llm)
    table = next(b for b in out["blocks"] if b["type"] == "table")
    assert table["total"] == 1 and table["rows"][0]["mark"] == "H2"
    action_types = [a["type"] for a in out["ui_actions"]]
    assert "filter" in action_types and "open_panel" in action_types


def test_run_pipeline_step_whitelist_rejects_non_whitelisted() -> None:
    out = chat_agent._tool_run_pipeline_step(step="delete")
    assert "not runnable" in out["data"]["error"]
    # A whitelisted-but-artifactless step fails gracefully, never raises.
    safe = chat_agent._tool_run_pipeline_step(step="match")
    assert "error" in safe["data"]
    # Whitelist is exactly the three non-destructive recompute steps.
    assert chat_agent.PIPELINE_WHITELIST == ("extract", "match", "compare")


def test_save_teach_rule_writes_through_store() -> None:
    out = chat_agent._tool_save_teach_rule(instruction="in this pdf HD3 means H3")
    assert out["data"]["saved"] is True
    entries = teach.load_memory()["entries"]
    assert len(entries) == 1
    assert entries[0]["rule"] == {
        "kind": "mark_alias", "category": "holdown", "token": "HD3",
        "maps_to": "H3", "regex": None}


# A leaked DSML block: fullwidth (｜) bar tokens wrapping an Anthropic-style
# <invoke> tool call, as some OpenRouter models emit instead of tool_calls.
_LEAKED_RUN = (
    "<｜tool▁calls▁begin｜><｜tool▁call▁begin｜>function<｜tool▁sep｜>run_pipeline_step\n"
    '<invoke name="run_pipeline_step"><parameter name="step">extract</parameter></invoke>\n'
    "<｜tool▁call▁end｜><｜tool▁calls▁end｜>"
)


def test_leaked_tool_call_block_executes_and_is_scrubbed(tmp_artifacts: Path) -> None:
    _write_element_list(tmp_artifacts)
    llm = ScriptedLLM([
        {"role": "assistant", "content": _LEAKED_RUN},   # leaked, no structured calls
        {"role": "assistant", "content": "Extraction re-run."},
    ])
    out = chat_agent.run_chat("re-extract please", llm=llm)
    # The tool actually executed: run_pipeline_step audits the step before running.
    audit = json.loads((tmp_artifacts / "chat_pipeline_audit.json").read_text("utf-8"))
    assert any(e["step"] == "extract" for e in audit)
    # Final reply carries no delimiter tokens or invoke markup.
    assert out["reply"] == "Extraction re-run."
    for junk in ("｜", "tool▁calls", "<invoke", "<parameter"):
        assert junk not in out["reply"]


def test_unparseable_leaked_block_is_stripped_from_reply(tmp_artifacts: Path) -> None:
    leaked = "<｜tool▁calls▁begin｜>garbled unparseable blob<｜tool▁calls▁end｜> Here is the answer."
    llm = ScriptedLLM([{"role": "assistant", "content": leaked}])
    out = chat_agent.run_chat("hello", llm=llm)
    assert out["reply"]  # not empty
    assert "｜" not in out["reply"] and "tool▁calls" not in out["reply"]
    assert "Here is the answer." in out["reply"]


def test_loop_cap_forces_plain_answer(tmp_artifacts: Path) -> None:
    _write_element_list(tmp_artifacts)
    # Always ask for a tool → the cap must kick in and force a no-tools wrap-up.
    responses = [_tool_call(f"c{i}", "get_counts", {})
                 for i in range(chat_agent.MAX_TOOL_ROUNDS)]
    responses.append({"role": "assistant", "content": "Wrapped up."})
    llm = ScriptedLLM(responses)
    out = chat_agent.run_chat("loop forever", llm=llm)
    assert out["reply"] == "Wrapped up."
    # MAX_TOOL_ROUNDS tool calls (all with tools) + 1 final call with tools=None.
    assert len(llm.calls) == chat_agent.MAX_TOOL_ROUNDS + 1
    assert llm.calls[-1][1] is False
