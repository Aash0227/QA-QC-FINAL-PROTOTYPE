# QBC — Complete State Reconstruction

**Date:** 2026-08-19 · **Repo:** `C:\QA-QC-FINAL-PROTOTYPE-bkp` @ `fix/integration-runcheck` (HEAD `b165acd`)
**Method:** read-only reconstruction. 3 parallel investigation subagents + direct source verification. Zero code changes.

---

## A. CURRENT ARCHITECTURE

The diagram is correct in spirit; precise module names below. The system moved substantially past the "QBC_RND_MASTER_REPORT" state — the evidence-consensus gate was built.

```
PDF + Revit (upload: /api/upload 50MB, magic-byte; Revit JSON export)
  → EXTRACT (element_detector: schedule_tables learns vocabulary → detect_marks
      + teach overrides + leader_anchor snap → element_intelligence.json)
  → REVIT_CONVERT (revit_convert v2 / revit_v3_adapter v3 → ai_revit.json)
  → PDF_INTELLIGENCE (generic_page_intelligence → s201_detector geometry engine
      → pdf_page_intelligence.json)
  → PDF_CONVERT (normalized ai_pdf + leader_anchor → ai_pdf.json)
  → RANSAC / registration (ransac_holdown seeded; registration.py both chiralities,
      provenance gates, holdout validation; benchmark path blocked on chirality)
  → COMPARE (compare.py: registration-gated greedy, 16/40pt env-config)
  → MATCH (element_registry join → device_match per-category adapters
      → matching_engine.py generic evidence engine [946 lines])
  → EVIDENCE (engine emits per-channel vector: mark / adaptive distance /
      ambiguity / level / orientation / context-consensus)
  → PRODUCT VERDICT (matching_engine.product_verdict: internal statuses mapped to
      LOCATION_MATCH | LOCATION_MISMATCH | NEEDS_REVIEW | NOT_APPLICABLE;
      read-time backfill via ensure_product_blocks)
  → REVIEW QUEUE (/api/review/queue) + element_list
  → UI (hybrid: vanilla dashboard + React mounting under dashboard-main.tsx;
      pipeline.html = React PipelineIsland only)
  → AI AGENT (chat_agent.py tool loop: real evidence via explain_element /
      get_pipeline_story / get_counts / query_elements / get_device; LLM
      advisory-only, never gates a verdict)
```

**Orchestration:** `run_engine.py` (daemon thread, run_state.json, 409 duplicate lock, stale recovery) + `stage_graph.py` (7-stage DAG, invalidate_downstream). Backend: single FastAPI, uvicorn **1 worker**, no database (JSON artifacts under `artifacts/projects/<slug>/`), per-request project isolation via ContextVar, shared bearer token `QAQC_AUTH_TOKEN` (empty = no auth).

---

## B. IMPLEMENTED FEATURES (proven to exist)

**Generic matching engine** (`backend/app/matching_engine.py`, 946 lines):
- `AdapterConfig` (:41) — frozen dataclass, all category knobs.
- `adaptive_match_ft` (:220) — registration-uncertainty-aware gating: widens base tolerance by worst-sheet registration residual (rms/scale), capped at ceiling×base, never narrows.
- `optimal_assignment` (:241) — pure-Python Hungarian (Jonker-Volgenant), O(n³), pinned vs 300 random matrices (test_device_match.py:~455-469). OFF by default (greedy preserved for regression-validated categories).
- `_flag_ambiguous` (:385) — runner-up within ambiguity_margin_ft → NEEDS_REVIEW, no target consumed.
- `fit_inverse` (:92) — both chiralities, refuses <3 pairs.
- `resolve_ambiguity_by_orientation` (:675, **called** :446) — post-hoc tie-break on NEEDS_REVIEW-ambiguous devices only.
- `resolve_ambiguity_by_context` (:740, called :447) — sheet-consensus tie-break.
- `sheet_context_consensus` (:530) — ranked votes, MATCH authoritative, LOCATION_MISMATCH corroborates-only.
- Product layer: `product_verdict` (:863), `product_result` (:887), `ensure_product_blocks` (:913 — idempotent read-time backfill), `summarize_product_verdicts` (:939).

**Adapters** (both in `device_match.py`, not separate files):
- `HOLDOWN_ADAPTER` (:57) — point_distance, match_ft=2.0, mismatch_ft=6.0, mark_blind=True, NO context/orientation, greedy (`global_assignment=False`, regression-pinned test_device_match.py:495).
- `SHEAR_WALL_ADAPTER` (:62) — segment_distance, match_ft=4.0, mismatch_ft=12.0, `context_key='level'`, orientation_tolerance_deg=20.0, `global_assignment=True` (Hungarian).

**Leader-tip corrected anchor fix** — device_match.py:184-194; regression test test_device_match.py:202 (`test_shear_wall_uses_leader_corrected_anchor_not_raw_bubble`).

