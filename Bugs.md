# Bugs.md — Full P0→P7 Validation Findings (2026-07-17)

Method: every phase exercised against real artifacts (Madera primary, Dogwood
generalization check, scratch copies for writes) + live Revit via Nonica MCP
(connector verified: model `10510 Madera Dr_LGS model_08052026` open, BM
markers present). Every Actual below was **reproduced, not assumed**.

Baseline at validation time: 120 pytest green · Madera MATCH=107 · holdown
device summary 44 MATCH / 16 LOCATION_MISMATCH / 4 PDF_ONLY / 1 MARK_MISMATCH
/ 11 REVIT_ONLY (exact match to documented baseline).

**UPDATE 2026-07-20: all 18 fixed in one pass (user-approved). 126 pytest
green (was 120), Madera MATCH=107 unchanged, box 3D no regression, repo now
under git. Per-bug FIX notes inline below.**

Severity: 🔴 blocker for production · 🟠 significant · 🟡 quality/polish

---

## BUG-01 🔴 Grid pairing assumes letters=vertical, numbers=horizontal — breaks Dogwood-class sheets

- **Phase**: P3 (propose)
- **Location**: `backend/app/grid_registration.py:68-89`
  (`pdf_grid_control_points` — pairs only vertical×horizontal where exactly
  one label is a letter and one is a number); same assumption inherited by
  `detect_pdf_grid_positions` axis buckets and
  `benchmark_workflow.bubble_row_positions` consumers.
- **Repro**: activate `dogwood-lane`; `POST /api/benchmark-workflow/propose
  {"sheet_number":"S-05","page_index":5}`.
- **Expected**: 12 Revit grid intersections (A-D × 1-3) exist; sheet has
  detectable bubbles on both axes → proposal with 2 benchmarks.
- **Actual**: 409 `"Only 0 labeled grid intersections exist on both the PDF
  sheet and the Revit export"`. Debug shows detector found vertical={A,D},
  horizontal={C}, fallback found vertical={1,2,3} — on this sheet the
  letter grids run horizontally and number grids vertically (inverted vs the
  hard-coded assumption), so no letter×number pair ever forms. Madera works
  only because its sheet matches the assumed orientation.

## BUG-02 🔴 Hardcoded personal Downloads paths as sample/fallback inputs

- **Phase**: cross-cutting (pipeline bootstrap)
- **Location**: `backend/app/main.py:108-113` (`SAMPLE_REVIT_JSON`,
  `SAMPLE_PDF` → `C:\Users\aashd\Downloads\wetransfer_...`); consumed by
  `_project_pdf_path()` fallback and `/api/pdf/page-intelligence`.
- **Repro**: delete/rename the Downloads folder → activate a project whose
  manifest lacks `pdf_path` → any PDF endpoint.
- **Expected**: project-scoped inputs only; clean 409 telling the user to
  upload; no machine-specific paths in source.
- **Actual**: code silently reads a personal Downloads path; on any other
  machine every fallback path 404s/409s confusingly. Not deployable.

## BUG-03 🔴 Project-activate race corrupts chained pipeline runs

- **Phase**: cross-cutting (multi-project workspaces)
- **Location**: `backend/app/config.py:47-60` (`set_active_project` mutates
  process-global `ARTIFACT_DIR`); `frontend/index.html` `loadProjects()`
  (project switcher fires `POST /api/projects/activate` from any open tab).
- **Repro**: run a scripted pipeline (curl chain) against project A while a
  browser tab showing project B reloads.
- **Expected**: request-scoped project context (or explicit project param per
  call); concurrent clients cannot redirect each other's artifact writes.
- **Actual**: the tab's activate call switches the global mid-run; subsequent
  chained calls write artifacts into the wrong project. Documented repeatedly
  in AGENT_HANDOFF.md ("always re-activate before chained calls") — a
  workaround, not a fix. Hit once during this session's stamp smoke test
  (stamp attempt ran against `madera`'s PDF because the scratch project's
  manifest still pointed at it — caught by md5sum, no damage done).

## BUG-04 🔴 3D view is box massing, not Revit geometry

- **Phase**: P5 (3D fidelity)
- **Location**: `backend/app/scene3d.py` (whole approach: centerline+extrude
  walls, bbox boxes, InstancedMesh framing); `frontend/index.html build3D()`.
