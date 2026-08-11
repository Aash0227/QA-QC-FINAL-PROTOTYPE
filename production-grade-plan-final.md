# Production-Grade Plan — Final (2026-07-17)

The complete execution plan for taking the QA-QC prototype to a production
web application: no Claude dependency in the product loop, one visual system,
Revit-accurate 3D, an agentic chatbot as the intelligence layer, and a
codebase any stakeholder can navigate.

Grounding: every claim here is backed by evidence gathered in the 2026-07-17
validation pass (see `Bugs.md`). Key verified facts this plan builds on:

- Nonica MCP is a **plain stdio executable**
  (`C:\NONICAPRO\OtherFiles\System\Core\net8.0-windows\RevitMCPConnection.exe`)
  — the backend can drive it directly as an MCP client. Verified live this
  session (active view read, marker locations read, bboxes read).
- Export geometry is **accurate**: live bbox spot-verify matched the v3
  export exactly. The 3D gap is rendering fidelity, not data.
- The real Madera IFC exists (`10510 Madera Dr_LGS model V2.ifc`).
- The gated calibration math, device matching, and the 11-state benchmark
  workflow with stamp/calibrate verification guards are working and tested
  (120 pytest, MATCH=107 baseline intact).

---

## 1. System architecture

```
┌────────────────────────── Browser ──────────────────────────┐
│  frontend/ (Vite build, vanilla ES modules — no framework)  │
│  tokens.css · store.js · api.js · panels/ (list, pdf,       │
│  scene3d+ifc, table, wizard, chat) · SSE event bus          │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP + SSE (localhost, token opt.)
┌──────────────────────────┴──────────────────────────────────┐
│  FastAPI backend (backend/app/)                             │
│  routers/: projects · pipeline · elements · registration ·  │
│            benchmark_workflow · revit · chat                │
│  services/: (existing modules — compare, registration,      │
│            device_match, benchmarks, … FROZEN math intact)  │
│  revit_bridge.py  ── MCP stdio client ──►  RevitMCPConnection.exe ──► Revit
│  chat_agent.py    ── OpenRouter function-calling loop       │
│  artifact store: artifacts/projects/<slug>/ (unchanged)     │
└─────────────────────────────────────────────────────────────┘
```

Principles: frozen math modules stay frozen; routers are thin; every
Revit-side claim is verified server-side before entering the audit trail
(extends the existing stamp/calibrate guard pattern to all steps).

### Backend restructure (mechanical, no behavior change)

Split the ~2,300-line `main.py` into routers registered on one `create_app()`:

- `routers/projects.py` — projects list/activate/upload. **Fixes BUG-03** by
  making the project explicit: every artifact read/write goes through a
  request-scoped `ProjectContext` (path param or header `X-Project`), and
  `config.set_active_project` global mutation is retired; the "active
  project" becomes a UI-only preference.
- `routers/pipeline.py` — extract/convert/intelligence/compare/match + SSE.
- `routers/elements.py` — element list, devices, review, evidence.
- `routers/registration.py` — RANSAC, grids, benchmarks (gates untouched).
- `routers/benchmark_workflow.py` — the state machine endpoints + stamp.
- `routers/revit.py` — bridge status + bridge-executed actions.
- `routers/chat.py` — the agentic chatbot.

`SAMPLE_PDF`/`SAMPLE_REVIT_JSON` are deleted (**BUG-02**); the only inputs
are per-project uploads.

### Frontend restructure

`frontend/` becomes a Vite project (plain ES modules, no framework — keeps
Three.js/GSAP, lowest-risk path from the current code):

```
frontend/
  index.html            (shell only)
  src/tokens.css        (ONE design-token system — see §7)
  src/store.js          (single state store + pub/sub)
  src/api.js            (fetch wrapper: error unwrap, project header)
  src/sse.js            (one EventSource, fan-out bus)
  src/panels/{list,pdf,viewer3d,table,wizard,chat,inspector}.js
  src/components/{button,card,chip,pill,modal,table}.css
```

`index_v3_backup.html` convention retired — git is the backup (**BUG-13**).
Build output is served by FastAPI's StaticFiles exactly as today.

---