**Product verdict mapping** (matching_engine.py:842-884): MATCH→LOCATION_MATCH; LOCATION_MISMATCH|MARK_MISMATCH|PDF_ONLY|REVIT_ONLY→LOCATION_MISMATCH; NO_REVIT_DATA|SPEC_ONLY|NOT_IN_SCHEDULE|NOT_EVALUATED→NOT_APPLICABLE; everything else→NEEDS_REVIEW. Uncertainty never promoted. Backfill is read-time, pure, idempotent, never overwrites fresh blocks (callers: routers/elements.py:50-61 GET /api/elements, :480 punch-list export, chat_agent.py:247; write-time stamp element_registry.py:269-275).

**Frontend** — hybrid migration is real:
- `index.html` loads BOTH vanilla `src/app.js` AND React `src/react/dashboard-main.tsx`.
- React features exist: ProjectManager (+VerdictRing), element-review (ElementList/ResultsTable/ScopeBanner), inspector (Inspector/ReviewWorkspace/RunsComparison/CountConsistency), chat/Chat.tsx, benchmark-wizard, verdict (VerdictBadge/VerdictBarPanel) — mounted into vanilla DOM containers, bridged via shared store.js + CustomEvents. Documented staged strategy (no Tailwind on dashboard, tokens.css/app.css identity kept).
- `pipeline.html` = React-only PipelineIsland.
- Shared infra: API **shared** (`src/shared/api.ts`); SSE duplicated-connection/shared-contract; auth shared.
- **Correction to a prior claim:** revit-live is NOT React — still vanilla `panels/revit_live.js`.

**Pipeline UI** — stage headlines read real artifact counts, not LLM fabrication: `main.py:57 _step_headline` (verdict_counts, canonical assemblies), `phase_summary.py` ("Reading drawings: {len(marks)} callouts across {len(sheets)} sheets", "Reading model: {len(assemblies)} assemblies", "Match: {total} elements — {breakdown}").

**AI/QBC agent** (`chat_agent.py`) — OpenAI-style tool loop, capped at 6 rounds, nothing destructive. Tools: get_counts, query_elements, get_device, get_run_comparison, get_workflow_state, run_pipeline_step, save_teach_rule, **explain_element** (:184/:419 — returns actual row evidence), **get_pipeline_story** (:202/:468), focus_element. System prompt mandates: "call explain_element… it returns the actual evidence, not hallucinated." Read-mostly toolbox.

**Testing/QA** — real infrastructure: backend pytest (436 tests), Playwright UI QA docs (`UI_QA_FINDINGS.md`), Madera snapshot manual-diff validation.

---

## C. VALIDATED FEATURES (real-data vs unit-test-only)

| Feature | Real-data (Madera) | Unit-test |
|---|---|---|
| Hold Down adaptive matching | ✅ manual pre/post-diff, byte-identical over `artifacts_madera_snapshot/` | ✅ behavior pins (adaptive gate, ambiguity, chirality, cross-floor) |
| Shear Wall on generic engine | ✅ OLD→NEW measured on real data (commit messages) | ✅ per-channel synthetic tests (test_device_match.py:264-588) + leader-tip regression (:202) |
| Hungarian optimal assignment | ✅ optimal==greedy on Madera (fa1da74) | ✅ pinned vs 300 random matrices |
| Chirality | ✅ benchmark path blocked on mirror | ✅ test_device_match.py:45-66 |
| Product verdict backfill | ✅ (read-time, idempotent) | ✅ test_product_verdict.py:126-170 |
| Orientation rejection | ✅ measured then rejected on real data (4ed9065) | n/a (experimental) |

**Validation methodology is honest but has one gap:** the headline numbers are locked by **manual commit-message diffs over the Madera snapshot + synthetic-fixture behavior pins**, NOT by an automated regression test that re-runs the snapshot. If the snapshot or engine changes, no CI test catches drift in the 45/8/21 or 12/8/2 totals (see §F).

---

## D. CURRENT ACCURACY STATE (verified)

**Hold Down (real Madera, commit `a92156a`):** 122 callout rows → 84 devices →
**45 MATCH · 8 LOCATION_MISMATCH · 21 NEEDS_REVIEW · 10 PDF_ONLY**
Matches Gate 3's validated numbers post-refactor, byte-identical. (The 10 PDF_ONLY is additionally reported; the ~45/8/21 claim omitted it.)

**Shear Wall (real Madera):**
- OLD (commit `7458edd`, leader-tip fix): 53 devices → 5 MATCH · 3 LOCATION_MISMATCH · 14 NEEDS_REVIEW · 31 PDF_ONLY
- NEW (`0faf543` level channel root-caused 14/14 NR as stacked same-mark walls; `4ed9065`/`fa1da74`): **12 MATCH · 8 NEEDS_REVIEW · 2 LOCATION_MISMATCH · 31 PDF_ONLY · 12 revit_only**

Crucially, NEW was NOT achieved by widening thresholds — by level/context evidence (identical SW at same XY on different floors) + ambiguity guard. Shear Wall deliberately frozen rather than forcing more matches.

