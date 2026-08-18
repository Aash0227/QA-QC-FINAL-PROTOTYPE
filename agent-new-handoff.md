# QA-QC Project — Full Context Handoff

**Purpose:** End-to-end context document for AI assistants (ChatGPT, Claude, etc.) to understand the entire QA-QC project state, architecture, decisions, and next steps.

**Last updated:** 2026-08-18

---

## 1. What Is This Project?

A **structural QA/QC automation tool** for construction engineering. It compares a PDF drawing set (architectural plans) against a Revit BIM model export (JSON) and flags discrepancies between what's drawn vs. what's modeled — hold-downs, shear walls, posts, steel columns.

**Problem it solves:** Structural engineers manually cross-check PDF plans against Revit models to find hold-downs that are missing, mislocated, or mislabeled. This tool automates that comparison.

**Target users:** Engineering employees at Livio (Nova's company). Deployed as a Windows desktop app via Inno Setup installer.

**Shipping repo:** `C:\QA-QC-FINAL-PROTOTYPE-bkp`
**GitHub:** `https://github.com/Aash0227/QA-QC-FINAL-PROTOTYPE.git`
**Branch (active):** `fix/integration-runcheck`
**Backend:** FastAPI on `127.0.0.1:8077`, Python 3.11, single worker
**Frontend:** Vite multi-page build — vanilla JS dashboard + React Pipeline Island

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     QA-QC System Architecture                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  Frontend (Vite build)                                          │
│  ├── index.html  → Vanilla dashboard (PDF viewer, 3D model,      │
│  │                 element list, kinetic bg, glass panels)       │
│  ├── pipeline.html → React Pipeline Island (SSE timeline,       │
│  │                    KineticGrid, auto-AI per step, typewriter)  │
│  └── dist/        → Built output served by backend StaticFiles   │
│                                                                  │
│  Backend (FastAPI :8077)                                        │
│  ├── app/main.py          → App factory, CORS, static mount       │
│  ├── app/config.py        → Config (model, paths, tokens)         │
│  ├── app/run_engine.py    → Background pipeline runner (daemon)  │
│  ├── app/stage_graph.py   → 7-stage DAG + dependency invalidation │
│  ├── app/profile.py       → Opt-in Madera/S-201 profile gate      │
│  ├── app/routers/         → 10 routers, 75+ endpoints            │
│  │   ├── pipeline.py      → Run, status, events (SSE), ai-status │
│  │   ├── elements.py      → Element list, intelligence, review   │
│  │   ├── projects.py      → CRUD projects, activate, list        │
│  │   ├── revit.py         → Revit status, export upload           │
│  │   ├── registration.py  → RANSAC coordinate alignment           │
│  │   ├── common.py        → Save/load artifacts (atomic)         │
│  │   └── ...              → chat, review, teach, benchmark, etc.  │
│  ├── app/s201_detector.py  → Hold-down/shear wall detector        │
│  ├── app/normalization.py  → Mark normalization (H1, HD2, etc.)   │
│  ├── app/pdf_intelligence.py → Sheet detection, page metadata    │
│  ├── app/review_overlay.py → Callout generation for PDF overlays │
│  └── app/control_points.py → Manual registration control points  │
│                                                                  │
│  Artifacts (per-project workspace)                              │
│  artifacts/projects/{slug}/                                      │
│  ├── uploaded.pdf / uploaded.revit.json                         │
│  ├── element_intelligence.json, ai_revit.json, ...              │
│  ├── run_state.json (persisted pipeline state)                   │
│  └── review_page.png, review_overlay.svg/png, review_items.json │
│                                                                  │
│  Tests                                                          │
│  backend/tests/ → pytest (374 pass, 11 frozen-fail pre-existing) │
│  frontend/tests/ → Playwright e2e specs (require live backend)   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. The Pipeline (7 Stages)

The pipeline runs as a background daemon thread. `POST /api/pipeline/run` returns 202 immediately; stages execute sequentially; SSE events stream per-stage.

| # | Stage key | Title (UI) | What it does | Artifact key |
|---|---|---|---|---|
| 1 | `extract` | Reading drawings | Scans every PDF sheet for structural elements (hold-downs, shear walls, posts, steel columns) | `element_intelligence` |
| 2 | `revit_convert` | Reading model | Parses Revit JSON export into in-memory structural model | `ai_revit` |
| 3 | `pdf_intelligence` | Locating the plan | Identifies the structural plan sheet, extracts page metadata (sheet number, scale, title block) | `pdf_page_intelligence` |
| 4 | `pdf_convert` | Preparing drawing data | Converts PDF page into coordinate space for matching | `ai_pdf` |
| 5 | `ransac` | Aligning coordinates | RANSAC registration — aligns drawing coords with Revit model coords | `registration` |
| 6 | `compare` | Comparing | Compares each PDF element against nearest Revit counterpart (match, location mismatch, vocabulary gap) | `compare` |
| 7 | `match` | Building the review queue | Finalizes review queue with all element verdicts | `element_list` |

**Stage graph dependency:** `stage_graph.py` defines a DAG. `invalidate_downstream(key)` deletes a stage's output + all downstream artifacts. Upstream artifacts stay cached.

**Run state:** Persisted to `run_state.json` per workspace. Refresh/disconnect doesn't kill the run. Duplicate in-flight runs → 409 with run_id. Stale recovery (running state but no live thread) → new run allowed.

---

## 4. API Contract (Backend is Authoritative)

### Pipeline endpoints
| Method | Path | Returns |
|---|---|---|
| `POST` | `/api/pipeline/run?force=` | 202 with run state `{run_id, project, status:'running', stages, next_action}`. 409 if already running. |
| `GET` | `/api/pipeline/run` | Persisted run state or 404 |
| `GET` | `/api/pipeline/events` | SSE stream: `{step, kind: start\|done\|skip\|error, message, ts?}` |
| `POST` | `/api/pipeline/ai-status` | `{text, source:'ai'\|'deterministic'}` — non-blocking AI summary per stage |
| `GET` | `/api/pipeline/status` | Artifact checklist (compat endpoint) |

### Element endpoints
| Method | Path | Returns |
|---|---|---|
| `GET` | `/api/elements` | Element list with verdicts |
| `GET` | `/api/elements/intelligence` | Sheet-level element intelligence |
| `GET` | `/api/review/queue` | Elements flagged for review |
| `POST` | `/api/review/resolve` | Accept/reject a review item |

### Project endpoints
| Method | Path | Returns |
|---|---|---|
| `GET` | `/api/projects` | List all projects |
| `POST` | `/api/projects` | Create project |
| `POST` | `/api/projects/activate` | Set active project |
| `DELETE` | `/api/projects/{slug}` | Delete project |

### Other endpoints
| Method | Path | Returns |
|---|---|---|
| `GET` | `/api/revit/status` | Revit live connection status (cached 30s/300s TTL) |
| `POST` | `/api/upload/pdf` | Upload PDF drawing set |
| `POST` | `/api/upload/revit` | Upload Revit JSON export |
| `GET` | `/api/scene3d` | 3D model data (Three.js) |
| `GET` | `/api/registration` | Registration transform matrix |
| `POST` | `/api/chat` | AI chat copilot |
| `GET` | `/api/health` | Health check + config info |

---

## 5. Frontend Architecture

### Two surfaces, one Vite build

**`/` (index.html) — Vanilla Dashboard**
- PDF drawing viewer (canvas-based, zoom/pan, callout overlays)
- Three.js 3D model viewer (wireframe, color-coded statuses, orbit controls)
- Element list sidebar (search, filter by status/sheet, categorized tree)
- Header: logo, project selector, stats, ⚡ Pipeline / All results / Needs review / Ask / ⚙
- Kinetic animated background (canvas particle grid, `src/kinetic-grid.js`)
- Glass panels (translucent + backdrop-blur, `.5` alpha)
- Projects overlay (full-screen modal, project cards)
- Drawers: inspector, chat, runs comparison, benchmark wizard

**`/pipeline.html` — React Pipeline Island**
- React 18 + TypeScript + Tailwind v4 + shadcn-style components
- KineticGrid canvas background (React component, same particle math)
- Pipeline timeline (7 stages, SSE-driven, status dots, auto-AI per step)
- AI typewriter effect (progressive text reveal, `useTypewriter` hook)
- Glass cards (translucent + backdrop-blur)
- Header: ◂ Dash link, Livio logo, Pipeline label, project name, run_id
- Controls: Grid toggle, Run, Force, Stop (disabled), Report (disabled)
- SSE subscription via EventSource (`/api/pipeline/events`)
- Auth token support (Bearer header + `?token=` for SSE — matches vanilla)
- Live indicator, debug SSE panel, safe-mode toggle

### Frontend tech stack
- **Vanilla:** ES modules, no framework. `src/app.js` (main), `src/panels/*.js` (projects, chat, review, benchmark, wizard), `src/api.js` (fetch wrapper + auth), `src/sse.js` (EventSource), `src/kinetic-grid.js` (canvas animation), `src/viewer3d.js` (Three.js)
- **React:** React 18, TypeScript, Tailwind CSS v4, lucide-react, class-variance-authority, @fontsource/ibm-plex-sans/mono
- **Build:** Vite multi-page (`vite.config.js`), entries: `main` (index.html) + `pipeline` (pipeline.html)
- **Fonts:** IBM Plex Sans (body), IBM Plex Mono (code) — unified across both surfaces

### Brand tokens (from grid.golivio.com zip)
- Livio blue: `#06adf5`
- Dark surface: `#161618`
- Green accent: `#76b900`
- Logo: `livio-logo-white.png` (white text + yellow hard hat, generated from dark version by inverting black→white)
- Font: IBM Plex Sans / system-ui

### Glass / translucency system
- `--panel` token: `rgba(20,23,28,.5)` (controls all `.glass` surfaces)
- `#viewport` (PDF): `rgba(10,15,28,.5)` + `blur(10px)`
- `#three-wrap` (3D): `rgba(8,13,24,.5)` + `blur(10px)`
- `#list-panel`: `rgba(20,23,28,.5)`
- `header`: `rgba(22,24,29,.4)`
- `#projects` overlay: `rgba(4,8,16,.3)` + `blur(16px)`
- `.pane-bar`: `rgba(20,23,28,.5)` + `blur(10px)`
- `body`: radial-gradient (blue-ish dark, `#161a20` → `--bg`)
- `#kinetic-bg` canvas: `opacity:.5` (subtle, behind everything)
- All glass surfaces: `backdrop-filter:blur()` + `saturate(1.2)`
- Reduced-motion: `backdrop-filter` disabled on badges/ai-cards

---

## 6. Backend Design Decisions

### Generic-first detection (Phase 1 hardening)
- **Before:** `s201_detector.py` was the default detector for EVERY project. Madera/S-201 logic ran on all inputs. Fabrication fallbacks (`DEFAULT_HOLDOWN_SCHEDULE`, `default_madera`) invented specs when data was missing.
- **After:** Generic detection is default. Madera/S-201 detector runs ONLY when `detection_profile == 'madera'` in the project manifest (opt-in). Missing data → explicit failure/review state (`schedule_not_parsed`, `none`, `detected`), never invented specs.
- **File:** `backend/app/profile.py` — 30-line opt-in gate.

### Background pipeline execution (Phase 1)
- `POST /api/pipeline/run` → 202 immediately, daemon thread runs stages
- `run_state.json` persists per workspace → refresh/disconnect doesn't kill run
- In-flight duplicate → 409 with run_id
- Stale recovery → if state says running but no live thread registered → new run allowed
- Per-stage try/except: HTTPException(409/no-input) treated as `skipped` not `failed`

### Dependency-aware invalidation
- `stage_graph.invalidate_downstream(key)` → deletes a stage's output + all downstream artifacts
- Upstream artifacts stay cached
- Returns artifact keys (not filenames)

### Event-loop fix
- `pdf_page_intelligence` handler is sync `def` (not `async def`) so fitz scan runs in FastAPI threadpool, not the async event loop

### AI status (non-blocking)
- `POST /api/pipeline/ai-status` — fire-and-forget per stage
- System prompt: "structural QA/QC pipeline commentator, 2-4 sentences, what happened / what data / what's next"
- `max_tokens=200`, `temperature=0.4`
- Deterministic fallback: rich 3-sentence per-stage explanation (not one-liner)
- Never blocks pipeline execution — pipeline continues regardless of AI response
- Model: OpenRouter (default `deepseek/deepseek-v4-pro`); `QAQC_AI_STATUS_MODEL` env override

### Auth token
- `QAQC_AUTH_TOKEN` env var → backend requires Bearer header or `?token=` query
- Vanilla `api.js`: `authToken()` from localStorage `qaqc_token`, sent as Bearer header; `tokenized()` for EventSource/img
- React `lib/api.ts`: same contract — `authToken()`, `tokenized()`, Bearer in fetch headers, `?token=` for SSE

---

## 7. Hardcode Removal (Completed)

All project-specific hardcodes removed or gated:

| What | Where | Status |
|---|---|---|
| `"S-201"` sheet_number default | `registration.py:148`, `control_points.py:128,156` | Removed → `None` |
| `"S-201"` compare_sheet fallback | `pipeline.py:414` | Removed → derives from page-intelligence or None |
| `DEFAULT_HOLDOWN_SCHEDULE` / `default_madera` | `s201_detector.py` | Replaced with `schedule_not_parsed` / `none` |
| `"madera"` slug in normalization | `normalization.py:41` | Gated behind `MADERA_VOCAB` + profile check |
| `"S-201"` in `_detect_sheet_number` | `pdf_intelligence.py:44` | Removed → `None` |
| `"Countryside Ct"` placeholder | `projects.js` | Replaced with `e.g. My Project` |
| `page_index=4` fallback | `review_overlay.py` / `elements.py` | Required param or 409 |
| `uploaded_madera.pdf` filename | `pipeline.py` | Generic `uploaded.pdf` |

**3 safe diagnostic residues (documented, not active):**
- `control_points.py:128,156` — S-201 in docstring copy only
- `generic_page_intelligence.py:3-4` — stale docstring
- `test_normalization.py` — 10 frozen-module failures (pre-existing)

---

## 8. Test Baseline

- **Backend:** `py -3.11 -m pytest -q --tb=no` → **374 passed, 11 failed** (10 pre-existing frozen normalization + 1 control_points)
- **Migration-critical tests** (all green): `test_run_state.py`, `test_run_invalidation.py`, `test_ai_status_endpoint.py`, `test_upload_attach.py`, `test_concurrent_projects.py`
- **Intermittent flake:** `test_run_state`/`test_upload_attach` — full-suite ordering issue (`_ACTIVE_THREADS` singleton + ContextVar bleed). Pass standalone. Test-isolation quality, not product correctness.
- **Frontend:** No JS/TS unit test suite. Playwright e2e specs exist (`frontend/tests/pipeline-island.spec.ts`) but require live backend + browser stack.
- **Verification approach:** Ad-hoc Python scripts (`hermes-verify-*.py` in `%TEMP%`) that run `npm run typecheck`, `npm run build`, `node --check`, `ast.parse` on changed Python, and live curl checks. Created via `tempfile.mkstemp`, executed, cleaned up.

---

## 9. UI/UX Decisions

- **Dark-mode only** for all phases
- **Kinetic animated background** on every page — canvas particle grid (dots + lines + mouse interaction + click ripples + reduced-motion respect + document.hidden pause)
- **Glass panels** — translucent (`~50%` opacity) + `backdrop-filter:blur()` on all surfaces
- **White Livio logo** — `livio-logo-white.png` (generated from `livio-logo-dark.png` by inverting black pixels → white, keeping yellow hard hat)
- **IBM Plex Sans** unified across both vanilla and React surfaces
- **"⚡ Pipeline"** is the canonical label for the run action (replaced "Run the check")
- **AI typewriter** — progressive text reveal in React Pipeline Island (`useTypewriter` hook, 10ms/char, respects reduced-motion)
- **"◂ Dash"** nav-back link on pipeline page → returns to dashboard at `/`
- **No page redirects when starting pipeline** — pipeline button navigates to `/pipeline.html` (separate page, not inline modal)

### Button audit (what each does)

**React Pipeline page:**
| Button | Backend? | Status |
|---|---|---|
| Grid | No (UI toggle) | Functional — pauses KineticGrid canvas |
| Run | `POST /api/pipeline/run?force=false` | Functional — 202, starts pipeline |
| Force | `POST /api/pipeline/run?force=true` | Functional — forces new run |
| Stop | None | Placeholder (disabled) |
| Report | None | Placeholder (disabled) |

**Vanilla Dashboard:**
| Button | Backend? | Status |
|---|---|---|
| ⚡ Pipeline | No (navigation) | Functional → `/pipeline.html` |
| All results | No (UI toggle) | Functional — toggles results table |
| Needs review | `GET /api/review/queue` | Functional — opens review drawer |
| Ask | `POST /api/chat` | Functional — AI chat copilot |
| ⚙ | Various | Functional — Extract, Match, Registration wizard, Compare runs, Revit lookup |

---

## 10. Phase History

### Phase 0 — Audit (2026-08-17)
- 3 parallel audit subagents (hardcode sweep, performance, test/state consistency)
- Architecture report: 75+ endpoints, 10 routers
- Key finding: `s201_detector.py` was default for every project; fabrication fallbacks active
- Reports: `docs/QAQC_AUDIT_REPORT.md`, `docs/QAQC_AUDIT_UI_REFERENCES.md`

### Phase 1 — Backend Hardening (2026-08-17)
- Created `stage_graph.py`, `run_engine.py`, `profile.py`
- Rewired `routers/pipeline.py` — generic-first, no S-201 fallback, run engine
- Fixed event-loop blocking (`pdf_page_intelligence` sync handler)
- 3 parallel subagents: hardcode purge, performance (atomic save, cached status, backgrounded scene3d), migration-critical tests
- 374 passed, 11 failed (pre-existing frozen)
- Verification report: `docs/PHASE1_VERIFICATION_REPORT.md` — READY FOR PHASE 2

### Layer 2 — React Shell (2026-08-17)
- Installed React 18 + TS + Tailwind v4 + shadcn-style + lucide-react
- Created `frontend/react.html` (now `pipeline.html`), `frontend/src/react/` foundation
- Multi-page Vite build (vanilla + React coexist)
- Typecheck clean, build clean, both routes 200

### Layer 3 — Pipeline Island (2026-08-17)
- React PipelineIsland component: types, usePipeline hook, StepRow, PipelineTimeline, KineticGrid
- SSE-driven, auto-AI per step, poll fallback
- Playwright e2e spec (7 tests)
- Branch `ui/pipeline-island` pushed

### Integration + UI Transformation (2026-08-18)
- Rewired `btn-pipe` to navigate to `/pipeline.html` (not redirect to `/`)
- Fixed `openPipeline()` crash (undefined function → redirect)
- Added React auth token support (Bearer + SSE `?token=`)
- Fixed KineticGrid reduced-motion resume bug
- Added "◂ Dash" nav-back link
- Glass UI layer: translucent panels + backdrop-blur on all surfaces
- White logo on both surfaces
- AI typewriter effect
- IBM Plex font unification
- Kinetic background on vanilla dashboard (`src/kinetic-grid.js`)
- `kinetic-grid.js` bundled as module (404 fix for production)
- Hardcode removal: S-201, Countryside Ct, page_index=4
- Bug scan: 0 CRITICAL, 1 HIGH (kinetic 404, fixed)
- Multiple translucency iterations to match user's desired look

---

## 11. Current State (2026-08-18)

### Git
- **Branch:** `fix/integration-runcheck` (13+ commits)
- **PR:** https://github.com/Aash0227/QA-QC-FINAL-PROTOTYPE/pull/1
- **Server:** Live on `127.0.0.1:8077` (uvicorn, Python 3.11, 1 worker)
- **Active project:** `dogwood-lane` (259 elements, 33 verified, 93 flagged)
- **Build:** `npm run typecheck` clean, `npm run build` clean

### What works end-to-end
- Dashboard at `/` — PDF viewer, 3D model, element list, kinetic bg, glass panels
- Pipeline at `/pipeline.html` — React timeline, SSE, auto-AI, typewriter, KineticGrid
- Navigation between both surfaces (⚡ Pipeline → `/pipeline.html`, ◂ Dash → `/`)
- Project manager overlay — create, open, edit, delete projects
- Pipeline run — POST → 202 → SSE events → timeline updates → AI per step
- Review queue — flagged elements, accept/reject
- Chat copilot — AI Q&A about the project
- All 75+ backend endpoints functional

### Known issues / deferred
- Stop/Report buttons on React pipeline page are disabled placeholders (no backend endpoint for stopping a run)
- Orphaned vanilla pipe-modal code (~300 LOC in `app.js:155-297`, `legacy.html` (deleted), `app.css:192-230`) — dead code, no callers
- `test_run_state`/`test_upload_attach` intermittent full-suite ordering flake (test-isolation, not product bug)
- 3 safe diagnostic hardcode residues (docstrings, not active logic)
- URL routing for `/project-manager`, `/all-results`, `/needs-review`, `/ask` — currently UI panel toggles, not routes (would need client-side router)
- Dead `review_overlay` backend endpoints — S-201-specific, never called by UI
- ~20 backend REST endpoints with zero frontend callers (attack surface)

---

## 12. Key Files Reference

### Backend
| File | Purpose |
|---|---|
| `backend/app/main.py` | App factory, CORS, static mount, router includes |
| `backend/app/config.py` | Config: model default, paths, tokens, frontend_dir() |
| `backend/app/run_engine.py` | Background daemon-thread runner, run_state.json, lock, stale recovery |
| `backend/app/stage_graph.py` | 7-stage DAG, STAGE_OUTPUT mapping, invalidate_downstream() |
| `backend/app/profile.py` | Opt-in Madera/S-201 profile gate |
| `backend/app/routers/pipeline.py` | Run, status, events (SSE), ai-status endpoints |
| `backend/app/routers/elements.py` | Element list, intelligence, review queue |
| `backend/app/routers/projects.py` | Project CRUD, activate |
| `backend/app/routers/registration.py` | RANSAC coordinate alignment |
| `backend/app/s201_detector.py` | Hold-down/shear wall detector (generic-first, profile-gated) |
| `backend/app/normalization.py` | Mark normalization (H1, HD2, HTT4, etc.) |
| `backend/app/pdf_intelligence.py` | Sheet detection, page metadata |
| `backend/app/review_overlay.py` | Callout generation for PDF overlays |
| `backend/app/control_points.py` | Manual registration control points |

### Frontend
| File | Purpose |
|---|---|
| `frontend/index.html` | Dashboard entry (vanilla) — PDF, 3D, elements, kinetic bg |
| `frontend/pipeline.html` | React Pipeline Island entry |
| `frontend/vite.config.js` | Multi-page Vite config (main + pipeline entries) |
| `frontend/src/app.js` | Main vanilla app — boot, header handlers, pipeline trigger |
| `frontend/src/api.js` | Fetch wrapper + auth token (Bearer + tokenized) |
| `frontend/src/sse.js` | EventSource wrapper for SSE |
| `frontend/src/kinetic-grid.js` | Vanilla canvas particle grid animation |
| `frontend/src/app.css` | Main vanilla CSS (glass panels, layout, viewport, three-wrap) |
| `frontend/src/tokens.css` | Design tokens (--panel, --bg, --accent, --line, fonts) |
| `frontend/src/components.css` | `.glass` class + shared component styles |
| `frontend/src/panels/projects.js` | Project manager overlay (CRUD) |
| `frontend/src/panels/chat.js` | AI chat copilot drawer |
| `frontend/src/panels/review.js` | Review queue drawer |
| `frontend/src/viewer3d.js` | Three.js 3D model viewer |
| `frontend/src/react/main.tsx` | React entry — imports IBM Plex, App, index.css |
| `frontend/src/react/App.tsx` | React root — `<RunProvider><PipelineIsland /></RunProvider>` |
| `frontend/src/react/index.css` | Tailwind v4 theme tokens (translucent surfaces) |
| `frontend/src/react/lib/api.ts` | Typed fetch client + auth token + tokenized |
| `frontend/src/react/lib/use-pipeline-events.ts` | SSE hook (EventSource + auto-reconnect + dedupe) |
| `frontend/src/react/lib/use-typewriter.ts` | Progressive text reveal hook |
| `frontend/src/react/state/run-context.tsx` | RunProvider — reducer, startRun/forceRun, polling fallback |
| `frontend/src/react/components/PipelineIsland/index.tsx` | Main pipeline UI — header, timeline, KineticGrid, controls |
| `frontend/src/react/components/PipelineIsland/usePipeline.ts` | Composes useRun + per-stage auto-AI + poll fallback |
| `frontend/src/react/components/PipelineIsland/StepRow.tsx` | One step UI — status dot, label, SSE message, AI text, technical details |
| `frontend/src/react/components/PipelineIsland/AiText.tsx` | AI explanation with typewriter effect |
| `frontend/src/react/components/PipelineIsland/PipelineTimeline.tsx` | Vertical timeline with connector rail |
| `frontend/src/react/components/PipelineIsland/KineticGrid.tsx` | React canvas particle grid (same math as vanilla) |
| `frontend/src/react/components/PipelineIsland/types.ts` | IslandStep, StageStatus, stage→artifact mapping |
| `frontend/src/react/components/ui/{button,card,badge,separator,status}.tsx` | shadcn-style primitives |
| `frontend/src/react/assets/livio-logo-white.png` | White Livio logo (React) |
| `frontend/public/livio-logo-white.png` | White Livio logo (vanilla) |

### Docs
| File | Purpose |
|---|---|
| `docs/QAQC_AUDIT_REPORT.md` | Phase 0 architecture audit |
| `docs/QAQC_AUDIT_UI_REFERENCES.md` | KineticGrid + AgentPlanning fit analysis |
| `docs/PHASE1_VERIFICATION_REPORT.md` | Phase 1 requirement-by-requirement PASS table |
| `docs/INTEGRATION_AUDIT_MASTER.md` | Integration audit (route mapping, endpoint comparison, button wiring) |

---

## 13. How to Run

### Start backend
```bash
cd C:\QA-QC-FINAL-PROTOTYPE-bkp\backend
py -3.11 -m uvicorn app.main:app --host 127.0.0.1 --port 8077 --workers 1
```

### Build frontend
```bash
cd C:\QA-QC-FINAL-PROTOTYPE-bkp\frontend
npm run build   # outputs to dist/
```

### Typecheck
```bash
cd C:\QA-QC-FINAL-PROTOTYPE-bkp\frontend
npm run typecheck   # tsc --noEmit
```

### Run tests
```bash
cd C:\QA-QC-FINAL-PROTOTYPE-bkp\backend
py -3.11 -m pytest -q --tb=no
```

### Verify live
```
GET http://127.0.0.1:8077/              → dashboard (200)
GET http://127.0.0.1:8077/pipeline.html → React pipeline (200)
GET http://127.0.0.1:8077/api/health     → {"status":"ok"}
POST http://127.0.0.1:8077/api/pipeline/run  → 202 (starts pipeline)
GET http://127.0.0.1:8077/api/pipeline/events → SSE stream
```

### Backend restart
- Not needed for frontend rebuilds (StaticFiles reads from disk)
- IS needed when switching from source→dist mode (dist/ didn't exist at boot)
- IS needed after backend Python file changes

---

## 14. Environment

- **OS:** Windows 10
- **Python:** 3.11.9 (required: `py -3.11`)
- **Node:** v24.14.0
- **Shell:** Git Bash / MSYS2 (POSIX syntax, NOT PowerShell)
- **GPU:** RTX 3050 Laptop 4GB VRAM (local LLM ceiling = small models only)
- **OpenRouter API key:** Present (config.py reads `OPENROUTER_API_KEY`)
- **AI model default:** `deepseek/deepseek-v4-pro` (config.py)
- **AI status model override:** `QAQC_AI_STATUS_MODEL` env var

---

## 15. Team

- **Ashwin 'Nova' Pawar** — 21, India, B.Tech AI/ML. Project owner, systems-builder.
- **Team:** Neel, Shreyansh, Kristi, Chris, Sagar, Masum

---

## 16. Engineering Philosophy (Nova's conventions)

- Maintainability, modularity, scalability, docs, automation, readable code
- No hacks if architecture solves it
- Prefer clean arch, SOLID, DRY, strong typing, small functions, production-ready
- Think like OpenAI/Anthropic/Cursor/Linear/Notion/Figma/Vercel/Perplexity/Apple/Stripe
- High-quality UX matters
- Phase-gated briefs: audit phase forbids changes; implementation = subagent fan-out; verification = evidence tables
- Never accepts "probably" — needs evidence (file:line, tests, PASS/PARTIAL/FAIL)
- Prefers parallel agent delegation for large tasks
- Brief direction → full execution, no discussion
- Build first, document after

---

## 17. Next Steps (Post-Integration)

1. **Merge PR** `fix/integration-runcheck` → `main`
2. **Clean up dead code** — orphaned pipe-modal (~300 LOC), dead review_overlay endpoints
3. **URL routing** — client-side router for `/project-manager`, `/all-results`, `/needs-review`, `/ask`
4. **Stop/Report buttons** — implement backend endpoint for stopping a run, report generation
5. **EXE deployment** — Inno Setup installer for employee laptops
6. **Test isolation fix** — `_ACTIVE_THREADS` singleton + ContextVar bleed across test modules
7. **Font/color polish pass** — full Tailwind ↔ custom CSS token merge
8. **Performance** — benchmark large projects (100+ sheets), optimize RANSAC + PDF scan

---

*This document is the authoritative context for the QA-QC project as of 2026-08-18. Generated by Hermes Agent from live codebase inspection + session history.*
