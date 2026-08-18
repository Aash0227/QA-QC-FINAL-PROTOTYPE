# QBC Project — Master R&D Report

**Date:** 2026-08-18 · **Repo:** `C:\QA-QC-FINAL-PROTOTYPE-bkp` · **Method:** Read-only research. 3 parallel research subagents + direct source verification. **Zero code changes.**

**Checklist analyzed:** `aftermodeling qa checklist.xlsx` — sheet "LIncoln Avenue After Modeling", 58 items in 4 groups (Walls 1–21, Hold-downs & Anchor Bolts 22–29, Floors 30–50, Plumbing 51–58).

**Sources:**
- Architecture/Claude-changes/pipeline audit: `subagent-summary-0-20260818_182529_596718.txt`
- Matching engine deep-dive: `C:\Users\aashd\matching-engine-research\matching-engine-report.{json,md}`
- Frontend + checklist AI design: `subagent-summary-2-20260818_182529_600740.txt`
- Direct source reads: `compare.py`, `device_match.py`, `leader_anchor.py`, `registration.py`, `all-in-one-fix.md` (217 lines, fully read)

---

## A. Current Architecture

A 7-stage artifact-chained pipeline. Each stage reads upstream artifacts, writes one artifact, and is orchestrated by `run_engine.py` (daemon thread, `run_state.json` persistence, 409 duplicate-run lock, stale recovery) against the DAG in `stage_graph.py`.

```
PDF upload (routers/workflow.py /api/upload, 50MB cap, magic-byte check)
  │
  ├─ 1. EXTRACT          element_detector.scan_pdf — 2-pass: schedule_tables
  │                      discovers tables → learns mark vocabulary from header
  │                      regex → detect_marks (count-prefix expansion, table/
  │                      title-strip exclusion) + teach.build_overrides +
  │                      leader_anchor.snap → element_intelligence.json
  │
  ├─ 2. REVIT_CONVERT    revit_convert.convert_revit (v2 family dict) OR
  │                      revit_v3_adapter.build_ai_revit (v3 spec-map assemblies)
  │                      + control_points scope diagnostics → ai_revit.json
  │
  ├─ 3. PDF_INTELLIGENCE generic_page_intelligence (picks holdown-densest sheet,
  │                      derives mark alternation from learned vocab) →
  │                      s201_detector.detect_s201_holdowns (generic geometry
  │                      engine: leader-following, marker snap, table masking)
  │                      → pdf_page_intelligence.json
  │
  ├─ 4. PDF_CONVERT      page-intel → normalized ai_pdf holdowns + leader_anchor
  │                      snap; advisory LLM mapping confirm → ai_pdf.json
  │
  ├─ 5. RANSAC           ransac_holdown — seeded mark-constrained RANSAC
  │                      (seed=42, both reflections, scale bounds) → calibration
  │                      (source=holdown_ransac); benchmark_verified never
  │                      overwritten; failed solve never saved
  │
  ├─ 6. COMPARE          registration-gated greedy match (16/40pt env-config);
  │                      anchor_verified refit accepted only if strictly better
  │                      → compare report (blockers/attempts/honesty)
  │
  └─ 7. MATCH            per-sheet calibrations; wall_match per sheet; per-sheet
                         holdown compare; v3 post/column points; element_registry
                         join; device_match physical-device re-accounting;
                         human-resolution reapply → element_list + device_registry
```

**Frontend:** two surfaces over one FastAPI backend (~8 routers, 75+ endpoints). Vanilla dashboard (`index.html`, 272 LOC + 9 panels, ~3178 LOC total) for PDF viewer / three.js 3D / element list; React island (`pipeline.html` + `src/react`, ~1403 LOC TS/TSX) for the pipeline timeline. Live Revit (Nonica/revitMCP via `revit_bridge.py`) is interaction-only, never verdict math. LLM (openrouter.py, deepseek/deepseek-v4-pro) is advisory-only throughout.

---

## B. Claude's Recent Changes

**Critical discovery:** Claude's recent changes are **uncommitted in the working tree** (HEAD is `d7db219`). The Madera fix went *further* than the docs describe — `profile.py` and `pdf_intelligence.py` were **deleted outright**, making generic the only code path. `all-in-one-fix.md` (dated today) is already partially stale.

