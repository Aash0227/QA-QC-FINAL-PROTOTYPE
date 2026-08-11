# Prompt for a new Claude Code session on this project

Paste everything below as your first message in the new session.

---

You're picking up the **Livio QA-QC AI** prototype — an automated PDF-drawing
↔ Revit-model QA-QC tool for a construction QA company. It compares a
client's stamped structural drawings (PDF) against their Revit export (JSON)
and flags every hold-down, shear wall, column, post etc. as MATCH /
LOCATION_MISMATCH / MARK_MISMATCH / PDF_ONLY / REVIT_ONLY — replacing a
manual process that currently takes ~8 days per project.

**Read these first, in order, before touching any code:**
1. `AGENT_HANDOFF.md` — current status checkpoint, environment setup, key
   facts, gotchas. This is the single most important file. If its checklist
   looks unfinished/stale, trust the git log and the artifacts on disk over
   the checklist — it was edited by mistake during a rate-limit resume once.
2. `docs/ACCURACY_100_PLAN.md` — the device-level matching architecture
   (why per-sheet-appearance counting was wrong, how physical-device
   matching in model feet fixes it).
3. `docs/HUMAN_REVIEW_V2_PLAN.md` — the AI-assisted human review loop
   (analyze → human logic → AI verdict → animated accept/reject → propagate).
4. `graphify-out/GRAPH_REPORT.md` and `graphify-out/graph.html` (if present)
   — a generated knowledge-graph map of the whole codebase: communities,
   god nodes (most-connected files), and suggested questions. Open
   `graph.html` in a browser for a visual, clickable map before diving into
   code — it's the fastest way to see how main.py/device_match.py/review.py/
   the frontend/the Revit adapter all connect.
5. `docs/PRODUCTION_ROADMAP.md`, `docs/QA_REVIEWER_GUIDE.md`,
   `docs/REVIT_MCP_EVALUATION.md` — supporting context.

**Environment (must follow exactly):**
- Python: `C:\Users\aashd\AppData\Local\Programs\Python\Python311\python.exe`,
  run from `backend/` (module is `app`).
- Server: `python -m uvicorn app.main:app --host 127.0.0.1 --port 8077`
  (background process). A browser tab can fire
  `POST /api/projects/activate` at any time and change the active project
  mid-session — always re-activate your target project
  (`madera` or `country-side-ct`) before any chained API calls.
- Tests: `python -m pytest -q` from `backend/` — 86 tests, must stay green.
- Frontend is one file: `frontend/index.html` (+ keep `index_v3_backup.html`
  in sync after edits).

**Frozen modules — read-only, additive params only, NEVER change their
logic:** `compare.py`, `registration.py` (math), `s201_detector.py`,
`pdf_intelligence.py`, `review_overlay.py`, `normalization.py`,
`revit_convert.py`, `pdf_convert.py`. Non-negotiable project rule: **no fake
matches, ever** — every MATCH must trace to a verified registration +
explicit distance gate. Never silently mutate a status; human-accepted
matches carry a permanent `resolution` audit block with the original status
and distance.

**Architecture in one paragraph:** PDF → `pdf_intelligence.py` /
`element_detector.py` / `schedule_tables.py` extract marks, schedules, and
per-sheet geometry. Revit JSON (schema v3.1 from a custom pyRevit exporter,
category- and view-scoped) → `revit_v3_adapter.py` clusters raw elements
into holdown assemblies and normalizes point marks. `registration.py` +
`ransac_holdown.py` + `grid_registration.py` compute a per-sheet PDF↔model
similarity transform. `compare.py` (frozen) does the actual point-distance
verdict. `device_match.py` (new, this sprint) re-accounts everything at the
**physical-device level in model feet** — inverse-projects every sheet
callout into model space, clusters into one record per real device, and
does one global assignment against Revit assemblies/walls — because raw
per-sheet-row counting produced logically-impossible phantom PDF_ONLY /
REVIT_ONLY statuses (the same bolt drawn on 3 sheets counted 3 times).
`review.py` is the Human Review v2 loop: `analyze()` (deterministic offset +
systematic-shift detection), `evaluate()` (checks the reviewer's stated
logic against the numbers, LLM only phrases it), `resolve()` (human
accept/reject → propagates status everywhere + memory rule),
`apply_stored_resolutions()` (re-applies prior accepts on every re-match).
`main.py` wires it all into FastAPI endpoints; `frontend/index.html` is the
single-file dashboard (3D THREE.js view, PDF viewer, Teach AI chat, Review
drawer with animated accept/reject, ⚖ Runs before/after comparison).

**Current state (verify against `AGENT_HANDOFF.md` and `git log` — this may
be out of date by the time you read it):** device-level matching sprint is
complete and tested. Madera: MATCH went 69→102 (0 phantom PDF_ONLY holdowns,
down from ~51), coverage 62%→95%. Country Side: MATCH 12→21. 86/86 tests
green. Human Review v2 verified end-to-end. Security/stability fixes applied
(stored XSS, WebGL leak, v3-upload bypass, teach-memory ID collision).

**Known small items possibly still open** (check `AGENT_HANDOFF.md` for the
authoritative list before redoing any of this):
1. Three tiny bug patches: `scene3d.py` (~line 89, `if c.get("z")` should be
   `is not None` — a real elevation of 0.0 was being treated as missing);
   `element_registry.py` (~line 35-37, a dict comprehension keyed by
   `sheet_number` silently drops marks if two sheets ever share a number —
   iterate the original list, don't rebuild via dict); `elements_match` in
   `main.py` (capture `config.ARTIFACT_DIR` at request start, refuse the
   final `_save_artifact` write if a project switch changed it mid-request —
   a long-running match call can otherwise write into the wrong project).
2. Push this repo to GitHub as a **private** repo named `Livio-QA-QC-AI`
   (not yet confirmed done — check `git remote -v` and GitHub). If doing
   this: NEVER write any access token to a file, `.gitignore` must exclude
   `artifacts/`, `artifacts_*/`, `**/uploads/`, `.env`, `__pycache__/`,
   `.playwright-mcp/`, `*.log` (client drawings + API keys must never be
   committed), and confirm no OpenRouter key
   (`sk-or-v1...`) is committed anywhere before pushing.
3. Country Side live acceptance check via the Revit MCP (`mcp__Revit__*`
   tools, from the NonicaTab AI Connector — only available when Revit is
   open with the connector enabled): expect 28 structural columns when that
   model is open.
4. The user has NOT yet described "the Livio checklist" — the standardized
   QA-QC checklist step that comes after element matching, which is the
   next major phase of this project. Do not build it speculatively; ask.

**Working style the user expects (important):** move fast, verify every
claim against real saved artifacts/API responses (not assumptions), report
exact before/after numbers, keep the pipeline's frozen modules untouched,
never fake a match, and prefer running actual pipeline calls over inspecting
code alone when validating a fix. The user has been extremely engaged and
technical about the honesty of the matching logic — treat any "PDF_ONLY" or
"REVIT_ONLY" result with suspicion and verify it isn't a double-counting or
mismatched-unit artifact before reporting it as real.

Start by reading `AGENT_HANDOFF.md`, confirming server + tests are green,
and asking the user what's next (likely: apply the 3 patches, finish the
GitHub push, or start the Livio checklist).
