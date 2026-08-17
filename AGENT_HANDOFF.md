# AGENT_HANDOFF — Livio QA-QC (prototype repo)

> **Fresh agent:** read this top-to-bottom before touching anything. It encodes
> where the project is, the pinned decisions, and the current task (element
> expansion). The other source of truth is `C:\QA-QC Livio Automation` (the
> *new* engine/R&D repo) — **this repo `C:\QA-QC-FINAL-PROTOTYPE-bkp` is the
> production-trained prototype** where recent deployment/Project-Manager work
> landed.

---

## What this project is

An AI-assisted **Revit ↔ PDF structural QA/QC** workstation. It reads a client
structural PDF + a Revit model export, aligns their coordinates, and produces a
per-element verdict: `MATCH / LOCATION_MISMATCH / MARK_MISMATCH / PDF_ONLY /
REVIT_ONLY / NEEDS_REVIEW` — each with a plain-English reason. Live Revit
pillar (Nonica PRO + revitMCP) binds findings to real model elements + "Show in
Revit".

## Two repositories — know which you're in

| Repo | Role | Owns |
|---|---|---|
| `C:\QA-QC-FINAL-PROTOTYPE-bkp` | **Prototype, production-trained** | holdowns + all sacred math, exporters, recent Vite + Project Manager + installer work |
| `C:\QA-QC Livio Automation` | **R&D fresh engine build** | clean architecture (Phase 0–8), Grok AI bus, new PM, installer — the "new app" | 

Rule: for **product/shipping on real data**, work in the prototype. For
**architecture/R&D/clean-slate**, work in the Automation repo. They are NOT in
sync — treat each as independent.

## Environment (hard)

- Python **3.11** only (vendored/frozen PyMuPDF + Pillow). `py -3.11`. Never bare `python`.
- Backend: FastAPI on `127.0.0.1:8077`, 1 worker. Launch:
  - `backend-start.ps1` (new, pretty banner)
  - or `py -3.11 -m uvicorn app.main:app --host 127.0.0.1 --port 8077 --workers 1` from `backend/`
- Frontend: **Vite build** now. `cd frontend; npm ci; npm run build` → serves `frontend/dist`
- Tests: `cd backend; py -3.11 -m pytest -q`
- **Known baseline:** ~355 pass / ~11 fail in frozen `normalization.py`/`control_points.py`
  — do NOT "fix" by changing production data unless asked.

## Recent work in THIS repo (uncommitted, working tree)

### 1. Project Manager (backend + UI) — the big recent change
- `backend/app/routers/projects.py`: real CRUD — `POST/GET /api/projects`,
  `GET /api/projects/{slug}` (incl. `size_bytes/file_count`), `PATCH` whitelist
  (`display_name, client, revision, status, notes`). Additive manifest keys.
- `frontend/src/panels/projects.js`: card-grid overlay, verdict progress rings,
  Create/Open/Edit/Delete with typed confirm.
- Test: `backend/tests/test_projects_crud.py`; Playwright `frontend/tests/projects.spec.js`.
- `backend/tests/conftest.py` autouse guard pops a shadowing `ARTIFACT_DIR`
  (prevented a live-manifest clobber). Repair tool: `scripts/repair_manifest.py`.

### 2. Vite migration (frontend)
- `frontend/vite.config.js`, `frontend/src/fonts.js`. Removed CDN (Google Fonts,
  GSAP, importmap) from `index.html` → bundled, offline-capable.
- `config.frontend_dir()` prefers `frontend/dist` if built, else source.
- Playwright globalSetup builds first.

### 3. Launcher + Setup
- `backend-start.ps1` (new), `setup.bat` (self-extracting PS), `installer/qaqc.iss`
  (Inno Setup), **deleted** old `scripts/setup_qaqc.ps1` + `run_backend.ps1`.
- Guide: `docs/AGENT_EXECUTION_GUIDE.md`.

## Core logic (the part a fresh agent MUST understand)

### The QA pipeline (artifact chain, all JSON on disk per project)

```
upload PDF + Revit export (export_watch or /api/upload)
  → element_detector.scan_pdf (schedule tables → learn vocab → find plan marks)
  → page intelligence → pdf_convert + leader_anchor.snap
  → register (RANSAC / benchmarks / manual) → registration_calibration.json
  → compare (holdowns, point) → device_match (physical devices in feet)
  → wall_match (shear walls, segment)
  → element_registry.build_element_list → element_list.json
  → review mobile (accept/reject) + punch list
```

### The REUSABLE pattern (the current task hinges on this)

1. `schedule_tables.discover_tables()` — finds schedule tables by **header text
   regex** → infers MARK column → `learned_vocabulary {category: {mark: spec}}`.
   **No hardcoded marks.** `CATEGORY_HEADERS` + `CATEGORY_MARK_RE` list known families.
2. `element_detector.detect_marks()` — plan tokens matching vocab → mark instances
   with `center_pdf`. Handles multiplicity "(2)P-1", excludes tables/title/detail refs.
3. **Two match shapes:**
   - **POINT** (holdowns, posts, steel columns): `compare.py` pairs transformed
     Revit centers with PDF points by mark + distance gate → MATCH/LM/PO/RO.
     `device_match.py` clusters multi-sheet callouts to physical devices in FEET.
   - **SEGMENT** (shear walls): `wall_match.py` PDF point → Revit wall centerline.
