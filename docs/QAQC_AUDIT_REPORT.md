# QA/QC App — Phase 0 Engineering Audit

**Date:** 2026-08-17 · **Repo:** `C:\QA-QC-FINAL-PROTOTYPE-bkp` · **Scope:** Audit only, zero code changes.

---

## A. Current Architecture

Single-machine workstation app. One Python process serves API + static frontend; no DB, no queue, no external services besides OpenRouter + local Revit connectors.

```
┌─ Frontend (vanilla JS SPA, Vite-bundled, served from backend StaticFiles)
│    index.html → src/app.js → store.js (single mutable state)
│      ├─ api.js (fetch wrapper + X-Project header)
│      ├─ sse.js  (ONE EventSource: /api/pipeline/events)
│      └─ panels/ (list, pdf, viewer3d, inspector, revit_live, projects,
│                  chat, wizard, table) — self-wiring, innerHTML renders
│
├─ Backend (Python 3.11, FastAPI, single uvicorn worker :8077)
│    app/main.py        — auto-includes app.routers.*, mounts frontend LAST
│    app/config.py      — ContextVar project binding; dirs resolve per request
│    app/routers/       — 75+ endpoints across 10 routers
│    app/<domain>*.py   — frozen math + generic engine
│
├─ Artifacts (JSON on disk, per project folder)
│    artifacts/projects/<slug>/ {uploads, evidence, pages, *.json}
│    artifacts/active_project.json — the ONLY cross-project state pointer
│
├─ Revit side (on Sagar's machine)
│    pyRevit add-in (tools/LivioQAQC.extension) — exporter
│    NonicaTab PRO — live MCP (selection, highlight, scene)
│    revitMCP TCP :8080 — fallback selection channel
│
└─ AI — OpenRouter HTTPS API (openrouter.py), key from .env
```

Key architectural facts:
- **Project isolation** via `config._PROJECT_SLUG` ContextVar (set per request by `make_router()`); `active_project.json` is the ambient default.
- **No database** — every pipeline artifact is a JSON file; state = file existence.
- **Frontend mounted last** in main.py so `/api/*` always wins; `frontend_dir()` prefers `dist/` (Vite build) over raw source, resolved at import time (a rebuild after boot needs a backend restart).

## B. Pipeline Architecture

**Real pipeline** (the math chain, verified working on dogwood-lane this session):

```
upload (PDF + Revit JSON → project workspace)
  → extract            POST /api/elements/extract         (element_detector.scan_pdf + teach overrides + leader-anchor snap)
  → revit ai-convert   POST /api/revit/ai-convert?use_saved=true  (v3 adapter → assemblies)
  → pdf page-intel     POST /api/pdf/page-intelligence?use_saved=true (generic page intel)
  → pdf ai-convert     POST /api/pdf/ai-convert          (pdf_convert + leader snap)
  → registration       POST /api/registration/auto-holdown (mark-constrained RANSAC)
  → compare            POST /api/compare/ai               (16pt/40pt gates; MATCH withheld w/o verified calibration)
  → match              POST /api/elements/match           (shear walls + joins → element_list.json + scene3d)
```

**Orchestration today:**
- `GET /api/pipeline/status` — 9-step checklist, `done` = artifact file exists.
- `POST /api/pipeline/run` — NEW (this session): server-side orchestrator; runs stages in dependency order, **idempotent** (skips stages whose output artifact exists), per-stage try/except so one failure never 409s the whole run; returns `{project, stages[], complete, next_action}`.
- `POST /api/pipeline/ai-status` — NEW: non-blocking AI status line w/ deterministic fallback.
- `GET /api/pipeline/events` — SSE stream; `progress.py` emits start/done/error per step; single shared EventSource on the frontend (`sse.js`) fanned out by step name.

**State ownership:** the backend artifact files are the truth; the frontend derives everything from `pipeline/status` + `elements` GETs. There is no run-id/task model — the "run" is implicitly the set of artifacts in the active project.