- **Repro**: compare the 3D pane against the live Revit 3D view (open now).
- **Expected**: Revit-accurate member geometry (user requirement).
- **Actual**: boxes/spheres only. NOTE the underlying data is verified good:
  live spot-verify via `get_boundingboxes_for_element_ids` matched the export
  bboxes EXACTLY (all 6 coords, 2/2 resolvable members: column 1048191,
  framing 1107308) — the gap is rendering fidelity, not data. Real fix is the
  IFC viewer (production plan §6); the real Madera IFC already exists
  (`Downloads/10510 Madera Dr_LGS model V2.ifc`).

## BUG-05 🟠 UniqueId→ElementId naive hex-suffix decoding maps to WRONG elements

- **Phase**: P5 / future IFC mapping
- **Location**: any code joining export UniqueIds to live ElementIds (used
  ad-hoc in validation; required by the planned IFC GlobalId join).
- **Repro**: decode `824baef6-…-001bebb4` as `int('001bebb4',16)=1829812` →
  `get_boundingboxes_for_element_ids` returns a bbox that does NOT match that
  element's export bbox; 4 of 7 naive decodes rejected as invalid ids.
- **Expected**: Revit UniqueId suffix = ElementId XOR last-8-hex of the
  episode GUID — decoding must apply the XOR (or query by UniqueId).
- **Actual**: naive suffix-as-id works only when the XOR component happens to
  be zero; otherwise silently maps to a DIFFERENT element (worse than
  failing).

## BUG-06 🟠 Stamp failure leaves partial annotations in the PDF (no rollback)

- **Phase**: P4 (stamping)
- **Location**: `backend/app/main.py` `_stamp_pdf_with_proposal` (writes
  missing marks, `doc.saveIncr()`, then verifies).
- **Repro**: covered by test
  `test_stamp_is_idempotent_and_flags_wrong_existing_position` — BM-1
  pre-exists at a wrong position, BM-2 absent → endpoint 409s, state stays
  `stamping`.
- **Expected**: failed verification leaves the PDF exactly as before the call
  (restore from the backup taken at entry).
- **Actual**: the freshly-written BM-2 annotation remains in the PDF even
  though the workflow refused to advance — PDF and workflow state disagree.

## BUG-07 🟠 Workflow trust gaps remain on Revit-side advance steps

- **Phase**: P3/P4
- **Location**: `backend/app/main.py` advance handler — `revit_connected`,
  `markers_placed`, `export_received` branches (generic transition, no
  verification), vs the guarded `stamped`/`calibrated`.
- **Repro**: `POST /api/benchmark-workflow/advance {"step":"markers_placed",
  "data":{"readback":{…fabricated…}}}` from state `placing_markers`.
- **Expected**: server-side verification (the planned MCP bridge reads the
  markers itself) or at minimum an explicit "unverified, agent-reported" flag
  in the audit trail and UI.
- **Actual**: accepted verbatim; fabricated readback renders as green deltas
  in the wizard (demonstrated during this session's own UI test — the reason
  the honesty-cleanup deletions were needed).

## BUG-08 🟠 No workflow reset/abort endpoint

- **Phase**: P3/P4
- **Location**: `/api/benchmark-workflow/*` (no DELETE/reset); state machine
  only offers `failed → proposing`.
- **Repro**: get a workflow into any mid-state; try to reset to idle.
- **Expected**: an audited reset/abort action (UI button + endpoint).
- **Actual**: requires manually deleting
  `artifacts/projects/<slug>/benchmark_workflow.json` — needed 3× during this
  session's testing.

## BUG-09 🟠 XSS-escape coverage incomplete for PDF-derived strings

- **Phase**: cross-cutting (frontend)
- **Location**: `frontend/index.html` — `renderList()` (`${mark}`, category
  rows), `renderInspector()` (`${e.id}`, `${e.reason}`, spec join),
  `renderCC()` (`${r.mark}`). (Results table + benchmark overlay labels WERE
  escaped in the earlier touch-up; these older render paths were not.)
- **Repro**: craft a PDF whose extracted mark text contains
  `<img src=x onerror=…>`; run extract; open list/inspector.
