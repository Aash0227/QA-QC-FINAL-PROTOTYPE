"""One-shot merge script: take the existing chat_agent.py + teach.py content,
produce a new chat_agent.py with teach logic inlined. Also produces the new
thin-shim teach.py. Run once then delete this script.
"""
import pathlib, re

BASE = pathlib.Path(__file__).resolve().parent
chat_path = BASE / "app" / "chat_agent.py"
teach_path = BASE / "app" / "teach.py"

chat_text = chat_path.read_text(encoding="utf-8")
teach_text = teach_path.read_text(encoding="utf-8")

# -----------------------------------------------------------
# 1. Extract the teach logic block (strip the module docstring + imports + __main__)
# -----------------------------------------------------------
# Find the section starting after the imports, up to the __main__ guard.
# teach.py structure:
#   - docstring
#   - from __future__ import
#   - imports (json, re, datetime, typing, config, openrouter, schedule_tables)
#   - constants (SCHEMA_VERSION, RULE_KINDS, CATEGORIES, CATEGORY_WORDS, regexes, LLM_SYSTEM_PROMPT)
#   - functions (load_memory, _save_memory, add_entry, delete_entry,
#                build_overrides, _category_from_words, _category_for_mark,
#                _fallback_parse, _llm_parse, teach, unrecognized_report)
#   - if __name__ == "__main__": block
# We'll extract everything between the first constants block and the __main__ guard.

# Strip the teaching module docstring
strip_start = teach_text.find("from __future__ import")
strip_end = teach_text.find("SCHEMA_VERSION = ")

# The part we want is from SCHEMA_VERSION to the __main__ guard
main_block_start = teach_text.find('\nif __name__ == "__main__":')
teach_body = teach_text[strip_end:main_block_start].rstrip()

# Rename the public teach() to avoid clashing later — actually we want to
# keep it as `teach` because that's what external callers use. But we also
# have _tool_save_teach_rule currently calling teach.teach(...). We'll
# update that reference separately.
# 
# Strategy: keep all names from teach.py unchanged; they become top-level
# in chat_agent.py. The one clashing concern is that chat_agent.py itself
# already has a tool called "save_teach_rule" whose implementation calls
# `teach.teach(...)`. We'll change that to `teach_fn(...)` and later expose
# `teach` as the public name.

# -----------------------------------------------------------
# 2. Modify chat_agent.py
# -----------------------------------------------------------

# 2a. Replace the import line: "from . import config, openrouter, teach" -> drop teach
chat_text = chat_text.replace(
    "from . import config, openrouter, teach\n",
    "from . import config, openrouter\nfrom .schedule_tables import CATEGORY_MARK_RE\n",
)

# 2b. Insert the teach body right after the ChatUnavailable class block
insert_marker = '''class ChatUnavailable(RuntimeError):
    """Raised when the LLM cannot be reached (e.g. no OPENROUTER_API_KEY)."""'''

new_docstring = '''"""Agentic chatbot (production-plan §5) — an OpenRouter function-calling loop
over a read-mostly toolbox. It answers questions about the QA-QC results AND
acts on the UI (select an element, apply a filter, open a view) via ``ui_actions``
the frontend executes. Nothing destructive is in the toolbox by design.

Now unified with the teach-the-AI memory engine: humans explain non-standard
drawing conventions, rules persist to ai_teach_memory.json, and the NEXT
extraction run applies them (element_detector/schedule_tables consume
build_overrides()).
"""'''

# Update module docstring
old_doc_end = chat_text.find('"""\n\nfrom __future__')
chat_text = new_docstring + chat_text[old_doc_end + 4:]

# Drop "from .schedule_tables import CATEGORY_MARK_RE" duplicate (already added)
# Actually we inserted it above — now check if teach_body re-imports it
# teach_body starts with SCHEMA_VERSION = ..., no imports, so no conflict.

# Insert teach body
chat_text = chat_text.replace(
    insert_marker,
    insert_marker + "\n\n" + teach_body,
)

# 2c. Rename internal references from teach.teach -> teach (now in same module)
# Change _tool_save_teach_rule: `res = teach.teach(str(...))` -> `res = teach(str(...))`
# But `teach` is also the name of the function we just inserted. So simply
# renaming teach.teach -> teach works because the function lives in this module now.
chat_text = chat_text.replace("res = teach.teach(", "res = teach(")