**Determinism/safety:**
- Verdicts deterministic; LLM in compare is advisory (`llm_assessment` metadata only — `match_justified` is recorded, not enforced; gates stay math-only: verified registration required for MATCH).
- Retry-safe for already-complete stages (idempotent skip); retry after mid-failure re-runs stages whose outputs are missing — no invalidation of downstream artifacts (stale-output risk exists if an upstream stage is re-run after downstream completed — needs verification).
- Refresh mid-run: safe (state on disk; SSE reconnects on reload), but a browser refresh while `POST /pipeline/run` executes leaves the POST running server-side with no client attached (uvicorn sync endpoint blocks the only worker — see §G).

## C. Frontend Architecture

- **Stack:** vanilla ES modules (no framework, no TS, no JSX) + Vite 8 bundling; Three.js 0.160; GSAP 3.12; @fontsource fonts (IBM Plex Sans/Mono, Big Shoulders Display); Playwright e2e.
- **State:** `store.js` — one plain mutable object; panels read it and re-render themselves via `innerHTML` template strings. No reactivity, no virtual DOM, no component lifecycle.
- **Files:** `app.js` (entry + header + pipeline modal), `api.js`, `sse.js`, `util.js`, `fonts.js`, `tokens.css`, `app.css`, `components.css`, and `panels/` (list, pdf, viewer3d, inspector, revit_live, projects, chat, wizard, table).
- **Pipeline UI:** was a 9-step "lab" list (STEPS array, per-step Run buttons, logs, result strips). This session it was replaced by a guided 4-state flow (`pipeState()` → upload_pdf / upload_revit / ready / complete) with drag-drop, auto-run on upload, and `POST /api/pipeline/run` — verified rendering in browser.
- **Rendering:** full innerHTML rebuilds per panel refresh (`renderList`, `renderPipeline`, etc.); the 3D scene and PDF overlay are imperative canvas/DOM code.
- **Styling:** hand-written CSS + design tokens in `tokens.css`; dark theme; no utility framework.

## D. React Migration Assessment

**What the target wants:** React + TypeScript + Tailwind + shadcn structure (`/components/ui`), with the KineticGrid background and AgentPlanning timeline components (both are TSX + Tailwind + `cn()` + lucide-react — full shadcn idioms).

**Feasibility verdict:** the backend can stay 100% untouched (all API contracts remain). The entire frontend `src/` is framework-less and would need replacement or incremental island adoption.

| Piece | Migrate strategy | Risk |
|---|---|---|
| API contracts (75 endpoints, SSE, uploads) | **keep unchanged** | none |
| Backend pipeline/orchestrator | **keep unchanged** | none |
| Pipeline modal | rewrite in React first (smallest, highest-value) | low |
| Element list + filters | rewrite second (pure DOM/CSS) | low-med |
| Inspector drawer, projects overlay | rewrite | low-med |
| PDF sheet render + overlay (SVG marks, hit-testing, zoom) | rewrite — imperative canvas/DOM logic | **high** |
| viewer3d (three.js scene, GSAP, live-revit colors) | port as React wrapper around three.js — keep imperative core | **high** |
| sse.js / store.js | replace with hooks + a tiny client store (zustand or React state) | med |
| app.css / tokens.css | port tokens to Tailwind config | med |

**Build system:** Vite already supports React/TS with zero infra change (`@vitejs/plugin-react`, `tsconfig`). Tailwind v4 + shadcn CLI bolt on cleanly. **Recommended order:** (1) stand up React shell alongside existing app under one Vite config, (2) pipeline modal as first React island, (3) list → inspector → projects, (4) PDF overlay, (5) viewer3d last. Keep old panels until each replacement passes Playwright parity. **Do not** attempt big-bang — viewer3d + pdf overlay carry the real regression risk.

## E. Hardcoded Project Audit

**Active execution path (runs for every project — real risks):**

