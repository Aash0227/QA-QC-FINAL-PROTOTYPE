# AGENT_HANDOFF — QBC (Livio QA/QC) — Project Blueprint

> **Read this entire document before touching any code.** It is the single
> long-term handoff for this project — not a session summary. It explains what
> QBC is, how it got here, how the pipeline actually works today, and what the
> current gate is. If something here conflicts with the code, the code wins —
> but check the code before assuming an old Claude session's summary was right.

**Repo:** `C:\QA-QC-FINAL-PROTOTYPE-bkp` · GitHub `Aash0227/QA-QC-FINAL-PROTOTYPE`
**Branch of record:** `main` (as of this document, `main` == `fix/integration-runcheck` HEAD `60a977d`, fast-forwarded and pushed)
**Last reconciled:** this document was rewritten immediately after merging ~54 commits of Stage-9 Hold-Down/Shear-Wall accuracy work and UI/architecture audit fixes into `main` (see §10).

---

## 1. Project purpose

QBC ("Quality Between CAD" / Livio QA-QC) compares a structural engineer's PDF
drawing set against the Revit BIM model built from it, and reports — per
structural element — whether what's drawn matches what's modeled.

**Why this needs to exist:** structural engineering firms produce two parallel
representations of the same building: the PDF construction documents (what
gets stamped, printed, and built from) and the Revit model (used for
coordination, quantities, and downstream trades). These two artifacts drift —
a hold-down added in Revit never makes it onto the PDF schedule, a shear wall
moves on the plan but not in the model, a mark gets relabeled in one place and
not the other. Today a human checks this by eye, sheet by sheet. QBC automates
that cross-check for structural connector/wall/etc. categories, one at a time,
starting with Hold Downs.

**The final QA/QC workflow this is meant to accomplish:** upload a project's
PDF + Revit export → run the pipeline → get a reviewable list of every
structural element in scope, each with a verdict (`LOCATION_MATCH`,
`LOCATION_MISMATCH`, `NEEDS_REVIEW`, `NOT_APPLICABLE`) and the evidence behind
it → a human QA/QC engineer reviews the flagged ones, can jump to the element
in the live Revit model ("Show in Revit"), and exports a punch list.

---

## 2. Full historical evolution

This is reconstructed from the actual repo (commit history, `docs/*.md`), not
invented. Where multiple historical docs disagree on a number, that
disagreement is preserved rather than silently resolved — see §14.

1. **Original QA/QC concept.** A Windows desktop tool (FastAPI backend +
   browser-based frontend) that a structural QA engineer runs locally against
   one project at a time. Originally hard-locked to one real client project
   ("Madera," sheet S-201) as a proof of concept — the very first detector
   (`s201_detector.py`) had the Madera hold-down schedule and page layout
   baked in (a locked "54 hold-downs" baseline; see
   `docs/COMPLETE_TECHNICAL_REFERENCE.md`).
2. **PDF extraction.** `schedule_tables.py` learns a project's own hold-down
   schedule from its schedule table (header-regex driven, no hardcoded marks
   once generalized) and `s201_detector.py` / `element_detector.py` locate
   plan-view callouts matching that vocabulary.
3. **Revit extraction.** `revit_v3_adapter.py` (current) / `revit_convert.py`
   (legacy v2 path, frozen) turn the raw Revit JSON export into a normalized,
   category-tagged assembly list.
4. **Hold Down detection** hardened from the single-client S-201 detector into
   a profile-gated generic path — see `docs/QAQC_AUDIT_REPORT.md` and the
   Phase-1 hardening work: the Madera-specific detector now only runs when a
   project's manifest explicitly opts in (`detection_profile: "madera"`);
   every other project uses the generic geometry engine.
5. **Coordinate registration** (RANSAC + benchmark control points) aligns PDF
   page space to Revit model space via a similarity transform — this had to
   be hardened repeatedly (chirality/mirroring, collinear-point refusal,
   provenance gating) because a bad registration silently corrupts every
   downstream distance gate (see §6).
6. **Problems discovered** (documented candidly in
   `docs/QBC_RND_MASTER_REPORT.md` and `docs/CODEBASE_AUDIT_REPORT.md`):
   same-mark neighbor swaps under greedy assignment, synthetic
   count-expansion points ("(2)HD2") false-matching, mirrored RANSAC
   consensus, scale-blind PDF-point gates (16pt means a different physical
   distance at ¼″ vs ⅛″ scale), registration error alone able to exceed the
   match gate, multi-level bleed (XY-only matching letting a level-1 point
   match a level-2 assembly).
7. **Physical-device matching** (Stage 9, Gates 1–3) was built specifically to
   fix the "122 PDF rows ≠ 122 physical devices" problem: a real hold-down or
   shear wall is drawn once per sheet it appears on, so raw row counts
   overcount physical elements. `device_match.py` clusters same-mark,
   near-coincident sheet callouts into one physical device before matching
   against Revit. This is the layer described in detail in §7.
8. **Benchmark/registration work.** Manual control points and a benchmark
   workflow (`benchmark_workflow.json`, `pdf_benchmarks.json`) exist as a
   fallback/verification path when RANSAC's automatic solve isn't trustworthy
   enough — a "benchmark_verified" calibration is never silently overwritten
   by a later automatic solve.
9. **Gate 4 — generic matching engine extraction.** The Hold-Down-specific
   logic in `device_match.py` was proven correct on real Madera data, then
   extracted into a category-agnostic core, `matching_engine.py`, with
   `device_match.py` reduced to two `AdapterConfig` instances (Hold Down,
   Shear Wall) plus category-specific row/target shaping. This is a pure
   extraction — regression-locked to be byte-identical to the pre-extraction
   Hold Down output (see `docs/QBC_STATE_RECONSTRUCTION.md`).
