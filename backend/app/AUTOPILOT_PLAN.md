# Benchmark Autopilot + Dashboard Evolution — Plan (approved 2026-07-16)

## Context
Proved the 2-benchmark registration end-to-end with ZERO human clicks: agent read
the live Revit model via Nonica MCP Pro, placed BM-1/BM-2 markers, stamped the real
permit PDF, ran extract+calibrate, transform matched the weeks-old trusted one to
~1e-5 pt. User wants this standardized as a repeatable, human-approved, webapp-
visible workflow, plus visibility gaps closed, plus UI evolved toward the
docs/session-report-benchmark-registration.html aesthetic, plus a skill capturing
the automated procedure.

## What was lacking (at plan time)
1. Revit model with placed markers still UNSAVED (session-only) — no fresh export
   with "Benchmarks: 2" yet. ACCEPTANCE LOOP NOT CLOSED.
2. Webapp never showed the benchmark stamps: Madera's PDF read from a Downloads
   path, stamped PDF not "uploaded" as project artifact, no PDF overlay or 3D
   rendering of benchmarks.
3. No tabular results view — only the grouped left list.
4. 3D scene is boxes/spheres from bbox data; below Revit reference fidelity
   (docs/UI-UX-V2-PLAN.md B4, still open).
5. Benchmark process lived only in chat — no skill, no state machine, no UI.
6. Known bugs from AGENT_HANDOFF.md: scene3d.py `if c.get("z")` z==0.0 truthiness
   bug (~line 89); element_registry.py duplicate-sheet dict overwrite (~line 35).
7. ALSO DISCOVERED DURING RE-MATCH TESTING (already fixed, see below): compare.py
   line 39 had corrupted identifier "group. ed" instead of "grouped"; main.py
   elements_match crashed on dict+list TypeError when resolutions re-applied.

## Scoping decisions (already agreed with user)
- UI restyle STAGED: Phase 4 wizard ships first in the full report aesthetic +
  design tokens applied to dashboard; deep dashboard restyle is the LAST phase
  (P6), with index_v3_backup.html kept as fallback per project rule.
- Automation actor = Claude agent + webapp approvals. Backend cannot drive Revit —
  only a Claude session with Nonica MCP can. Webapp holds state machine + approval
  UI; agent (running new skill) executes and advances state via API calls.

## PHASES (order: P0 -> P1 -> P2 -> P3 -> P4 -> P7 -> P5 -> P6)
Gate after EVERY phase: `python -m pytest -q` green (98+ baseline), Madera MATCH
count unchanged/improved (baseline 107), dashboard loads, backup synced.

### P0 — Close today's loop (STATUS: bug patches NOT applied — blocked by tool outage)
1. USER ACTION (blocking, not agent-doable): save/sync Revit model (Ctrl+S) —
   markers 3951194 (BM-1, grid A x 1) and 3951193 (BM-2, grid C x 3) are
   session-only until saved. Then run Livio exporter, confirm dialog shows
   "Benchmarks: 2", save the JSON.