## 2. Revit ↔ webapp bridge (the critical challenge — real implementation)

**`backend/app/revit_bridge.py`** — a Python MCP client (package: `mcp`)
that spawns `RevitMCPConnection.exe` over stdio, the same transport Claude
uses today. No LLM required: the placement procedure is a deterministic tool
sequence, already proven step-by-step in the 2026-07-16 live run.

```python
class RevitBridge:
    # async context manager; single-flight asyncio.Lock — one Revit op at a time
    async def start(self): ...   # stdio_client(StdioServerParameters(
                                 #   command=NONICA_EXE)) → ClientSession.initialize()
    async def call(self, tool: str, args: dict) -> dict: ...  # + timeout, retry(1)

    async def status(self) -> dict:
        # get_active_view_in_revit → {connected, model_title, view}
    async def place_benchmarks(self, proposal) -> dict:
        # 1. find template: get_all_families_in_model → family name ~ "Benchmark"
        #    (fallback: get_elements_by_category + Mark BM-*)
        # 2. for each proposal benchmark (BM-1, BM-2):
        #    a. compute translation vector: template location → revit_point_ft
        #       (exact coords from proposal, NEVER the 2-dp display readback)
        #    b. set_copy_elements with the vector; if "Element is Pinned":
        #       copy WITH vector to point 2, then copy result back by reverse
        #       vector (the proven pinned-copy trick)
        #    c. set_parameter_value_for_elements(idParameter=-1001203, "BM-n")
        #    d. read back: get_location_for_element_ids → verify vs
        #       revit_point_ft within 0.05 ft (readback is 2-dp rounded —
        #       tolerance accounts for it)
        # 3. return {element_ids, readback, deltas}  — VERIFIED data
```

Config: `NONICA_MCP_EXE` in `.env` (default the known install path).

Wiring into the state machine (closes **BUG-07**):

- `GET /api/revit/status` — bridge status; wizard shows a live
  connected/disconnected pill instead of a passive spinner.
- `POST /api/benchmark-workflow/place-markers` — requires state
  `placing_markers`; runs `bridge.place_benchmarks(wf["proposal"])`; on
  verified success transitions to `awaiting_revit_approval` with the REAL
  readback payload; on failure returns 409 with the tool-level error, state
  unchanged. The manual `advance{step:"markers_placed"}` path stays for
  external agents but its payload gets flagged `"verified": false` in the
  audit trail and rendered amber (not green) in the wizard.
- `advance{step:"revit_connected"}` is replaced by the wizard calling
  `/api/revit/status` — a state the server can check itself is never
  self-reported.

What stays human (honest limits): saving the model (Ctrl+S) and running the
Livio **pyRevit exporter** — neither is MCP-reachable. The wizard's
`awaiting_export` card keeps the guided instructions; the existing
upload-auto-advance (built + tested) completes the loop the moment the JSON
lands.

End-to-end product flow after this section:

```
Upload PDF+JSON → propose (auto or user-picked grids, §3) → human approves
→ /stamp (backend writes+verifies PDF) → /place-markers (bridge places+
verifies in Revit) → human approves placement → user saves+exports (guided)
→ upload auto-advances → gated calibrate → done. Zero Claude involvement.
```

## 3. Grid marking in the UI

- Wizard proposal card gains **"Pick manually"**: click the PDF pane → snap
  to the nearest detected grid intersection (from the same
  `pdf_grid_control_points` set) → assign BM-1, click again → BM-2; propose
  endpoint accepts `{"points": [{grid_id, mark}, …]}` as an alternative to
  auto-max-diagonal. Evidence crops + approval gate identical either way.
- **Fix BUG-01** so detection generalizes: make pairing axis-agnostic —
  `pdf_grid_control_points` pairs any vertical grid with any horizontal grid
  regardless of which is a letter; join to Revit intersections by the
  unordered label pair (`grid_{a}_{b}` normalized). `calibrate_sheet_from_grids`
  callers re-tested against the existing S-202/S-205 calibrations before
  ship (label-pair ids stay identical for letter-vertical sheets — zero
  change for Madera-class sheets).
- **Fix BUG-14**: `sheet_number` alone resolves its `page_index` from
  element_intelligence.