| Item | Status | Evidence |
|---|---|---|
| registration | **actually-fixed** | registration.py:176-332 (≥3 pairs, collinear refusal, both-chirality fit, provenance gate VERIFIED_SOURCES, holdout validation, match_allowed); benchmark 2-pt separation/scale/rotation checks; failed solve never saved (routers/registration.py:268-271) |
| chirality/mirror | **actually-fixed** | registration.py:240-249 (both flips, lower RMS); device_match.fit_inverse:65-80 refuses <3 pairs; benchmark chirality cross-check is a BLOCKER never a silent flip (registration.py:454-480); test_device_match.py:45-66 pins it — *all-in-one-fix C1/T1 STALE* |
| clustering | **actually-fixed** | device_match.build_devices:137-191 anchor-based (not running centroid — kills chain-drift), same-sheet merges forbidden; tests pin no-same-sheet-merge + no chain-drift |
| same-mark handling | **actually-fixed** | same-sheet same-mark stays two devices (device_match.py:166-169); per-mark grouping compare.py:32-43; count-prefix expansion element_detector.py:40-41 |
| candidate assignment | **partially-fixed** | STILL greedy one-to-one everywhere (compare.py:156-172, device_match.assign:218-243, wall_match.py:163-184). Not Hungarian. Ambiguity guard exists ONLY in device_match, NOT in compare.py sheet-level. *all-in-one-fix L2 still valid* |
| ambiguity handling | **actually-fixed** | device_match._flag_ambiguous:196-215 + _claim:265-276 — near-tied same-mark → NEEDS_REVIEW, no target consumed, AMBIGUITY_MARGIN_FT env knob; tests pin it |
| NEEDS_REVIEW | **actually-fixed** | compare.py:146-153 (no coords), :173-178 (diagnostic never MATCH), :239-242 (type-only fallback); MATCH requires verified registration (honesty guarantee holds) |
| pipeline stage dispatch | **actually-fixed** | git diff: duplicate pipeline._run_stage DELETED; single dispatch run_engine._exec_stage:214-237 wired to /api/pipeline/run. *all-in-one-fix C2 resolved as recommended* |
| Madera logic | **actually-fixed** | profile.py + pdf_intelligence.py DELETED; pipeline.py:170-229 generic-only; normalization.py:22-32 vocabulary solely from project_config.json (MADERA_VOCAB removed); fabrication removed |
| Madera test fixtures | **fixed-but-architecturally-weak** | s201_detector.py retains PLAN_BBOX/S201_TABLE_BBOXES/HOLDOWN_RE solely for the Madera-PDF regression test (54 baseline); production module still ships dead client-specific constants |
| cross-project leakage | **actually-fixed** | config.py:49-59 ContextVar _PROJECT_SLUG + PEP 562; routers/common.py:31-51 binds per request. Residual (benign): common.py:67 _read_artifact.cache_clear() clears globally (AR4) |

---

## C. Current Accuracy Analysis

Sources of possible false MATCH and false MISMATCH (16 enumerated in `matching-engine-report.json` FM1–FM16):

**Worst false-MATCH paths:**
- **FM1 — same-mark neighbor swap**: compare.py has NO ambiguity gate; in dense same-mark clusters (4+ hold-downs), greedy assignment can swap true pairs. Only device_match has the 1ft ambiguity margin.
- **FM2 — synthetic-expansion MATCH**: `(2)HD2` count expansion fabricates 18pt-spaced points when leaders under-resolve; a synthetic point can MATCH a real assembly.
- **FM3 — leader-dot false snap**: leader_anchor snaps to a neighboring device's dot.
- **FM6 — mirrored RANSAC consensus**: RANSAC path has NO chirality cross-check; a near-symmetric plan can consensus-fit a mirrored layout and get a "verified" transform.
- **FM7 — scale blindness**: all sheet-side gates are in PDF points (see §D).
- **FM8 — multi-level bleed**: XY-only matching lets a level-1 point match a level-2 assembly (LEVEL_DELTA_FT=8 is only advisory at device level).