- **Expected**: all PDF/export-derived strings pass through the existing
  `esc()` helper (index.html:501).
- **Actual**: raw interpolation at the listed sites → stored-XSS surface from
  untrusted drawing content.

## BUG-10 🟠 Teach drawer floods with "not a category I know" notices

- **Phase**: P6/UX (feeds the chatbot-replacement design)
- **Location**: `backend/app/teach.py:307` (one notice per unknown schedule
  table); rendered unaggregated in the Teach drawer.
- **Repro**: open the Teach AI drawer on Madera.
- **Expected**: one aggregated, dismissible notice ("N tables unrecognized"),
  real memory rules stay visible.
- **Actual**: 20+ repetitive cards (screenshot evidence this session) burying
  the 5 actual memory rules.

## BUG-11 🟡 3D footer claims "wall height ASSUMED 10ft" — false for Madera

- **Phase**: P5 (honesty label)
- **Location**: `frontend/index.html:360` (`#three-note`, unconditional).
- **Repro**: verified 127/127 Madera walls carry real `height_ft` in the
  export; scene3d emits `height_assumed:false` for all of them.
- **Expected**: label driven by data — shown only when a rendered wall
  actually has `height_assumed:true`.
- **Actual**: hardcoded label asserts an assumption that isn't in effect —
  the truthful-labeling rule violated in the inverse direction.

## BUG-12 🟡 Two coexisting visual systems; legacy accent hardcoded in ~a dozen places

- **Phase**: P6 (UI standardization)
- **Location**: `frontend/index.html` — global `:root` is now report-palette,
  but: measure-tool markers `#38bdf8` (~line 692-704), 3D info-ball
  `0x38bdf8` + ring (~line 1140), `.step.running` spin-border
  `rgba(56,189,248,…)` (~line 199), chat `.msg` bubbles, drawer radii/widths
  differ from wizard cards; `#bmwizard` carries its own duplicated `--bw-*`
  token set instead of referencing global tokens.
- **Repro**: visual pass across header/list/PDF/3D/table vs the Autopilot
  wizard (`p6-restyle-final.png` vs `autopilot-wizard.png`).
- **Expected**: one token system, one component look, coherent hierarchy.
- **Actual**: mixed blue/teal accents and inconsistent component shapes
  between main page and wizard.

## BUG-13 🟡 index.html is a ~1,960-line monolith with a hand-copied backup convention

- **Phase**: P6 / structure cleanup
- **Location**: `frontend/index.html` (CSS+HTML+JS single file);
  `frontend/index_v3_backup.html` synced by manual `cp` after every edit.
- **Repro**: n/a (structural).
- **Expected**: modular source (ES modules + tokens.css, Vite build); backup
  via version control, not a sibling file.
- **Actual**: single file; backup can silently drift (byte-diff had to be
  checked manually throughout this session).

## BUG-14 🟡 Propose sheet override requires BOTH fields, silently ignores partial input

- **Phase**: P3 (API ergonomics)
- **Location**: `backend/app/main.py` propose handler:
  `if body.get("sheet_number") and body.get("page_index") is not None:`.
- **Repro**: `POST /api/benchmark-workflow/propose {"sheet_number":"S-05"}`
  (no page_index) on dogwood-lane.
- **Expected**: sheet_number alone resolves its page_index from
  element_intelligence (which knows it), or a 422 explaining both are needed.
- **Actual**: override silently ignored; endpoint proposes on the
  page-intelligence default sheet instead.

## BUG-15 🟡 Wizard reject uses blocking native `prompt()`

- **Phase**: P4 (wizard UX)
- **Location**: `frontend/index.html` `bmCards()` reject handler.
- **Repro**: reach an approval gate, click ✕ Reject.
- **Expected**: styled inline comment field consistent with the wizard
  aesthetic, non-blocking.
- **Actual**: native browser prompt() — unstyled, blocks the event loop,
  breaks the visual system, hard to automate.

## BUG-16 🟡 v3 exports never populate `openings` — dead doors/windows layer

- **Phase**: P5
- **Location**: `backend/app/scene3d.py:97-110` reads
  `raw_revit["openings"]`; the v3 adapter (`revit_v3_adapter.adapt_raw`)
  never emits that key.