**Orientation rejection (measured, not hypothesized, commit `4ed9065`):** promoting orientation to a primary claim-ordering key + scoping ambiguity to orientation-compatible candidates resolved 3 ambiguities but **cost a MATCH and turned 4 pairings into LOCATION_MISMATCH (MATCH 12→11, LM 2→6)** on real data. **Reverted.** Orientation remains ONLY as a post-hoc, near-tie, conservative resolver (`resolve_ambiguity_by_orientation` @ :446). Never reintroduce the primary usage.

---

## E. CURRENT TEST STATE

Ran `cd backend && py -3.11 -m pytest -q --tb=no`: **436 tests — 434 pass, 2 fail.** (Better than the doc's stale 374/11; the 10 test_normalization failures are FIXED.)

- **Failing (pre-existing, documented):** `test_control_points.py::test_scope_diagnostics_flags_missing_metadata` — 1 of the 11 PHASE1-documented failures, still open.
- **Failing (NEW, not a functional regression):** `test_ai_status_endpoint.py::test_ai_status_without_key_is_deterministic` — copy-vs-test drift. Endpoint correctly returns `source='deterministic'`, but the rewritten deterministic 'ransac' copy no longer contains the word 'complete' that the test asserts. Stale assertion.
- **Order-dependent/flaky:** none fired this run (the documented test_run_state flake did not reproduce; both failures reproduce standalone).
- **Targeted:** `test_product_verdict.py + test_device_match.py + test_wall_match.py` = **48/48 pass.**

---

## F. REMAINING GAPS (to production-grade end-to-end)

1. **No automated regression lock on Madera totals** — validation is manual commit-message diff + synthetic pins. A CI test must re-run `artifacts_madera_snapshot/` and lock 45/8/21 (HD) and 12/8/2 (SW).
2. **Elements_match is ~260 lines (all-in-one-fix AR2, still open)** — refactor before adding more categories.
3. **UI QA — C-1 + H-1..H-6 + H-7-remainder OPEN** (21 findings; only H-7 partially fixed mid-audit by 2 commits): stuck verdict filter, dead Verdict sort, two contradictory "needs review" counts, filter-survives-reload, dual colour palettes, horizontal overflow, no responsive <1100px, ReviewWorkspace still raw engine statuses. Cheapest: H-3 (1 line), C-1 (1 line + chip), H-1 (3-line comparator).
4. **Soft-fail stages read green** (from the prior R&D report, still true): pdf_intelligence error-artifact-200, ransac ok:false-without-raise — both look "done" to run_engine.
5. **Deployment — Revit Agent does not exist.** Only single-workstation deployment ships today (≤1 concurrent Revit user). Auth = one shared token, empty-by-default, no users/permissions/audit. Pilot-grade only.
6. **Checklist expansion needs NEW element coverage** — the 58-item After-Modeling checklist's floor/plumbing items (blocking, joists, punches, plumbing runs) have no QBC evidence yet, so the AI checklist layer cannot reason over them.
7. **Soft-fail/new test failure** — fix the stale ai_status assertion (or pin the deterministic copy).

---

## G. ARCHITECTURAL RISKS

- **Single-worker run lock is process-local** (C3): fine at `--workers 1`, silently breaks duplicate-run detection if workers ever scale. Enforce at launch or move to filesystem lock.
- **Soft-fail pipeline stages** (see F4) — a green run can be empty/unregistered.
- **Scale-blind point gates at the compare layer** (16/40pt): the adaptive engine has model-ft gates, but the compare.py per-sheet gate is still PDF-pt — a mixed-unit boundary.
- **Dense same-mark clusters**: Hungarian exists for SW; Hold Down is intentionally greedy (regression-pinned). A dense-HD project would stress this — not covered by the current baselines.
- **Checklist layer not yet grounded** — LLM checklist is design-only; shipping it before evidence coverage (F6) would produce hallucinated verdicts.
- **Auth before network exposure** — token is empty by default; deploying beyond localhost without setting it = no auth at all.

---

## H. RECOMMENDED NEXT STEPS (prioritized)

1. **CEO/demo reliability** — Land the cheap UI-QA fixes (C-1 + H-3 to unblock the filter trap; H-1 sort; H-2 single review count). Single-workstation deployment works today — demo from one machine.
2. **QA/QC engineer usefulness** — Fix the ai_status stale assertion; make ReviewWorkspace speak product verdicts (finish H-7); punch-list CSV already has verdict column (verify M-6).
3. **Matching accuracy** — CI-lock the Madera totals (F1); factor the RANSAC chirality cross-check onto the RANSAC path (parity with the benchmark/manual paths); consider moving the compare.py point-gate to model-ft; split elements_match (AR2).
4. **Workflow smoothness** — soft-fail visibility (stage reads "done (error)"); run-button pending/disabled state + Force confirmation (from the pipeline QA note).
5. **Deployment readiness** — set QAQC_AUTH_TOKEN + TLS + internal bind before ANY exposure; scope the Revit Agent (protocol, offline-mid-run, unavailable handling) as the only real new engineering.

Raw sub-agent reports: `subagent-summary-{0,1,2}-20260819_161926_*.txt`. Zero code changed.
