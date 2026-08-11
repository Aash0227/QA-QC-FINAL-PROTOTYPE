# AGENT HANDOFF — QA-QC prototype (updated 2026-07-17, benchmark-autopilot sprint)

If you are a fresh agent picking this up: read this file top to bottom, then
`backend/app/AUTOPILOT_PLAN.md` (the approved plan currently being implemented —
P0/P1/P2/P3/P4 done as of 2026-07-17, see its "Progress" section for exact
diffs and live-verification evidence; next in plan order: P7 (skill), then
P5 (3D fidelity), then P6 (full restyle)).
Older context: `docs/ACCURACY_100_PLAN.md` (the device-matching plan, now shipped).

## Environment (non-negotiable)
- Python: `C:\Users\aashd\AppData\Local\Programs\Python\Python311\python.exe`, run from `backend/` (module `app`).
- Server: `python -m uvicorn app.main:app --host 127.0.0.1 --port 8077` (background). A browser tab may fire `POST /api/projects/activate` at any time — always re-activate your project before chained pipeline calls.
- Tests: `python -m pytest -q` from backend/ (86 green as of handoff).
- Frozen modules (do NOT edit): compare.py, registration.py math, s201_detector.py, pdf_intelligence.py, review_overlay.py, normalization.py, revit_convert.py, pdf_convert.py. No fake matches ever.
- Frontend: single file `frontend/index.html` (+ keep `index_v3_backup.html` in sync).

## Current sprint (user goal, active Stop-hook)
1. **Implement `docs/ACCURACY_100_PLAN.md`** — physical-device matching:
   new `backend/app/device_match.py` (P1 registry: inverse-project per-sheet
   callouts to model ft, chirality-aware — see working math in
   `scripts/holdown_dedup_probe.py`; P2 global 1:1 assignment in FEET:
   MATCH ≤2ft, LOCATION_MISMATCH 2–6ft, MARK_MISMATCH same-place-different-mark,
   REVIT_ONLY only when no callout anywhere; P3 device statuses re-applied to
   element_list rows truthfully with device evidence in reason).
   Then P5 same for shear walls (pt-to-segment vs SW wall centerlines).
   Artifact: `device_registry.json`; endpoint GET /api/devices.
2. **Test on Madera + Country Side**, produce before/after table (probe
   ground truth: 122 holdown rows = 62 physical devices; 0 devices lack a
   Revit partner within 6ft; expect ~40+ device MATCH, 0 phantom PDF_ONLY).
3. **Human Review v2** — plan doc FIRST (`docs/HUMAN_REVIEW_V2_PLAN.md`), then:
   AI-first deterministic analysis per LOCATION_MISMATCH (offset ft +
   direction + systematic-shift detection), human comment → AI evaluates →
   animated Accept/Reject → on Accept: status → MATCH (via:"human_review",
   original distance retained), reflected in PDF overlay + 3D + punch list,
   and a teach-memory rule saved. Never silently mutate: the audit trail
   stays in review_comments.json.
4. **Bug sweep**: reviewer subagents over backend + frontend, fix CRITICAL/HIGH.

## Key facts discovered (do not re-derive)
- PDF y is FLIPPED vs model y: any similarity fit must try both chiralities
  (see `_fit_one(pairs, flip)` in scripts/holdown_dedup_probe.py).
- Per-sheet calibrations: `registration_calibration.json` (S-201/global),
  `registration_calibration_S-202.json`, `_S-205.json` in the project dir;
  `point_pairs` hold revit_ft ↔ pdf_pt pairs.
- Madera holdowns: 72 Revit assemblies (after the body-split fix in
  revit_v3_adapter.build_ai_revit), 122 sheet callout rows, 62 physical.
- Madera raw = `revit_export_enriched.json` (Downloads, built by
  scripts/enrich_madera_export.py; v2-merge provenance-tagged).
- Nonica Revit MCP: registered user-scope as "Revit"; use headless
  `claude -p "..." --allowedTools "mcp__Revit__*"` (tools not in this session).
  Live model must be open with A.I. Connector enabled.
- Run baselines: `artifacts/projects/madera/run_baseline.json` (v2 run);
  snapshot of entire old run at `artifacts/projects/madera_prev_v2_run/`.
- ⚖ Runs drawer + /api/runs/compare show old-vs-new tables.