4. `element_registry.build_element_list()` — joins all into one category/mark/status list.

Everything downstream is **category-driven** (reads `category`/`mark` from
artifacts, never hardcodes a name).

### Categories already wired (may be partial)
- `holdown` (strong, compare + device_match)
- `shear_wall` (segment)
- `post` (`{post:(P,)}` in pipeline `V3_POINT_CATEGORIES`)
- `steel_column` (`{steel_column:(C,)}` in `V3_POINT_CATEGORIES`)
- `wall_type` (spec-only rows)
- `unknown` (generic \bSCHEDULE\b fallback)

## CURRENT TASK (the priority)

**Expand QA-QC beyond hold-downs to all structural elements** using the same
generic engine — NO hardcoding. The per-element list + generic recipe was
delivered to the user (point-matched beams/joists/footings/embeds/stairs/
connections + segment-matched wall types/frames). Implement categories by the
recipe: add header regex + mark regex + (point prefix in `V3_POINT_CATEGORIES`
OR segment handler), reuse `compare`/`device_match`.

## PIPELINE FIX (completed 2026-08-17 — this is the new baseline)

**LAYER 2 — React shell landed (2026-08-17).** `frontend/react.html` + `frontend/src/react/` is a React 18 + TS + Tailwind v4 + shadcn-style foundation served at `/react.html`, built by the SAME `npm run build` (multi-entry: `index.html` vanilla + `react.html` React). Structure: `src/react/{components/ui, lib, state, types, assets}`. `@/*` → `src/react/*`. API boundary in `lib/api.ts` (run/status/ai-status/projects), SSE hook `lib/use-pipeline-events.ts`, state `state/run-context.tsx` (RunProvider). Livio brand tokens in `index.css` (bg #161618, Livio blue #06adf5, accent #76b900). Logo: `src/react/assets/livio-logo-dark.png` (from grid.golivio.com). Verified: typecheck clean, build clean, /react.html renders live run state + SSE + AI status against dogwood-lane; legacy app untouched (still the default at /). DO NOT migrate PDF overlay / viewer3d / list / inspector / projects / chat yet — they stay vanilla until their phases.

Phase 1 hardening landed. The new architecture:

- **Run model** (`app/run_engine.py` + `app/stage_graph.py`): `POST /api/pipeline/run?force=` starts a BACKGROUND run (202) and returns immediately; `GET /api/pipeline/run` reads the persisted `run_state.json` (survives refresh/disconnect); `GET /api/pipeline/status` unchanged for compat. Duplicate runs → 409 with run_id; stale runs (thread dead) auto-recover. SSE per-stage start/done/error/skip via `progress.emit`. Dependency-aware invalidation: `stage_graph.invalidate_downstream(key)` deletes downstream artifacts; failed stages invalidate downstream automatically; `force=true` wipes all outputs first.
- **Generic-first detection** (`app/profile.py`): the frozen S-201/Madera detector runs ONLY when project_manifest declares `detection_profile: "madera"`. `_detect_sheet_number` returns None (no "S-201" fallback); `compare_sheet` derives from page-intel (no hardcode); upload filename is `input.pdf` (not `uploaded_madera.pdf`). NO fabrication: failed schedule parse → `schedule_not_parsed` with empty specs; uncovered marks → `not_in_schedule`. `DEFAULT_HOLDOWN_SCHEDULE` exists only behind the opt-in profile.
- **Performance**: atomic artifact writes (tmp+os.replace) + mtime-aware load cache (routers/common.py); cached revit status (no MCP spawn per poll); scene3d serves from cache; single PDF open per match loop; `pdf_page_intelligence` is sync `def` (threadpool, not event loop); frontend: debounced search, deferred wizard/inspector fetches, live-scene only on toggle, SSE-idle fallback poll.
- **Frontend**: `pipeState()` now reads run_state ("running" survives refresh); `pollRunState()` renders live stage list; 409 → reuse in-flight run.

Tests: 373 pass / 12 fail (10 pre-existing frozen normalization/control_points + 1 test-ordering leak in test_upload_attach + 1). New test files: test_run_state, test_run_invalidation, test_ai_status_endpoint, test_upload_attach, test_concurrent_projects.

**DON'T**:
- add `if slug == "madera"` or any client literals to engine code
- let LLM write verdicts (MATCH is deterministic-only)
- re-add manual step buttons — the guided flow + `/api/pipeline/run` is the goal
- delete `frontend/dist` without rebuilding (`npm run build`)
- run the S-201 detector without the madera profile (generic is the default)

## Do-not-repeat gotchas

- PDF y is FLIPPED vs model y — always try both chiralities in fits.
- Distances: model FEET (device_match MATCH ≤2ft, LM ≤6ft) vs PDF POINTS (compare 16/40pt). Don't mix.
- Export = source of truth for math; live = interaction only.
- Tests must not leave `config.ARTIFACT_DIR` as a real attribute (conftest guard).
- Never ship client PDFs / corpus in the installer.
- Nonica window must be OPEN (not just installed) else `connected:false`.
- Revit modal dialog blocks MCP tools — honest error, not "nothing selected".