**Worst false-MISMATCH paths:**
- **FM4 — label-center fallback vs 16pt gate**: when leader-following fails, the label text center is used (±24pt), exceeding the 16pt gate. leader_anchor's docstring cites a live 2.04ft-vs-2.0ft-gate miss caused purely by label parking.
- **FM5 — registration budget exhaustion**: a medium match-allowed calibration may carry 32pt max residual vs a 16pt MATCH gate — registration error alone can eat the entire budget.
- **FM10 — schedule-parse cascade**: marks flow PDF-schedule → Revit; a schedule parse failure → mass REVIT_ONLY (honestly reported as vocabulary gap).
- **FM11 — insertion-point≠device offset**: Revit assembly center is the body insertion point, not the device center — a systematic offset.
- **FM12 — cross-sheet centroid drift**: clustering across sheets each solving its own transform.

**Systemic risk:** soft-fail stages read as "done." `pdf_intelligence` saves an error artifact and returns 200; `ransac` returns ok:false without raising. Both look green to run_engine, so a run can complete "successfully" with an empty or unregistered comparison.

---

## D. 2ft/3ft/6ft Analysis

The thresholds live in two different coordinate spaces — this is the core issue.

| Gate | Where | Compares | Space | Problem |
|---|---|---|---|---|
| **16pt / 40pt** | compare.py:24-25 | Revit body insertion pt (transformed) ↔ PDF callout anchor (dot/marker/label) | PDF points | **Scale-blind** |
| **2.0ft / 6.0ft / 3.0ft** | device_match.py:30-37 | device centroid ↔ assembly point; mismatch band; cross-sheet cluster box | model ft | honest |
| 2.0ft | revit_v3_adapter.py:40 | body+bolt member clustering box | model ft | — |
| 60/120pt | wall_match.py:26-27 | SW bubble/leader-tip ↔ wall centerline (point-to-segment) | PDF points | scale-blind |
| 1.0ft | device_match.py:41 | ambiguity margin (runner-up proximity) | model ft | only place it exists |

**What the point actually is differs by evidence path**: leader dot (best), hardware marker, or label center (worst, ±24pt) on the PDF side; body insertion point (not device center) on the Revit side.

**The three structural problems:**

1. **Scale blindness** — 16pt = 0.89ft at ¼″ scale but 2.7ft at ⅛″. The same "16pt MATCH" means wildly different physical tolerances depending on the sheet's drawing scale. Only the benchmark path checks scale. **This is the single most important reason "change 3ft to 1ft" is the wrong question** — the gate isn't even in a consistent unit.
2. **Registration error eats the budget** — solve-RMS + max-residual (up to 32pt on a medium calibration) can exceed the 16pt gate entirely. The calibration's own uncertainty is never subtracted from the gate.
3. **Uncertainty recorded but never consumed** — PDF-side `location_uncertainty_pt` (4–24pt by method) is written to the artifact but no gate reads it.

**Recommendation (from the research):** distance stays necessary but never sufficient. MATCH should require consensus — see §E.

---

## E. Hold Down Matching

**Current approach:** PDF callout → leader-following → filled-marker snap → `leader_anchor` re-anchors to the leader's target dot → registered to model space → greedy nearest same-mark assembly → verdict.

**Strongest next architecture (the evidence gate):** MATCH requires ALL of:
1. **mark equal** (normalized, schedule-derived)
2. **model-ft distance** within an **uncertainty-derived gate** = solve-RMS + PDF `location_uncertainty_pt` + anchor penalty (all already recorded) — NOT a fixed point gate
3. **spec equivalence OR host context** (schedule row spec match, or host-wall/panel context equal)
4. **uniqueness margin** (runner-up distance exceeds best by a margin, or a disambiguator exists)
5. **level compatible** (PDF z / Revit level)

Single-channel pairings (distance-only) degrade to NEEDS_REVIEW. Every verdict carries the per-channel evidence vector. **Every piece already exists scattered in the codebase** (ambiguity margin, chirality evidence, systematic-shift advisory, spec normalization, sheet_status audit) — the proposal unifies them into one gate.

---

## F. Generic Matching Architecture

One engine, per-category config. The config shape:

```
{ pdf_mark_regex, anchor_method, revit_categories, family_regex,
  geometry (point|segment), schedule_parser, datum_pair, gates_ft, context_join }
```

Posts/columns are already routed through compare.py (`V3_POINT_CATEGORIES`); shear walls through wall_match.py. The Hold Down evidence gate becomes the template: anchor method + geometry type + gates are the only things that change per category.