## Status checkpoint (update this section as you work)
- [x] Plan written (docs/ACCURACY_100_PLAN.md)
- [x] device_match.py implemented (self-check green)
- [x] Integrated into /api/elements/match + GET /api/devices
- [x] Madera + Country Side results delivered (Madera 122 holdown rows -> 65
      physical devices: 44 MATCH/16 LM/4 PDF_ONLY/1 MARK_MISMATCH/11 honest
      REVIT_ONLY, 0 phantoms; overall MATCH 69->102->106 after review-accepts,
      coverage 95%. Country Side 12->21. 86 pytest green.)
- [x] Wall device matching (segment dist, absorb same-mark run segments,
      gates 4/12 ft; SW-3/SW-4 = vocabulary gap, teachable)
- [x] Human Review v2 plan doc + implementation, VERIFIED e2e
      (s-201_h2_035_1: analysis -> human logic -> AI verdict -> accept ->
      MATCH everywhere + audit block; persists across re-match, keyed
      category:mark:target_id)
- [x] Bug sweep fixed (XSS esc(), WebGL dispose+rAF cancel, filter desync,
      v3 bypass in /api/revit/ai-convert, teach.py id max+1)
- [x] Server verified running + dashboard screenshotted live (2026-07-15,
      354 elements / 106 MATCH / 231 discrepancies, 3D + PDF + review OK)
- [x] graphify knowledge graph built: graphify-out/graph.html + GRAPH_REPORT.md
      (753 nodes, 1540 edges, 42 labeled communities)
- [x] NEW_SESSION_PROMPT.md written (onboarding brief for any fresh agent)
- [x] 2-BENCHMARK REGISTRATION COMPLETE (2026-07-16, docs/BENCHMARK-REGISTRATION-PLAN.md
      A1-A7 all done): A1 registration.compute_calibration_from_benchmarks +
      A2 benchmarks.extract_pdf_benchmarks (were already on disk);
      config "pdf_benchmarks" artifact; A3 exporter collect_benchmarks()
      (doc-wide, family~Benchmark OR Mark BM-\d) + core.is_benchmark() +
      benchmarks passthrough in adapt_raw; A4 POST/GET /api/pdf/benchmarks +
      POST /api/registration/benchmarks (saves ONLY when match_allowed —
      never overwrites a working calibration with a failed solve; chirality
      evidence = holdown clouds via ransac_holdown._gather); A5
      tools/make_benchmark_stamp.py -> tools/stamps/BM-{1,2}.pdf (self-check:
      vector pass finds own crosshair) + docs/BENCHMARK-SOP.md; A6 "4b ·
      Benchmark calibration (2-point)" panel in Pipeline modal (backup
      synced); A7 tests/test_benchmarks.py: 98 pytest green (86+12).
      VERIFIED e2e via scratch project: stamped fixture PDF + synthetic
      raw_revit benchmarks -> extract found BM-1/BM-2 -> calibrate saved=True
      confidence=medium scale=18.0 drift=0.0% source=benchmark_verified;
      unstamped Madera -> honest not-found + 409, existing holdown_ransac
      calibration untouched.
- [x] REAL ACCEPTANCE DONE (2026-07-16, live via Nonica MCP Pro trial):
      placed mwfBenchmark copies in the LIVE Madera model (3951194=BM-1 at
      grid A x 1, 3951193=BM-2 at grid C x 3, exact-vector copies of pinned
      GM0 @1756546; readback-verified). Stamped the REAL permit PDF
      (Downloads/...STAMPED_10510 Madera Dr-DWG-20260122-D1.pdf, backup
      .pre_benchmarks.bak.pdf) with BM-1/BM-2 circle annots on S-201 p4 at
      trusted-transform projections. Injected benchmarks into
      raw_revit_export.json (backup kept). extract -> both found 0.98;
      calibrate -> saved=true, benchmark_2pt scale 17.966403 rot 0.051163
      offsets agree with holdown_ransac to ~1e-5 pt. Madera calibration is
      now benchmark_verified. Runner: backend/run_benchmark_acceptance.py.
      REMAINING: user saves/syncs the Revit model (copies are session-only
      until saved) + next real export should show "Benchmarks: 2".