| file:line | What | Why it matters |
|---|---|---|
| `routers/pipeline.py:176-186, 212-214` | `use_saved` + direct-upload PDF-intel runs the frozen S-201 Madera detector **first for every project**; generic path only on error | wrong detector precedence |
| `s201_detector.py:38-56` | `PLAN_BBOX`, 4 `S201_TABLE_BBOXES`, `HOLDOWN_ROW_BANDS` (H1-H4 y-bands), `HOLDOWN_RE = H[1-4]` — Madera geometry | page-scan misbehaves on other sheets |
| `s201_detector.py:68-94` | `MARK_TO_CORE_TOKEN` (H1→HDU6…) + full `DEFAULT_HOLDOWN_SCHEDULE` (Madera hardware spec) | wrong spec data |
| `s201_detector.py:223,248,357` | **Fabrication fallback**: schedule parse fail → `sched_source="default_madera"` → manufactures Madera spec rows for any project | fabricates client data |
| `s201_detector.py:144-146` | `locate_s201_page` scans for literal `S-?201` + `H[1-4]` | page locator for every PDF |
| `normalization.py:41,45-50` | `slug != "madera"` gate keeps Madera H1-H4↔HDU vocab for every project | name-literal logic |
| `routers/pipeline.py:414,417` | `compare_sheet = "S-201"` default + `.get("sheet_number","S-201")` | calibration sheet selection |
| `routers/pipeline.py:55,200-201` | uploaded PDF saved as `uploaded_madera.pdf` | confusing filename |
| `pdf_intelligence.py:44` | `_detect_sheet_number` falls back to `"S-201"` | sheet misattribution |
| `config.py:177-180` + `review_overlay.py:167,362,366,380` | review artifacts named `s201_review_*` for every project | cosmetic but client-facing |
| `panels/chat.js:158`, `panels/projects.js:288` | UI copy: "what's PDF only on S-201?" / placeholder "1311 Countryside Ct" | client names in product UI |

**Fallback/env-gated (safe until env unset):** `SAMPLE_PDF`/`SAMPLE_REVIT_JSON` (common.py:23-26), `use_sample=true` paths (pipeline.py:120-128), Nonica exe fallback path (revit_bridge.py:36), `mwfBenchmark` family (revit_bridge.py:40), model default (config.py:245).

**Clean:** main.py startup, compare.py no-registration path (withholds MATCH, no fabricated counts), chat_agent, projects slug logic, openrouter, frontend counts/sheets — all backend-driven, no literals.

**Verdict:** the purge removed hardcoded *counts*, but the frozen `s201_detector.py` is still the **default detector for every project** — this is the single biggest project-agnosticism blocker and must be inverted (generic first, Madera as an opt-in profile).

## F. UI/UX Assessment

1. Old lab UI exposed 9 implementation steps, "Run this step", raw 409 text, steplogs — internal debug tool (replaced this session by the guided flow; still pre-React).
2. No live progress: `pipeline/run` is one blocking POST; the new guided flow shows a static "running" line and **does not consume the SSE stream** (`app.js` renderPipeline vs `sse.js`).
3. `pipeState` declares a `"running"` state that is never returned — dead code (app.js:132 vs :135-142).
4. No Livio branding, no signature motion; functional dark theme only.
5. AgentPlanning status model maps 1:1 to real run stages — the only blocker is per-stage live transitions (needs background-run + SSE, see §G 4d).

## G. Performance Findings

**Duplicates (frontend):** `/api/elements` (268-436KB) refetched on every pipeline-modal open though already in store (app.js:189,199) · `/api/scene3d` (1.9-3.2MB) + `/api/revit-live/scene` both fetched on every load (viewer3d.js:20,53) · `/api/projects` twice (app.js:34 + projects.js:173) · benchmark-workflow on every page load (wizard.js:327) · `/api/review/queue` twice (inspector.js).

**Polling:** 8s fallback poll (sse.js:40) never pauses when SSE is healthy → benchmark-workflow every 8s + on every SSE event.

**Large payloads:** `/api/elements` returns whole 436KB artifact, no pagination · `/api/scene3d` builds scene **in the request thread** from the 15-28MB `raw_revit` JSON when cache missing · `raw_revit` full-`json.loads` at 10 call sites · `/api/review/{id}/analysis` reloads element_list + device_registry per click.

**Blocking sync work (high severity):** `pdf_page_intelligence` is `async def` but runs the full fitz scan **on the event loop** (pipeline.py:170) — freezes ALL concurrent requests · extract (two-pass words scan) sync · match (wall_match + device_match + 28MB parse) sync · `pipeline/run` runs the entire DAG in one request with `asyncio.run()` per stage · RANSAC 4000 iterations sync · `/api/revit/status` spawns MCP exe per call, uncached variant used.

