# Revit-Side Flaw Report & Solution Plan

**Date:** 2026-07-27 · **Audience:** founder + QA-QC reviewers · **Scope:** everything between Revit and the verdict table. The PDF side (extraction, RANSAC, benchmarks) is solid and untouched.

> **Status update (2026-07-27 late):** ✅ DONE that night: R-01, R-13, R-16 (highlight selects all hits), R-18 (REVIT_ONLY cause split as `status_detail`), R-19/R-24 (classification_reason + registration_quality surfaced), R-26 (Why-panel everywhere), R-29 (per-device run diff in the Runs drawer), R-07 partial (scope-warning banner; full fix still needs doc-wide exporter counts). Plus a NEW flaw found & fixed live: **R-34 — Nonica compresses large tool responses into subset lines** (`selected_ids[28]{SubsetId,IdsCount,SampleElementId}: -9000017,28,2804799`), which made successful 28-element selections read as "selected none"; parser now handles subset form (`_subset_ids` in revit_bridge.py). Also shipped: `GET /api/revit/selected-element` — click an element in Revit, one click in the webapp, full explanation (open-source revit-mcp socket on 127.0.0.1:8080, Nonica fallback).

> **Status update (2026-07-28 ship day):** ✅ ALSO DONE: R-03 (safe version — Δz plumbing + different-level note, dormant until rows carry elevation), R-10 (Generic Models + Structural Framing searched, regex-guarded), R-15 (cached/age_s surfaced end-to-end, "as of Ns ago" in UI), R-21 (MARK_MISMATCH in accuracy denominator), R-22 (CSV exports distance_ft), R-25 (reasons name the PDF callout + sheet), R-27 (per-project pdf_baseline from the project's own pdf_page_intelligence — hardcoded Madera dict deleted from compare.py diagnostics, invariance sha-proven), R-30 (structural connector-response check — empty parse without ContextUpdate markers = transport failure, not a model fact), plus **R-35 (new, found live)**: a modal dialog in Revit (e.g. revitMCP "Open Server") blocks all tools and made an active selection read back as "nothing selected" — blocked-UI responses now return an honest error with the unblock hint. De-hardcoding: benchmark family env/payload override (QAQC_BENCHMARK_FAMILY), dynamic primary-sheet lookup in the frontend, `/api/registration/sheet/{sheet}` implemented (was a phantom 404 route), intelligence_source stamped. STILL OPEN (need the pyRevit exporter, outside this repo): R-04, R-05, R-06, R-07 full, R-08, R-11, R-12, R-14 full; and R-02, R-09, R-17, R-20, R-23, R-28, R-31, R-32, R-33 (tracked for the next sprint).

This synthesizes four deep audits (2 codebase-understanding passes, 1 adversarial flaw audit, 1 plan-feasibility analysis). Every flaw below was verified against actual code — two were **executed and reproduced**, not just read.

---

## Part 1 — The headline problems (read these five first)

### 1. CRITICAL — The mirror-flip (chirality) is decided by luck under 2-benchmark calibration
`device_match.py:31-75` re-solves the PDF→model transform from the calibration's point pairs and picks the mirrored-vs-not variant by lower RMS. With exactly **2** benchmark points, *both* variants fit perfectly — the winner is decided by ~1e-13 of floating-point noise. Reproduced live on the real Madera calibration (flip wins by 4e-14 vs 1.7e-13). Madera is correct **by luck**. On the next project, a near-axis benchmark line can mirror the entire holddown report: every device 20–60 ft wrong, everything PDF_ONLY/REVIT_ONLY, all under a green `benchmark_verified` badge.

**What the QA-QC employee sees:** 60 rows of "No H2 Revit device within 6.0 ft" and concludes the model has no holdowns. Nothing hints the drawing was read mirror-image.
**Fix:** the calibration already stores the exact `inverse_matrix` — use it; never re-derive chirality from fewer than 3 pairs. *(Being fixed tonight — verdict logic untouched, only the transform source.)*

### 2. CRITICAL — The one ID a reviewer can hand-check decodes wrong
`routers/revit.py:43` converts UniqueId→ElementId with the naive decode that `revit_ids.py` (in the same codebase!) documents as wrong — 4 of 7 real Madera elements fail it. When the Nonica connector is off, the UI shows these wrong IDs; a reviewer pastes one into Revit's *Select by ID* and lands on a random element ~half the time. Instant trust destruction.
**Fix:** one import line — use `revit_ids.unique_id_to_element_id`. *(Fixed tonight.)*

### 3. CRITICAL — The report can't tell you it's stale or incomplete
- The exporter counts elements it **silently skipped** (exceptions) but never writes that count into the JSON — 14 skipped holdowns look identical to 14 modeling omissions (`script.py:224,255`).
- The exporter writes `exported_at`, and `revit_v3_adapter.adapt_raw` **drops it**. No screen shows how old the Revit data is. A reviewer fixes 11 holdowns Monday, re-runs Tuesday against Friday's export, sees the same 11 mismatches, and concludes the tool is broken.
**Fix:** carry `exported_at` + `skipped_count` end-to-end; show "Revit export: N days old" above the results.

### 4. CRITICAL — PDF_ONLY / REVIT_ONLY accuse the modeler when the export view merely hid the element
The exporter collects through one view (`FilteredElementCollector(doc, view.Id)`). Hidden category → 0 elements → "the model doesn't have these" verdicts. Already burned the Dogwood demo (25 shear walls "missing" — they were just hidden in the view). Also: linked models are invisible entirely; holdowns modeled as Generic Models are never collected (only Structural Connections/Foundation categories are searched).
**Fix:** doc-wide counts alongside view-wide; when view=0 but doc>0, verdict becomes `SCOPE_SUSPECT — hidden in export view '{name}'`, not PDF_ONLY.

### 5. HIGH — The two best explanations already computed are never shown
- `revit_v3_adapter` writes a genuinely good `classification_reason` per assembly ("Family 'SHDU15S-WITH BOLT' → variant 'HD15S' → mark 'HD3' via the PDF hold-down schedule") — **no screen reads it**.
- Registration quality (RMS, source) never reaches a verdict row: a MATCH under a 12-pair verified calibration and one under an unvalidated guess look identical.
- `review.analyze()` already computes offset distance, compass direction, and "15 of 19 peers shifted the same way — systematic offset" — but it's only reachable in one drawer, for one status. *(Being surfaced tonight as the "Why?" panel.)*

---

## Part 2 — Full flaw inventory (33 items)

Severity: C=Critical, H=High, M=Medium, L=Low. "Doc-21" = status of the corresponding flaw in the earlier 21-flaw explainability doc.

### A. Coordinates / chirality
| ID | Sev | Flaw | Fix |
|----|-----|------|-----|
| R-01 | C | 2-point chirality coin flip in `device_match.fit_inverse` (reproduced) | Use stored `inverse_matrix`; refuse refit <3 pairs |
| R-02 | H | Two unit systems in one table: compare.py gates in PDF points (16/40pt), device_match in feet (2/6ft); wall gates disagree ~2× between modules | Print both units in every reason ("0.64 ft (11.5 pt)") |
| R-03 | H | Z/level exported, then ignored at match time — a level-2 holddown 0.00 ft "away" from a level-1 callout can claim it | Level/elevation gate in assign(); print level in reason |
| R-04 | M | No record of coordinate origin (project-internal vs survey/shared); breaks the moment a linked/relocated model appears | Export base-point/survey/true-north in view_info |
| R-05 | M | Wall base_z vs level elevation use different datums (acknowledged in code comment, unresolved) | Reconcile in adapter |

### B. Export fidelity
| ID | Sev | Flaw | Fix |
|----|-----|------|-----|
| R-06 | C | Silently skipped elements never reach the JSON | `skipped_count`+`skipped_ids` in payload; UI banner |
| R-07 | C | View-scoped export → "hidden" is indistinguishable from "absent" (the Dogwood walls bug, still live) | Doc-wide counts + `SCOPE_SUSPECT` verdict |
| R-08 | H | Linked models invisible to the exporter | Traverse RevitLinkInstances or warn |
| R-09 | H | Holddown family regex `(HTT|HD[UB]?)\d+` over-matches (PHD5/SHD10/THD8 → false HD5) and under-matches (MST/CS/LTT/DTT straps vanish entirely — not even REVIT_ONLY) | Anchored product-prefix regex + `unclassified_families` log |
| R-10 | H | Only 2 Revit categories searched for holdowns; Generic Model holdowns → whole report PDF_ONLY | Add categories; state searched categories in report |
| R-11 | M | Export overwrites fixed filename, no version stamp | Timestamped filename or stamp inside |
| R-12 | L | ASCII folding mangles Ø etc. to "?" with no record | Record folding; widen table |

### C. ID stability
| ID | Sev | Flaw | Fix |
|----|-----|------|-----|
| R-13 | C | Naive UniqueId decode in the endpoint reviewers use (reproduced; correct decoder exists unused in same repo) | One-line import *(fixed tonight)* |
| R-14 | H | Nothing detects a stale export; `exported_at` dropped by adapter | Carry through + display age |
| R-15 | H | Live-ID lookup silently serves a 5-minute cache; `cached` flag stripped before reaching the UI labeled "fetch live ID" | Pass `cached`/age through; label "as of N min ago" |
| R-16 | M | 0.75 ft live-match radius returns body+bolt+companion (2-3 ids) but the note names only the first | Select/report all hits *(highlight endpoint tonight selects all)* |
| R-17 | M | `rev_asm_NNN` ids are positional — any Revit edit reshuffles them; review notes then point at different devices | Stable content-hash ids (mark+rounded xy) |

### D. Verdict semantics
| ID | Sev | Flaw | Fix |
|----|-----|------|-----|
| R-18 | H | REVIT_ONLY conflates 5 causes (extra device / no schedule spec matched / lost the 1:1 race / other floor / mirrored registration) with no reason string at all | Split into REVIT_ONLY / REVIT_UNCLASSIFIED / REVIT_OUTSCOPED |
| R-19 | H | `classification_reason` + `classification_confidence` written to disk, never displayed | Copy onto row — cheapest big win |
| R-20 | M | Two different clustering tolerances (2.0 ft box in adapter vs 3.0 ft in device_match), order-dependent; merges/splits untracked | Record cluster decisions |
| R-21 | M | MARK_MISMATCH excluded from the accuracy denominator — table and headline number disagree | Add to `evaluable` |
| R-22 | M | Punch-list CSV exports stale `distance_pdf_points` next to a foot-based status | Export `distance_ft` |
| R-23 | L | NEEDS_REVIEW means 3 unrelated things | Sub-code the status |

### E. Explainability
| ID | Sev | Flaw | Fix |
|----|-----|------|-----|
| R-24 | H | Registration quality (RMS/source) never stamped per verdict | Add `registration_quality` to device rows |
| R-25 | H | No verdict names the PDF callout it paired with — reasons reference `rev_asm_011`, meaningless to a reviewer | Name sheet + callout in reason |
| R-26 | M | Offset direction/systematic analysis exists (`review.analyze`) but only in one drawer | Surface everywhere *(the "Why?" panel, tonight)* |
| R-27 | M | Hardcoded Madera baseline `{"H1":10,"H2":21,...}` fires on every project (Doc-21 #17 still open) | Make per-project or delete |
| R-28 | M | Two disagreeing SW-token regexes; device pass silently overwrites wall pass verdicts | Share one tokenizer |
| R-29 | L | Run-over-run diff is counts-only — can't see *which* device changed | Per-device diff keyed category:mark:target |

### F. Bridge reliability
| ID | Sev | Flaw | Fix |
|----|-----|------|-----|
| R-30 | H | Disconnect detection = 4 English substrings; a wording change makes "connector off" read as "model is empty" | Treat 0-elements-for-populated-category as transport failure |
| R-31 | M | Fresh exe per call, no retry; failed multi-step placement leaves partial state → duplicate benchmarks on retry | Idempotency check before re-place |
| R-32 | M | `_element_ids` regex-scrapes any ≥5-digit int from prose responses; can stamp Mark onto the wrong element | Parse structured MCP results |
| R-33 | L | `MARK_PARAM_ID=-1001203` hardcoded, unverified | Verify at runtime |

### Doc-21 verification summary
Fixed since that doc: #3 (mark map now schedule-driven), #6 (in data, not UI), partial #1/#7/#12 (review.analyze), partial #18 (runs diff). Still open: #2,4,5,8,9(worse),10,11,13,14,15,16,17,19,21. New flaws not in that doc: R-01, R-06, R-08, R-10, R-13, R-15, R-22, R-28, R-30, R-31, R-32.

---

## Part 3 — Your plan, mapped to reality

**Headline:** both planning docs (`REVIT_LIVE_WORKFLOW_ARCHITECTURE.md`, `NONICA_PRO_FEASIBILITY_EVALUATION.md`) cite Nonica tools that **don't exist** (`operate_element`, `send_code_to_revit` — those belong to a different open-source Revit MCP). The real tools were live-verified today: `set_user_selection_in_revit` works (element selected in your open Madera model during this session). Also: **there is no zoom tool** — the honest UX is "selected in Revit, press ZS to zoom", which is one keystroke for the reviewer.

| Your vision item | Verdict | How |
|---|---|---|
| Reviewer understands WHY matched/mismatched | **Mostly built, unwired** | `review.analyze()` already computes distance, direction, systematic-shift, suggestion. Tonight it becomes the "Why?" panel on every mismatch. |
| Revit as visual front end, webapp as brain | **Right architecture** | Keep it exactly so. |
| Click mismatch → "Show in Revit" highlights in live Revit | **Feasible, shipping tonight** | `POST /api/revit/highlight` → coordinate-match to live ids → `set_user_selection_in_revit`. Blue Revit selection + "press ZS" toast. |
| Paste ElementId → element + reasoning | **Feasible, shipping tonight** | `GET /api/revit/lookup/{id}` + lookup drawer. Better: a "Use current Revit selection" button — click the element in Revit, one click in the webapp, no ID copying at all. |
| New pyRevit tab for the lookup | **Don't** | Second codebase/deploy for a text box. The webapp drawer + read-selection button is equal value, 10× less work. |
| AI summary per element | **Deterministic first** | The template explanation from real facts ships tonight (grounded, free, can't hallucinate). LLM polish via existing chat_agent later if the wording feels dry. |
| Confirm mismatch / False alarm workflow | **~90% already built** | `review.resolve(accept/reject)` already persists with audit trail and survives re-matches. Needs button labels + a "confirmed" filter section. |
| Backend fetches model live via Revit API (no manual export) | **Defer — the one hard item** | Live tools can give ids/locations/types/marks, but the assembly-clustering logic that produces the 107-MATCH baseline runs on the export. Swapping the data source risks the baseline with no way to attribute regressions. Do it as its own sprint after Show-in-Revit is proven. Live fetch stays what it is today: interaction (ids, highlight, params), not math. |
| Element ID is the key | **Already solved** | `GET /api/revit/element-ids/{assembly_id}` does coordinate-matched live-ID resolution (Nonica has no UniqueId lookup — coordinate matching is the only and correct path). |
| Holdowns first | **Correct** | The live path is already holdown-only (StructConnections category). |

## Part 4 — Recommended roadmap after tonight

1. **Trust fixes (1 day):** R-01 inverse-matrix, R-14 export age banner, R-06 skipped-count, R-15 cache honesty, R-22 CSV column, R-19 classification_reason on rows.
2. **Verdict honesty (1-2 days):** R-07 SCOPE_SUSPECT, R-18 REVIT_ONLY split, R-03 level gate, R-24 registration quality per row.
3. **Reviewer workflow polish (1 day):** Confirm/False-alarm relabel + confirmed section, per-device run diff (R-29), LLM-polished summaries via chat_agent.
4. **Live-fetch sprint (2+ days, separate):** replace the manual export for holdowns via Nonica (`get_elements_by_category` → locations → types → marks), validated against the export baseline before cutover. Write-back of qa_status via `set_additional_property_for_all_elements` (the correct tool; the docs' C#-snippet approach doesn't exist).
5. **Fix the docs:** correct the tool names in both planning docs so no future agent implements against a fictional API.