10. **Shear Wall extension** onto the same generic engine — required new PDF
    geometry work (`pdf_wall_geometry.py`, since shear walls are drawn as runs
    of short parallel hatch ticks, not lines), a new evidence channel
    (level/story context, since two identical shear walls stacked on
    different floors are otherwise indistinguishable), and a global
    (Hungarian/Jonker-Volgenant-style) one-to-one assignment to replace
    greedy nearest-first claiming.
11. **Unified product verdict.** Category-specific engine statuses (`MATCH`,
    `LOCATION_MISMATCH`, `MARK_MISMATCH`, `PDF_ONLY`, `REVIT_ONLY`,
    `NOT_IN_SCHEDULE`, `SPEC_ONLY`, `NOT_EVALUATED`, …) were collapsed at the
    product seam into four verdicts a non-engineer can act on:
    `LOCATION_MATCH / LOCATION_MISMATCH / NEEDS_REVIEW / NOT_APPLICABLE`
    (`matching_engine.product_verdict`).
12. **Revit-live integration** (Nonica PRO + revitMCP, `revit_bridge.py`) —
    interaction/inspection only, never part of the verdict math. Adds
    "Show in Revit" (select + zoom to an element in a live, open Revit
    session), live connection status, and a Revit element lookup panel.
13. **Review/evidence workflow** — a reviewer can accept/reject/annotate a
    flagged row (`review_overlay.py`, `review_comments`), which is folded back
    into the element list without touching the underlying deterministic
    verdict.
