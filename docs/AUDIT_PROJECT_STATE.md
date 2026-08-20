# Audit: Active-Project State, Open Flow, and Project Creation

Read-only audit. No code modified. Backend live at http://127.0.0.1:8077, active project `madera`.

Legend: **CONFIRMED** = read in code / observed on disk. **SUSPECTED** = inferred, not executed.

---

## 1. Where "which project is active" lives

| # | Store | Location | Scope / lifetime | Written by | Read by |
|---|-------|----------|------------------|-----------|---------|
| 1 | `artifacts/active_project.json` | `backend/app/config.py:22`, written `config.py:117` | **Global, process-wide, persisted on disk** | `set_active_project()` — only `POST /api/projects/activate` (`projects.py:259`) and `POST /api/upload` (`projects.py:328`) | `active_project()` `config.py:75-82` |
| 2 | `_PROJECT_SLUG` ContextVar | `config.py:49`, set in `bind_project()` `config.py:102` | **Per-request** (Starlette copies context into the sync threadpool) | `project_context` dependency `common.py:51` | `config.__getattr__` `config.py:56` → ARTIFACT_DIR/EVIDENCE_DIR/UPLOAD_DIR/PAGES_DIR |
| 3 | `X-Project` header / `?project=` query | `common.py:47-51` | Per-request, client-supplied | *nobody in the shipped frontend* (see #5) | `project_context` |
| 4 | `projectHeader` module variable | `frontend/src/shared/api.ts:49-51` | Per browser tab, in-memory | `setProjectHeader()` — **zero call sites** (grep: only the re-export in `frontend/src/api.js:9`) | `authHeaders()` `api.ts:58` |
| 5 | `pipelineApi(project?)` per-call arg | `shared/api.ts:94,102,110-118` | Per call | **no caller passes it** (`react/state/run-context.tsx:83,97` call `api.runState()` / `api.runPipeline(force)` with no project) | |
| 6 | `run_state.json.project` | written by `run_engine.py`; read at `usePipeline.ts:144` | Snapshot of the active project *at run start* | run engine | Pipeline Island header badge |
| 7 | Dashboard header label | `app.js:34-42` — derives from `GET /api/projects` `.find(x => x.active)` | Per page load | — | display only |
| 8 | `frontend/src/store.js` | — | — | **holds no project field at all** | — |
| 9 | localStorage | only `qaqc_token` (`api.ts:36`) | — | — | **no project key** |
| 10 | URL | `index.html` / `pipeline.html` carry **no project param** | — | — | — |

**Single source of truth: yes, but the wrong one.** Every UI surface ultimately resolves through
`active_project.json` (#1) because #3/#4/#5 are all wired and all unused. The backend was
deliberately refactored (BUG-03) to be request-scoped and per-client — and the frontend never
adopted it, so the system behaves exactly like the global-mutable-state design the refactor
replaced. The ContextVar isolates *concurrent requests*, not *concurrent users*: every request
without a header falls back to the one global file.

### Where they can disagree — CONFIRMED

- **Two browser tabs on different projects.** Tab A opens project X (`POST /activate` rewrites
  `active_project.json`). Tab B, already loaded on project Y, issues its next fetch with no
  `X-Project` header → `common.py:49` falls back to `active_project()` → **serves X's data under
  Y's rendered header, silently**. Nothing in tab B detects the swap. **CRITICAL.**
- **Pipeline Island badge vs. real active project.** `usePipeline.ts:144` shows
  `run.project` — the project the *last run* was started under. After a switch the badge shows
  the old slug until a new run starts; `run` is null before any run, so the badge disappears
  rather than showing the current project. **MEDIUM.**
- **`_workspace_dir` vs. `bind_project`.** `POST /api/upload` calls `config.set_active_project(slug)`
  at `projects.py:328` for a slug that may not exist yet, mutating the global preference as a
  *side effect of an upload* — an upload in one tab retargets every other tab. **HIGH.**
- **`active_project()` raises `ValueError`** when the file is missing (`config.py:82`). It is
  called unguarded in `elements.py:354,460`, `projects.py:367`, `revit.py:160`, `teach.py:118,138`
  → uncaught `ValueError` = HTTP 500 on a fresh install with no projects. `projects.py:79`
  (`_active_slug`) is the only caller that guards it. **HIGH, SUSPECTED** (not executed; `main.py`'s
  `_init()` swallows the same error at boot, so the file legitimately can be absent).

**Fix (all of the above, one change):** let the frontend own the project and always declare it.
Persist the slug in `localStorage` on open, call `setProjectHeader(slug)` at boot of both entry
points (`app.js` boot, `react/main.tsx`), and demote `/activate` to what its own docstring already
claims it is — a default for *new* sessions. Owner: **frontend + one line of API layer**.
Complexity **S** (the seam already exists at `api.ts:49-58`). Dependency: SSE cannot carry a
header (`use-pipeline-events.ts:12`), so the EventSource URL needs `?project=` appended via the
existing `tokenized()` pattern (**S**, same change).

---

## 2. "Open project" flow — `ProjectManager.tsx`

**What Open does — CONFIRMED** (`ProjectManager.tsx:423-433`):
1. `POST /api/projects/activate {slug}` — rewrites the global `active_project.json`. Nothing else.
2. `toast("Opening …")`.
3. `setTimeout(() => location.reload(), 500)`.

It does **not** set a header, does **not** touch `setProjectHeader`, does **not** update any local
store. The full-page reload *is* the state-propagation mechanism (documented deliberately at
`ProjectManager.tsx:16-18`). Same pattern for delete-then-switch (`:481-497`, 600 ms).

**Race — CONFIRMED, HIGH.** Two of them:
- The 500 ms `setTimeout` is a fixed guess, not a sequencing guarantee. Any in-flight fetch issued
  between the `activate` response and the reload (`app.js` `loadAll`, `revit_live.js`'s 15 s status
  cache refresh, the SSE stream) resolves against the **new** project and paints into the **old**
  DOM. Reproduction: open the manager while a run is streaming, click Open on another project,
  watch the element/verdict panes repaint with the other project's data for ~500 ms before reload.
- Cross-tab, the race is unbounded: other tabs never reload at all (§1).
- Root cause: activation is a *server-global* write with a *client-local* refresh strategy. The
  reload only re-syncs the tab that performed the write.
- Fix: same as §1 — carry the slug per request; Open then becomes a local state change and the
  reload/`setTimeout` can be deleted outright. **S** once §1 lands, **M** standalone.

---

## 3. Does `/pipeline.html` resolve the same project as the dashboard?

**CONFIRMED — yes, by accident, and it will drift.**

- `pipeline.html` mounts `react/main.tsx` → `App.tsx` → `RunProvider` → `PipelineIsland`.
- All its calls go through `shared/api.ts` with `projectHeader === null` (never set), so every
  request hits `active_project.json` — the same file `api.js` resolves through on the dashboard.
- The Pipeline Island *displays* `run.project` (`usePipeline.ts:144`), a **stale snapshot**, not the
  resolved project. The two surfaces therefore agree on *data* and can disagree on *label*.
- **Two tabs on different projects: impossible to sustain.** There is exactly one active project
  server-side. The last tab to press Open wins for both. The losing tab keeps its stale badge and
  stale rendered data while every new fetch it makes returns the winner's project. No error, no
  banner, no reload. **CRITICAL, CONFIRMED.**
- Severity is amplified by the domain: this tool issues QA verdicts. Rendering project X's element
  verdicts under project Y's name is a wrong-answer bug, not a UX bug. The backend already treats a
  cousin of this as its most expensive failure — see the wrong-model ingest guard, `revit.py:141-149`.

---

## 4. Project creation and the dead-end state

**Minimum to create — CONFIRMED:** a name. `NewProjectForm` (`ProjectManager.tsx:255-330`) requires
only `name`; `client`, `revision` and the PDF file input are all optional. `POST /api/projects`
creates the directory tree and manifest (`projects.py:200-207`). The form's own copy says an empty
project "is a valid state, not a half-finished one" (`:307`).

**Can a project be permanently stuck? — CONFIRMED, yes. `madera` is the live example.**
- `artifacts/projects/madera/project_manifest.json` has `pdf_path` but **no `revit_path`**.
- `run_state.json`: `revit_convert`, `ransac`, `compare`, `match` are all `"status": "skipped"`,
  `"reason": "waiting on: raw_revit"` — while the run's top-level `"status": "completed"`.
- Root cause of the misleading verdict: `run_engine.py:192-194` sets `completed` whenever the run
  finishes without a *failed* stage; `skipped` is not counted (`:200` checks only `failed`). A run
  in which the four answer-producing stages never executed reports success. **Backend ownership,
  HIGH.** Fix: a third terminal status (`incomplete` / `blocked`) when any stage is skipped for a
  missing prerequisite, surfaced in the timeline. **S**.
- `GET /api/elements` → **409** (`common.py:83-88`, "Required artifact … not found").
- `app.js:81`: `if (!ok) { if (first) window.location.href = "/pipeline.html"; return; }` — the
  dashboard **silently teleports** to the pipeline page on any elements failure. The `catch` at
  `:76-78` sets the header to "no data yet — open ⚡ Pipeline", which the user never reads because
  the redirect fires immediately. A 409 (missing input) and a 500 (broken backend) are
  indistinguishable to the user. **HIGH, frontend ownership.** Fix: don't redirect; render the 409
  `detail` as an empty state naming the missing artifact. **S**.

**Does any UI say what is missing?**
- Yes, in exactly one place, and only as a fact, not an action: the project card's `Facts` row
  renders `"no Revit export"` (`ProjectManager.tsx:47`) from `has_revit` (`projects.py:100`).
- The Pipeline timeline shows the skipped stages' `reason` (`"waiting on: raw_revit"`) — an internal
  artifact key, not a user instruction. **SUSPECTED** the user cannot decode it.
- Nowhere does anything say "this project needs a Revit export, here is how to add one". **HIGH.**

---

## 5. UI affordances for getting Revit data into a project

**There are none. CONFIRMED.** A user cannot add a Revit export through this UI at all.

Evidence:
- The string `revit_json` — the `POST /api/upload` file parameter (`projects.py:303`) — appears
  **nowhere** in `frontend/src` (grep, whole tree).
- The only `<input type="file">` in the entire frontend is `name="pdf" accept=".pdf"`
  (`ProjectManager.tsx:320`). The only `FormData` builder appends only `pdf` (`:284-286`).
- `POST /api/revit/ingest` (`revit.py:107`) — the zero-upload watch-dir auto-ingest — has **no
  frontend caller** (grep `revit/ingest` in `frontend/src`: no hits). Reachable only by hand.
- `GET /api/revit/export-status` is polled by `panels/revit_live.js:35` and `paintRevitPill`
  (`revit_live.js:51`) renders the state — but `paintRevitPill` is **imported at `app.js:15` and
  never called** (grep: import only, zero call sites). The status pill is dead code.
- `app.js:150-152` states it outright: the guided upload modal including `revitUpload` "was
  superseded … and removed" — superseded by the Pipeline Island, which has no upload control
  (`PipelineIsland/index.tsx`: Run / Force / Report only; `PipelineTimeline.tsx:16` tells the user
  to "upload a drawing to begin" with no way to do so).
- The Benchmark Wizard instructs the user to "run the Livio exporter … then upload the JSON"
  (`Wizard.tsx:522`) — a step the UI does not implement.

**This is the root cause of madera.** The product's core comparison requires Revit data; the only
supported ingest paths are the watch-dir auto-ingest (no UI trigger) and a multipart field no UI
sends. Severity **CRITICAL**. Ownership **frontend**; the API is already complete.

Fix, cheapest first:
- **S** — add `<input type="file" name="revit_json" accept=".json">` to `NewProjectForm` and append
  it to the same `FormData`. The endpoint already accepts both files in one call.
- **S** — actually call the already-written `paintRevitPill` so connector state is visible.
- **M** — an "Add Revit export" action on any project card where `has_revit === false`, wired to
  `/api/upload?project=<slug>` and offering `POST /api/revit/ingest` when
  `/api/revit/export-status` reports a pending file.
- Dependency: the upload-only path calls `set_active_project` as a side effect (§1) — fix §1 first,
  or pass `?project=` explicitly (the create form already does, `ProjectManager.tsx:286`).

---

## Prioritized findings

| # | Severity | Status | Finding | Where | Owner | Fix | Cx |
|---|----------|--------|---------|-------|-------|-----|-----|
| 1 | CRITICAL | CONFIRMED | No UI can attach a Revit export; `revit_json` unused in frontend | `ProjectManager.tsx:320`, `projects.py:303` | frontend | add file input to existing FormData | S |
| 2 | CRITICAL | CONFIRMED | Active project is one global file; a second tab silently serves another project's verdicts | `config.py:22,117`, `common.py:49`, `api.ts:49` | frontend + API layer | call `setProjectHeader`, persist slug per tab, `?project=` on SSE | S–M |
| 3 | HIGH | CONFIRMED | Run reports `completed` with 4 answer-producing stages `skipped` | `run_engine.py:192-200` | backend | terminal `incomplete` status when any stage skipped for a prereq | S |
| 4 | HIGH | CONFIRMED | Dashboard silently redirects to /pipeline.html on any `/api/elements` failure | `app.js:81` | frontend | render the 409 detail as an empty state | S |
| 5 | HIGH | CONFIRMED | `POST /api/upload` mutates the global active project as a side effect | `projects.py:328` | backend | `bind_project` unless explicitly activating | S |
| 6 | HIGH | SUSPECTED | `active_project()` `ValueError` unguarded in 6 call sites → 500 on fresh install | `config.py:82`; `elements.py:354,460`, `revit.py:160`, `teach.py:118,138` | backend | route through an `_active_slug()`-style guard | S |
| 7 | HIGH | CONFIRMED | Nothing tells the user *what* is missing or *how* to supply it | `ProjectManager.tsx:47`, timeline `reason` strings | frontend | blocked-state card naming the missing input + its action | M |
| 8 | MEDIUM | CONFIRMED | Open = server write + `setTimeout(reload, 500)`; in-flight fetches resolve against the new project | `ProjectManager.tsx:424-431` | frontend | falls out of #2 | S |
| 9 | MEDIUM | CONFIRMED | Pipeline badge shows `run.project` (stale snapshot), blank before first run | `usePipeline.ts:144` | frontend | show the resolved active project | S |
| 10 | LOW | CONFIRMED | `paintRevitPill` imported, never called — connector status invisible | `app.js:15`, `revit_live.js:51` | frontend | call it, or drop the import | S |
| 11 | LOW | CONFIRMED | `setProjectHeader` / `pipelineApi(project?)` are dead seams | `api.ts:50,94,102` | frontend | consumed by #2 | S |

**Dependency order:** #2 unblocks #8 and #9 and de-risks #1 and #5. #3 and #4 are independent and
are the two cheapest changes that would have made madera's dead end visible instead of silent.
