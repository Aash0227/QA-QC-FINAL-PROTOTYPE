z# Coordinate Matching — Progress Summary (Truth-Safe Registration)

## Goal
Map Revit model coordinates (`revit_internal_feet`, 3D, Y-up) to PDF page coordinates
(`pdf_points`, 2D, Y-down) so hold-downs are compared by position. **This phase makes
registration truth-safe**: the system no longer treats the auto-extent estimate as real
production calibration, and provides a clean path for real manual/grid/anchor calibration.

## Transform direction (locked)
`revit_internal_feet -> pdf_points` only. Inverse stored for reference, never used by compare.

## Why the old auto-estimate produced only 4 matches
The "Auto-estimate test calibration" button built 4 point pairs from the **min/max extents**
(bounding-box corners) of the Revit and PDF hold-down clouds. A similarity transform fit to
those extreme corners has near-zero residual *on the corners*, but it does **not** prove
interior alignment — so only ~4 interior posts happened to land within 16pt. The backend
accepted this as high-confidence / MATCH-allowed, which was misleading.

## What changed in this phase

### 1. Calibration provenance gating (`registration.py`)
- New `calibration_source`: `auto_extent_estimate` | `manual_verified` | `grid_verified` | `anchor_verified`.
- `auto_extent_estimate` is **diagnostic only** — `match_allowed` is forced `false`.
- Only verified sources may permit MATCH.

### 2. Manual calibration support (`POST /api/registration/manual`)
Payload now accepts `calibration_source`, labeled `point_pairs` (id/label/pdf_point/revit_point),
and optional `validation_pairs`. Requires ≥3 non-collinear pairs (prefers 4+). Labels/ids stored
in `registration_calibration.json`.

### 3. Holdout validation
Optional `validation_pairs` are **not** used to solve; they are scored against the solved
transform → `validation_rms_residual_pt`, `validation_max_residual_pt`. If validation RMS > 8pt
or max > 16pt, `match_allowed=false` (blocker `REGISTRATION_VALIDATION_FAILED`) even if solve RMS
is low. If no validation supplied, calibration may still be used but is flagged
`REGISTRATION_UNVALIDATED` (warning).

### 4. Quality model
`{confidence, match_allowed, solve_rms_residual_pt, solve_max_residual_pt,
validation_rms_residual_pt, validation_max_residual_pt, used_pair_count,
validation_pair_count, confidence_reason}`.
- failed: <3 pairs / collinear / invalid / solve fail.
- low: solve RMS>16 or max>32. medium: RMS≤16 & max≤32. high: RMS≤8 & max≤16.
- `match_allowed` true ONLY if verified source + high/medium + validation passing-or-absent.

### 5. Comparison JSON (`ai-compare-report/2.1`)
`registration` block now: `{status, calibration_source, match_allowed, quality, message}`.
- `auto_extent_estimate` → MATCH=0, diagnostic distances (NEEDS_REVIEW), one global blocker
  `AUTO_EXTENT_CALIBRATION_DIAGNOSTIC_ONLY`.
- status values: `available | missing | failed | low_confidence | diagnostic_only`.

### 6. Nearest-candidate debug output
Every `PDF_ONLY` row carries `nearest_revit_candidates` (same type, transformed to PDF, with
distance); every `REVIT_ONLY` row carries `nearest_pdf_candidates`. Critical for diagnosing
why items do not match.

### 7. Revit over-count diagnostics (no exporter change yet)
`revit_count_diagnostics` added to `AIConvert_revit.json` (and echoed in the compare report):
raw records, canonical assemblies, by_mark, pdf_baseline, family_breakdown,
schedule_type_breakdown, level/view availability (with all-null warning), likely_issue,
required_next_fix.

### 8. Frontend
Button relabeled "Auto-estimate (diagnostic only · no MATCH)" and tags
`calibration_source:'auto_extent_estimate'`. Status panel shows source, solve/validation RMS,
and `confidence_reason`.

## Current counts (real Madera S-201 artifacts)
- **PDF (must not change):** H1=10, H2=21, H3=6, H4=17, total=54.
- **Revit AIConvert:** raw records=150, canonical assemblies=72; by mark H1=22, H2=25, H3=10, H4=15.
- All Revit records have `level=null` and `view=null` → cannot scope by level/view (flagged).

## Comparison results (deterministic; advisory LLM stubbed for the demo)
| Scenario | status | match_allowed | MATCH | LOC_MM | PDF_ONLY | REVIT_ONLY | NEEDS_REVIEW | blocking |
|---|---|---|---|---|---|---|---|---|
| No registration | missing | false | 0 | 0 | 2 | 20 | 52 | REGISTRATION_MISSING |
| auto_extent_estimate | diagnostic_only | false | **0** | 0 | 27 | 45 | 27 | AUTO_EXTENT_CALIBRATION_DIAGNOSTIC_ONLY |
| manual_verified (same corner pts) | available | true | 4 | 23 | 27 | 45 | 0 | — (warn: REGISTRATION_UNVALIDATED) |

Key point: the auto-extent transform now yields **MATCH=0** (diagnostic), instead of silently
reporting 4 "real" matches. The 4 matches are only reachable through an explicitly verified
source, and even then are flagged unvalidated.

## Tests
`cd C:\QA-QC-FINAL-PROTOTYPE-bkp\backend && python -m pytest -q` → **33 passed**. New tests cover:
auto_extent never allows MATCH; manual_verified good RMS allows MATCH; failed validation blocks
MATCH; <3 pairs / collinear fail; validation residuals computed; unverified source blocked;
nearest candidates present for PDF_ONLY/REVIT_ONLY; no duplicate one-to-one assignment;
revit_count_diagnostics present. PDF detector still returns H1=10/H2=21/H3=6/H4=17/total=54.

## Remaining blocker to get more REAL matches (next phase)
1. **Real grid/anchor calibration**: pick true shared S-201 grid intersections (A–F / 1–n) as
   `grid_verified` point pairs + independent `validation_pairs`, replacing the corner estimate.
2. **Revit scope filtering**: scope the Revit export to the S-201 level/view/schedule (levels and
   views are currently all null), to stop raw hardware records inflating 72 assemblies vs 54 PDF.