## 4. Holdown exact matches on click

Already 100%-traceable data exists (`device_registry.json`: per-device
appearances, target assembly, distance_ft, status — driven by the frozen
compare pipeline). Product surface:

- Click any holdown (list/PDF/3D/table) → inspector shows the DEVICE block:
  matched Revit assembly id, distance_ft, every sheet appearance
  (each clickable), and the evidence crop. Data source:
  `GET /api/devices` joined by the row's `device_id` — no new matching code,
  no accuracy change (the validated numbers stay byte-identical).

## 5. Agentic chatbot (replaces the Teach AI drawer)

**`backend/app/chat_agent.py`** — OpenRouter function-calling loop (reuses
`openrouter.py` client + call-logging; model via env, default the configured
reasoning model):

```python
TOOLS = [
  get_counts(),                      # totals + by_status + by_category
  query_elements(status?, category?, sheet?, mark?, limit),
  get_device(mark_or_id),            # device registry block
  get_run_comparison(),              # baseline vs current
  get_workflow_state(),              # benchmark autopilot state
  run_pipeline_step(step),           # whitelisted: extract|match|compare
  save_teach_rule(instruction),      # writes through existing teach.py store
  focus_element(element_id),         # returns a ui_action, executed client-side
]
# Loop: user msg → LLM w/ tools → execute tool calls server-side →
# feed results back → final answer + structured payload:
# {reply, blocks: [{type: count_card|table|status_breakdown}, ...],
#  ui_actions: [{type: select|filter|open_panel, ...}]}
```

- **Agentic**: `ui_actions` are executed by the frontend (select an element
  → all three panes fly to it; apply a filter; open the table). The bot acts,
  not just answers. `run_pipeline_step` is whitelisted + audit-logged;
  anything destructive is out of the toolbox by design.
- "How many holdowns?" → `get_counts` + `query_elements(category=holdown)` →
  count card + per-mark breakdown table + optional highlight sweep across the
  panes.
- The teach RULE STORE stays (extraction overrides depend on
  `teach.build_overrides()`); teaching now happens conversationally via
  `save_teach_rule`. The unknown-table notice spam (**BUG-10**) is aggregated
  into one card the bot can expand on request.
- Frontend: the Teach drawer is replaced by a Chat panel (same drawer slot,
  new `panels/chat.js`), streaming optional (phase 2); every block type is a
  small renderer reusing the table/pill components.

## 6. Revit-accurate 3D (IFC viewer)

- Per-project IFC upload (`POST /api/upload` accepts `ifc` alongside pdf +
  revit_json; stored under `uploads/model.ifc`, manifest key `ifc_path`).
- Frontend `panels/viewer3d.js` loads it with **web-ifc** (WASM) into the
  EXISTING Three.js scene — real member geometry replaces the box massing.
- Status coloring: map IFC GlobalId ↔ v3 export UniqueId. These are the same
  identifier in Revit-exported IFC (GlobalId = IFC-base64-encoded UniqueId) —
  implement the standard decode, and (per **BUG-05**) never use naive
  hex-suffix→ElementId shortcuts. Fallback matching by category+bbox overlap
  for unmapped elements, reported honestly as "unmapped: N".
- The current scene3d box view remains as the no-IFC fallback; benchmarks/
  grids/status overlays render identically over either geometry.
- Nonica live reads stay as a validation tool
  (`POST /api/revit/spot-verify` — N random elements, live bbox vs export,
  report deltas; this session's manual spot-verify becomes a product
  feature).

## 7. UI standardization (one visual system)

- `src/tokens.css` = THE system, taken from the Autopilot/report aesthetic
  (ink `#0B0D10`, panel `#14171C`, line `#262B33`, paper `#ECE9E1`, signal
  `#5EEAD4`, markup `#FF5A36`; Big Shoulders Display for display text, IBM
  Plex Sans body, IBM Plex Mono for all data/numerals with tabular-nums).
  `#bmwizard`'s duplicated `--bw-*` set is deleted — it references the
  global tokens (**BUG-12**).
- Component classes (`components/*.css`): one button set (primary/ghost/
  mini/danger), one card, one chip, one status-pill, one table style — the
  wizard's versions become the app's versions.