# 2d. Update the docstring references that mention "teach.py" or similar
# (optional cosmetic; leave as-is — they're still accurate references to the
#  legacy module name which now re-exports.)

# 2e. Remove the "from .schedule_tables import CATEGORY_MARK_RE" if duplicated
# (We only add it once above; chat_agent.py didn't import it before.)
# Count occurrences:
if chat_text.count("from .schedule_tables import CATEGORY_MARK_RE") > 1:
    # Keep only the first occurrence
    first = chat_text.find("from .schedule_tables import CATEGORY_MARK_RE")
    start = first + len("from .schedule_tables import CATEGORY_MARK_RE\n")
    chat_text = chat_text[:start] + chat_text[start:].replace(
        "from .schedule_tables import CATEGORY_MARK_RE\n", ""
    )

# 2f. Add the teach module docstring preamble that describes the migration.
# Actually, insert a small block comment at the end of the teach section so
# it's clear where the chat_agent code resumes.

# Find the insertion point: right after `unrecognized_report` ends (last function in teach body)
# and before the next section (the chat SYSTEM_PROMPT / TOOLS).
# The teach body ends with the `if __name__` block which we excluded.
# After our insertion, the text reads:
#   class ChatUnavailable(...):
#       ...
#   <teach body — all the way through unrecognized_report ending with `return items`)
#   SYSTEM_PROMPT = (
#     ...
# We want a clear separator.
separator = '''


# ===========================================================================
# chat_agent: schemas, tool implementations, and the LLM loop
# (merged from the legacy app/teach.py — teach API is above)
# ===========================================================================

'''

# Find the SYSTEM_PROMPT that starts the second half of chat_agent.py
# (the original one, not the LLM_SYSTEM_PROMPT from teach which we just inserted)
# After insertion, there are two: LLM_SYSTEM_PROMPT (teach) and SYSTEM_PROMPT (chat).
# The chat SYSTEM_PROMPT is the one that says "You are the QA-QC copilot".
target = '\nSYSTEM_PROMPT = (\n    "You are the QA-QC copilot'
chat_text = chat_text.replace(target, separator + "SYSTEM_PROMPT = (\n    \"You are the QA-QC copilot")

# -----------------------------------------------------------
# 3. Write the updated chat_agent.py
# -----------------------------------------------------------
# Fix: also update the docstring to mention unified teach
chat_path.write_text(chat_text, encoding="utf-8")
print("Wrote merged chat_agent.py (", len(chat_text), "bytes)")

# -----------------------------------------------------------
# 4. Write the thin-shim teach.py
# -----------------------------------------------------------
shim_teach = '''"""Thin shim: the teach-the-AI memory engine has been unified into
:mod:`app.chat_agent`. This module re-exports the public surface so that any
caller still doing ``from . import teach`` / ``teach.build_overrides()`` etc.
continues to work unchanged. New code should import from ``app.chat_agent``
directly.
"""
from __future__ import annotations
from .chat_agent import (  # noqa: F401 — re-exports
    SCHEMA_VERSION,
    RULE_KINDS,
    CATEGORIES,
    load_memory,
    add_entry,
    delete_entry,
    build_overrides,
    teach,
    unrecognized_report,
    # Convenience aliases matching the task spec's expected surface:
)

# Module-level aliases expected by callers
save_rule = add_entry
list_rules = lambda: load_memory()["entries"]
delete_rule = delete_entry

def apply_on_extract(*args, **kwargs):
    """Backward-compatible hook; callers consume build_overrides() directly."""
    return build_overrides(*args, **kwargs)
'''
teach_path.write_text(shim_teach, encoding="utf-8")
print("Wrote thin-shim teach.py")

# -----------------------------------------------------------
# 5. Sanity check: syntax OK?
# -----------------------------------------------------------
import ast
try:
    ast.parse(chat_path.read_text(encoding="utf-8"))
    print("chat_agent.py: syntax OK")
except SyntaxError as e:
    print(f"chat_agent.py SYNTAX ERROR: {e}")
try:
    ast.parse(teach_path.read_text(encoding="utf-8"))
    print("teach.py: syntax OK")
except SyntaxError as e:
    print(f"teach.py SYNTAX ERROR: {e}")