- [x] FULL RE-MATCH UNDER benchmark_verified (2026-07-16 evening): compare/ai
      + elements/match re-run with the benchmark calibration -> results
      IDENTICAL to the holdown_ransac run (107 MATCH, holdown devices
      44 M/16 LM/4 PO/1 MM/11 RO), proving the 2-benchmark transform is a
      drop-in replacement (delta < 0.00002 pt). Two bugs fixed en route:
      (1) compare.py:39 had a corrupted identifier "group. ed" (stray edit,
      restored to "grouped" — pure repair, logic identical to _group_revit);
      (2) main.py elements_match crashed with dict+list TypeError when
      stored resolutions re-applied (registration_notes is a dict) — now
      sets result["resolutions_reapplied"]=N instead. Server restarted with
      fixed code; UI Match verified HTTP 200; 98 pytest green.

## SHIP DAY (2026-07-28 — 279 pytest + 7 Playwright green, live-verified on Country Side)
User workflow now: (1) upload PDF + Revit JSON — auto-benchmark proposes
BM-1/BM-2 from the PDF's own grids and asks approval via banner; (2) open the
same model in Revit with BOTH connectors on (Nonica A.I. Connector + revitMCP
"Open Server"); (3) review in the webapp. 🤖 deterministic phase summaries
appear in the pipeline log after every phase (phase_summary.py, SSE +
phase_summaries.json replay).
- **De-hardcoded** (HARDCODING_AUDIT.md): per-project pdf_baseline from each
  project's own pdf_page_intelligence (surgical compare.py diagnostics edit,
  invariance sha-proven on all 3 projects); QAQC_BENCHMARK_FAMILY env/payload
  override + benchmark-family discovery suggestions; frontend primary-sheet
  lookup via new GET /api/sheets/primary (no "S-201" literal);
  GET /api/registration/sheet/{sheet} implemented (was phantom 404 — measure
  scale was broken on every non-primary sheet); intelligence_source stamp.
- **Live hybrid 3D**: GET /api/revit-live/scene + POST /api/revit-live/refresh-3d
  (bbox massing via Nonica, 60s cache, capped at 3000/category with honest
  truncation note); viewer3d.js renders snapshot instantly then swaps in LIVE
  with badge + ⟳ live button. Country Side live: 499 walls/3000 framing/28
  columns/1150 connections, 219 status-joined when its project is active.
- **Flaw fixes**: R-03(safe/dormant) R-10 R-15 R-21 R-22 R-25 R-27 R-30 and
  new R-35 (Revit modal dialog blocks tools → reads must error, not report
  "nothing selected"; _looks_blocked in revit_bridge). See flaw report status
  block for the honest STILL-OPEN list (mostly needs the pyRevit exporter).
- **Country Side acceptance (all pass)**: correct model detected; live 3D ok;
  Show-in-Revit on rev_asm_031 → live selection 0.003 ft; "Use current Revit
  selection" via revit_mcp → full plain-English verdict; match deterministic
  across 2 runs; runs-drawer per-device baseline works.
- Docs: README/USER_GUIDE/LIVIO_TEAM_GUIDE rewritten for the 3-step workflow;
  docs/CODEBASE_AUDIT_REPORT.md = senior-engineer line audit;
  HARDCODING_AUDIT.md = triaged hardcode inventory.

## REVIT-LIVE ROUND 2 (2026-07-27 late — all live-verified, 207 pytest + 7 Playwright green)
- **"Show in Revit" bug ROOT-CAUSED + FIXED (R-34, new flaw)**: Nonica
  compresses LARGE tool responses into subset lines
  (`selected_ids[28]{SubsetId,IdsCount,SampleElementId}: -9000017,28,2804799`);
  the parser read that as "selected none" even though selection succeeded.
  `_subset_ids()` in revit_bridge.py handles subset form in select_elements +
  get_selection; responses now carry `selected_count`. The frontend was NEVER
  the bug — it already passed assembly_id.
- **Open-source revit-mcp integrated** (`mcp-servers-for-revit`, add-in at
  %APPDATA%\Autodesk\Revit\Addins\2023\revit_mcp_plugin\): its Node "server"
  is a pure relay to a raw TCP socket at 127.0.0.1:8080 (REVIT_MCP_ADDR env
  overrides) — backend talks to the socket directly, no node. 25 tools incl.
  get_selected_elements (returns Id/UniqueId/Name/Category only — no point;
  point comes from the Nonica coordinate cache). OPERATOR STEP: revitMCP
  ribbon > "Open Server" must be clicked in Revit, else honest Nonica
  fallback. New bridge fn get_selected_element_full(); new endpoint
  GET /api/revit/selected-element (merged with _explain_element — the
  refactored shared join also used by /api/revit/lookup/{id}); lookup drawer's
  "Use current Revit selection" is now one call.
