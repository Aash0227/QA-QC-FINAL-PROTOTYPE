# 2-Benchmark Registration — Implementation Plan (adapted to this repo)

*Source: manager's `BENCHMARK-UPDATE-PLAN.md` + `QAQC-ENGINE-V2-PLAN.md`,
adapted 2026-07-15 to the current state of `QA-QC-FINAL-PROTOTYPE-bkp`.
Decisions: implement additively in THIS repo; Bluebeam Revu for stamping.*

## Summary (one paragraph)

Today the coordinate alignment between drawing and model comes from RANSAC
over detected hold-downs (or manually entered pairs). It works, but its
error budget (≈8 pt rms on Dogwood) eats most of the MATCH gate and varies
run to run. This update adds a **2-benchmark workflow**: the team stamps two
`BM-1`/`BM-2` crosshairs on the plan PDF in Bluebeam and places two matching
benchmark family instances in Revit at the same grid intersections. Two
exact correspondences determine translation + rotation + scale, checked
against the title-block scale — registration becomes deterministic,
operator-independent, and ~5–8× more precise. Everything is strictly
additive: the frozen compare/registration math is untouched; existing flows
keep working; the new path is a new artifact + two new endpoints.

## What's different from the manager's document

His plan was written against an older clone (`D:\LIVIO\QAQC`, commit
c33c3e8) with a broken `normalization.py` and 26 tests. This repo already
has: working normalization (Phase 0 void), 86 green tests, the review queue
+ evidence crops + teach memory (his M4), per-sheet profiles partially (his
M2), device-level matching, and Human Review v2. What does NOT exist yet and
this plan adds: benchmark extraction/registration (his §3 / phases 1–5) and
its Bluebeam SOP. His v2 items that remain future work after this: Hungarian
matching (still greedy), Excel report, Revit color pushback, hexagon
shear-wall tags.

## Benefits (numbers from the manager's analysis, §4 of his doc)

| Metric | Manual pairs today | With 2 benchmarks |
|---|---|---|
| Registration error per element | RMS 8–16 pt ≈ 135–271 mm (whole MATCH budget) | ~1–2.5 pt ≈ 17–42 mm worst case (**5–8× lower**) |
| Smallest true deviation distinguishable | ~270–500 mm | **~50–80 mm** — one stud bay becomes unambiguous |
| Repeatability | operator-dependent picks; verdicts flip between sessions | deterministic — stamps live in the PDF, family in the model |
| Failure classes | mirrored transform on poor picks; click noise | reflection pinned + chirality check; scale drift alarmed; wrong page alarmed |
| Setup labor | 5–10 min re-picking every session | one-time: 2 stamps/sheet + 2 family instances/model |
| Follow-up unlocked | — | after 2–3 validated runs, MATCH gate can tighten 16→~4 pt as pure config |

## The math trap handled (n=2 specifics)

- **Reflection is undecidable from 2 points** (both variants fit exactly).
  PDF y-down vs Revit y-up means the true transform IS reflected → benchmark
  mode pins `assume_reflection=True` + runs a chirality cross-check against
  the detection clouds (evidence + blocker, never a silent flip).
- **RMS is meaningless at n=2** (always ~0) → quality comes from benchmark
  separation, derived-scale vs title-block scale, chirality consistency, and
  optional holdout validation pairs.

## Phases

- **A1 `registration.py`** — additive `compute_calibration_from_benchmarks()`
  reusing the existing `_fit_variant`; scale cross-check (≤0.5% ok / ≤2%
  warn / >2% `BENCHMARK_SCALE_MISMATCH`); rotation sanity; chirality check
  (`BENCHMARK_CHIRALITY_CONFLICT`); `_classify_benchmark_quality()`;
  `VERIFIED_SOURCES` += `"benchmark_verified"`. Separation gate ≥200 pt/10 ft.
- **A2 `benchmarks.py` (new)** — `extract_pdf_benchmarks()`: Pass 1 PDF
  annotations (Stamp/Square/Circle, Subject/Title `BM-x`; FreeText excluded
  so review comments are never misread); Pass 2 vector crosshair fallback
  (circle + ⊥ lines, adjacent BM-x text required). Artifact
  `pdf_benchmarks.json`.
- **A3 exporter** — our pyRevit exporter emits optional top-level
  `benchmarks` (family name contains "Benchmark" OR Mark `BM-\d`), feet.
- **A4 endpoints** — `POST /api/pdf/benchmarks`,
  `POST /api/registration/benchmarks`; compare/match then work unchanged.
- **A5 Bluebeam kit** — `tools/make_benchmark_stamp.py` stamp asset +
  `docs/BENCHMARK-SOP.md` (Tool Set import; two DIAGONAL grid
  intersections; ≥400% zoom; Subject BM-1/BM-2; same intersections in
  Revit with Mark set).
- **A6 frontend** — "Benchmark calibration (2-point)" panel in Pipeline.
- **A7 tests** — synthetic-transform round-trips, chirality/scale/error
  cases, generated fixture PDFs; 86 existing tests = regression gate.

## Acceptance (end-to-end, needs the team)

1. Stamp Madera S-201 at grid A/1 + H/6 in Bluebeam; place the benchmark
   family at the same intersections in the model; re-export.
2. Run: registration quality `high`, derived scale within 0.5% of 18 pt/ft.
3. Seeded error: move one Revit H2 by 500 mm → exactly one
   LOCATION_MISMATCH ≈29.5 pt; delete one H1 → exactly one PDF_ONLY,
   zero cascade.

## Needs from the team before final sign-off

1. Madera model with `BM-1`/`BM-2` benchmark instances + re-export; S-201
   stamped in Bluebeam (SOP will show exactly how).
2. Name the standard benchmark family if one exists (default detection:
   name contains "Benchmark" or Mark = BM-*).