14. **Project/readiness architecture.** Every request is scoped to one active
    project via a per-tab `X-Project` header (not a single global "active
    project"); a project now reports its own readiness
    (`ready` / `runnable` / `incomplete` + `missing_inputs`) instead of the UI
    silently redirecting when inputs are missing.
15. **Frontend migration to React** — a Vite multi-page build now serves a
    vanilla-JS dashboard (`index.html`) alongside a React 18 + TypeScript
    "Pipeline Island" (`pipeline.html`) for the run timeline, with the
    vanilla dashboard's Project Manager, Elements, Results, Chat, Inspector,
    Review, and Benchmark Wizard panels also migrated into React components
    under `frontend/src/react/features/`.
16. **Current state (this document):** all of the above is now on `main`.
    The project is gated on Hold Down accuracy against real Madera data,
    pending a QA/QC sign-off before any further element is picked up (§15–17).

---

## 3. Complete Hold Down pipeline

Seven stages, orchestrated by `run_engine.py` (background daemon thread,
`run_state.json` persisted per project so a browser refresh doesn't kill an
in-flight run) against the DAG in `stage_graph.py`. Artifact names below are
the literal keys in `config.ARTIFACT_FILES` (backend/app/config.py) — nothing
here is invented.

| # | Stage key | Input | Output artifact | Purpose | Key module | What can fail it | Consumed by |
|---|---|---|---|---|---|---|---|
| 1 | `extract` | uploaded PDF | `element_intelligence` (`element_intelligence.json`) | Scan every sheet for schedule tables → learn mark vocabulary → find plan-view callouts | `element_detector.py`, `schedule_tables.py` | Schedule table not recognized by header regex → `schedule_not_parsed`; no plan sheet found | `pdf_intelligence`, `compare` |
| 2 | `revit_convert` | uploaded Revit JSON | `ai_revit` (`AIConvert_revit.json`), `raw_revit` (`raw_revit_export.json`) | Parse Revit export into a normalized, category-tagged assembly list | `revit_v3_adapter.py` (current v3 path), `revit_convert.py` (frozen legacy v2 path) | Malformed export JSON; assembly has no PDF-mappable family token | `compare`, `device_match` |
| 3 | `pdf_intelligence` | `element_intelligence` | `pdf_page_intelligence` | Identify the primary structural plan sheet, page metadata (scale, sheet number where derivable) | `s201_detector.py` (generic geometry engine; Madera-specific constants only active under the opt-in profile) | Wrong sheet picked as "densest"; schedule mis-parsed | `pdf_convert`, `ransac` |
| 4 | `pdf_convert` | `pdf_page_intelligence` | `ai_pdf` (`AIConvert_pdf.json`) | Normalize PDF-side detections into the shared point/segment shape, snap leaders to their target dot | `leader_anchor.py` | Leader-following fails → falls back to label-center anchor (worse anchor precision) | `ransac`, `compare` |
| 5 | `ransac` | `ai_pdf`, `ai_revit` | `registration` (`registration_calibration.json`), `registration_report` | Solve the PDF↔model similarity transform (mark-constrained RANSAC, seed=42, both chiralities tried) | `registration.py` | Too few constrained pairs; collinear points refused; solve fails → nothing saved (never silently degraded) | `compare`, `device_match`, `wall_match` |
| 6 | `compare` | `registration`, `ai_pdf`, `ai_revit` | `compare` (`ai_compare_report.json`) | Per-sheet, per-mark greedy comparison (registration-gated) | `compare.py` | No verified registration → NEEDS_REVIEW, never a fabricated MATCH | `device_match`, `element_registry` |
| 7 | `match` | everything above | `element_list`, `device_registry` | Physical-device re-accounting (`device_match`/`matching_engine`), shear-wall segment matching (`wall_match`), join into one reviewable list, fold in any human review resolutions | `device_match.py`, `wall_match.py`, `element_registry.py` | Physical-device assignment gate (§7) | Frontend element list, chat agent, punch-list export |

**Downstream of the pipeline:** the reviewer works the element list in the
frontend (PDF viewer + 3D viewer + element list), can jump to "Show in Revit"
for a live element, annotates/resolves flagged rows, and exports
`GET /api/export/punch-list.csv`. Human QA/QC validation (Sagar's sign-off,
§16) happens on this output, not on raw engine artifacts.

**A specific, documented failure mode to know about:** `pdf_intelligence` and
`ransac` can each write an artifact that says "this didn't really work" (an
error payload, or `ok:false`) while still returning HTTP 200 — `run_engine`
treats a 200 as "stage done." This means a run can complete "successfully"
with an empty or unregistered comparison underneath it. This was fixed at the
run-status level (a `blocked` terminal state now exists distinct from
`completed`/`failed` — §9) but is worth re-checking whenever a stage's own
artifact-assertion logic changes.

---

## 4. How Hold Downs are detected (PDF side)

**Generic path (default for every project except an opted-in profile):**

1. `schedule_tables.discover_tables()` finds schedule tables on any sheet by
   **header text regex** (not by knowing this specific project's table
   layout), infers which column is the MARK column, and builds
   `learned_vocabulary = {category: {mark: spec}}` — no hardcoded marks.
2. `s201_detector.detect_holdowns_on_page()` (despite the module name, this is
   the generic geometry engine, not Madera-only logic) walks the plan sheet
   for tokens matching the learned vocabulary: leader-following from a mark
   label to its target dot, filled-marker snapping, and table/title-block/
   detail-reference exclusion so a schedule-table cell or a detail callout
   isn't mistaken for a plan instance.
3. **Multiplicity** — a label like `(2)H2` is expanded into two instance
   points via `_expand_instance_points` / `_normalize_instance_count`, using
   the source bounding box to place the synthetic second point. (This is a
   documented source of possible false-MATCH — a synthetic point can land
   close enough to a real assembly to match it; see §14 for how this is
   tracked, not hidden.)
4. **Coordinates** are produced per detection as `center_pdf` (PDF-page point
   space, **not yet in feet** — see §6 for why the units matter).
5. **Evidence crops** — `_render_detection_crop()` saves a small PNG crop
   around each detection for review-time visual confirmation.
6. **Schedule/type association** — each detected mark is matched back to its
   schedule row (`_extract_holdown_schedule` / `_extract_holdown_schedule_from_words`)
   to attach the hold-down's type/spec, or explicitly flagged
   `not_in_schedule` if the schedule has no matching row — never invented.

**Frozen Madera S-201 detection vs generic detection — these are different
concepts, do not merge them:**
- The **frozen Madera path** (`detection_profile == "madera"` in the project
  manifest) uses hardcoded plan bounding boxes, table bounding boxes, and a
  hold-down regex tuned specifically to sheet S-201 of one real client
  project. It exists to reproduce a locked, manually-verified 54-hold-down
  baseline for regression testing — it is a fixture, not a product path.
- The **generic path** is what every other project (Country Side, Dogwood
  Lane, and any future upload) actually runs through. It has no client-
  specific literals in the live code path (the audit history in
  `docs/CODEBASE_AUDIT_REPORT.md` documents several places where a Madera
  literal was found leaking into the "generic" path and had to be removed —
  check that document if you suspect a hardcode has crept back in before
  assuming the generic path is clean).

---

## 5. The Revit side

- **Raw Revit JSON** (`raw_revit_export.json`) — whatever the pyRevit "Export
  QAQC" button or the manual upload produced: a flat dump of Revit elements
  and their parameters.
- **Family records** — each element carries its Revit family/type name,
  parameters, and geometry (insertion point, bounding box, host reference).
- **Body vs. evidence-member classification** — a hold-down "assembly" in
  Revit is usually more than one family instance (the hardware body, bolts,
  washers); the adapter clusters these into one canonical assembly rather
  than counting each member separately.
- **Canonical assemblies** — `revit_v3_adapter.build_ai_revit()` (current v3
  export path) produces the normalized `ai_revit` list QBC actually compares
  against. `revit_convert.convert_revit()` is the legacy v2 path — frozen,
  reachable only when `revit_v3_adapter.is_v3()` is false; all current real
  projects (Madera, Country Side, Dogwood Lane) export v3, so the v2 path is
  effectively dead code kept for backward compatibility, not something to
  extend.
- **Family normalization / core tokens** — `normalization.py` strips a family
  name down to a "core token" comparable against a PDF mark (e.g. an
  `SHDU11`-style family name → a core token that can be matched against a
  schedule-derived mark). This is where category-specific naming quirks get
  absorbed so the matching engine itself never has to know about family
  naming conventions.
- **PDF mark mapping** — each canonical assembly is tagged with the mark it
  should correspond to on the PDF, derived from its family/type, not from a
  hardcoded lookup table for one project.
- **Assembly center point / elevation (Z)** — the point actually compared
  against the PDF-derived point is the assembly's model-space center; `Z`
  (elevation) is used as a level-compatibility signal when comparing
  same-mark candidates (Hold Down assemblies carry a raw Z but no separate
  "level" field in the export — see the `context_key` note in §7).
- **Evidence members** — the bolts/washers/other sub-elements are retained as
  supporting evidence for a match, not compared independently.
- **Revit ElementId / UniqueId issues** — `revit_ids.py` exists specifically
  because ElementId is per-session and not stable across a re-export, while
  UniqueId is stable; anything that needs to re-identify "the same Revit
  element" across pipeline runs or live-Revit lookups needs to reason in
  UniqueId, not raw ElementId, or it will silently point at the wrong (or a
  now-nonexistent) element after a model edit.
- **Live Revit connectors** — see §12; these read the *live, open* Revit
  session for interaction (selection, zoom, lookup), not for the comparison
  math itself, which always runs against the exported JSON snapshot.

---

## 6. Coordinate registration

```
Revit internal feet
        │  (forward transform, solved by RANSAC or a manual/benchmark fit)
        ▼
PDF page points
```

- **Transform direction.** The registration solve fits a similarity transform
  (`registration.py`) from constrained mark-pair correspondences: same-mark
  Revit points ↔ same-mark PDF points. The transform's `inverse_matrix` is
  what `matching_engine.inverse_from_calibration()` uses to project PDF
  callouts *into* model space for the physical-device layer (§7) — that's the
  authoritative inverse, preferred over re-fitting one from scratch.
- **Chirality / Y-flip.** PDF page-space Y increases downward; Revit model
  space Y is a normal Cartesian axis. A naive fit can converge on a mirrored
  (chirality-flipped) solution that still minimizes residual error but is
  physically wrong. The fix tried **both** reflections and kept whichever
  gives the lower RMS (`registration.py` — both-chirality fit), and the
  benchmark verification path treats a chirality mismatch as a hard blocker,
  never a silent auto-flip.
- **Point pairs** used for the fit come from same-mark correspondences found
  during comparison, or from manual/benchmark control points
  (`revit_control_points.json`, `pdf_control_points.json`,
  `manual_registration_points.json`) when the automatic solve isn't trusted
  enough.
- **Calibration provenance** — a calibration records where it came from
  (`source: "holdown_ransac"` vs. a manual/benchmark source) so a
  `benchmark_verified` calibration is never silently overwritten by a later,
  possibly worse, automatic RANSAC solve.
- **Registration quality / validation pairs** — collinear point sets are
  refused (a similarity transform is underdetermined/unstable from collinear
  points), and a **holdout validation** check exists: some point pairs are
  held out of the fit and used only to check the resulting transform's
  residual, rather than every available pair being spent on the fit itself.
- **MATCH gating** — `compare.py` requires a *verified* registration before
  it will emit a `MATCH`; a diagnostic-only or unverified calibration can
  only ever produce `NEEDS_REVIEW`, never a MATCH — this is a deliberate
  honesty guarantee, not an oversight.
- **Diagnostic vs. verified calibration.** "Diagnostic" means the transform
  exists and can be inspected, but nothing has confirmed it's trustworthy
  enough to gate a MATCH; "verified" means it passed the benchmark/holdout
  checks.

**Why this matters directly for Hold Down accuracy:** every downstream
distance gate (16/40pt on the PDF side, 2ft/6ft on the model side) is
comparing a *transformed* point against a Revit point. If the registration is
even slightly wrong — wrong chirality, wrong scale, residual error eating
into the gate's own tolerance — every device_match verdict downstream is
built on a shifted coordinate system. This is why registration hardening
(chirality cross-check, provenance gating, holdout validation) was treated as
a Hold Down accuracy problem, not a separate concern.

---

## 7. Physical-device matching architecture

**Why 122 PDF rows ≠ 122 physical Hold Downs:** a hold-down is drawn once per
sheet it appears on (e.g. a foundation plan sheet and a framing plan sheet
both show the same physical device). Counting PDF callout rows overcounts
real, physical elements — the device layer exists to collapse repeated sheet
appearances of the *same physical device* into one entity before it's ever
compared against Revit.

This is implemented in two files with a clean separation of responsibility:

- **`matching_engine.py`** — category-agnostic core (Stage 9 Gate 4
  extraction). Knows nothing about "hold-down" or "shear wall"; everything
  category-specific is supplied via an `AdapterConfig`.
- **`device_match.py`** — the Hold Down and Shear Wall `AdapterConfig`
  instances, plus folding device-level verdicts back onto sheet rows.

**P1 — Physical-device registry** (`matching_engine.build_devices`):
inverse-project every sheet callout into model space using the registration's
inverse transform, then cluster same-mark, near-coincident points across
sheets into one physical device (anchor-based clustering, not a running
centroid, and same-sheet duplicates are never merged into one device — two
same-mark hold-downs drawn on the same sheet are always two devices).

**P2 — Global one-to-one assignment** (`matching_engine.assign` /
`optimal_assignment`): each physical device is matched against Revit
assemblies using an **evidence-gated** decision, not distance alone:
1. **Mark equal** — required; a same-mark pass never lets a device claim a
   target of a different mark.
2. **Adaptive distance gate** (`adaptive_match_ft`) — the flat base tolerance
   (2ft MATCH / 6ft mismatch band for Hold Downs; 4ft/12ft for Shear Walls)
   is *widened*, never narrowed, by that device's own registration residual,
   capped at a ceiling multiplier (3× base) — a device with a worse local
   registration fit isn't punished for it, but the gate can't be blown open
   indefinitely either.
3. **Uniqueness margin** (`_flag_ambiguous`) — if a runner-up candidate is
   within `ambiguity_margin_ft` (1ft) of the best candidate, the assignment
   refuses to auto-pick and the device is flagged rather than coin-flipped.
4. **Level compatibility** — when both sides carry real elevation data
   (currently reliable only on the Revit side for Hold Downs — see below),
   a level mismatch can rule out an otherwise-close candidate.

Assignment itself uses a **globally optimal** one-to-one solve
(Jonker-Volgenant/Hungarian-style `optimal_assignment`, with decisive pairs
pinned before optimization) rather than greedy nearest-first — greedy lets
whichever pair happens to be closest claim first, which can hand a device's
correct Revit element to a neighboring device and leave the true device with
nothing. This is `global_assignment=True` on the Shear Wall adapter; the Hold
Down adapter is regression-locked to its original (validated) behavior and
does not use the flag, so no change here silently altered the numbers Sagar
already reviewed.

**P3 — Verdict/status propagation:** the device-level verdict is folded back
onto every sheet row that contributed to that device, while the original
per-sheet verdict is retained as `sheet_status` for audit — nothing is
overwritten, only supplemented.

**Verdicts at this layer** (category engine statuses, before product
collapse — see §11):
- `MATCH` — mark equal, within the adaptive gate, unambiguous, level-compatible.
- `LOCATION_MISMATCH` — mark equal, but distance exceeds the match gate (up to
  the mismatch ceiling).
- `PDF_ONLY` — a physical device with no Revit counterpart found.
- `REVIT_ONLY` — a Revit assembly with no PDF device found.
- `MARK_MISMATCH` — geometrically close, but marks disagree.
- `NEEDS_REVIEW` — ambiguous (tied candidates), or evidence insufficient to
  decide either way. This state is *preserved*, never collapsed into a
  MATCH or MISMATCH just because a number would look better — this is a
  hard rule carried over from the Stage 9 program (see §17).

**Why one shear-wall-specific evidence channel exists that Hold Down doesn't
use:** Revit walls carry a `level` (story) name, and one plan sheet draws one
story — so two identical shear walls stacked at the same plan XY on
different floors are distinguishable by level. This was the dominant real
ambiguity cause found on Shear Wall data (`context_key="level"` on
`SHEAR_WALL_ADAPTER`). Hold-down assemblies carry only a raw Z, not a
separate level field, so `HOLDOWN_ADAPTER` leaves `context_key` unset —
this is a genuine data-availability difference between the two categories,
not an oversight to "fix" by adding a level field that doesn't exist in the
export.

**Why this layer exists above the older per-sheet comparison
(`compare.py`):** `compare.py` does a per-sheet, per-mark greedy comparison
with no ambiguity gate and no cross-sheet device concept — it was the
original comparison logic and is still what produces the first-pass
`compare` artifact. The device layer sits on top of it specifically to fix
the sheet-repetition overcounting problem and add the evidence-gated
assignment `compare.py` never had. Both layers currently coexist; do not
assume `compare.py`'s own greedy assignment has the same ambiguity
protections as `device_match`/`matching_engine` — it does not (documented as
FM1 in `docs/QBC_RND_MASTER_REPORT.md`).

---

## 8. Complete artifact flow

Real artifact keys, from `backend/app/config.py:ARTIFACT_FILES` — nothing
below is invented or renamed for readability:

```
project_manifest            → per-project metadata: slug, display name, detection_profile,
                               readiness inputs, last-ingested-export info
raw_revit                    → raw_revit_export.json (unmodified Revit export dump)
ai_revit                     → AIConvert_revit.json (normalized, category-tagged assemblies)
element_intelligence          → element_intelligence.json (PDF-side scan: schedule tables + detections)
pdf_page_intelligence          → primary-sheet identification + page metadata
ai_pdf                        → AIConvert_pdf.json (normalized PDF detections, leader-anchored)
registration                  → registration_calibration.json (the similarity transform + provenance)
registration_report           → coordinate_registration_report.json (diagnostics on the fit)
revit_control_points /
pdf_control_points /
manual_registration_points     → manual/benchmark registration inputs
compare                       → ai_compare_report.json (per-sheet, per-mark verdicts — first pass)
device_registry               → physical-device registry + re-accounted verdicts (Hold Down / Shear Wall)
element_list                  → the final, joined, reviewable per-element list the frontend renders
revit_scope_diagnostics       → Revit-side scope/coverage diagnostics vs. the PDF-derived baseline
review_page / review_overlay_png / review_overlay_svg / review_items
                               → PDF review-mode overlay artifacts
review_comments                → reviewer annotations, folded back without touching engine verdicts
scene3d                       → cached data for the Three.js 3D viewer
teach_memory                  → `ai_teach_memory.json`, accumulated per-project detection overrides
pdf_benchmarks / benchmark_workflow → manual benchmark control-point workflow state
phase_summaries               → per-stage human-readable narration (chat agent + UI use this)
openrouter_log                → raw LLM call log (advisory usage only — see §11)
```

Relationships: `extract` writes `element_intelligence`; `revit_convert` writes
`ai_revit`/`raw_revit`; `pdf_intelligence` reads `element_intelligence` and
writes `pdf_page_intelligence`; `pdf_convert` reads that and writes `ai_pdf`;
`ransac` reads `ai_pdf`+`ai_revit` and writes `registration`+
`registration_report`; `compare` reads all of the above and writes `compare`;
`match` reads `compare`+`ai_revit`+`ai_pdf`+`registration` and writes
`element_list`+`device_registry`.

---

## 9. The frontend

Two surfaces, one Vite multi-page build (`frontend/vite.config.js`):

- **`/` — vanilla dashboard** (`frontend/index.html` + `frontend/src/`): PDF
  viewer with callout overlays (`panels/pdf.js`), Three.js 3D model viewer
  (`panels/viewer3d.js`), element list sidebar (`panels/list.js`,
  `panels/table.js`), chat copilot (`panels/chat.js`), inspector/runs-
  comparison, benchmark wizard (`panels/wizard.js`), and the project
  manager overlay.
- **`/pipeline.html` — React "Pipeline Island"** (`frontend/src/react/`):
  React 18 + TypeScript + Tailwind v4, SSE-driven run timeline
  (`components/PipelineIsland/`), with the dashboard's other panels
  progressively re-implemented as React features under
  `src/react/features/` — `project-manager/ProjectManager.tsx` (project
  CRUD, readiness-aware upload/attach), `element-review/ElementList.tsx` +
  `ResultsTable.tsx`, `inspector/Inspector.tsx` + `ReviewWorkspace.tsx` +
  `RunsComparison.tsx`, `chat/Chat.tsx`, `benchmark-wizard/Wizard.tsx`,
  `verdict/VerdictBadge.tsx` + `VerdictBarPanel.tsx` (the product-verdict
  layer surfaced in the UI, §11).
- **Project selection / pinning** — every tab is pinned to one project via an
  `X-Project` header (`frontend/src/shared/api.ts:setProjectHeader`,
  persisted to `localStorage` under `qbc.project`), not a single
  server-global "active project" — this was a fix for one tab's action
  leaking into another tab's project.
- **Upload / readiness** — `ProjectManager.tsx` shows a project's readiness
  (`ready` / `runnable` / `incomplete` + which of `pdf`/`revit` is missing,
  from `GET /api/projects` — see `routers/projects.py:_summary()`), with
  attach controls for either input directly on the project card, rather than
  the UI silently redirecting when a project has no results yet.
- **Pipeline** — `PipelineIsland`/`usePipeline.ts` drives the 7-stage
  timeline from `run_state.json` + SSE events, with a poll fallback when SSE
  disconnects, and reports `running` / `completed` / `blocked` / `failed` as
  genuinely distinct terminal states (§ below).
- **Report** — the "Report" button fetches (not navigates to)
  `GET /api/export/punch-list.csv`, project-scoped, and triggers a browser
  download; a 409/404 (no results yet) is surfaced as a toast, not a raw
  JSON blob rendered as a page.
- **Show in Revit** — see §13.
- **Revit lookup** — a panel to query the live Revit session for an
  element's current state (see §12).
- **Run comparison** (`RunsComparison.tsx`) — diffs a saved baseline run
  against the current run, per-category and per-device, honestly reporting
  "no baseline saved yet" rather than a fabricated comparison.

---

## 10. Backend architecture

FastAPI app (`backend/app/main.py`), single worker (`127.0.0.1:8077` —
multiple workers would each keep their own in-memory run-lock state, breaking
the single-run guarantee), CORS configured for the Vite dev server and the
built static bundle. Routers (`backend/app/routers/`):

| Router | Owns |
|---|---|
| `pipeline.py` | `POST/GET /api/pipeline/run`, `GET /api/pipeline/status`, `GET /api/pipeline/events` (SSE), `POST /api/pipeline/ai-status` |
| `elements.py` | `GET /api/elements`, element intelligence, review queue, resolve/disposition |
| `projects.py` | `GET/POST /api/projects`, `GET /api/projects/{slug}`, `PATCH`, `DELETE`, activate, readiness computation |
| `revit.py` | Revit live-connection status, export upload |
| `registration.py` | Manual/benchmark registration endpoints |
| `common.py` | Shared artifact save/load (atomic writes, mtime-aware cache) |
| (chat, review, teach, benchmark, workflow/upload routers) | AI chat, review resolution, per-project teach overrides, benchmark workflow, upload endpoints |

**Artifact storage:** `artifacts/projects/<slug>/*.json` — the artifact-as-
database pattern; there is no SQL/NoSQL database anywhere in this system.
Atomic writes (write to a temp file, `os.replace`) prevent a reader from ever
observing a half-written artifact.

**Project/request context:** `config.py` holds a `ContextVar`-based
project-slug binding (not a single global mutable "active project"),
resolved per-request in `routers/common.py` from, in order: `X-Project`
header → `?project=` query param → the legacy global `active_project.json`
fallback. This was specifically hardened after a cross-project SSE leak was
found (an event from one project's run appearing on another project's open
tab) — `progress.py` now stamps every emitted event with the project it
belongs to at emit time, and `GET /api/pipeline/events` filters to the
requesting project.

**Run engine** (`run_engine.py` + `stage_graph.py`): background daemon
thread per run; `run_state.json` persists stage-by-stage progress so a
browser refresh or disconnect doesn't lose the run; duplicate concurrent
run requests get a 409 with the existing `run_id`; a stale "running" state
with no live thread is detected and allowed to restart. Terminal states are
`completed` / `blocked` / `failed` — `blocked` is a deliberate, distinct
state (nothing broke, but required inputs were missing, so no result was
produced) added specifically because it used to be reported as `completed`,
which made a project that could never produce an answer look finished.

**Revit bridge** (`revit_bridge.py`): talks to a live, open Revit session via
Nonica PRO's revitMCP connector — see §12.

**Registration / matching:** `registration.py`, `matching_engine.py`,
`device_match.py`, `wall_match.py`, `compare.py` — see §6–7.

**Review:** `review_overlay.py` generates the PDF overlay/crop artifacts a
reviewer sees; review resolutions are stored separately from engine output
and folded in at read time, never overwriting the deterministic verdict.

---

## 11. AI usage — deterministic vs. advisory, explicitly separated

**Deterministic (authoritative, no LLM involved):**
- Every stage of the 7-stage pipeline.
- All matching/registration math (`registration.py`, `matching_engine.py`,
  `device_match.py`, `wall_match.py`, `compare.py`).
- Every verdict (`MATCH`/`LOCATION_MISMATCH`/etc. and the product-verdict
  collapse in `matching_engine.product_verdict`).

**AI/LLM (advisory only, never authoritative):**
- `chat_agent.py` — the "QBC QA/QC Agent" chat copilot: answers questions
  about *already-recorded* evidence (it reads artifacts, it does not
  recompute or override a verdict).
- `POST /api/pipeline/ai-status` — a non-blocking, per-stage narration
  ("what happened / what data / what's next") requested after a stage
  completes; on timeout or failure it falls back to a deterministic
  templated sentence, and the pipeline's actual progress is never gated on
  the AI call succeeding.
- Model: OpenRouter, default configured in `config.py` (`QAQC_AI_STATUS_MODEL`
  env override available); calls are logged to the `openrouter_log`
  artifact for audit.

**The rule this separation exists to enforce:** the LLM must never be
described, or allowed to act, as making the final geometric matching
decision. If a future change makes the chat agent or AI-status endpoint
influence a stored verdict, that is a regression against this architecture,
not a feature.

---

## 12. Revit-live architecture

- **Nonica connector / revitMCP** (`revit_bridge.py`) — talks to a live, open
  Revit session through Nonica PRO's revitMCP plugin. Requires the Nonica
  window to actually be **open** (not merely installed) or the bridge
  reports `connected:false`; a modal dialog open in Revit blocks MCP tool
  calls entirely, and the bridge is expected to report that honestly (an
  explicit blocked/error state) rather than silently returning "nothing
  selected."
- **Live model** — whatever model is currently open in the user's Revit
  session. This can be a *different* state than the exported snapshot the
  pipeline compared against (the model may have been edited since export).
- **Exported snapshot vs. live connectors** — **the exported Revit JSON
  snapshot is the source of truth for all comparison math.** Live Revit
  connectors (Nonica/revitMCP) are an interaction/inspection path only:
  selecting an element, reading its live location for "Show in Revit," or
  looking up its current parameters. Nothing in the live-Revit path
  recomputes or overrides a verdict — this is the same separation of
  concerns as §11 (deterministic vs. advisory), applied to data source
  instead of decision logic.
- **Selection / lookup / live 3D** — the Revit lookup panel and "Show in
  Revit" both go through `revit_bridge.py`'s selection/element-location
  functions (`select_elements`, `get_selection`, `live_connection_locations`).

---

## 13. Show in Revit

- **How an element is identified:** the element list carries the Revit
  UniqueId (not raw ElementId — see §5) for any row with a Revit
  counterpart; this is what's sent to the bridge.
- **How the backend selects it:** `revit_bridge.select_elements()` /
  `get_selection()` drive the live Revit session through the revitMCP
  connector to select the given element(s).
- **How the frontend triggers it:** the vanilla `panels/revit_live.js` and
  the React `Inspector.tsx` both expose a "Show in Revit" action wired to
  this backend path.
- **Current limitations (state this honestly — do not claim more than the
  repo demonstrates):**
  - **Zoom limitation:** selection is confirmed to work through the
    connector; a dedicated "zoom/frame to element" behavior beyond
    selection is not independently verified in this repo's test suite as
    of this document — treat "select" as validated and "zoom" as an
    operator-observed convenience, not a tested guarantee.
  - Requires Revit + Nonica actually open, on the same machine reachable by
    the backend, with no blocking modal dialog.
  - There is no automated (Playwright/pytest) test exercising a live Revit
    session in this repo — it cannot be, since it depends on a real,
    running Revit instance. Anything claimed "working" here is based on
    manual operator verification, not CI evidence. Do not upgrade this to
    "validated" without a documented manual test log.
- **Operator workflow:** open Revit + Nonica → open the QBC dashboard →
  select a flagged element → "Show in Revit" → confirm the correct element
  is selected in the live Revit session.

---

## 14. Current validation baseline

**Do not silently reconcile the numbers below into one "clean" figure — they
belong to different points in the codebase's history and are preserved as
such.** Sources: `docs/QBC_STATE_RECONSTRUCTION.md`,
`docs/QBC_RND_MASTER_REPORT.md`, `docs/COMPLETE_TECHNICAL_REFERENCE.md`.

**Hold Down, real Madera data, post Gate-4 extraction (commit `a92156a`,
carried unchanged through every subsequent commit on `main` as of this
document):**
> 122 callout rows → 84 physical devices → **45 MATCH · 8 LOCATION_MISMATCH ·
> 21 NEEDS_REVIEW · 10 PDF_ONLY**

This is stated in `docs/QBC_STATE_RECONSTRUCTION.md` to be byte-identical to
the pre-extraction (Gate 3) validated numbers — the extraction into
`matching_engine.py` was verified to change no output.

**Shear Wall, real Madera data — two historical numbers, not the same run:**
- OLD (commit `7458edd`, leader-tip fix only): 53 devices → 5 MATCH · 3
  LOCATION_MISMATCH · 14 NEEDS_REVIEW · 31 PDF_ONLY.
- NEW (after the level/context evidence channel, commits `0faf543` /
  `4ed9065` / `fa1da74`): **12 MATCH · 8 NEEDS_REVIEW · 2 LOCATION_MISMATCH ·
  31 PDF_ONLY · 12 REVIT_ONLY.**

  The NEW numbers were reached by adding a real evidence channel
  (level/story context resolving stacked-same-mark-wall ambiguity) and a
  global assignment solve — **not** by widening any distance threshold. This
  is explicitly documented and should be treated as the load-bearing example
  of "how this project is allowed to improve a number."

**Orientation rejection (measured on real data, then reverted — commit
`4ed9065`):** promoting drawn-orientation to a *primary* claim-ordering key
was tried, measured, and found to cost accuracy (Shear Wall MATCH 12→11,
LOCATION_MISMATCH 2→6 on the same real data) — it was reverted. Orientation
now exists **only** as a conservative, post-hoc, near-tie resolver
(`resolve_ambiguity_by_orientation`), never as a primary decision input. Do
not reintroduce orientation as a primary signal without repeating this same
measure-first discipline.

**Known validation gap, stated plainly (from `docs/QBC_STATE_RECONSTRUCTION.md`):**
these headline numbers are locked by **manual commit-message diffs over a
real Madera snapshot plus synthetic-fixture behavior pins in
`backend/tests/test_device_match.py`** — there is **no automated regression
test that re-runs the real Madera snapshot end-to-end and asserts the
45/8/21/10 or 12/8/2/31/12 totals.** If the snapshot data or the engine
changes, nothing in CI will catch a silent drift in these numbers. This gap
is named here so a future agent does not assume "tests pass" implies "the
real-data numbers are unchanged."

**Older, now-superseded reference points** (kept for provenance only — do
not treat as current): a locked "54 hold-downs" fixture baseline tied to the
frozen Madera S-201 detector fixture (§4), and a UI-only "106 verified"
header-text assertion from an earlier dataset/build that predates the
current device-level accounting — neither of these is the number to compare
new work against; use the 45/8/21/10 figure above.

---

## 15. Current project gate

**The project is currently focused ONLY on Hold Down accuracy.** No other
element category is to be advanced past its current (already-implemented but
unvalidated-by-QA) state until Hold Down clears the gate below.

```
Madera (real project data)
  → Run Hold Down pipeline
  → Inspect results (45 MATCH / 8 LOCATION_MISMATCH / 21 NEEDS_REVIEW / 10 PDF_ONLY — §14)
  → Demo to Sagar (QA/QC engineer, §16)
  → Sagar validates accuracy
  → GREEN SIGNAL?
       YES → follow Sagar's QA/QC roadmap → move to the next element
       NO  → stay on Hold Downs → diagnose the specific issue → fix →
             re-run → revalidate (repeat until GREEN SIGNAL)
```

Shear Wall code exists and is on `main` (§2.10, §14), but **its existence is
not permission to consider it "next."** Nothing beyond Hold Down moves
forward until Sagar's sign-off, regardless of what other categories already
have working code.

---

## 16. Roles — do not confuse these two people

- **Sagar (QA/QC engineer)** — referred to in this handoff request as "Sagar
  Garpe"; the repo's own setup documentation (`docs/SAGAR_SETUP_GUIDE.md`)
  spells the same role/person "Sagar Karpe." This is the person who actually
  **validates whether Hold Down results are accurate** against real
  engineering judgment. **His sign-off ("GREEN SIGNAL") is the acceptance
  gate for moving to any next element** — not a passing test suite, not an
  agent's own assessment of the numbers.
- **Sagar Shawan** — the manager. Needs project status and a tentative ETA.
  Does not validate matching accuracy — status reporting only.

Do not treat a code-complete category, a passing pytest run, or an agent's
own read of the numbers in §14 as equivalent to Sagar (Karpe/Garpe)'s
sign-off. They are not interchangeable.

---

## 17. Current roadmap

```
CURRENT: Hold Down implementation + Madera validation (§14, §15)
   ↓
Sagar (QA/QC engineer) GREEN SIGNAL on Hold Down accuracy
   ↓
Next element, per the QA/QC engineer's own roadmap — NOT invented by an agent
   ↓
Implement (reusing the generic matching_engine.py + an AdapterConfig, per §7)
   ↓
Validate against real data (measure, don't just widen thresholds — §14's
Shear Wall example is the model to follow)
   ↓
GREEN SIGNAL
   ↓
Next element
```

**The next element after Hold Down has not been specified by the QA/QC
engineer as of this document.** Shear Wall code already existing on `main` is
not evidence that Shear Wall is "the next element" — do not assume it. Ask,
or wait for Sagar's roadmap, rather than inferring from what code happens to
already exist.

---

## 18. Agent rules

1. Read this document (`AGENT_HANDOFF.md`) before modifying the project.
2. Inspect actual code before changing anything — do not trust a prior
   session's summary (including this one) as ground truth without checking.
3. Preserve validated Hold Down logic (§7, §14) — it is regression-locked for
   a reason.
4. Do not change match/mismatch thresholds (2ft/6ft Hold Down, 4ft/12ft Shear
   Wall, or any other gate) without an explicit QA/QC reason, and measure the
   real-data effect before and after (§14's orientation-rejection example is
   the discipline to copy).
5. Never fabricate a MATCH result. If evidence is insufficient, the correct
   output is `NEEDS_REVIEW`, not a best-effort guess.
6. Never hide uncertainty — a stage that half-succeeded should say so
   (§3's note on `pdf_intelligence`/`ransac` silently-OK failures is exactly
   the anti-pattern to avoid reintroducing).
7. Do not progress to the next element category before QA/QC (Sagar) approval
   (§15–17), even if code for it already exists.
8. Keep deterministic matching logic and AI/LLM explanation strictly separate
   (§11) — the LLM narrates, it never decides a verdict.
9. Update this handoff when a major architectural milestone completes —
   don't let it drift back into being a single-session summary.
10. Keep Git history clean and meaningful; this repo now has exactly one
    long-lived integration branch pattern (`main` is the fast-forwarded
    source of truth — see the note below); avoid creating parallel
    long-running branches that re-diverge from it without a clear reason.
11. Do not claim a deployment or a live-Revit feature (§13) is "validated"
    unless the repo actually contains a test or a documented manual
    verification log proving it — an agent's own confidence is not evidence.

---

### Note on repository state (for the next agent to verify, not just trust)

As of this document: `main`, `fix/integration-runcheck`,
`hotfix/header-logo-homepage`, and `ui/pipeline-island` were reconciled —
`fix/integration-runcheck` contained ~40 commits that existed only locally
and had never reached `origin`; it was pushed, then fast-forward-merged into
`main` (a clean ancestor relationship — no conflicts, no rebasing, nothing
discarded), and pushed. `hotfix/header-logo-homepage` and `ui/pipeline-island`
were confirmed to be strict ancestors of that branch (fully contained, no
unique commits) before being left alone. The open PR
(`fix/integration-runcheck → main`) auto-merged once `main` contained its
commits. Re-verify this with `git log --oneline --decorate --graph --all`
before assuming it still holds — branches move.