- **Trust fixes shipped**: R-18 `revit_only_detail` causes + `status_detail`
  pills (REVIT_UNCLASSIFIED vs REVIT_ONLY); R-07 scope_warnings banner
  (pdf callouts > 0 but 0 Revit targets); R-29 per-device run diff
  (`device_changes` in /api/runs/compare keyed category:mark:target_id;
  baselines now snapshot devices — old baselines report device_changes:null
  honestly; NOTE Madera's run_baseline.json was overwritten with a "trustfix"
  snapshot during verification). Madera invariance proven: by_status identical
  (MATCH 106) before/after.
- Tests: backend/tests/test_trust_fixes.py (+10), test_revit_live.py grew to
  cover subset compression + selected-element; smoke.spec.js mocks
  /api/revit/selected-element for the one-call flow.

## REVIT-LIVE PHASE 1 SHIPPED (2026-07-27 evening, live-verified on Madera)
- **Flaw audit**: `docs/REVIT_SIDE_FLAW_REPORT.md` — 33 verified Revit-side
  flaws (R-01..R-33), 2 reproduced by execution; read it before touching the
  Revit side. Both planning docs cited NONEXISTENT Nonica tools
  (`operate_element`, `send_code_to_revit`) — correction notes added to both;
  real tools are `set_user_selection_in_revit` etc. There is NO zoom tool
  (UX = select + "press ZS").
- **R-01 FIXED** (chirality coin flip): device_match now uses the
  calibration's stored `transform.inverse_matrix`
  (`inverse_from_calibration()`); `fit_inverse` refuses <3 pairs. Verified
  invariant: worst deviation 3.8e-8 ft across all 264 Madera callouts.
- **R-13 FIXED**: routers/revit.py now uses `revit_ids.unique_id_to_element_id`
  (correct XOR decode) everywhere.
- **New endpoints** (routers/revit.py, additive): POST /api/revit/highlight
  (assembly_id or element_ids → selects ALL coordinate hits in live Revit),
  GET /api/revit/selection, GET /api/revit/lookup/{element_id} (paste-an-id →
  assembly + device verdict + review.analyze() facts + deterministic
  plain_english + classification_reason + registration_quality). Bridge adds
  select_elements/get_selection/element_location.
- **R-24/R-19 partial**: device_registry now carries `registration_quality`
  per sheet; lookup surfaces `classification_reason`.
- **Frontend**: new `src/panels/revit_live.js` — 🎯 Show in Revit button
  (inspector + review drawer, greys out honestly when connector off),
  "Why this verdict?" details block (calls GET /api/review/{row_id}/analysis),
  🔎 Revit ID header drawer (paste id or "Use current Revit selection").
  Also FIXED: viewer3d.js had lost its `loadScene` export (app.js import
  crashed the whole module graph) — restored minus the removed IFC bits.
- **Tests**: 190 pytest green (165 baseline +25, new tests/test_revit_live.py);
  Playwright 7/7 green. MATCH baseline is now **106** (was 107): the 7-24
  leader-anchor snap made 4 previously human-accepted mismatches natural
  MATCHes (verified device-by-device; the one stored reject still honored).
- **Live acceptance**: rev_asm_004 (H2 LOCATION_MISMATCH) highlighted in the
  open Madera model via the UI button; selection read back = its 3 member
  ids; lookup of 1222142 returns the full explanation chain.
- NOT done (deferred, see flaw report Part 4): live model fetch replacing the
  JSON export, qa_status write-back (use set_additional_property_* when you
  do), SCOPE_SUSPECT verdict, export-age banner, R-06/R-07/R-14.

## Scope Changes (2026-07-21)

### IFC Integration Removed

All IFC/BuildingSmart data-model integration has been completely removed from the codebase:

**Backend (Python):**
- `routers/elements.py`: Removed `ifc_status()` and `ifc_model()` endpoints
- `routers/projects.py`: Removed IFC upload handling from `POST /upload`
- `main.py`: Removed IFC re-exports from elements module
- `revit_ids.py`: Removed IFC GlobalId handling functions

**Frontend:**
- Deleted `src/ifc_guid.js` entirely
- `src/panels/viewer3d.js`: Removed all IFC rendering logic (`initIFCViewer`, IFC element coloring, IFC picking, web-ifc import)
- `index.html`: Removed web-ifc library dependency and IFC button from UI