---

## G. Expansion Strategy

Hold Down → Anchor Points → Beams → Posts/Columns → Shear Walls → future.

- **Anchor bolts**: match as *groups relative to host assembly* (relative offsets), not absolute points — too dense for point gates.
- **Beams**: point-to-segment vs framing baselines + span evidence.
- **Posts**: symbol-center snap + grid-bay context (grid intersections already computed in control_points).
- **Shear walls**: upgrade bubble→wall-run segments; end hold-downs become cross-evidence anchors.

Shared must-haves: model-ft gates everywhere, uncertainty propagation, level/Z on PDF rows (channel exists, dormant).

---

## H. Frontend Architecture Research

**Inventory (verified LOC):**
- Vanilla surface: `index.html` (272) + `src/*.js` (app 137, api 38, sse 48, store 39, kinetic-grid 145, fonts 24, util 50) + 9 panels (`chat` 164, `inspector` 358, `list` 133, `pdf` 212, `projects` 390, `revit_live` 298, `table` 76, `viewer3d` 453, `wizard` 329) ≈ **3,178 LOC**
- React surface: `pipeline.html` + `src/react` (run-context 134, api/use-pipeline-events/use-typewriter/utils, 5 PipelineIsland components, 5 ui primitives) ≈ **1,403 LOC**
- **Duplication**: `api.js`↔`api.ts`, `sse.js`↔`use-pipeline-events.ts`, `kinetic-grid.js`↔`KineticGrid.tsx`
- Dead pipe-modal: the ~300 LOC is **already gone** from app.js (only 2 stray references, likely comments)
- Stale copy: `.claude/worktrees/blissful-neumann-*/frontend/` is an older snapshot — not part of the live app

**Recommendation — keep hybrid, migrate incrementally, NOT big-bang full React.**

Reasoning: PDF.js canvas and three.js WebGL CAN be React-owned (refs + useEffect escape hatches are standard), but the vanilla dashboard is a working, tested 9-panel app; a rewrite risks regressions for zero user-visible gain. The React island already proved the pattern (RunContext + SSE hook).

Path: extract one shared `apiClient` (delete `api.js`); port panels one at a time starting with `list`/`table` (pure data, lowest risk); leave `pdf`/`viewer3d` for last behind `<PdfCanvas/>`/`<Viewer3D/>` ref-boundary components.

React tree if migrated: `App > RunProvider > {TopBar, KineticGrid, PipelineIsland, PanelGrid > [PdfPanel, Viewer3DPanel, ElementList, Table, Inspector, Chat, Wizard], RunsDrawer}`.

---

## I. Full Pipeline Audit

| Stage | Soft-fail risk | Determinism | Evidence sufficiency |
|---|---|---|---|
| extract | novel schedule layout defeats row parser (fallback re-read) | deterministic | Good (center_pdf/bbox, vocab, count_consistency); wrong sheet heuristic poisons everything downstream |
| revit_convert | v3 empty spec map → unresolved marks (not an error) | deterministic, LLM advisory only | Assemblies + scope diagnostics naming missing exporter fields; whole-model exports stack levels → over-count |
| pdf_intelligence | **saves ERROR artifact, returns 200** — pdf_convert consumes empty artifact silently | deterministic | Detections + bbox/center/confidence; "done with error" indistinguishable from success in run_engine |
| pdf_convert | error-artifact input → 0 holdowns, no hard failure | deterministic core | ai_pdf with normalized marks + z_is_inferred honesty flags |
| ransac | **returns ok:false without raising** → stage DONE, no calibration saved; compare skips | deterministic (seeded) | Inlier pairs, RMS, per-pair residuals, drift vs benchmark; NO exterior validation unless validation_pairs supplied |
| compare | no usable registration → type-only fallback, all NEEDS_REVIEW (honest) | deterministic | Strong (nearest-candidate debug, per-mark counts, registration block, attempts); greedy-in-clusters + refit self-reinforcement risks |
| match | unregistered sheets → NOT_EVALUATED (honest) | deterministic | element_list + device_registry + scope_warnings; dual-verdict overwrite not explainable in UI (L1), elements_match ~260 lines (AR2) |

**Biggest systemic risk:** stages 3 and 5 fail softly and read green. A run can complete with an empty or unregistered comparison and no hard signal.