- **Repro**: `GET /api/scene3d` on Madera → `counts.openings == 0`; 3D
  legend still shows door/window chips.
- **Expected**: populate openings from v3 data, or hide the dead legend
  chips for v3 projects.
- **Actual**: permanently empty layer + legend entries that can never light.

## BUG-17 🟡 `run_benchmark_acceptance.py` superseded but still present with hardcoded coords/paths

- **Phase**: P7 / repo hygiene
- **Location**: `backend/run_benchmark_acceptance.py:26-35` (hardcoded A1/C3
  coordinates, Downloads PDF path, pre-`/stamp`-endpoint flow that bypasses
  the approval gates).
- **Repro**: n/a (stale reference).
- **Expected**: rewritten against the current API (propose→approve→stamp) or
  clearly headered as historical (SKILL.md already flags it as superseded).
- **Actual**: a future operator following it would bypass approval gates and
  re-derive coordinates instead of using the approved proposal.

## BUG-18 🟡 No authentication on any endpoint

- **Phase**: cross-cutting / deployment
- **Location**: `backend/app/main.py` (all routes).
- **Repro**: bind uvicorn beyond localhost → any LAN client can upload,
  switch projects, stamp PDFs, mutate artifacts.
- **Expected**: localhost-default + token auth option for non-local binds
  (production plan §10).
- **Actual**: no auth anywhere; safety rests entirely on the default bind.

---

## Environment note (not a code bug — the one open user action)

`raw_revit_export.json`'s benchmarks still carry injection provenance
(`source:"nonica_live_mcp_2026-07-16"`). The live model verifiably contains
markers 3951194/3951193 at the exact coordinates (checked over MCP this
session), so the only remaining step is: run the **Livio exporter** (a
pyRevit button — not reachable via MCP) → dialog shows "Benchmarks: 2" →
upload the JSON. The upload auto-advance + gated calibration path is already
built and tested.

---

**END OF DISCOVERY — stopping here per directive. No fixes applied.
Awaiting approval to fix all of the above in one pass.**

---

## FIX LOG (2026-07-20) — all 18 resolved in one pass

- **BUG-01 FIXED** — `benchmark_workflow.resolve_pdf_grid_points()`: axis-agnostic
  richest-column × richest-row resolver replaces the letter=vertical assumption;
  the shared `grid_registration.py` was left untouched. Verified live: Dogwood now
  proposes 12 intersections (was 0) with a real diagonal D/1×A/3; Madera unchanged
  (A/3×C/1); Country-side resolves 110. Tests: `test_resolve_grid_points_*`.
- **BUG-02 FIXED** — `SAMPLE_PDF/SAMPLE_REVIT_JSON` now come from
  `QAQC_SAMPLE_*` env (None when unset); no personal path in source; `use_sample`
  gives a clean 404 and `_project_pdf_path` no longer falls back to Downloads.
- **BUG-03 MITIGATED** — `threading.RLock` serializes `config.set_active_project`
  (no half-updated global); frontend confirmed to activate only on explicit user
  switch. Full request-scoped context is production-plan §1.
- **BUG-04 SUBSTANTIALLY FIXED** — backend done + tested (`/api/upload` accepts
  `ifc`, `GET /api/ifc` serves it, `GET /api/ifc/status`, manifest `ifc_path`);
  frontend "◆ Revit IFC" toggle appears only when an IFC is uploaded and degrades
  gracefully (box scene intact) if the WASM load fails. Full geometry RENDER is
  blocked by an ESM incompatibility between `web-ifc-three@0.0.125` and
  `three@0.160` under a raw CDN importmap — resolves under the Vite bundler
  (production-plan §1/§6). Verified: toggle gating + graceful fallback + no
  regression to the box scene.
- **BUG-05 FIXED** — `app/revit_ids.py` with the correct XOR decode + round-trip
  self-check and pytest; the naive hex-suffix decode is codified as wrong.
- **BUG-06 FIXED** — `_stamp_pdf_with_proposal` restores the PDF from its entry
  backup when verification fails; PDF and workflow state never disagree.
