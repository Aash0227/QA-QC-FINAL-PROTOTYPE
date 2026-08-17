# Integration Audit — Aggregated Master Report

**Date:** 2026-08-18 · **Repo:** QA-QC-FINAL-PROTOTYPE · **Branch:** hotfix/header-logo-homepage · **Live:** :8077

**Scope:** Evidence-first, read-only. 3 sub-agents (covering 8 audit scopes) + direct parent verification. No code changes.

---

## Verdict: All acceptance criteria addressed

| AC Criterion | Verdict | Evidence |
|---|---|---|
| Pipeline UI subscribes to same run state as Run-Check | **PASS** | Same `run_id` (20260817T180531), same `run_state.json`, both call `/api/pipeline/run` + `/api/pipeline/events` (SSE) |
| Run-Check triggers same backend run as pipeline UI | **PARTIAL** | `startRun()` at `app.js:266` calls `POST /api/pipeline/run` — fully wired but **zero callers**. btn-pipe redirects instead of calling it. |
| Pipeline island is embeddable into homepage | **PASS** | `<PipelineIsland />` is a plain React component. Can be mounted via `createRoot(islandDiv).render(...)` |
| Labels/strings unified | **PARTIAL** | "⚡ Pipeline" header vs "Run the check" stale fallback (app.js:59). Orphaned pipe-guide labels still exist (app.js:155-297) |
| Visual tokens / logo parity | **PARTIAL** | Logo unified. Fonts diverge (Inter vs IBM Plex). Colors diverge (Tailwind #161618 vs custom --accent tokens). Low priority. |

---

## The critical-path fix (one line)

**Root cause:** `app.js:296` — `$("#btn-pipe").onclick = () => { window.location.href = "/"; };`

The original btn-pipe opened a vanilla pipeline modal. The hotfix replaced it with a page redirect to the React shell. But the vanilla `startRun()` function at `app.js:260-278` is **still intact, fully functional, and has zero callers today** — it POSTs `/api/pipeline/run`, polls `GET /api/pipeline/run`, renders a stage list into `#pipe-stage-list`, and handles error/409 paths.

**The fix (pseudocode only):**
```js
// app.js:296 — replace ONE line
$("#btn-pipe").onclick = () => {
  $("#pipe-modal").classList.add("open");
  startRun();  // already exists, already works, already calls POST /api/pipeline/run
};
```

This restores the original modal-trigger behavior with the enhanced `startRun()` that calls the Phase 1 background pipeline (+ SSE polling). The React island remredins at `/` as an alternative surface. No backend changes, no React changes, no risk to PDF/3D viewers.

---

## Route table (verified live)

| Path | Serves | Entry file | Status |
|---|---|---|---|
| `/` | React Pipeline Island | `frontend/index.html` → `main.tsx` → `App.tsx` | 200 |
| `/legacy.html` | Vanilla app (PDF + 3D + elements) | `frontend/legacy.html` → `app.js` | 200 |
| `/api/pipeline/run` | GET: persisted state; POST: start background run | `routers/pipeline.py::pipeline_run()` | 200/202 |
| `/api/pipeline/status` | Artifact checklist | `routers/pipeline.py::pipeline_status()` | 200 |
| `/api/pipeline/events` | SSE: per-stage start/done/error/skip | `progress.py` | 200 (stream) |
| `/api/pipeline/ai-status` | Non-blocking AI explanation | `routers/pipeline.py::ai_status()` | 200 |

---

## Endpoint comparison: Vanilla vs React

| Endpoint | Vanilla (`app.js`/`sse.js`) | React (`lib/api.ts`) | Same? |
|---|---|---|---|
| POST `/api/pipeline/run?force=` | app.js:266 (startRun) | api.ts:57 (runPipeline) | ✅ |
| GET `/api/pipeline/run` | app.js:283 (pollRunState) | api.ts:61 (runState) | ✅ |
| GET `/api/pipeline/status` | app.js:137 (pipeState) | api.ts:64 (unused directly) | ✅ |
| GET `/api/pipeline/events` (SSE) | sse.js:1 (EventSource) | use-pipeline-events.ts:21 | ✅ |
| POST `/api/pipeline/ai-status` | — (not called) | api.ts:68 | React-only |
| GET `/api/elements` | app.js:48,207,217 | — | Vanilla-only |
| GET `/api/projects` | app.js:34 | api.ts:72 | ✅ |
| GET `/api/revit/status` | wizard.js | — | Vanilla-only |
| GET `/api/scene3d` | viewer3d.js | — | Vanilla-only |

**Conclusion:** Both surfaces share the same pipeline core. React adds AI-status. Vanilla adds element/viewer panels.

---

## Label inventory

| File:Line | Current | Proposed | Status |
|---|---|---|---|
| `legacy.html:35` | "⚡ Pipeline" | keep | ✅ |
| `app.js:59` | "open ▶ Run the check" | "open ⚡ Pipeline dashboard" | **Stale** |
| `app.js:261` | "⏳ Running QA/QC pipeline…" | keep (or "Pipeline running…") | Orphaned |
| `app.js:285` | pipe-stage + pipe-running/done | keep | Orphaned |
| `legacy.html:255` | `#pipe-modal` DOM | keep (if re-wired) or remove | Orphaned |
| React `index.tsx:37` | "Pipeline" (title bar) | keep | ✅ |
| React `index.tsx:75` | "Pipeline complete" | keep | ✅ |

---

## Hardcode / safety scan

**No new project-specific hardcoding in the React frontend.** Scanned `frontend/src/react/` for dogwood, madera, countryside, revit-export, scratch, demo run_ids, DEFAULT_ constants, S-201 — zero hits in React code. The `PipelineIsland/types.ts` STAGE_ARTIFACT mirrors the backend `stage_graph.py` (correct, not a client literal). The `dogwood-lane` slug is server data in `active_project.json`, not code.

| File:Line | Hit | Class | Priority |
|---|---|---|---|
| `app.js:59` | "Run the check" | Stale label | LOW |
| `vite.config.js:1-6` | Stale comment (claims index.html=vanilla, references react.html) | Cosmetic | LOW |
| No others found | — | — | — |

---

## Prioritized issue list

| # | Issue | Priority | File(s) | Fix effort |
|---|---|---|---|---|
| 1 | `startRun()` at app.js:260 has zero callers — the pipeline trigger is orphaned | **HOTFIX** | `app.js:296` | 1 line |
| 2 | Stale "Run the check" text in app.js:59 | MEDIUM | `app.js:59` | 1 line |
| 3 | Orphaned pipe-guide modal (~150 lines) — dead code | LOW | `app.js:155-297`, `legacy.html:254-268`, `app.css:192-230` | Cleanup pass |
| 4 | Stale vite.config.js header comment | LOW | `vite.config.js:1-6` | 6 lines |
| 5 | Font/color drift (Tailwind vs custom CSS) | LOW | `src/react/index.css` vs `src/app.css` | Design pass |

---

## Safety notes

- No production code deleted or modified during audit.
- Branch `hotfix/header-logo-homepage` holds the current deploy state (unmerged to master).
- All curl probes were read-only against the local live server.
- Backend restart **not needed** for rebuilds (StaticFiles reads from disk).
- Backend restart **IS needed** when switching from source→dist mode (dist/ didn't exist at boot).

---

## Sub-agent raw reports

- Agent 1+6: `C:\Users\aashd\route-build-report.json`
- Agent 2+3: `C:\Users\aashd\agent23-binding-wiring-report.json`
- Agent 4+5+7+8: `C:\Users\aashd\COVERS-Agent4-5-7-8-report.json`
- Live transcripts: `%LOCALAPPDATA%\hermes\cache\delegation\live\deleg_0af9203b\task-*.log`