---

## J. AI Checklist Architecture

The QBC engine owns everything measurable; the AI checklist layer owns only interpretation. Proposed flow:

```
CURRENT QBC ENGINE
  → accurate element detection/matching
  → structured results/evidence artifacts
  → CHECKLIST EVIDENCE LAYER (deterministic retrieval, sufficiency scoring)
  → AI CHECKLIST REASONING (analyst + critic, judge on disagreement)
  → PASS / FAIL / REVIEW
```

The 58 checklist items map onto QBC results: items 1–6 (schedule conformance) are already partially answerable by QBC's spec-normalization; hold-down items 22–29 map directly onto the hold-down matching evidence; most floor/plumbing items (30–58) need NEW QBC element coverage (blocking, joists, punches, plumbing runs) before the AI layer has evidence to reason over.

---

## K. Checklist Agent Architecture

**Recommended: 2-agent (analyst + critic) as default, judge only on disagreement.**

| Option | Verdict |
|---|---|
| Single agent | Hallucinates with no check. Rejected. |
| **2-agent (analyst + critic)** | **Recommended.** Analyst proposes PASS/FAIL/REVIEW against the evidence package; adversarial critic gets ONLY the evidence package + analyst output and tries to falsify it. Agree → emit. Disagree → judge or auto-route to human. |
| 4-agent debate | 4× tokens/latency for marginal accuracy on mostly-mechanical items. Overkill. |
| Analyst + verifier | Weaker than critic — a verifier confirms, a critic falsifies. Falsification catches more. |

Items the critic flags with low evidence sufficiency → REVIEW, never forced PASS/FAIL.

---

## L. Checklist Evidence Architecture

**Principle: deterministic retrieval BEFORE the LLM. The LLM never searches; it only reasons over a closed package. No raw files, ever.**

Per-item evidence package:
```json
{
  "checklist_item": {"id", "text", "severity", "discipline"},
  "qbc_result": "deterministic engine verdict + rule outputs (pass/fail data, not prose)",
  "pdf_evidence": [{"doc", "page", "sheet_id", "region_bbox", "excerpt_text", "vector_snippet_ref"}],
  "revit_elements": [{"element_id", "category", "family", "parameters": {}, "geometry_bbox", "level"}],
  "schedule_row": {"schedule_name", "row_key", "cells": {}},
  "context": {"project metadata", "code version", "units"},
  "limitations": ["pages unparseable", "elements without geometry", "OCR gaps"],
  "sufficiency": {"score": 0-1, "missing": [...], "retrievable": bool}
}
```

**Sufficiency gate is deterministic and runs BEFORE the LLM call:** score < threshold → verdict forced to REVIEW/INSUFFICIENT_EVIDENCE, LLM not called. Every claim in the AI's reasoning must cite evidence ids from the package; the output validator rejects citations to ids not present.

---

## M. Model Strategy

| Role | Model | Notes |
|---|---|---|
| Normal items | DeepSeek V4 Flash-class | cheap, fast, adequate for mechanical checks. **needs-verification: exact OpenRouter slug/availability** |
| Complex items | DeepSeek V4 Pro (current default `deepseek/deepseek-v4-pro` — keep) or Claude Sonnet-class | multi-drawing reasoning |
| Judge | Claude Sonnet-class or V4 Pro at temp 0 | rare (disagreement only), so cost is fine |
| Critic | same class as analyst, different prompt; optionally a different model family | decorrelates failure modes |

Engineering reasoning + doc understanding: Claude Sonnet > V4 Pro > Flash. Cost/latency: inverse. Structured output: JSON-schema enforced; DeepSeek function/JSON mode historically flakier than Claude — **needs-verification on V4**; add 1 schema-retry with error echo.

---

## N. Latency / Cost Strategy

**3–5 min/item is a huge budget, not a constraint.**
- Per item: analyst ~3–8s (2–6k tok in, 300–800 out) + critic ~3–6s = ~6–15s serial.
- 20–50 items: parallelize 5–10 concurrent → 50 items ≈ 2–6 min wall total.
- Cost: ~50 items × ~10k tok ≈ trivial at Flash pricing; Pro-only-everything is the only expensive mistake.
- Caching: cache evidence packages by (item_id, model_rev, pdf_rev); cache LLM verdicts keyed by package hash.
- Retry: 1 schema-retry → 1 model-escalation retry → REVIEW with error. Never loop.