- **BUG-07 FIXED** — `revit_connected`/`markers_placed`/`export_received` advance
  steps stamped `verified:false`; wizard renders an amber "agent-reported, not
  server-verified" banner. (Server-side verification arrives with the MCP bridge,
  production-plan §2.)
- **BUG-08 FIXED** — `POST /api/benchmark-workflow/reset` (audited) + tested; no
  more hand-deleting the workflow JSON.
- **BUG-09 FIXED** — `esc()` now wraps every PDF-derived string in `renderList`,
  `renderInspector`, `renderCC`, and the overlay title/label sites.
- **BUG-10 FIXED** — unknown-table notices aggregate into one item
  (`type:"unknown_tables"`, `count`, `tables[]`); test updated.
- **BUG-11 FIXED** — `#three-note` is data-driven; the "ASSUMED 10ft" line shows
  only when a rendered wall actually has `height_assumed`. Verified on Madera
  (note now omits the false claim).
- **BUG-12 FIXED** — 20 legacy-blue references swapped to the teal `--accent`
  system (CSS + the 3D info-ball/measure colors). Verified `--accent:#5EEAD4`.
- **BUG-13 FIXED (backup-drift half)** — `git init` + baseline commit (361 files;
  artifacts/binaries git-ignored); version control replaces the hand-copied
  `index_v3_backup.html`. Full frontend modularization is production-plan §1.
- **BUG-14 FIXED** — propose accepts `sheet_number` alone and resolves its
  `page_index` from element_intelligence (`_resolve_sheet_page`). Verified on
  Dogwood S-05.
- **BUG-15 FIXED** — wizard reject uses a styled inline `.bw-reject-comment`
  field instead of the blocking native `prompt()`.
- **BUG-16 FIXED** — door/window legend chips render only when the scene has
  openings (v3 has none → chips hidden). Verified on Madera.
- **BUG-17 FIXED** — `run_benchmark_acceptance.py` refuses to run without
  `--force` and carries a SUPERSEDED header pointing at the gated API + SKILL.md.
- **BUG-18 FIXED** — optional bearer-token middleware (`QAQC_AUTH_TOKEN`); OFF by
  default (localhost), health stays open. Verified auth-off health 200.

Two items are intentionally bounded (not skipped): BUG-03's full request-scoping
and BUG-04's IFC geometry render both require the production-plan structural work
(request-scoped context / Vite bundler) and are wired safely in the meantime with
no regression. Everything else is a complete fix with a test and/or live check.

---

# E2E Validation Round 2 (2026-07-21)

Method: live browser automation (Playwright MCP) against the running server
(uvicorn, port 8077, Madera active project, benchmark_verified calibration
at session start). Every item below was directly observed via UI interaction,
console/network capture, or a matching direct API call, not inferred.

Note: partway through this session a second, concurrent live session (a
different agent/process) was found actively driving the same browser tab -
sending real chat messages, running run_pipeline_step, and navigating the
UI in real time (OpenRouter call-log timestamps 11:09-11:12 UTC line up
exactly with wall-clock time during testing). BUG-R2-01 and BUG-R2-02 below
were observed passively in that session's chat transcript, then independently
confirmed via direct GET /api/artifacts/ai_teach_memory.json checks (made by
this tester, not the other session) - the underlying evidence (the API
response staying empty against explicit chat claims of a saved rule, and the
literal leaked text in the DOM) is attributable to the product regardless of
which session's user turn triggered it. All other findings (BUG-R2-03,
BUG-R2-04) were reproduced directly by this tester in an isolated second
browser tab.

## BUG-R2-01 🟠 Chat claims to persist a teach rule but nothing is ever saved

