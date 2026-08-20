# Audit — Pipeline Honesty + UI Cohesion

Read-only audit. Backend live at `http://127.0.0.1:8077`, active project `madera`
(PDF only, no Revit export). Browser evidence gathered with throwaway Playwright
scripts in a temp dir; screenshots in the session scratchpad.

Severity: CRITICAL / HIGH / MEDIUM / LOW. Status: CONFIRMED (observed) /
SUSPECTED (code-read only).

---

## PART A — PIPELINE HONESTY

### A1. CRITICAL · CONFIRMED — SSE progress bus is global, not per-project; it can repaint a skipped stage green
- **Problem**: `progress.py` is a single module-level ring buffer (`_EVENTS`) with
  no project/run field. `sse_stream()` replays from `last = 0`, so every page load
  receives up to 500 historical events from **any** project's runs. The pipeline UI
  applies them by stage key alone.
- **Where**: `backend/app/progress.py:21-24` (global `_EVENTS`), `:29` (`emit(step,
  kind, message)` — no project), `:55-65` (`sse_stream` starts at `last = 0`);
  `frontend/src/react/components/PipelineIsland/usePipeline.ts:112-127` (blindly
  overwrites `steps[idx].status` from `latest.step`).
- **Reproduction (observed)**: triggered `1 Extract elements` + `2 Match to model`
  on `dogwood-lane`, then loaded `/pipeline.html` with `madera` active. `madera`'s
  `run_state.json` says `match: skipped, reason "waiting on: element_intelligence,
  raw_revit, ai_revit, compare"`, but the page rendered **"Building the review queue
  — completed"** with the green success ring (`aria-label="success: Building the
  review queue"`, bg `oklch(0.95 0.052 163.051)`, opacity 1). Debug panel showed
  "raw SSE events (2)".
- **Root cause**: the event bus carries no identity. The React reducer trusts a
  keyed event over the authoritative persisted `run_state`.
- **Ownership**: backend (bus) + frontend (reducer).
- **Fix**: stamp `project` and `run_id` on every emitted event; filter in
  `sse_stream` (or client-side) against the currently-viewed run; on the client,
  ignore events whose `run_id` differs from `run.run_id`. Also start the SSE replay
  at the current `_SEQ` for a fresh connection rather than 0.
- **Complexity**: S–M. **Dependencies**: none.

### A2. HIGH · CONFIRMED — an all-skipped run reports overall status "completed"
- **Problem**: 4 of 7 `madera` stages are `skipped`; `run_state.status` is
  `"completed"` and the pipeline header reads **"Pipeline complete"**.
- **Where** (code path):
  1. `run_engine.py:152-157` — `if not stage_graph.artifact_present(prereqs)`
     sets `si["status"] = "skipped"`, `si["reason"] = f"waiting on: …"`, `continue`.
     A missing *input* is a skip.
  2. `run_engine.py:171-186` — an exception makes the stage `failed`, **except**
     `HTTPException` with 404/409, which is re-classified as `skipped` (`:174-179`).
  3. `run_engine.py:191-193` — post-loop: `if state.status == "running":
     state["status"] = "completed"`. **Nothing inspects the per-stage statuses**
     before writing `completed`. Even the `failed` branch at `:200-202` only changes
     `next_action`, never `status`.
  4. `usePipeline.ts:147-151` maps `run.status === "completed"` to `"completed"`,
     and `index.tsx:89` prints "Pipeline complete".
- **Root cause**: run-level status is a lifecycle flag ("the thread finished"), but
  it is presented as an outcome ("QA/QC is done").
- **Ownership**: backend (semantics) + frontend (wording).
- **Fix**: derive the terminal status — `completed` only when no stage is
  `failed`/`skipped`; otherwise `partial` (or `blocked`). Render "Pipeline
  finished — 4 of 7 steps could not run" for that case.
- **Complexity**: S. **Dependencies**: A5 (surface `next_action`).

### A3. HIGH · CONFIRMED (code) — `ransac` returning `ok:false` is recorded as a green success
- **Problem**: `ransac_holdown.ransac_calibrate` returns `{"ok": False, "reason":
  …}` on three distinct failures. The router wraps it in a **200** `JSONResponse`
  and never raises, so `run_engine` marks the stage `done` with a duration and a
  green check.