**Repeated PDF opens:** one run opens the same PDF ≥6× (extract×2, pdf-intel, s201×2, plus **fitz.open inside the per-sheet match loop** — pipeline.py:496).

**Re-renders:** full `#list-rows` innerHTML rebuild per keystroke (list.js:59,83, no debounce) · table re-renders on every select · SVG overlay rebuilt on every layer toggle · full Three.js scene rebuild per fetch.

**Top 5 fixes:** (1) move pdf_page_intelligence off the event loop · (2) one cached PDF doc handle per run · (3) parse raw_revit once + prebuild scene3d · (4) background pipeline run + SSE progress · (5) stop refetching elements/scene3d from store.

## H. AI Integration Assessment

*(as delivered earlier — model default `deepseek/deepseek-v4-pro`, 7 call sites, advisory-only in compare, blocking risk on sync call_llm in pipeline stages, `QAQC_AI_STATUS_MODEL` env ready for cheap per-step model.)*

## I. Testing Gaps

**Coverage today:** 30 backend test files (~355 passing) + 2 Playwright specs (projects, smoke). Zero TestClient/HTTP-level tests exist — everything is function-level.

**Untested (all confirmed):**
- `POST /api/pipeline/run` — **fully untested** (skip/done/failed logic, next_action branches, HTTPException→skip)
- `POST /api/pipeline/ai-status` + `_deterministic_status`
- Upload slug-fix regression (revit-only → attach to active project, projects.py:316-325)
- Refresh-mid-run; duplicate-run safety (no in-flight lock; non-atomic `write_text`)
- Request-level ContextVar isolation (unit-tested only; HTTP-level unverified)
- Frontend pipeState states + 409 recovery (zero Playwright coverage of `#pipe-modal`)

**Minimum test list before UI migration (7 tests):** pipeline/run happy path · degraded paths (upload_pdf/upload_revit/retry branches) · ai-status fallback · upload slug regression · two concurrent X-Project requests land in different workspaces · concurrent pipeline_run integrity · e2e pipe-modal (upload→run→complete + forced 409 → toast).

## J. Risk Assessment

**High:**
1. Frozen s201 detector as default + Madera fabrication fallback → wrong results on non-Madera projects (correctness, not UI)
2. `pdf_page_intelligence` blocks the event loop — full API freeze during scan
3. `pipeline/run` = one blocking POST, no run lock → duplicate runs race on non-atomic artifact writes
4. PDF overlay + viewer3d rewrites in the React migration (biggest regression surface)
5. Upload flips persisted active-project global → mid-session retargeting (Race 1)

**Medium:** repeated PDF opens/28MB re-parses (slowness) · SSE unconsumed by new UI · 436KB elements refetch · revit/status spawning MCP exe per call · stale downstream artifacts after mid-run retry.

**Low:** review artifact `s201_*` filenames · UI copy with client names · indent=2 JSON writes · uncached page.png first hit.

## K. Recommended Implementation Phases

1. **P0 — Correctness sealer (backend, no UI):** invert detector precedence (generic first; Madera → opt-in profile) + kill the `default_madera` fabrication fallback; delete `"madera"` slug literal; add the 7 migration-critical tests.
2. **P1 — Run architecture:** background `pipeline/run` (task + run-state file) + run lock + SSE per-stage transitions; UI consumes the existing stream. Fixes blocking, duplicate runs, and live progress in one move.
3. **P2 — React shell:** Vite + React + TS + Tailwind + shadcn structure alongside existing app; `tokens.css` → Tailwind config; brand from grid.golivio.com.
4. **P3 — Pipeline modal island:** AgentPlanning timeline driven by real `/api/pipeline/run` stages + `/api/pipeline/ai-status`; delete DEFAULT_STEPS demo data.
5. **P4 — Panel migration:** list (debounced search) → inspector → projects; store refactors to stop duplicate fetches (1a/1c/1f).
6. **P5 — Heavy panels:** PDF overlay, then viewer3d (React wrapper, imperative core) — with Playwright parity gates.
7. **P6 — Polish:** KineticGrid background (paused on hidden/background tab), per-stage AI explanations (cheap model), error cards with Technical Details.