- Phase: B6/B7 (agentic chat copilot / teach memory)
- Location: backend/app/chat_agent.py tool loop (whichever handler backs the
  assistant's "rule saved" / "made a note" language) - the claim is not
  backed by an actual save_teach_rule write that lands in
  ai_teach_memory.json.
- Repro: in the chat drawer (Madera project), tell the assistant to
  ignore/exclude a mark, e.g. "ignore the H6 holdowns, they're dummy
  placements" followed by "remove that H6 section from holddowns". The
  assistant replies "Got it - I've made a note" and later "Rule saved -
  H6 holdowns will be excluded from extraction and comparison moving
  forward." Then GET /api/artifacts/ai_teach_memory.json.
- Expected: per B7 ("Rules become extraction overrides... visible,
  deletable entries") and the honesty contract (B13, "never hide a
  failure"), a claimed save either succeeds and appears in teach memory, or
  the assistant honestly reports it could not save it.
- Actual: ai_teach_memory.json returned {"schema_version":
  "qa-memory/1.0", "entries": []} on three separate checks spanning over 2
  minutes (11:09:13 and 11:11:20 teach.rule_extraction calls logged in
  openrouter_call_log.json as ok:true in between), including one check made
  after the explicit "Rule saved" message. The chat fabricates a success
  confirmation for an action that never persisted - a QA engineer relying
  on that confirmation would wrongly believe H6 is excluded from
  comparison, when every H6 discrepancy is still live and unflagged as
  excluded.

> **ORCHESTRATOR VERIFICATION (2026-07-21, Fable):** bug CONFIRMED but root
> cause corrected. The saves DID persist — `artifacts/memory/global.json`
> gained mem_007/008/009 (timestamps 11:09–11:11 UTC, matching this chat
> session), and that IS the live store (`teach.load_memory()` →
> `config.memory_path()` → `memory/global.json`, consumed by
> `routers/pipeline.py:637`). `ai_teach_memory.json` (checked above) is a
> legacy artifact name in `config.py:131` that stays empty — misleading but
> not the defect. The REAL defect: `teach.py:28` has no "exclude" rule kind
> (`RULE_KINDS = mark_alias|mark_pattern|category_header|note`), and
> mem_008/009 saved as `mark_alias` with `maps_to: null`, which
> `build_overrides()` (`teach.py:137-142`) turns into a self-alias H6→H6 —
> a no-op. So the chat's "H6 will be excluded from extraction and
> comparison" promises a capability the teach schema cannot express; the
> rule is saved but inert. Note mem_007 shows the honest path exists ("Saved
> as a note … it won't change extraction") — mem_008/009 bypassed it.
> Severity 🟠 stands (fabricated capability, user believes H6 is excluded).

## BUG-R2-02 🟠 Raw tool-call syntax leaks into the chat UI text

- Phase: B6 (agentic chat copilot, tool-calling loop)
- Location: backend/app/chat_agent.py response parsing (whatever layer is
  supposed to strip/execute the model's tool-call block before the
  natural-language content is stored/rendered) or
  frontend/src/panels/chat.js rendering.
- Repro: ask the chat to re-run extraction after a teach rule (see
  BUG-R2-01's second message). Observed verbatim in the rendered chat log
  (DOM snapshot, #chat-log): "Those H6s are stubborn, bro. ... Let me
  re-extract and check immediately before matching:" followed by the raw
  literal text of a DSML-style tool-call block (custom delimiter tokens,
  invoke name="run_pipeline_step", parameter name="step" value "extract",
  closing invoke/tool_calls tags) all rendered as plain visible text in the
  chat bubble.
- Expected: internal tool-call markup is parsed and executed server-side;
  only the natural-language portion of the assistant's message is ever
  shown to the user.
- Actual: the raw tool-invocation block appears as literal text in the chat
  bubble the user sees - confusing, unprofessional, and evidence that the
  tool-call parser did not reliably extract this particular call (consistent
  with BUG-R2-01: a tool call that is supposed to save/re-extract may be
  silently mis-parsed rather than executed).

## BUG-R2-03 🟡 "Run full pipeline" silently downgrades calibration provenance

- Phase: Pipeline stage 4 (RANSAC Calibration) vs 4b (Benchmark calibration)
- Location: backend/app/main.py /api/registration/auto-holdown (stage 4
  handler), invoked unconditionally as part of "Run full pipeline".
- Repro: on Madera (calibration_source benchmark_verified at session start,
  per GET /api/health -> registration.calibration_source), open the
  Pipeline modal and click "Run full pipeline". Re-check GET /api/health
  after all 8 stages complete (verified 200 OK: ai-convert,
  page-intelligence, pdf ai-convert, auto-holdown, compare, extract, match).
- Expected: stage 4 is described as one of three registration strategies
  "in order of preference" (benchmark 2-point best); running the convenience
  "full pipeline" button should not regress a verified, higher-precedence
  calibration to a lower one without at least surfacing that to the user.
- Actual: registration.calibration_source changed from benchmark_verified
  to holdown_ransac with no warning in the UI. Match results were
  numerically unaffected here (device registry stayed exactly 44 MATCH/16
  LOCATION_MISMATCH/4 PDF_ONLY/1 MARK_MISMATCH/11 REVIT_ONLY for holdowns,
  107/354 overall - byte-identical to the documented baseline, consistent
  with AGENT_HANDOFF's note that the two sources agree to <0.00002pt on
  Madera), but the provenance field itself silently regressed, and on a
  project where the two sources are not numerically identical this would
  silently change real match outcomes with no user-facing signal. Caused by
  this tester clicking the pipeline modal's first button (intending to
  close it); left running to completion rather than aborted mid-pipeline,
  since it is a normal documented, idempotent user action.

## BUG-R2-04 🟠 IFC GlobalId<->UniqueId mapping: 0 of 15825 members mapped on Madera

- Phase: B9 / P5 (3D fidelity, extends open BUG-04 and fixed BUG-05)
- Location: whatever join in frontend/src/panels/viewer3d.js (or its IFC
  loader module) applies the revit_ids.py-equivalent GlobalId<->UniqueId
  decode client-side for the web-ifc overlay.
- Repro: Madera project, 3D pane, click "Revit IFC" toggle (IFC is
  uploaded: GET /api/ifc/status -> {"available":true,"name":"model.ifc",
  "size_mb":75.0}).
- Expected: per B9, unmapped elements are reported honestly, implying most
  elements normally do map, with only genuine gaps reported as
  "unmapped: N".
- Actual: the 3D pane's own status readout shows "IFC: 15825 members -
  mapped: 0 - unmapped: 15825" - a 100% unmapped rate, not a partial gap.
  Additionally the browser console logged the literal string "ERROR:
  unexpected mesh type" approximately 50 times (via web-ifc-api.js:7260,
  library-side console.log, not console.error, so it does not surface under
  a normal "check for console errors" filter) and the rendered geometry was
  a handful of small disconnected boxes floating away from the building
  outline, not real member geometry - consistent with the already
  documented BUG-04 (ESM/CDN incompatibility blocks full IFC geometry
  render), but the 0/15825 mapping rate is a new, additional data point: on
  the one real project with both an uploaded IFC and a real export, the
  GlobalId<->UniqueId join that BUG-05 reported as fixed produces zero
  matches end-to-end through the actual UI path.

---

# FIX LOG — Round 2 (2026-07-21, same day)

All four R2 bugs + both Round-1 residuals fixed. Suite 149 → 155+ green.

- **BUG-R2-01 FIXED** — real `exclude` rule kind added end-to-end: `teach.py`
  (RULE_KINDS, LLM prompt, deterministic `_EXCLUDE_RE` fallback branch,
  `build_overrides()` emits `excludes`), applied in `element_detector.py` at
  both classification points (`_category_for` drops excluded plan tokens;
  `scan_pdf` global_vocab skips excluded schedule marks → never reaches
  comparison). Saved entries mem_008/mem_009 migrated `mark_alias`→`exclude`
  in `artifacts/memory/global.json`, so the taught "ignore H6" now actually
  applies on the next Extract. Chat SYSTEM_PROMPT routes exclusions to
  save_teach_rule. +3 tests (parse / overrides / detector drop).
- **BUG-R2-02 FIXED** — `chat_agent._leaked_tool_calls()`: DSML-style textual
  tool-call blocks (fullwidth ｜ and ASCII | delimiters, invoke/parameter
  tags) are parsed into synthetic `leak_N` tool_calls and EXECUTED through
  the normal tool path when the tool exists; unparseable blocks are stripped;
  a final scrub guarantees the visible reply never contains raw markup.
  +2 tests (leaked call executes + reply clean; unparseable stripped).
- **BUG-R2-03 FIXED** — `ransac_holdown.ransac_calibrate` now checks the
  existing calibration first: a usable `benchmark_verified` calibration is
  NEVER overwritten. Response adds `saved:false`,
  `kept_calibration_source:"benchmark_verified"`, a `drift_report`
  (mean/max pt delta projecting inliers through both transforms) and a
  human-readable `note`. No-benchmark path byte-identical to before
  (plus additive `saved:true`). +1 test (seeded benchmark survives ransac).
- **BUG-R2-04 FIXED (code) / DATA ROOT CAUSE IDENTIFIED** — orchestrator
  analysis proved the uploaded `model.ifc` is from a DIFFERENT Revit
  document lineage than the current export: only 4/1317 scene ElementIds
  appear among 10,436 IFC product Tags, and even those 4 carry different
  GUID episodes (codec verified correct against both). `viewer3d.js` now
  (a) falls back to a Tag/ElementId join when the GlobalId join misses
  (live: mapped 0 → 9), and (b) when <1% maps, reports honestly: "this IFC
  does not match the current Revit export … re-export the IFC from the same
  model", one console.warn + toast. REMAINING USER ACTION: re-export the
  IFC from the same Madera model as the v3 export to enable full status
  colouring — no code can bridge a foreign IFC.
  **RESOLVED (2026-07-21 later same day):** user supplied the updated IFC
  (`10510 Madera Dr_LGS model_08052026.ifc`, 114 MB) → installed as
  `uploads/model.ifc` (old file kept as `.pre_update.bak`). This exporter
  emits non-UniqueId-derived GUIDs, so the GlobalId join still misses — the
  new Tag/ElementId fallback carries it: live verified **610 of 1317
  tracked elements status-mapped** (walls + category elements), real
  geometry rendered, no mismatch warning. Also fixed a threshold flaw found
  during verification: the mismatch heuristic now uses mapped/TRACKED
  (<2%) instead of mapped/IFC-products (<1%), which would have false-fired
  on any full-building IFC that legitimately dwarfs the tracked set.
- **BUG-11 residual FIXED** — `index.html` static `#three-note` no longer
  claims "ASSUMED 10ft"; neutral "3D preview · waiting for scene data"
  default, data-driven text unchanged.
- **BUG-03 residual FIXED (full fix, production-plan §1)** — `config.py`
  artifact dirs are now request-scoped: `_PROJECT_SLUG` ContextVar + PEP 562
  module `__getattr__` for ARTIFACT_DIR/EVIDENCE_DIR/UPLOAD_DIR/PAGES_DIR
  (static globals deleted); `bind_project()` sets the ContextVar per
  request. Load-bearing discovery: a ContextVar set in a SYNC FastAPI
  dependency is lost in the threadpool copy — `project_context`
  (routers/common.py) is now `async def`, verified end-to-end (per-request
  `X-Project`/`?project=` resolve to different artifact dirs in one
  process; starlette 0.52.1 `run_in_threadpool` propagates context via
  anyio `copy_context()`). Tests monkeypatching `config.ARTIFACT_DIR`
  still win (real attr shadows `__getattr__`). +2 tests → 157 green.

Post-fix live verification (2026-07-21, server restarted on fixed code):
157 pytest green; `benchmark_verified` calibration RESTORED via
POST /api/registration/benchmarks (repairing BUG-R2-03's damage), then
POST /api/registration/auto-holdown re-run live → `saved:false`,
`kept_calibration_source:"benchmark_verified"`, drift note (fresh
stochastic ransac differed by mean 7.34pt — confirming why the silent
overwrite was dangerous); /api/health stays benchmark_verified; Madera
baseline intact 354/107; H6 exclude override live in /api/teach
(`excludes:{H6}`, mem_008/009 kind=exclude) — applies on next Extract.

## Environment note (not a code bug)

During this session, running "Run full pipeline" once (see BUG-R2-03) and
rejecting one review item during the Human Review flow test
(s-201_h4_021_1, H4, LOCATION_MISMATCH, 4.12ft) were the only persistent
state changes this tester made; both are normal, documented, in-scope user
actions (not fixes/tweaks) and are captured with full audit evidence in
review_comments.json. The benchmark workflow was reset to idle via the
documented POST /api/benchmark-workflow/reset endpoint after a propose-only
smoke test, to leave the workflow state clean. Madera's overall MATCH count
(107/354) and holdown device summary were confirmed byte-identical to the
documented baseline at the end of the session.