- **Where**: `backend/app/ransac_holdown.py:103-109` (fewer than 3 correspondences),
  `:153-160` (no consensus transform), `:192-201` (degenerate solve, "Calibration
  not saved"); `backend/app/routers/registration.py:182-194` (`return
  JSONResponse(result)` — no status check); consumed at `backend/app/run_engine.py:166`
  (`_exec_stage`) then `:168-170` sets `done`.
- **Downstream tell**: none of the failure branches call
  `registration.save_calibration`, so `registration_calibration.json` is absent and
  `compare` then skips with "waiting on: … registration". The user sees
  **"Aligning coordinates OK" followed by "Comparing — skipped"** — the UI blames
  the wrong stage.
- **Root cause**: the stage contract is "did the handler return?", not "did the
  handler produce its declared output artifact".
- **Ownership**: backend.
- **Fix (root-cause, one place)**: in `run_engine._run_in_thread`, after
  `_exec_stage(key)` succeeds, assert `stage_graph.artifact_present((output_artifact,))`;
  if the declared output is missing, mark the stage `failed` with the handler's
  `reason`. This covers every soft-failing handler at once, not just ransac.
- **Complexity**: S. **Dependencies**: none.

### A4. HIGH · SUSPECTED — `pdf_intelligence` writes an ERROR artifact, returns 200, and the stage goes green
- **Problem**: two branches save a `pdf_page_intelligence` artifact whose body is
  `{"error": …, "holdowns": [], "summary": {"total": 0}}` and return HTTP 200. The
  artifact **exists**, so `run_engine` records `done`, and on the next run
  `stage_graph.artifact_present` short-circuits it as `"already run"` — the error is
  now permanently cached as a success.
- **Where**: `backend/app/routers/pipeline.py:181-198` (`use_saved` branch,
  `"error": "element_intelligence.json missing — run extraction first."`) and
  `:218-230` (direct-upload branch, `"error": "Run extraction first …"`), both ending
  in `save_artifact(...)` then `return JSONResponse(result)`.
- **Nobody reads the `error` key**: `pdf_ai_convert` at
  `backend/app/routers/pipeline.py:237-247` loads the artifact and feeds it straight
  to `pdf_convert.convert_pdf`. No consumer checks `.error`. Grep across
  `frontend/src` finds no reader either.
- **Not reproducible on `madera`**: its saved artifact has no `error` key
  (`sheet_number: "S-201"`, 54 hold-downs) — hence SUSPECTED. The code path is
  unambiguous.
- **Ownership**: backend.
- **Fix**: raise `HTTPException(409, detail=…)` instead of persisting a poisoned
  artifact; or make `save_artifact` refuse to write a payload carrying `error`. The
  A3 output-assertion fix does **not** cover this one (the file does get written),
  so it needs its own guard.
- **Complexity**: S. **Dependencies**: none.

### A5. HIGH · CONFIRMED — `next_action` is computed by the backend and rendered nowhere
- **Problem**: `run_engine.py:195-202` computes the single most useful sentence in
  the product. For `madera` it is `{"kind": "upload_revit", "message": "Export +
  upload the Revit JSON."}`. It is typed on the client
  (`frontend/src/react/types/pipeline.ts:32,68`) and **never referenced by any
  component** — grep for `next_action` across `frontend/src` returns only those two
  type declarations.
- **Reproduction**: `/pipeline.html` on `madera` shows "Pipeline complete" and no
  next step anywhere on screen.
- **Root cause**: backend contract shipped, UI never consumed it.
- **Ownership**: frontend.
- **Fix**: render `run.next_action.message` as a banner under the pipeline card
  title, with the `kind` driving a CTA (`upload_revit` opens the project's upload
  dialog).
- **Complexity**: S. **Dependencies**: none.

### A6. MEDIUM · CONFIRMED — "skipped" and "pending" are visually identical
- **Problem**: a blocked stage looks like a stage that simply has not started.
- **Where**: `frontend/src/react/components/PipelineIsland/StepRow.tsx:12-26` —
  `STATUS_ICON.skipped` and `STATUS_ICON.pending` are the same 1.5px dot,
  `STATUS_RING.skipped` and `.pending` are the same class string. Only the row
  opacity differs (`:45-46`, 0.5 vs 0.6).
- **Measured**: skipped rows render `bg rgb(38,38,43)`, `color rgb(161,161,170)`,
  opacity 0.5 — i.e. grey; success rows render emerald.
- **Fix**: give `skipped` its own icon (`MinusCircle`/`PauseCircle`) and an
  amber/outline ring, so "blocked" is distinguishable from "not yet".
- **Complexity**: S. **Dependencies**: none.

### A7. MEDIUM · CONFIRMED — "waiting on: raw_revit" IS on screen, but only as raw artifact keys
- **Finding (answers Q3)**: the reason is surfaced. `usePipeline.ts:54` maps
  `s.reason ?? s.error` into `step.message`, and `StepRow.tsx:116-118` renders it. On
  `/pipeline.html` the collapsed rows read:
  - "Reading model — waiting on: raw_revit"
  - "Aligning coordinates — waiting on: ai_revit, ai_pdf"
  - "Comparing — waiting on: ai_revit, ai_pdf, registration"
  - done rows read "already run"
- **Problem**: the strings are internal artifact keys (`raw_revit`, `ai_pdf`),
  produced by `run_engine.py:154` (`f"waiting on: {', '.join(prereqs)}"`). A reviewer
  cannot act on "waiting on: ai_revit". "already run" also reads as "nothing happened
  this time" rather than "this result is current".
- **Fix**: add a human label per artifact key (`raw_revit` -> "the Revit export")
  next to `config.ARTIFACT_FILES`, and format the reason from it.
- **Complexity**: S. **Dependencies**: none.

### A8. MEDIUM · CONFIRMED — input inventory exists, but only inside the Projects modal
- **Finding (answers Q4)**: the Project Manager overlay (dashboard, Projects button)
  does show per-project input presence — observed rows: `madera · 21 pages · PDF yes
  · no Revit export`, `dogwood-lane · PDF yes · Revit yes`, `pw-esc-… · no PDF · no
  Revit export`.
- **Problem**: it is two clicks away on a **different page** from the Run button.
  `/pipeline.html` shows only the project slug badge (`index.tsx:38-40`) — nothing
  about which inputs exist. A user presses Run with no way to know 4 of 7 stages
  cannot execute.
- **Fix**: put the same PDF-yes / Revit-no chips in the pipeline header next to the
  project badge, and disable/annotate Run accordingly.
- **Complexity**: S. **Dependencies**: needs an inputs field on the pipeline status
  payload (already available via `project_manifest`).

### A9. MEDIUM · CONFIRMED — every project is badged "ACTIVE"
- **Problem**: in the Projects modal all 7 projects carry an `ACTIVE` badge while
  only `madera` also shows `Open now`. "Active" reads as "this is the current
  project", so the modal appears to claim seven current projects.
- **Where**: `frontend/src/react/features/project-manager/ProjectManager.tsx` (badge
  bound to a lifecycle/archived flag, not to the active slug).
- **Fix**: rename the badge (`Ready` / `Archived`) or show it only for the active
  project.
- **Complexity**: S.

---

## PART B — UI COHESION

### B1. HIGH · CONFIRMED — two independent design systems ship in one product
`dashboard-main.tsx:1-13` states the split explicitly: it deliberately does **not**
import `index.css` "so migrated features keep the current, unchanged visual identity
instead of pulling in a second competing design-token system". That decision is
documented, but it is the direct cause of the two-apps feel.

| Axis | Dashboard (`index.html` + `tokens.css`/`components.css`/`app.css`) | Pipeline (`pipeline.html` + `react/index.css`, Tailwind v4) |
|---|---|---|
| Token mechanism | hand-written CSS vars (`--ink`, `--panel-solid`, `--line`, `--paper`, `--dim`) | Tailwind `@theme` (`--color-background`, `--color-card`, `--color-border`, …) |
| Background | `--ink: #0B0D10` (opaque) | `--color-background: rgba(22,22,24,0.6)` (translucent) |
| Border colour | `--line: #262B33` | `--color-border: #2e2e33`; cards use `border-white/8` |
| Surface | `.glass` — `rgba(20,23,28,.5)`, `blur(16px)`, radius **16px** | `Card` — `bg-card/50`, `backdrop-blur-md`, `rounded-xl` (**16px**) but header/steps mix `rounded-md` (6px) and `rounded-full` |
| Button radius | **10px** (`components.css:8`), mini 8px | **6px** `rounded-md` (`ui/button.tsx:8,20,21`) |
| Button height | padding-driven, `8px 14px` (~35px), mini `4px 9px` | fixed `h-9` (36px) / `h-8` (32px) / `h-10` |
| Primary button | teal-to-cyan **gradient**, no border (`components.css:13`) | flat `bg-primary` fill (`button.tsx:12`) |
| Type scale | inherited `font:inherit`; badges 11px mono; display face **Big Shoulders Display** exists only here (`tokens.css:53`) | Tailwind `text-sm`/`text-xs`/`text-[15px]`; **no display face at all** |
| Radius scale | ad-hoc literals: 8/10/16/20px | 4-step ramp `--radius-sm/md/lg/xl` (4/8/12/16px) — the two ramps do not line up |
| Icons | **emoji** — hamburger, folder, lightning, table, warning, speech bubble, gear, circled numbers, target, scales, magnifier, ruler | **lucide-react** line icons — `ChevronDown`, `Loader2`, `Check`, `AlertTriangle`, `Braces`, `BrainCircuit`, `Bug` |
| Density | dense multi-panel workspace, full-bleed, three columns | single centred `max-w-2xl` column, `py-8`, generous 24px step gaps |
| Accent | `--signal: #22D3EE` | `--color-primary: #22D3EE` (already unified) **but** `--color-accent: #76b900` Livio green exists only on the pipeline side |
| Font loading | `@fontsource` via `src/fonts.js` + `tokens.css` | `@fontsource` imports in `react/main.tsx:4-7` — two independent loaders for the same faces |

- **Root cause**: an incomplete migration frozen mid-way by an explicit decision not
  to unify tokens.
- **Fix (lazy path)**: keep the Tailwind `@theme` block as the single source and
  redefine `tokens.css`'s vars as aliases onto it (or vice-versa) — one palette, one
  radius ramp, one button geometry. Do **not** rewrite the vanilla panels; just make
  the two token files reference one set of values. Then pick one icon family (lucide)
  and replace the emoji in `index.html`.
- **Complexity**: M (tokens) + M (emoji to lucide). **Dependencies**: none blocking.

### B2. MEDIUM · CONFIRMED — Escape does not close the Results Table modal, and it blocks the toolbar
- **Reproduction**: open "All results", press `Escape` — modal stays. Subsequent
  clicks on "Ask", "Compare with the last run", "Find an element in Revit",
  "Registration wizard" produced no new content while it was open. Each of those
  controls works correctly from a fresh page load.
- **Where**: `frontend/src/panels/table.js` (no `keydown`/Escape handler; the other
  overlays have one).
- **Fix**: one shared `Escape` handler for all overlays.
- **Complexity**: S.

### B3. MEDIUM · CONFIRMED — the "Ask" button is not reachable at 1600x900 on a fresh load
- **Reproduction**: fresh load, `page.click('#btn-chat')` timed out (element not
  actionable) while every other header control clicked fine in the same run. The
  button is present, enabled, `pointer-events: auto` and has an `onclick`.
- **Root cause**: SUSPECTED — an overlapping element or a zero-size hit area at that
  breakpoint. Needs a 5-minute DOM inspection, not a redesign.
- **Ownership**: frontend. **Complexity**: S.

### B4. MEDIUM · CONFIRMED — `GET /api/runs/compare` 404s on every dashboard load
- **Reproduction**: normal load of `/` produces console error "Failed to load
  resource: 404", request `GET http://127.0.0.1:8077/api/runs/compare`.
- **Root cause**: the dashboard eagerly fetches the run-comparison baseline that the
  project does not have. The drawer already handles the empty case gracefully ("NO
  BASELINE — No baseline saved for this project yet"), so the eager fetch is pure
  noise.
- **Fix**: fetch on drawer open, or return 200 with `{present: false}` (the pattern
  `pdf_benchmarks_get` already uses at `backend/app/routers/registration.py:212-221`).
- **Complexity**: S.

### B5. MEDIUM · CONFIRMED — the honest empty-state message is written and then thrown away
- **Where**: `frontend/src/app.js:78` sets `#hdr-stats` to
  `"no data yet — open Pipeline"`, then `:81` immediately does
  `window.location.href = "/pipeline.html"`. The user never sees the sentence that
  explains what happened; they just find themselves on a different page.
- **Reproduction**: load `/` with `madera` active — `GET /api/elements` 409, `GET
  /api/review/queue` 409, silent redirect to `/pipeline.html`.
- **Fix**: render the empty state on the dashboard with an explicit "Open Pipeline"
  button instead of navigating for the user.
- **Complexity**: S.

### B6. Dead / misleading UI — enumerated
- **CONFIRMED · MEDIUM** — Technical-details panel advertises a feature that does not
  exist: *"artifact viewer: available when backend supports `GET /api/artifacts/{key}`"*
  — `StepRow.tsx:152-155`. Shipped copy describing an unimplemented endpoint. Remove
  or implement.
- **CONFIRMED · LOW** — `Report` button (`index.tsx:61-69`) does
  `window.location.href = tokenized("/api/export/punch-list.csv")`. It works, but it
  is unlabelled as a CSV download and gives no feedback; on a project with no
  `element_list` it will navigate to an error response.
- **CONFIRMED · LOW** — Debug SSE panel (`index.tsx:113-132`) is a developer
  affordance shipped in the production surface.
- **CONFIRMED · LOW** — Advanced-menu buttons "1 Extract elements" / "2 Match to
  model" fire a real backend job on click with no confirmation and only a transient
  status line ("Scanning all pages…", "Per-sheet registration + matching…").
  *(Noted: this audit triggered both on `dogwood-lane` while probing the menu — a
  destructive-by-accident control.)*
- **CONFIRMED · LOW** — Benchmark Autopilot drawer renders a full 9-step stepper
  (`PROPOSE · PDF APPROVAL · STAMP PDF · REVIT CONNECT · PLACE MARKERS · REVIT
  APPROVAL · FRESH EXPORT · CALIBRATE · DONE`) with `LIVE LOG — waiting for events`
  before anything has started. Nine future steps advertised up front on a feature
  whose Revit half depends on a live connector.
- **NOT dead (verified working)**: "Compare with the last run" (honest empty state +
  `Save as baseline`), "Find an element in Revit" (`Lookup`, `Use current Revit
  selection`), "Review queue" (25 items, "0 OF 25 REVIEWED"), "Projects" (7 projects
  with real input badges), "All results" (full table with a genuinely good "Export
  scope" warning banner).
- Pipeline page has **no** dead controls: `Run`, `Force`, `Report`, `Grid` toggle,
  `Dash` link, step expanders and the debug toggle all act. A previous disabled
  "Stop" placeholder was already removed (`index.tsx:55-60`).

### B7. Console errors and HTTP >= 400 on a normal load (Q7)
- `/` (dashboard, active project `madera`): `409 GET /api/elements`,
  `409 GET /api/review/queue`, two matching console errors, then the silent redirect
  (B5).
- `/` (dashboard, project with data): `404 GET /api/runs/compare` + one console error
  (B4). No `pageerror`, no uncaught exceptions.
- `/pipeline.html`: **no** HTTP >= 400, **no** console errors.
- Note: neither page ever reaches `networkidle` — the SSE stream is open forever by
  design; `waitUntil: "networkidle"` will always time out in tests.

### B8. LOW · CONFIRMED — horizontal overflow at 375px on the dashboard only (Q8)
`document.documentElement.scrollWidth` vs `window.innerWidth`, both pages:

| Width | Dashboard docEl / innerWidth / body | Pipeline docEl / innerWidth |
|---|---|---|
| 1600 | 1600 / 1600 / 1600 | 1600 / 1600 |
| 1100 | 1100 / 1100 / 1100 | 1100 / 1100 |
| 700 | 700 / 700 / 700 | 700 / 700 |
| 375 | 375 / 375 / **423** | 375 / 375 |

- `documentElement` never overflows on either page — the responsive work holds.
- At 375px the dashboard's `body.scrollWidth` is 423 (48px over): a child is wider
  than the viewport and is being clipped rather than reflowed. Most likely the
  header's fixed-width control row or the sheet-tab strip.
- **Fix**: find the offending child with an `outline: 1px solid red` sweep at 375px;
  add `min-width: 0` / wrap to that row. **Complexity**: S.

---

## Prioritised order

1. **A1** SSE bus has no project/run identity, so a skipped stage renders green. CRITICAL.
2. **A3** soft-failing handlers (ransac `ok:false`) recorded as success — fix once in `run_engine` via an output-artifact assertion. HIGH.
3. **A2** all-skipped run reports "completed". HIGH.
4. **A4** `pdf_intelligence` persists an ERROR artifact that then caches as "already run". HIGH.
5. **A5** `next_action` computed and never rendered. HIGH, cheapest high-value fix.
6. **B1** two design systems (tokens, radii, buttons, emoji vs lucide, density). HIGH.
7. **A6 / A7 / A8** skipped looks like pending; reasons are raw artifact keys; input inventory hidden in another page's modal. MEDIUM.
8. **B2 / B3 / B4 / B5** Escape-proof modal, unclickable "Ask", 404 on load, honest-message-then-redirect. MEDIUM.
9. **A9, B6, B8** ACTIVE badge on every project, dead/aspirational copy, 375px overflow. LOW.