**Tests:**
- Removed `test_ifc_status_and_serve` from test suite

**Reason:** The IFC viewer approach was abandoned in favor of direct Revit data extraction and the existing 3D visualization pipeline, which provides better integration with the native Revit coordinate system and element metadata.

---

## DOGWOOD DEMO (2026-07-15, CEO meeting) — done end-to-end, nothing mid-edit
- Exporter unicode crash fixed (ASCII-fold _fold() inline in
  ExportQAQC.pushbutton/script.py; 0xD8 diameter bytes -> "dia.").
- HTT tension-tie support: revit_v3_adapter HOLDOWN_FAMILY_RE now
  (HTT|HD[UB]?), variant keys PREFIXED ("HD15S", "HTT4") on BOTH spec and
  family sides; self-checks + 86 tests green.
- NEW spec_map_from_pdf_tables() in revit_v3_adapter + _spec_map_with_fallback()
  in main.py: when schedule row-parse yields {}, re-reads each holdown table
  bbox from the PDF (words grouped by y-row, mark/type disambiguated by the
  table's own column x-ranges). Dogwood: {'HTT4': 'HD2'} — matches the
  drawing's HOLDOWN SCHEDULE exactly.
- Pipeline order that WORKS for a fresh project: upload pdf -> extract ->
  page-intelligence (needs ei for the generic fallback; S-201 detector fails
  honestly on non-Madera sets) -> upload revit json -> ai-convert(use_saved)
  -> pdf ai-convert(use_saved) -> auto-holdown RANSAC -> compare -> match.
- Dogwood results: 43 PDF holdown devices vs 62 Revit (60 HTT4=HD2);
  16 MATCH / 20 LM (systematic: analyze() reports 15/19 peers same direction,
  lean-accept) / honest PDF_ONLY 16, REVIT_ONLY 35. Shear walls: 25 PDF runs
  vs 0 walls in export (view hides walls — re-export with Walls visible).
- Project workspace: artifacts/projects/dogwood-lane, active on server.

## Immediate next action (start here)
SPRINT COMPLETE — do NOT recreate device_match.py or redo any [x] item.
Remaining queue:
1. 3 tiny patches (diffs in transcript + NEW_SESSION_PROMPT.md): scene3d.py
   ~L89 `if c.get("z")` -> `is not None`; element_registry.py ~L35 duplicate
   sheet_number overwrite; elements_match ARTIFACT_DIR race guard.
2. GitHub push: PRIVATE repo `Livio-QA-QC-AI`; never store tokens in files;
   .gitignore artifacts/ artifacts_*/ **/uploads/ .env __pycache__/
   .playwright-mcp/ *.log; verify no sk-or-v1 key committed. The ghp_ token
   the user pasted in chat is BURNED — user must rotate it first.
3. Country Side live acceptance via mcp__Revit__* (expect 28 columns) when
   that model is open in Revit.
4. WAIT for the user to describe the "Livio checklist" (next major phase) —
   do not build it speculatively.

## Verification / smoke test (run before declaring any phase done)
1. From `backend/`: `python -m pytest -q` — must stay green (86 as of handoff).
2. Start server: `python -m uvicorn app.main:app --host 127.0.0.1 --port 8077`.
3. Re-activate project (`POST /api/projects/activate`) before any chained call.
4. Hit `GET /api/devices`; check against probe ground truth: Madera = 122 callout
   rows → 62 physical devices, 0 devices without a Revit partner within 6ft,
   expect ~40+ device MATCH and 0 phantom PDF_ONLY.
5. Confirm `device_registry.json` artifact is written and statuses are re-applied
   truthfully to element_list rows with device evidence in the reason field.

## Do-not-repeat gotchas
- PDF y is FLIPPED vs model y — always try both chiralities in any similarity fit.
- All distance thresholds are in FEET (MATCH ≤2, LOCATION_MISMATCH 2–6), not points.
- Never silently mutate a status: audit trail lives in `review_comments.json`;
  human-accepted matches carry `via:"human_review"` and retain original distance.
- REVIT_ONLY only when no callout exists anywhere — not merely no nearby callout.
- Keep `frontend/index.html` and `index_v3_backup.html` in sync.
- Write the plan doc FIRST for Human Review v2 (`docs/HUMAN_REVIEW_V2_PLAN.md`)
  before writing any code for sprint item 3.