---

## O. Checklist Output Contract

```json
{
  "item_id": "str",
  "verdict": "PASS | FAIL | REVIEW | INSUFFICIENT_EVIDENCE",
  "confidence": "0-1 (self-reported, loosely calibrated — never trusted alone)",
  "evidence_citations": ["evidence_id..."],
  "reasoning_summary": "<= 200 words, references citations",
  "critic_agreement": "AGREE | DISAGREE | NOT_RUN",
  "reviewer_required": "true if REVIEW/INSUFFICIENT, confidence<0.7, or critic disagrees",
  "sufficiency_score": "echo from package",
  "model": "slug",
  "latency_ms": "int"
}
```

Non-empty `evidence_citations` required for PASS/FAIL, validated against the package.

---

## P. Accuracy / Hallucination Protection

- Closed evidence package — no file access for the LLM
- Citation validation (reject ids not in package)
- Sufficiency gate BEFORE the LLM call
- temp=0, seed where supported, pinned model slugs
- Adversarial critic + disagreement detection → judge or human
- Confidence threshold → reviewer_required
- Spot-check sampling: deterministic re-run of N% of PASS verdicts
- Full audit log: package hash + prompts + raw outputs per item

---

## Q. Implementation Roadmap

1. **Commit the working tree** — Claude's fixes (incl. profile.py/pdf_intelligence.py deletion) are uncommitted; commit + add test_device_match.py before anything else, and fix the `all-in-one-fix.md` staleness.
2. **Soft-fail hardening** — make pdf_intelligence/ransac soft-fails VISIBLE (stage reads "done (error)" not "done").
3. **Evidence gate for hold-downs** — unify the scattered pieces into the §E consensus gate; retire scale-blind point gates in favor of uncertainty-derived model-ft gates.
4. **Ambiguity guard in compare.py** — port the device_match 1ft margin to sheet-level matching (FM1).
5. **Chirality cross-check on the RANSAC path** (FM6).
6. **Shared apiClient + incremental panel migration** (frontend §H).
7. **Generic matching foundation** → Anchor Points → Beams → Posts/Columns → Shear Walls.
8. **Checklist evidence layer** (deterministic retrieval + sufficiency scoring) — needs new QBC coverage for floor/plumbing items first.
9. **AI checklist engine** (2-agent + judge), starting with the hold-down subset (items 22–29) where QBC evidence already exists.

---

## R. Major Risks

- **Uncommitted working tree** — the most valuable fixes in the repo are not committed; a branch switch or merge loses them. (Highest-priority risk.)
- **Soft-fail stages** silently produce green-but-empty runs.
- **Greedy assignment in dense clusters** — no test coverage for dense same-mark layouts; current baselines (dogwood-lane) don't exercise it.
- **Scale-blind point gates** — the same "MATCH" means different physical tolerances on differently-scaled sheets.
- **Schedule-parse cascade** — one schedule parse failure mass-produces REVIT_ONLY.
- **LLM checklist hallucination** — mitigated by the closed-package + critic + sufficiency-gate design, but structured-output reliability on DeepSeek V4 is unverified.
- **Elements_match ~260 lines** — will get worse as categories expand; refactor before expansion.

---

## S. Final Recommendation

Build the system in this order: **(1) commit the working tree now** (it contains verified fixes that go beyond the docs); **(2) fix the two soft-fail stages** so green actually means green; **(3) build the §E evidence-consensus gate for hold-downs**, replacing scale-blind point gates with uncertainty-derived model-ft gates and porting the ambiguity margin into compare.py; **(4) generalize that one gate across categories** via per-category config — do NOT build five independent matchers; **(5) only then build the AI checklist layer**, on top of the closed evidence-package contract, with a 2-agent analyst+critic design, deterministic sufficiency gating before any LLM call, and citation validation on every claim. Distance is evidence, never the verdict. MATCH requires consensus. Anything less routes to REVIEW — a wrong MATCH is the only unacceptable outcome.

---

*Read-only research. No files modified in the repo (this report is the only artifact written). Sub-agent raw reports and the matching-engine JSON are preserved at the paths listed in the header.*