2. Agent: upload fresh export via POST /api/upload, re-run pipeline, confirm
   benchmarks arrive through collect_benchmarks() (real exporter path, removing
   the raw_revit_export.json injection provenance used in today's proof), re-run
   POST /api/registration/benchmarks.
3. Apply 2 leftover patches:
   - backend/app/scene3d.py ~line 89: change
     `"elevation_ft": round((c.get("z") or 0.0) - z0, 2) if c.get("z") else 0.0,`
     to a version using `c.get("z") is not None` (a real elevation of 0.0 was
     being treated as missing).
   - backend/app/element_registry.py ~line 35-37: dict comprehension keyed by
     sheet_number silently drops marks if two sheets share a number — iterate
     the original list instead of rebuilding via dict.
4. Test: pytest -q (expect 98 passed), re-run /api/elements/match, confirm
   MATCH counts >= 107 (baseline), device_summary unchanged from today's numbers
   (holdown: 44 MATCH/16 LM/4 PDF_ONLY/1 MARK_MISMATCH/11 REVIT_ONLY).

### P1 — Benchmarks visible everywhere
1. backend/app/main.py: fix project_manifest.pdf_path for madera so it points
   into artifacts/projects/madera/uploads/ instead of relying on the Downloads
   SAMPLE_PDF fallback (_project_pdf_path()) — copy the stamped PDF in.
2. backend/app/scene3d.py: add "benchmarks" key to build_scene() output from
   raw_revit["benchmarks"] (id, mark, point_ft/x,y,z) — additive, no schema break.
3. frontend/index.html: in renderOverlay() (~line 546), when active sheet matches
   pdf_benchmarks.json's page_index, draw BM-1/BM-2 as pulsing crosshair+ring
   markers (vermilion), reuse .pulse-ring animation; add "Benchmarks" chip to
   renderLayerToggles() (~line 648).
4. frontend/index.html: 3D view — render scene.benchmarks as glowing labeled
   markers (reuse flyBallTo pattern ~line 964, makeLabelSprite ~line 801),
   distinct color from status colors.
5. Test: reload dashboard, confirm BM-1/BM-2 visible on S-201 PDF overlay AND in
   3D view with labels; Playwright screenshot both panes.

### P2 — Tabular results view
1. New full-width collapsible section below #main (adjust #app grid-template-rows
   from "64px 1fr" to "64px 1fr auto").
2. Table: sortable/filterable columns (mark, category, sheet, status,
   distance_ft, device_id, reason) from element_list.elements.
3. Header toggle button "Table" to show/hide; row click calls existing select()
   function to sync PDF+3D+list.
4. Style per report aesthetic tokens (mono numerals, status pills).
5. Test: Playwright — table renders, sort works, filter works, row-click selects
   correctly across all 3 panes.

### P3 — Autopilot backend (state machine)
1. New artifact key "benchmark_workflow": "benchmark_workflow.json" in
   config.ARTIFACT_FILES (backend/app/config.py).
2. New module backend/app/benchmark_workflow.py:
   States: idle -> proposing -> awaiting_pdf_approval -> stamping ->
   awaiting_revit -> placing_markers -> awaiting_revit_approval ->
   awaiting_export -> calibrating -> done/failed (each with timestamp, actor,
   payload, note — audit trail like review.py's resolution blocks).
3. New endpoints in main.py:
   - POST /api/benchmark-workflow/propose — reuse
     grid_registration.detect_pdf_grid_positions() + pdf_grid_control_points()
     to find labeled grid intersections in PDF points on the plan sheet; pick
     the two with MAX diagonal separation (no circular transform dependency —
     works on brand-new unregistered projects); render evidence crops (reuse
     review.render_evidence_crop pattern); save proposal, state ->
     awaiting_pdf_approval.
   - POST /api/benchmark-workflow/approve {step, approved, comment} — human
     decision, audit-logged.
   - POST /api/benchmark-workflow/advance {step, data} — agent reports step
     completion (stamped coords, Revit element ids, export received, etc).
   - GET /api/benchmark-workflow — full state for UI; also emit via existing
     progress.emit() -> SSE (/api/pipeline/events).
4. Guard rail: calibration only ever saved through the EXISTING gated
   POST /api/registration/benchmarks (match_allowed gates unchanged) — the
   workflow state machine can never itself mint a transform.
5. Test: new pytest file test_benchmark_workflow.py — state transitions valid,
   propose picks max-diagonal pair (synthetic fixture), approve required before
   advance, invalid transitions rejected.

### P4 — Autopilot wizard UI (the showcase deliverable)
1. New panel in frontend/index.html, opened via header button "Benchmark
   Autopilot", built in session-report aesthetic (Big Shoulders Display +
   IBM Plex fonts, ink/vermilion/signal palette — reference
   docs/session-report-benchmark-registration.html for exact tokens/animations).
2. Vertical step rail mirroring the state machine, live via GET
   /api/benchmark-workflow + SSE.
3. Proposal card: PDF crops of both intersections with animated crosshair
   lock-on (adapt the diagram proximity-lock pattern from the report page).
4. Approve/Reject buttons reuse .resolve-btn animated pattern (pulse glow).
5. Second approval after Revit placement: show read-back coordinates vs
   intended, delta in ft.