- Every remaining hardcoded legacy color (`#38bdf8` measure tool, info-ball,
  spin-border, chat bubbles) is swapped to tokens.
- Header regrouped into 4 zones: `project ⋮ stats ⋮ pipeline actions
  (Pipeline·Extract·Match) ⋮ views (Table·Autopilot·Runs·Review) ⋮ AI (Chat)`
  with labels + separators; overflow collapses into a menu below 1280px.
- Honest labels audit: data-driven `#three-note` (**BUG-11**), dead
  door/window legend chips removed for v3 (**BUG-16**).
- Empty/loading/error states for every panel (one skeleton pattern).

## 8. State management

- `store.js`: single source of truth (elements, scene, workflow, chat,
  filters, selection) with a tiny pub/sub (`subscribe(key, fn)`); panels
  render from store events — no more cross-panel direct calls.
- `sse.js`: ONE EventSource for `/api/pipeline/events`, fanned out by `step`
  to subscribers (wizard log, pipeline modal, chat activity) — replaces the
  wizard's private EventSource + 4s polling with SSE + one slow fallback
  poll.
- Selection flow (`select()`) becomes a store mutation all panels react to —
  same behavior, one code path.

## 9. Testing strategy

- **pytest (existing 120 stay green)** + new: bridge unit tests against a
  **scripted fake MCP stdio server** (a ~50-line python script speaking the
  MCP handshake with canned tool responses) so `place_benchmarks` logic incl.
  the pinned-copy retry is CI-testable without Revit; chat_agent tests with a
  faked OpenRouter (tool-call loop, whitelist enforcement, ui_action shape);
  router tests via FastAPI TestClient per router.
- **Live-Revit tests** behind a `-m revit_live` marker (skipped unless the
  connector answers `status`): status, spot-verify, and — only on an
  explicitly-scratch model — a placement round-trip.
- **Playwright smoke suite committed to the repo** (`frontend/tests/`):
  the flows exercised manually all session, scripted — load, 3-pane select
  sync, table sort/filter, wizard propose→approve→stamp (scratch project),
  chat "how many holdowns" → count card + highlight, drawer independence.
- Every phase gate keeps the standing rule: suite green + Madera MATCH=107
  with byte-identical device summary.

## 10. Deployment readiness

- `.env`-driven config (`NONICA_MCP_EXE`, `OPENROUTER_API_KEY`, `BIND_HOST`
  default `127.0.0.1`, `AUTH_TOKEN` optional → simple bearer middleware when
  set; fixes **BUG-18**'s posture).
- Run as a Windows service (nssm or Task Scheduler) on the same machine as
  Revit (the bridge requires it); uvicorn workers=1 (artifact store + bridge
  lock are single-process by design).
- Artifact retention: per-project size cap + evidence-crop GC.
- Structured log file (uvicorn + app logger).
- `requirements.txt` pinned (add: `mcp`; keep pymupdf/fastapi/uvicorn); Vite
  build artifact committed or built in CI.

## 11. Execution order (after bug-fix approval)

1. **Bug pass** — all 18 Bugs.md items in one pass (per directive), gated by
   the standing test suite + MATCH baseline.
2. Backend router split + request-scoped project context (structure only).
3. Revit bridge + wizard wiring + fake-MCP tests (§2).
4. Frontend modularization + token unification (§1, §7, §8).
5. IFC viewer (§6).
6. Chatbot (§5) + Teach drawer replacement.
7. Grid-marking UI + axis-agnostic pairing (§3).
8. Playwright suite + deployment hardening (§9, §10).

Each step lands green before the next starts; the frozen-module rule and the
MATCH=107 gate hold throughout.

## 12. Model recommendation (objective 8)

**Claude Opus 4.8** for the implementation build. Rationale: this is a
multi-surface orchestration job — a FastAPI refactor with a live MCP client,
WASM IFC integration inside an existing Three.js scene, and an agentic tool
loop — where the failure mode is cross-file inconsistency and dropped
constraints, exactly what the strongest long-context coding model mitigates.
Use Sonnet only for isolated, reviewable UI polish subtasks. (Consistent
with the user's standing routing preference: Opus 4.8 as the coding model.)