6. Terminal-style live log of agent actions (reuse .steplog CSS class).
7. Keep index_v3_backup.html synced after edits (mandatory project rule).
8. Test: Playwright — open wizard, propose fires, crops render, approve/reject
   buttons animate correctly, SSE log updates live during a real or mocked run.

### P7 — Skill + memory (do this after P4, before P5/P6)
1. Create .claude/skills/benchmark-autopilot/SKILL.md capturing the PROVEN
   zero-click procedure from 2026-07-16:
   - Nonica connection checklist: MUST be NonicaTab PRO (Free blocks all set_/
     create_ tools); connector must show "SUCCESSFULLY RUN" in Revit before any
     MCP call; get_active_view_in_revit to verify connection first.
   - Pinned-element copy trick: mcp__Revit__set_copy_elements fails with
     "Element is Pinned" on a zero-vector copy of a pinned element — copy WITH
     a translation vector first (to the 2nd grid point), then copy that result
     back by the reverse vector to land on the 1st point. Confirmed clean
     framing-dimension vectors validate correct grid math (58'-8" / 57'-5.5").
   - Exact coordinates come from raw_revit_export.json grids[] line endpoints,
     NOT from the 2-decimal display in get_location_for_element_ids.
   - set_parameter_value_for_elements with idParameter -1001203 sets Mark.
   - PDF stamping: PyMuPDF page.add_circle_annot() with set_info(subject="BM-1")
     — ALWAYS backup the real PDF first (.pre_benchmarks.bak.pdf pattern);
     project S-201's PDF page index via pdf_page_intelligence.json
     ["page_index"], not hardcoded.
   - Gate expectations: extract confidence 0.98 for annotation_stamp method;
     calibrate agrees with existing trusted transform to ~1e-5 pt when correct.
   - Failure table: from docs/BENCHMARK-SOP.md (mark not found, benchmarks too
     close, scale mismatch, chirality conflict, no benchmarks in export).
   - Reference runner: backend/run_benchmark_acceptance.py.
   Written to drive the P3/P4 state machine steps directly (propose -> stamp ->
   place -> approve -> export -> calibrate).
2. Update user memory (qaqc-project-state.md) with workflow + skill pointer.
3. Test: run the skill's documented steps against a SECOND project (Dogwood)
   as a dry run — confirms the skill generalizes beyond Madera.

### P5 — 3D fidelity pass (time-boxed, data-driven only)
1. Use per-element bbox from v3 export for true member sizes (scene.framing
   already does this — extend pattern to walls with real height_ft where
   present, foundations as slabs, grid labels at both ends not just one).
2. Use Nonica Pro live reads (get_boundingboxes_for_element_ids) to spot-verify
   5-10 members' dimensions against the live model; correct scene3d.py mapping
   only where the export data was actually wrong. NEVER invent geometry.
3. Test: side-by-side screenshot vs user's real Revit view; scene counts ==
   export counts; click-select still works; no regression in existing 3D tests.

### P6 — Full dashboard restyle (final phase)
1. Apply report-aesthetic tokens across the WHOLE app: swap :root CSS variables
   (fonts via Google Fonts import, ink background, panel/line colors from
   session-report-benchmark-registration.html), restyle header/toolbar
   grouping, list rows, drawers, pipeline modal. Add reveal/count-up
   micro-interactions where cheap.
2. CSS + small classname additions ONLY — no DOM/logic restructure, no
   framework rewrite (per docs/UI-UX-V2-PLAN.md B3 constraint).
3. Sync index_v3_backup.html.
4. Test: full Playwright smoke suite — drawers hidden by default, each opens
   only via its own button, pipeline runs end-to-end, select() flow works
   across PDF/3D/list, no visual regressions vs a reference screenshot.

## Progress as of context loss
- Plan approved by user via /goal command (session-scoped Stop hook enforcing
  completion with per-phase testing).
- P0 step 3 (bug patches) was ATTEMPTED but blocked: Edit/Write/Bash/PowerShell/
  TaskCreate/ToolSearch/AskUserQuestion/ExitPlanMode all returned "exists but is
  not enabled in this context" — only Read/Grep/Glob remained callable for the
  rest of that session. NO FILES WERE ACTUALLY MODIFIED by that failed attempt.
- Everything from "What was lacking" item 7 (compare.py corruption, main.py
  TypeError) WAS ALREADY FIXED in the prior session (see AGENT_HANDOFF.md,
  entry "FULL RE-MATCH UNDER benchmark_verified") — confirmed by 98 pytest
  passing before the tool outage. Do not re-diagnose these as new bugs.
- P0 items 1 (user saves Revit model + re-exports) status UNKNOWN — verify
  fresh export exists with real benchmarks before assuming step 2 is needed.

### 2026-07-17 (sonnet session — P0/P1/P2 DONE, gate green)
- **P0**: item 1 (user Ctrl+S the Revit model + re-run exporter) is a human
  action, NOT agent-doable — still not done, raw_revit_export.json benchmarks
  still carry `source:"nonica_live_mcp_2026-07-16"` (the injection-proof
  provenance), not a real exporter re-export. Item 2 (re-upload) is blocked on
  item 1 — skipped. Item 3 (the 2 code patches) DONE:
  scene3d.py ~L89 elevation_ft now uses `c.get("z") is not None` (was a
  truthiness bug dropping real z=0.0); element_registry.py ~L133 now iterates
  `element_intelligence["sheets"]` directly instead of the deduped
  `sheets_meta` dict (was silently dropping marks from any sheet sharing a
  sheet_number with another sheet). compare.py "grouped" corruption was
  already fixed in a prior session — verified clean, no action needed.
  Item 4 verified: 98 pytest green, /api/elements/match MATCH=107 (exact
  match to the 107 baseline gate in this doc).
- **P1**: all done. (1) project_manifest.json for madera now has `pdf_path`
  pointing at `artifacts/projects/madera/uploads/input.pdf` (copied the
  stamped PDF in from the Downloads WeTransfer path — Downloads is a
  personal-machine path and must not stay the source of truth); no main.py
  code change needed since `_project_pdf_path()` already preferred
  manifest.pdf_path over the SAMPLE_PDF fallback. (2) scene3d.build_scene()
  now emits a `"benchmarks"` key (id, mark, x_ft, y_ft, elevation_ft) sourced
  from `raw_revit["benchmarks"]`, plus `counts.benchmarks` — additive, no
  schema break, verified via GET /api/scene3d (2 benchmarks). (3) frontend
  renderOverlay() draws BM-1/BM-2 as vermilion (#ff6a00) crosshair+ring
  markers via `renderBenchmarkMarkers()`, gated on `pdf_benchmarks.page_index
  === store.pageIndex[activeSheet]`; store now fetches GET /api/pdf/benchmarks
  and tracks pageIndex per sheet; new "Benchmarks" chip in renderLayerToggles
  toggles `store.showBenchmarks`. (4) build3D() adds a `bmGroup` with emissive
  spheres + makeLabelSprite labels for each benchmark, distinct vermilion
  color from all status colors. (5) Verified live via Playwright on Madera:
  both BM-1/BM-2 render on S-201 PDF overlay (DOM + on-screen bounding-box
  checked) and BM-2 visible with label in the 3D pane (screenshotted). 98
  pytest green throughout; index_v3_backup.html synced after every edit.
- **P2**: tabular results view done. `#app` grid-template-rows changed to
  `64px 1fr auto`; new `#table-panel` (hidden by default, toggled by new
  header button "▤ Table" / a "✕" close button) renders a sortable table
  (mark/category/sheet/status/distance_ft/device_id/reason) via new
  `renderTable()`, called from the end of `renderList()` so it always mirrors
  the SAME filter state as the left list (reused `visibleElements()` —
  no duplicate filter UI). Click a `<th>` to sort (toggles asc/desc); click a
  row to call the existing `select(id, "table")`, which syncs the left list,
  PDF pane, and 3D pane exactly like the other two entry points. status-pill
  styling + monospace tabular-nums for the distance column, per report
  aesthetic tokens (full restyle is still P6-only, this is scoped to the
  table). One real bug found and fixed during Playwright testing: initial
  code used `$("#results-table thead th")` where `$` is
  `document.querySelector` (single-element) not `querySelectorAll` — swapped
  to `document.querySelectorAll(...)`. Verified via Playwright: table renders
  354/354 rows on load, sorting by mark and by status both work (asc/desc
  toggle confirmed), filtering via the existing status-filter select narrows
  the table to exactly 107 rows when set to MATCH (matches the MATCH=107
  baseline), row click syncs `.row.selected` in the left list AND
  `#results-tbody tr.selected` in the table to the same element id. No
  console errors besides the pre-existing harmless `/favicon.ico` 404.
- **Gate check for P0→P2** (per the line above "Gate after EVERY phase"):
  98 pytest green ✓, Madera MATCH=107 (unchanged from 107 baseline) ✓,
  dashboard loads and all three panes (list/PDF/3D) + new table verified live
  via Playwright ✓, index_v3_backup.html synced ✓.
- **Next up for Opus 4.8 (P3, P4)**: P0 item 1 is still an open human
  dependency — the state machine work in P3 does not require it (P3 proposes
  fresh benchmark pairs from PDF grid geometry, independent of today's
  already-verified transform), but do not assume Madera has a second,
  independently-verified benchmark export yet. `backend/app/config.py`
  ARTIFACT_FILES has no `benchmark_workflow` key yet and
  `backend/app/benchmark_workflow.py` does not exist — both still to be
  created per the P3 spec below.

### 2026-07-17 (fable session — P1/P2 touch-ups + P3/P4 DONE, gate green)
- **P1/P2 touch-ups**: table cells + benchmark overlay labels now go through
  the existing `esc()` (marks/reasons are PDF-derived, untrusted — matches
  the prior XSS bug-sweep convention); dead `TABLE_COLS` const removed.
- **P3 DONE**: `config.ARTIFACT_FILES["benchmark_workflow"]` added;
  `backend/app/benchmark_workflow.py` created — TRANSITIONS edge map,
  APPROVAL_GATES {awaiting_pdf_approval→stamping,
  awaiting_revit_approval→awaiting_export}, ADVANCE_STEPS {stamped,
  revit_connected, markers_placed, export_received, calibrated}, audit
  history entries (ts/actor/from/to/note/payload), pure geometry helpers
  `pick_max_diagonal_pair` + `propose_from_geometry` (joins PDF/Revit grid
  intersections by id, BM-1 = smaller revit x). Endpoints in main.py:
  GET /api/benchmark-workflow, POST …/propose | …/approve | …/advance,
  GET …/evidence/{mark}.png; all emit progress via progress.emit(step
  "benchmark_workflow") → existing SSE. Guard rail implemented BOTH ways:
  the machine never computes a transform, AND the "calibrated" advance
  refuses `done` unless a `benchmark_verified` + registration_usable
  calibration actually exists on disk (it reads registration.load_calibration).
- **KEY P3 DISCOVERY**: grid_registration.detect_pdf_grid_positions came up
  EMPTY on Madera S-201 — the sheet has noise "1"/"2"/"3" words scattered in
  the edge bands, so the conservative detector honestly skips those labels
  (vertical={}). Fix (WITHOUT touching grid_registration, which S-202/S-205
  calibrations depend on): `benchmark_workflow.bubble_row_positions()` — the
  true grid bubbles all sit on ONE thin row/column (one bubble per label,
  ≥2 distinct labels, cluster with most uniquely-represented labels wins;
  ambiguity → honestly empty). The propose endpoint uses it only as a
  fallback for axes the shared detector missed. On real Madera S-201 it
  finds 1/2/3 at y≈125.6 → 9 intersections → picks Grid A/3 + Grid C/1
  (82.12 ft apart — same rectangle diagonal as the proven A/1+C/3 run).
- **P3 tests**: tests/test_benchmark_workflow.py — 11 tests (happy path
  walks every state; illegal edges rejected AND leave no history; advance
  before approval impossible; reject→failed→restart; persistence round-trip;
  max-diagonal pick; join-by-id excludes unmatched; 2-point minimum;
  bubble-row fallback beats band noise (real Madera pattern) and stays empty
  when a label is duplicated in the row). 109 pytest green (98 + 11).
- **P4 DONE**: full-screen "◎ Autopilot" wizard in frontend/index.html,
  session-report tokens scoped under `#bmwizard` (ink #0B0D10, panel
  #14171C, markup #FF5A36, signal #5EEAD4; Big Shoulders Display + IBM Plex
  via Google Fonts link — the rest of the dashboard is untouched, deep
  restyle stays P6). Vertical step rail (9 ticks, past/active/failed glow),
  Start card, proposal card with the two evidence crops + animated crosshair
  lock-on rings (bwLock keyframes; crops are centred on the point by
  render_evidence_crop so the CSS crosshair needs no coordinates), mono
  coordinate table, approve/reject via the existing .resolve-btn
  accept/reject classes, agent-working spinners per state, read-back vs
  intended table with per-mark Δft (green <0.05 ft), fresh-export
  instructions card, done card showing calibration source+scale, terminal
  live log fed by its own EventSource on /api/pipeline/events filtered to
  step "benchmark_workflow" + a 4s poll fallback for out-of-band agent
  advances. index_v3_backup.html synced.
- **P4 VERIFIED live via Playwright on real Madera data**: propose from the
  UI → 2 crops render with tags "BM-1 · Grid A/3"/"BM-2 · Grid C/1";
  advance-before-approve returns 409; approve → rail advances to Stamp PDF;
  agent-side advances posted via curl while the wizard was open appeared
  live (SSE log grew 12→16 lines); read-back card showed Δ 0.0001/0.0000 ft
  in green; second approval → Fresh export; export_received + calibrated →
  DONE (guard rail accepted because the project's REAL benchmark_verified
  calibration is on disk, scale 17.966); done card + full rail lit;
  screenshots autopilot-wizard.png + autopilot-done.png at repo root.
- **Honesty cleanup**: the Playwright run wrote SIMULATED advance steps into
  the real Madera benchmark_workflow.json (no markers were actually placed
  today) — artifact deleted afterwards, workflow reset to idle. Do NOT
  treat a "done" workflow state as evidence unless its history is real.
- **Gate after P3+P4**: 109 pytest green ✓, Madera MATCH=107 unchanged ✓,
  dashboard loads (354 elements · 107 MATCH header verified after wizard
  close) ✓, backup synced ✓.
- **Next (per plan order P7 → P5 → P6, assigned Sonnet/Fable)**: P7 skill
  (.claude/skills/benchmark-autopilot/SKILL.md) should drive THIS state
  machine: propose → approve gate → advance(stamped) → advance(revit_connected)
  → advance(markers_placed with readback) → approve gate →
  advance(export_received) → run the real extract+calibrate endpoints →
  advance(calibrated). P0 item 1 (user saves Revit model + fresh export)
  REMAINS OPEN.

### 2026-07-17 (later, same-day follow-up) — Stamping gap closed + P7 done

- **Stamping gap closed** (found via user-requested audit): a prior
  Playwright test had proven `advance{step:"stamped"}` could reach the
  `done` state purely from fabricated reports — no PDF ever written. Added
  `POST /api/benchmark-workflow/stamp` (the only place that writes BM-1/BM-2
  PyMuPDF circle annotations, always at the human-approved
  `wf.proposal.pdf_point_pt`, backs up the PDF, reads it back via
  `extract_pdf_benchmarks`, refuses to advance unless both marks verify
  within `STAMP_TOLERANCE_PT=3.0`). Same verify-before-trust guard applied
  to the `advance{step:"stamped"}` fallback. `awaiting_export` now
  auto-detects via a hook in `POST /api/upload` right after it saves
  `raw_revit` — no manual `/advance` needed once an upload's `benchmarks[]`
  covers both proposal marks. Live-tested end-to-end on a scratch copy of
  Madera (never the real project — confirmed via md5sum unchanged): real
  write + read-back verified at 0.0pt delta; re-stamp-after-done correctly
  409s; upload-triggered auto-advance confirmed. Also fixed a live UI bug
  found via Playwright: `api()`'s error handling rendered `[object Object]`
  for the new endpoint's dict-shaped 409 details — now unwraps `.message`.
  11 new tests, 120 pytest green total.
- **P7 DONE**: `.claude/skills/benchmark-autopilot/SKILL.md` written,
  driving the full state machine end-to-end including the Nonica connection
  checklist, the pinned-element copy trick, exact-coordinate sourcing, and
  the BENCHMARK-SOP.md failure table — with an explicit honesty rule never
  to simulate Revit-side steps without a live connection. User memory
  (`qaqc-project-state.md`) updated with a pointer + summary. Dry-run
  against Dogwood: `propose` correctly ran the same code path and honestly
  reported "0 labeled grid intersections" rather than crashing or
  fabricating a proposal — **root cause identified but NOT fixed (out of
  scope, touches shared code)**: `grid_registration.py`'s
  `detect_pdf_grid_positions`/`pdf_grid_control_points` hard-code an
  assumption that letter labels are always vertical grid lines and number
  labels always horizontal; Dogwood's S-05 sheet has that inverted (grid
  "C" geometrically forms a horizontal line, "1"/"2"/"3" form verticals),
  so no letter+number pair ever forms even though both axes were detected.
  This is pre-existing behavior in a function shared with the Madera
  S-202/S-205 calibrations — flagged here for whoever picks up a future
  "make grid pairing axis-agnostic" task, not fixed now. No side effects
  from the dry run (propose is read-only on the PDF; the resulting
  `dogwood-lane/benchmark_workflow.json` test artifact was deleted after).
- **Gate**: 120 pytest green ✓, Madera MATCH=107 unchanged ✓.

### 2026-07-17 (continued) — P5 done (data-driven only, live spot-verify blocked)

- **Wall height fidelity**: already done in prior work — `scene3d.py` walls
  already use real `height_ft` from the v3 export when present
  (`height_assumed` flag when falling back to the 10ft default). No change
  needed.
- **Foundations as slabs**: real gap found and fixed. Madera's 21
  `Structural Foundation` elements are strip footings up to 44.6ft ×
  40.9ft in real bbox data, but `frontend/index.html`'s generic
  category-element box sizing clamped x/z to 8ft (meant for posts/columns/
  connections) — a 44ft footing rendered as an 8ft cube. Added a
  category-specific cap (`Structural Foundation` → 60ft, everything else
  unchanged at 8ft) in the `build3D()` sizing block. Real Revit bbox data,
  not invented geometry — just stopped truncating it.
  Location: the `let sx=1.1...` block right after `CAT3D`.
  Confirmed via `GET /api/scene3d`: 21 foundation elements now render at
  their true footprint (verified two footings at 44.6ft/40.9ft).
- **Grid labels at both ends**: `build3D()`'s grid loop only labeled the
  line's start point; added a second `makeLabelSprite` at the end point.
  Verified via Playwright top-view screenshot: grid letters A/B/C now
  appear at both the top AND bottom edges, numbers 1/2/3 at both left AND
  right edges (previously only one side each).
- **Live Nonica spot-verify: BLOCKED, same as P0 item 1.** Called
  `mcp__Revit__get_active_view_in_revit` directly — timed out ("AI
  Connector for Revit by Nonica was not enabled, or it was closed").
  Revit is not currently open with a live connection in this environment.
  This step needs the user to have Revit open with NonicaTab PRO's A.I.
  Connector enabled before any spot-verification of 5-10 members against
  the live model can happen. Not fabricated — explicitly left undone.
- **Gate**: 120 pytest green ✓, Madera MATCH=107 unchanged ✓, scene counts
  unchanged (walls 127, holdowns 72, category_elements 1190, framing 6166)
  ✓, click-select still works (verified via existing Playwright flows in
  this session) ✓, backup synced ✓.

### 2026-07-17 (continued) — P6 DONE (final phase), all 8 phases complete

- **Report-aesthetic tokens applied app-wide, CSS + classnames only** — no
  DOM/logic restructure, per the plan's own constraint. `:root` swapped to
  the report palette (`--bg:#0B0D10, --panel:rgba(20,23,28,.82),
  --line:#262B33, --txt:#ECE9E1, --dim:#9AA0A6, --accent:#5EEAD4` replacing
  the old blue `#38bdf8`); status legend colors (`--match`/`--revitonly`,
  COL in JS) deliberately left untouched — they're semantic/documented
  baselines, not part of the report's ink/vermilion/signal palette. Fonts:
  `--font-display` (Big Shoulders Display) on `.brand`/`.drawer-hd`,
  `--font-mono` (IBM Plex Mono) on `.pane-bar .title`/badges/table headers/
  counts (tabular-nums), `--font-body` (IBM Plex Sans) as the app default
  replacing Segoe UI. `button.primary` gradient shifted teal-to-match the
  new accent. `.glass` panels get a cheap `panelIn` CSS keyframe
  (opacity+translateY reveal) — the only "micro-interaction," kept
  CSS-only per the plan's constraint (no JS count-up animation added).
- **Full Playwright smoke suite**: all 4 drawers (teach/review/runs/
  inspector) + table panel + wizard + pipeline modal confirmed hidden by
  default and each opens/closes independently without affecting the
  others; pipeline modal renders all 11 steps; results-table row click
  still syncs `.row.selected` in the list AND `tr.selected` in the table to
  the same element id (verified post-restyle); screenshot
  `p6-restyle-final.png` at repo root for visual reference.
- **Gate**: 120 pytest green ✓, Madera MATCH=107 unchanged ✓, backup
  synced and diff-verified byte-identical ✓.

## ALL 8 PHASES COMPLETE (P0→P1→P2→P3→P4→[stamping gap]→P7→P5→P6)

Everything in this plan is shipped except the recurring human dependency:
**P0 item 1 — save the Revit model (Ctrl+S) and re-export so the exporter
dialog shows "Benchmarks: 2"** — this also blocks P5's live Nonica
spot-verify. Both require the user to have Revit open with NonicaTab PRO's
A.I. Connector enabled; neither is agent-doable. The
`.claude/skills/benchmark-autopilot/SKILL.md` skill is ready to drive the
rest the moment that's done.

## Key files/functions to reuse (don't rebuild)
- grid_registration.detect_pdf_grid_positions/pdf_grid_control_points — PDF-side
  benchmark proposal geometry.
- registration.compute_calibration_from_benchmarks + POST
  /api/registration/benchmarks — the ONLY calibration path, do not bypass gates.
- benchmarks.extract_pdf_benchmarks — stamp verification after stamping.
- progress.emit + GET /api/pipeline/events (SSE) — live wizard log.
- review.render_evidence_crop pattern — proposal crops.
- flyBallTo (~line 964) / makeLabelSprite (~line 801) in frontend/index.html —
  3D benchmark markers.
- .resolve-btn / .steplog / drawer CSS patterns in frontend/index.html — wizard
  interactions.
- backend/run_benchmark_acceptance.py — reference for agent-side stamping code
  (already proven working end-to-end on real Madera data).
- docs/session-report-benchmark-registration.html — design source (tokens,
  diagram, animation patterns) for P4 and P6.

## Environment reminders (do not re-derive)
- Python: C:\Users\aashd\AppData\Local\Programs\Python\Python311\python.exe,
  run from backend/ (module app).
- Server: python -m uvicorn app.main:app --host 127.0.0.1 --port 8077.
- Tests: python -m pytest -q from backend/ — 98 green as of last good state.
- Frontend is frontend/index.html (+ keep index_v3_backup.html in sync).
- Frozen modules — read-only, additive params only: compare.py, registration.py
  (math), s201_detector.py, pdf_intelligence.py, review_overlay.py,
  normalization.py, revit_convert.py, pdf_convert.py.
- Nonica MCP requires Revit open + A.I. Connector enabled + NonicaTab PRO trial
  active (installed 2026-07-16, ~30 day trial) for any set_/create_ tool.
- Baseline numbers to protect: Madera 107 MATCH overall, holdown devices 44
  MATCH/16 LOCATION_MISMATCH/4 PDF_ONLY/1 MARK_MISMATCH/11 REVIT_ONLY.