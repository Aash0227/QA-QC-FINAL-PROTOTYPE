# QA-QC-FINAL-PROTOTYPE-bkp — Complete Technical Reference

> **Audience:** AI agents (Claude, Codex, etc.) picking up this project cold.
> **Purpose:** Exhaustive end-to-end documentation of every module, data flow, algorithm, decision gate, and current state.
> **Last verified:** 2026-07-05 · 63/63 tests passing · 32 real MATCHes achieved

---

## Table of Contents

1. [Project Identity & Scope](#1-project-identity--scope)
2. [Repository Structure](#2-repository-structure)
3. [The Domain Problem](#3-the-domain-problem)
4. [Canonical Mappings (Never Change These)](#4-canonical-mappings-never-change-these)
5. [End-to-End Pipeline](#5-end-to-end-pipeline)
6. [Module-by-Module Deep Dive](#6-module-by-module-deep-dive)
7. [Coordinate Registration Mathematics](#7-coordinate-registration-mathematics)
8. [RANSAC Hold-down Calibration](#8-ransac-hold-down-calibration)
9. [Comparison Engine & MATCH Gating](#9-comparison-engine--match-gating)
10. [Review Overlay System](#10-review-overlay-system)
11. [Frontend Architecture](#11-frontend-architecture)
12. [Artifact Registry](#12-artifact-registry)
13. [OpenRouter LLM Integration](#13-openrouter-llm-integration)
14. [Test Suite](#14-test-suite)
15. [Current Verdict Results](#15-current-verdict-results)
16. [Known Blockers & Root Causes](#16-known-blockers--root-causes)
17. [Path to 54/54](#17-path-to-5454)
18. [How to Run](#18-how-to-run)
19. [File Inventory](#19-file-inventory)
20. [Glossary](#20-glossary)

---

## 1. Project Identity & Scope

| Field | Value |
|-------|-------|
| **Project name** | QA-QC Automated System (Final Prototype Backup) |
| **Root path** | `C:\QA-QC-FINAL-PROTOTYPE-bkp` |
| **Company** | Livio Building Systems Inc (golivio.com) |
| **Target drawing** | Madera Dr S-201 Foundation Plan |
| **Scope** | Hold-down comparison ONLY (H1–H4 marks) |
| **Backend** | FastAPI (Python 3.11), port 8077 |
| **Frontend** | Single HTML file (no React, no build step) |
| **Test count** | 63 (all passing) |
| **Relationship to `C:\qa-qc`** | This prototype is a focused extraction from the production codebase. The S-201 detector (`s201_detector.py`) is copied verbatim from `C:\qa-qc\backend\app\services\s201_holdown_detector.py` with the only change being removal of the `DrawingIntelligenceGraph` dependency. |

### Design Philosophy: "No Fake Matches"

The entire system is engineered around one principle: **never claim a MATCH unless it is evidence-backed and provable**. This means:

- MATCH requires a **verified calibration source** (`manual_verified`, `grid_verified`, `anchor_verified`, or `holdown_ransac`)
- MATCH requires **high or medium confidence** registration
- MATCH requires the Revit point (transformed to PDF space) to be within **16 PDF points** of the PDF detection point
- `auto_extent_estimate` calibration is **diagnostic-only** — it can never produce a MATCH
- Missing coordinates → `drawable: false`, never a placeholder box
- PDF Z-coordinates are always flagged `z_is_inferred: true` — never claimed as real Revit elevations
- Revit over-counts (+18) are surfaced honestly, not silently filtered

---

## 2. Repository Structure

```
C:\QA-QC-FINAL-PROTOTYPE-bkp\
├── .env                          # OPENROUTER_API_KEY (gitignored)
├── .env.example                  # Template
├── .gitignore
├── README.md                     # Setup instructions
├── BUILD_SUMMARY.md              # Build process docs
├── COORDINATE_MATCHING_SUMMARY.md
├── claude-Build-summary.md       # Prior Claude handoff (23.5 KB)
├── run_backend.ps1               # PowerShell launcher
│
├── backend/
│   ├── requirements.txt          # fastapi, uvicorn, PyMuPDF, python-multipart, Pillow
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py               # FastAPI app, all 20+ endpoints (357→460 lines)
│   │   ├── config.py             # Paths, env loader, artifact registry
│   │   ├── openrouter.py         # LLM client (deepseek/deepseek-v4-pro)
│   │   ├── normalization.py      # Hold-down name canonicalization
│   │   ├── s201_detector.py      # PyMuPDF S-201 detector (753 lines, verbatim from production)
│   │   ├── pdf_intelligence.py   # Orchestrator locking 54 baseline
│   │   ├── revit_convert.py      # AI Revit Convert (150→72 assemblies)
│   │   ├── pdf_convert.py        # AI PDF Convert
│   │   ├── compare.py            # Comparison engine with MATCH gating (510 lines)
│   │   ├── registration.py       # 2D similarity transform, quality thresholds
│   │   ├── control_points.py     # Grid extraction, label-matched pairing
│   │   ├── ransac_holdown.py     # Mark-constrained RANSAC registration
│   │   └── review_overlay.py     # NEW: S-201 review overlay generator
│   └── tests/
│       ├── conftest.py
│       ├── test_normalization.py       (7 tests)
│       ├── test_pdf_detector.py        (3 tests)
│       ├── test_schemas.py             (4 tests)
│       ├── test_compare_and_openrouter.py (3 tests)
│       ├── test_registration.py        (16 tests)
│       ├── test_control_points.py      (12 tests)
│       ├── test_ransac_holdown.py      (3 tests)
│       └── test_review_overlay.py      (15 tests) ← NEW
│
├── frontend/
│   ├── index.html                # Single-file futuristic UI (730 lines)
│   └── tester_backup.html        # Backup of earlier version
│
├── docs/
│   └── architecture-diagrams.html # Visual diagrams (simple + technical)
│
└── artifacts/                    # Generated at runtime
    ├── evidence/                 # 54 PNG hold-down crops
    ├── raw_revit_export.json     (1.75 MB)
    ├── AIConvert_revit.json      (120 KB, 72 assemblies)
    ├── pdf_page_intelligence.json (49 KB, 54 detections)
    ├── AIConvert_pdf.json        (49 KB)
    ├── ai_compare_report.json    (46 KB, 90 verdicts)
    ├── registration_calibration.json
    ├── coordinate_registration_report.json
    ├── revit_control_points.json
    ├── pdf_control_points.json
    ├── manual_registration_points.json
    ├── revit_scope_diagnostics.json
    ├── openrouter_call_log.json
    ├── s201_review_page.png      ← NEW
    ├── s201_review_overlay.png   ← NEW
    ├── s201_review_overlay.svg   ← NEW
    └── s201_review_items.json    ← NEW
```

---

## 3. The Domain Problem

### What is being compared?

A **hold-down** is a structural connector that anchors a wood-framed wall to its foundation. On construction drawings (PDFs), hold-downs are marked with callout labels like `H1`, `H2`, `H3`, `H4`. In a Revit BIM model, the same hold-downs exist as 3D model elements (families like `SHDU6-With Bolt`, `SHDU11`, etc.).

The QA/QC engineer's job is to verify that **every hold-down shown on the PDF drawing also exists in the Revit model, at the correct location, with the correct type**. Doing this manually for 54 hold-downs takes hours.

### The Madera S-201 Baseline

The target drawing is the **Madera Dr S-201 Foundation Plan**, page index 4 (0-based) in the PDF:

```
STAMPED_10510 Madera Dr-DWG-20260122-D1.pdf
```

The QA-verified baseline (locked, never break):

| Mark | Hold-down Type | Count |
|------|---------------|-------|
| H1   | HDU6 / S/HDU6 | 10    |
| H2   | HDU11 / S/HDU11 | 21  |
| H3   | HD10S / S/HD10S | 6   |
| H4   | HD15B / S/HD15B | 17  |
| **Total** | | **54** |

### The Revit Reality

The Revit model export contains:
- **150 raw hold-down records** (bodies + anchor bolts + fasteners as separate elements)
- After canonicalization (grouping body+anchor into one assembly): **72 canonical assemblies**
- Delta vs PDF: **+18 over-count**

The over-count exists because all 150 records have `level=null`, `view=null`, `sheet=null`, `export_scope="model"`. The Revit exporter pulls hold-downs from every level/view, not just S-201.

---

## 4. Canonical Mappings (Never Change These)

### Mark ↔ Core Token ↔ Revit Family

```
H1  ↔  HDU6   ↔  SHDU6 / S/HDU6 / S-HDU6 / SHDU6-With Bolt
H2  ↔  HDU11  ↔  SHDU11 / S/HDU11 / SHDU11-With Bolt
H3  ↔  HD10S  ↔  SHD10S / S/HD10S
H4  ↔  HD15B  ↔  SHD15B / S/HD15B
```

The normalization module (`normalization.py`) strips prefixes (`S/`, `S-`, `S`), suffixes (`-With Bolt`, `With Bolt`), normalizes case, and reduces every variant to a single core token (`HDU6`, `HDU11`, `HD10S`, `HD15B`). The core token then maps to exactly one PDF mark (`H1`, `H2`, `H3`, `H4`).

### Hold-down Schedule (Default)

```python
H1: S/HDU6,    (12) #14 studs,    5/8" anchor,  24" embedment
H2: S/HDU11,   (27) #14 studs,    7/8" anchor,  28" embedment
H3: S/HD10S,   (27) #14 studs,    1" anchor,    30" embedment
H4: S/HD15B,   (4) 3/4" DIA studs, 1" anchor,   30" embedment
```

### PDF Page Geometry

| Property | Value |
|----------|-------|
| Page index | 4 (0-based) |
| Sheet number | S-201 |
| Page size | 2592 × 1728 PDF points |
| Rotation | 0 (no rotation handling needed) |
| Plan bbox | (40, 60, 2250, 1660) |
| Schedule table bboxes | 4 regions (excluded from detection) |

### Distance Thresholds (PDF points)

| Threshold | Value | Meaning |
|-----------|-------|---------|
| `MATCH_MAX_PT` | 16.0 | Revit↔PDF distance ≤ this → MATCH |
| `LOCATION_MISMATCH_MAX_PT` | 40.0 | Distance 16–40 → LOCATION_MISMATCH |
| | | Distance > 40 → no pairing (PDF_ONLY / REVIT_ONLY) |

### Confidence Levels

| Level | RMS Residual (pt) | Match Allowed? |
|-------|--------------------|----------------|
| high  | ≤ 8               | ✓ Yes          |
| medium | ≤ 20             | ✓ Yes          |
| low   | > 20              | ✗ No           |
| failed | N/A (transform=None) | ✗ No       |

### Verified Calibration Sources

```python
VERIFIED_SOURCES = {
    "manual_verified",
    "grid_verified",
    "anchor_verified",
    "holdown_ransac",   # ← This is what produces current 32 MATCHes
}
```

`auto_extent_estimate` and `sample` are **NOT** in this set — they can never produce a MATCH.

---

## 5. End-to-End Pipeline

```
┌─────────────────────────────────────────────────────────────────────┐
│                        INPUT DATA                                    │
├─────────────────────────────────────────────────────────────────────┤
│  revit_export.json (1.75 MB)          Madera PDF (S-201, page 4)   │
│  150 raw hold-down records            Construction blueprint        │
│  grids[], holdowns[], units=feet      2592×1728 pt, rotation 0      │
└──────────────┬────────────────────────┴──────────────┬──────────────┘
               │                                        │
               ▼                                        ▼
┌──────────────────────────┐         ┌────────────────────────────────┐
│ STEP 1: AI Revit Convert │         │ STEP 2: PDF Page Intelligence  │
│ (revit_convert.py)       │         │ (pdf_intelligence.py +         │
│                          │         │  s201_detector.py)             │
│ • Parse 150 raw records  │         │                                │
│ • LLM learns naming      │         │ • PyMuPDF page.get_text(words) │
│   patterns               │         │ • Detect H1-H4 labels in plan  │
│ • Group body+anchor into │         │   area (exclude schedule table)│
│   assemblies             │         │ • Expand (2)H2 → 2 instances   │
│ • Normalize family names │         │ • Follow leader lines to       │
│   → core tokens → marks  │         │   physical locations           │
│ • Compute center points  │         │ • Extract schedule row data    │
│   (revit_internal_feet)  │         │ • Render evidence crop PNGs    │
│                          │         │ • Lock baseline: 54 total      │
│ Output: 72 assemblies    │         │ Output: 54 detections          │
│ (H1=22, H2=25, H3=10,    │         │ (H1=10, H2=21, H3=6, H4=17)   │
│  H4=15)                  │         └──────────────┬─────────────────┘
└──────────┬───────────────┘                        │
           │                                        ▼
           │                   ┌────────────────────────────────┐
           │                   │ STEP 3: AI PDF Convert         │
           │                   │ (pdf_convert.py)               │
           │                   │                                │
           │                   │ • Structure PDF detections     │
           │                   │   into Revit-compatible schema │
           │                   │ • Z=None, z_is_inferred=true   │
           │                   │ • LLM confirms mark mapping    │
           │                   │ Output: AIConvert_pdf.json     │
           │                   └──────────────┬─────────────────┘
           │                                  │
           └──────────────┬───────────────────┘
                          │
                          ▼
          ┌────────────────────────────────┐
          │ STEP 4: RANSAC Registration    │
          │ (ransac_holdown.py +           │
          │  registration.py)              │
          │                                │
          │ • Build candidate pairs:       │
          │   same-mark H1↔H1, H2↔H2, etc.│
          │ • 1,133,264 valid similarity   │
          │   fits inspected               │
          │ • 4000 iterations × 20 restarts│
          │ • Keep best inlier set (32)    │
          │ • Refit with all inliers       │
          │ • Compute quality: RMS, scale, │
          │   rotation, reflection         │
          │                                │
          │ Transform: scale=17.97 pt/ft,  │
          │ rot=0.05°, reflection=true     │
          │ (PDF y-down convention)        │
          │                                │
          │ Output: registration_          │
          │ calibration.json               │
          │ (source=holdown_ransac,        │
          │  match_allowed=true)           │
          └──────────────┬─────────────────┘
                         │
                         ▼
          ┌────────────────────────────────┐
          │ STEP 5: AI Compare             │
          │ (compare.py)                   │
          │                                │
          │ • Load calibration             │
          │ • Transform all Revit points   │
          │   into PDF space               │
          │ • Group by mark (H1, H2, H3,   │
          │   H4)                          │
          │ • For each mark:               │
          │   - Build candidate pairs      │
          │     within 40pt                │
          │   - Sort by distance ascending │
          │   - One-to-one greedy assignment│
          │   - ≤16pt → MATCH              │
          │   - 16-40pt → LOCATION_MISMATCH│
          │   - Unpaired PDF → PDF_ONLY    │
          │   - Unpaired Revit → REVIT_ONLY│
          │ • LLM advisory assessment      │
          │ • Generate blockers list       │
          │                                │
          │ Output: ai_compare_report.json │
          │ (90 verdicts: 32 MATCH, 4      │
          │  LOC_MM, 18 PDF_ONLY, 36       │
          │  REVIT_ONLY)                   │
          └──────────────┬─────────────────┘
                         │
                         ▼
          ┌────────────────────────────────┐
          │ STEP 6: Review Overlay         │
          │ (review_overlay.py)            │
          │                                │
          │ • Render S-201 page to PNG     │
          │   (150 DPI, 2592×1728)         │
          │ • Build review items:          │
          │   - LOC_MM → red box + red     │
          │     connector line             │
          │   - PDF_ONLY → blue box        │
          │   - REVIT_ONLY → orange box    │
          │     (on-sheet only)            │
          │   - MATCH → green dot (hidden  │
          │     by default)                │
          │ • Undrawable items listed      │
          │   separately                   │
          │ • Build SVG overlay (viewBox = │
          │   page size, raw PDF coords)   │
          │ • Burn annotations onto PNG    │
          │                                │
          │ Outputs:                       │
          │ • s201_review_page.png         │
          │ • s201_review_overlay.svg      │
          │ • s201_review_overlay.png      │
          │ • s201_review_items.json       │
          └────────────────────────────────┘
```

---

## 6. Module-by-Module Deep Dive

### 6.1 `config.py` — Configuration & Artifact Registry

**Purpose:** Centralizes all paths, environment variables, and artifact file names.

**Key constants:**
- `PROJECT_ROOT` — `C:\QA-QC-FINAL-PROTOTYPE-bkp`
- `ARTIFACT_DIR` — `PROJECT_ROOT / artifacts`
- `EVIDENCE_DIR` — `ARTIFACT_DIR / evidence`
- `OPENROUTER_API_KEY` — loaded from `.env` or environment
- `OPENROUTER_REASONING_MODEL` — `deepseek/deepseek-v4-pro`

**Artifact registry (`ARTIFACT_FILES` dict):**
Maps logical keys to filenames. All artifacts live in `ARTIFACT_DIR`. The `artifact_path(key)` function resolves any key to an absolute path. Currently 16 registered artifacts.

**`.env` loader:**
Minimal parser — reads `KEY=VALUE` lines, strips quotes, doesn't override existing env vars.

---

### 6.2 `normalization.py` — Hold-down Name Canonicalization

**Purpose:** Reduce divergent Revit/PDF naming styles to a single canonical vocabulary.

**Core function:**
```python
normalize_holdown_type(raw: str) -> NormalizedHoldownType
```

**Normalization steps:**
1. Uppercase the input
2. Strip whitespace
3. Remove prefixes: `S/`, `S-`, `S` (when followed by `HD`)
4. Remove suffixes: `-With Bolt`, `With Bolt`, `-With Bolt`
5. Remove separators: `/`, `-`, `_`, spaces
6. Extract the core token: `HDU6`, `HDU11`, `HD10S`, `HD15B`

**Reverse mapping:**
```python
expected_core_token_for_mark("H1") → "HDU6"
mapped_mark_for_core_token("HDU6") → "H1"
```

**Tests:** 7 parametrized tests covering slash/hyphen/space/case/suffix variants.

---

### 6.3 `s201_detector.py` — S-201 Hold-down Detector (753 lines)

> **CRITICAL:** This file is copied **verbatim** from `C:\qa-qc\backend\app\services\s201_holdown_detector.py`. The only change is removal of the `DrawingIntelligenceGraph` dependency, replaced with standalone `locate_s201_page()`. **Do not modify detection logic** — it reproduces the proven Madera baseline exactly.

**Purpose:** Detect H1–H4 hold-down callouts on the S-201 foundation plan page using PyMuPDF vector + text extraction.

**Key constants:**
```python
PLAN_BBOX = (40, 60, 2250, 1660)                    # Plan area
S201_TABLE_BBOXES = (                                # Schedule table regions (excluded)
    (1760, 725, 2250, 1045),
    (1785, 1435, 2250, 1590),
    (1875, 1035, 2250, 1425),
    (1460, 1225, 1790, 1650),
)
HOLDOWN_ROW_BANDS = (                                # Y-coordinate bands for schedule rows
    ("H1", 1504, 1524),
    ("H2", 1524, 1544),
    ("H3", 1544, 1565),
    ("H4", 1564, 1586),
)
HOLDOWN_RE = r"^(?:(?:\((?P<count_paren>\d+)\)|(?P<count_plain>\d+))\s*)?(?P<label>H[1-4])$"
```

**Detection pipeline:**

1. **`locate_s201_page(pdf_path)`** — Scans all pages for `S-201` text + cluster of H1-H4 marks. Returns page index with most marks (page 4 for Madera).

2. **`_extract_holdown_schedule(page)`** — Reads the schedule table by scanning words within `HOLDOWN_ROW_BANDS` y-ranges and column x-ranges. Extracts: holdown_type, stud_fasteners, anchor_bolt, embedment. Falls back to `DEFAULT_HOLDOWN_SCHEDULE` if extraction fails.

3. **`_label_hits(words, table_bboxes)`** — Finds H1-H4 text tokens in the plan area (excluding schedule tables). For each hit:
   - Matches against `HOLDOWN_RE` regex
   - Checks for nearby count prefix (e.g., `(2)H2`)
   - Filters out detail references (numbers near `S-NNN` sheet references)
   - Deduplicates overlapping hits

4. **`_page_vector_context(page)`** — Extracts vector graphics from the page:
   - **Filled markers:** Small filled rectangles (4-22pt) that represent physical hold-down symbols
   - **Line segments:** Diagonal lines that represent leader lines from label to physical location

5. **`_build_detection_plan(hit, vector_context)`** — For each label hit, builds a plan to locate the physical hold-down:
   - **`targets`:** Endpoints of leader lines originating near the label
   - **`hardware_pair`:** Two filled markers near the label (paired hold-down)
   - **Scoring:** `hardware_pair_score` = sum of distances from label to each marker

6. **`_resolve_hardware_pair_claims(plans)`** — Resolves conflicts when multiple labels claim the same filled marker. Assigns each marker to the closest label.

7. **`_instance_points_from_plan(plan)`** — Extracts physical location points:
   - If `use_hardware_pair`: use the two marker centers
   - If `targets` count ≥ multiplicity: use leader line endpoints
   - If `targets` exist but < multiplicity: use available targets + synthetic expansion
   - Fallback: label center

8. **`_location_evidence(plan, total)`** — Assigns confidence and method:
   - `paired_hardware_markers` (0.94, ±4pt) — two filled markers found
   - `multiple_leader_targets` (0.90, ±7pt) — enough leader endpoints
   - `leader_target` (0.84, ±10pt) — single leader endpoint
   - `leader_plus_synthetic_count_expansion` (0.74, ±15pt) — some leaders + synthetic
   - `label_center_synthetic_count_expansion` (0.62, ±20pt) — count prefix, no leader
   - `label_center_fallback` (0.55, ±24pt) — no leader, no count

9. **`detect_holdowns_on_page(...)`** — Main entry: builds plans, resolves claims, generates instances, renders evidence crops, returns detection dicts.

**Output per detection:**
```python
{
    "id": "s-201_h1_022_2",
    "sheet_number": "S-201",
    "page_index": 4,
    "raw_mark": "(2)H2",
    "normalized_mark": "H2",
    "schedule_type_raw": "S/HDU11",
    "normalized_core_token": "HDU11",
    "multiplicity_index": 2,
    "total_multiplicity": 2,
    "bbox_pdf": (x0, y0, x1, y1),
    "center_pdf": [x, y],
    "evidence_crop_path": "s-201_h2_001_1.png",
    "anchor_bolt": '7/8" (SABR)',
    "fasteners": "(27) #14",
    "embedment": '28"',
    "confidence": 0.94,
    "source": "s201_focused_holdown_detector",
    "location_method": "paired_hardware_markers",
    "location_uncertainty_pt": 4.0,
    "leader_found": True,
    "hardware_marker_found": True,
    "explicit_count_found": True,
}
```

**Evidence crops:** Each detection gets a PNG crop rendered at 2x zoom showing the label + surrounding context, saved to `artifacts/evidence/`.

---

### 6.4 `pdf_intelligence.py` — PDF Page Intelligence Orchestrator

**Purpose:** Thin orchestrator that calls `s201_detector` and wraps output in the page intelligence schema.

**Key function:**
```python
run_page_intelligence(pdf_path: Path) -> dict
```

**Output schema:**
```json
{
  "schema_version": "pdf-page-intelligence/1.0",
  "source_file": "C:\\...\\STAMPED_10510 Madera Dr-DWG-20260122-D1.pdf",
  "page_index": 4,
  "sheet_number": "S-201",
  "summary": {
    "total": 54,
    "by_type": {"H1": 10, "H2": 21, "H3": 6, "H4": 17}
  },
  "matches_expected_baseline": true,
  "holdowns": [...]
}
```

**Baseline enforcement:** The `matches_expected_baseline` field is `true` only when `total == 54` and `by_type == {H1:10, H2:21, H3:6, H4:17}`.

---

### 6.5 `revit_convert.py` — AI Revit Convert

**Purpose:** Transform raw Revit export JSON into canonical hold-down assemblies with proper grouping and mark assignment.

**Input:** `raw_revit_export.json` containing:
- `holdowns[]` — 150 raw records with `element_id`, `family`, `scheduled_type`, `location[x,y]`, `elevation`, `bbox`, `level`
- `grids[]` — Grid line definitions
- `units` — `revit_internal_feet`

**Pipeline:**

1. **Build family type dictionary** — Group all records by `family` name. For each family, record: core_token, scheduled_type, sample locations, element count.

2. **LLM naming pattern learning** (OpenRouter call):
   - System prompt: "You are a structural QA expert. Given Revit hold-down family names, infer the naming pattern and map each family to a Simpson Strong-Tie core token."
   - Input: list of unique family names + their scheduled types
   - Output: JSON mapping `family_name → {core_token, confidence, reason}`
   - Fallback if LLM unavailable: deterministic regex-based mapping using `normalization.py`

3. **Group body + anchor into assemblies:**
   - For each "body" element (family contains "HD" prefix, elevation > 0):
     - Find nearby "anchor" elements (same scheduled_type, within 0.5 ft, elevation ≈ 0)
     - Group them: body becomes `primary_element_id`, anchors become `member_element_ids`
   - Ungrouped anchors → unmapped records

4. **Assign PDF mark candidates:**
   - Map core_token → mark using `normalization.mapped_mark_for_core_token()`
   - Records with unknown core tokens → `pdf_mark_candidate = None`

5. **Compute assembly center points:**
   - Primary element location `[x, y]` in `revit_internal_feet`
   - Bbox from all member elements

6. **Generate QA warnings:**
   - `level=null` → warning
   - `view=null` → warning
   - `export_scope != "active_view"` → warning
   - Unmapped families → warning

7. **Build revit_count_diagnostics:**
   - `raw_holdown_records`: 150
   - `canonical_assembly_count`: 72
   - `by_mark`: {H1:22, H2:25, H3:10, H4:15}
   - `pdf_baseline`: {H1:10, H2:21, H3:6, H4:17, total:54}

**Output:** `AIConvert_revit.json` with:
- `schema_version`, `generated_at`, `source_file`
- `ai_model_used`: `"deepseek/deepseek-v4-pro"` or `"deterministic_fallback"`
- `learned_key_points`: {raw_record_count, family_count, ...}
- `family_type_dictionary`: per-family mapping
- `canonical_holdown_assemblies[]`: 72 assemblies
- `unmapped_or_ambiguous_records[]`: records that couldn't be classified
- `qa_warnings[]`: scope/export warnings
- `revit_count_diagnostics`: count chain
- `openrouter_call_status`: LLM call metadata

---

### 6.6 `pdf_convert.py` — AI PDF Convert

**Purpose:** Structure PDF detections into the same schema as Revit assemblies, enabling direct comparison.

**Input:** `pdf_page_intelligence.json` + optional `AIConvert_revit.json` (for "memory" — LLM uses Revit family names to confirm mark mapping).

**Key transformation:**
- `center_pdf: [x, y]` → `center_point: {x, y, z: None, z_is_inferred: true, space: "pdf_page", unit: "points"}`
- Z is always `None` and `z_is_inferred: true` — PDF has no Z dimension

**LLM call (optional):**
- Purpose: `pdf_ai_convert.confirm_mark_mapping`
- Input: PDF marks + Revit family dictionary
- Output: confirmation that H1↔HDU6 etc. are correct
- Fallback: deterministic mapping

**Output:** `AIConvert_pdf.json` with structured hold-down records matching the Revit schema.

---

### 6.7 `registration.py` — Coordinate Registration

**Purpose:** Compute a 2D similarity transform that maps Revit internal coordinates (feet) to PDF page coordinates (points).

**Transform model:**
```
PDF = A × Revit + T
```
Where:
- `A` = `[[a, -b], [b, a]]` (scale + rotation matrix, allows reflection when det(A) < 0)
- `T` = translation `[tx, ty]`

This is a **4-parameter similarity transform** (scale, rotation, tx, ty) with optional reflection.

**`compute_calibration(point_pairs, calibration_source, validation_pairs)`:**

1. **Minimum 3 non-collinear pairs required.** Fewer → `confidence="failed"`, `transform=None`.

2. **Solve via least squares:**
   - Build 2N×4 matrix from N point pairs
   - Solve for `[a, b, tx, ty]` using normal equations
   - Extract: `scale = sqrt(a² + b²)`, `rotation = atan2(b, a)`, `reflection = (det < 0)`
   - Compute residuals: `residual_i = transformed_revit_i - pdf_i`
   - `RMS = sqrt(mean(residual_x² + residual_y²))`
   - `max_residual = max(|residual_i|)`

3. **Assign confidence:**
   - `high` if RMS ≤ 8pt
   - `medium` if RMS ≤ 20pt
   - `low` if RMS > 20pt
   - `failed` if transform is None

4. **Validation holdout (if provided):**
   - Apply transform to validation pairs (not used in solve)
   - Compute validation RMS and max residual
   - `validation_failed = True` if validation_max > 20pt or validation_rms > 15pt
   - If validation fails → `match_allowed = False`

5. **Source gating:**
   - If `calibration_source` not in `VERIFIED_SOURCES` → `match_allowed = False`
   - This is the critical gate that prevents `auto_extent_estimate` from producing MATCHes

**`apply_transform(matrix, x, y)`:**
```python
[[a, -b], [b, a]] @ [x, y] + [tx, ty] = [a*x - b*y + tx, b*x + a*y + ty]
```

**`registration_usable(calibration)`:**
Returns `True` only when:
- `calibration_source` in `VERIFIED_SOURCES`
- `confidence` in `{"high", "medium"}`
- `validation_failed` is `False` (or no validation was performed)

**`registration_status(calibration)`:**
- `"missing"` — no calibration exists
- `"failed"` — transform is None (couldn't solve)
- `"diagnostic_only"` — source is `auto_extent_estimate` (has transform but not verified)
- `"low_confidence"` — verified source but RMS too high
- `"validation_failed"` — holdout residuals exceeded limits
- `"available"` — everything passes, MATCH allowed

**Transform direction:** `revit_internal_feet → pdf_points`

**Output:** `registration_calibration.json`:
```json
{
  "schema_version": "registration-calibration/2.0",
  "calibration_source": "holdown_ransac",
  "method": "least_squares_similarity_2d",
  "transform": {
    "matrix": [[17.97, 0.02], [-0.02, 17.97]],
    "scale": 17.97,
    "rotation_degrees": 0.05,
    "reflection": true,
    "translation": [301.2, 1272.9]
  },
  "quality": {
    "used_pair_count": 32,
    "solve_rms_residual_pt": 6.22,
    "solve_max_residual_pt": 14.8,
    "confidence": "high",
    "match_allowed": true,
    "validation_pair_count": null,
    "validation_failed": false
  }
}
```

---

### 6.8 `control_points.py` — Grid Control Points

**Purpose:** Extract Revit grid intersections and pair them with manually-entered PDF grid points for `grid_verified` calibration.

**`extract_revit_control_points(raw_revit)`:**
1. Read `grids[]` from raw Revit export
2. Classify each grid as letter (A, B, C…) or number (1, 2, 3…) by first character
3. Compute line-line intersections of every letter × number pair using general 2D line intersection formula
4. Return points with IDs like `grid_A_1`, `grid_B_2`, etc.

**Current Revit grid intersections (9 points):**
```
grid_A_1 = (17.30, 62.17) ft   grid_B_1 = (60.89, 62.17) ft   grid_C_1 = (75.97, 62.17) ft
grid_A_2 = (17.30, 20.59) ft   grid_B_2 = (60.89, 20.59) ft   grid_C_2 = (75.97, 20.59) ft
grid_A_3 = (17.30,  4.72) ft   grid_B_3 = (60.89,  4.72) ft   grid_C_3 = (75.97,  4.72) ft
```

**`build_pairs_from_labels(revit_cp, pdf_cp)`:**
- Set intersection of point IDs between Revit and PDF sides
- Returns `matched_ids`, `revit_only_ids`, `pdf_only_ids`, `point_pairs[]`
- Sets `calibration_source = "grid_verified"`

**`auto_calibrate_from_grids(raw_revit, pdf_cp, validation_pairs)`:**
End-to-end: extract Revit points → match with PDF points → if ≥3 pairs, compute calibration → save.

**`build_scope_diagnostics(raw_revit, ai_revit)`:**
Standalone artifact documenting the Revit over-count:
- `revit_by_mark`: {H1:22, H2:25, H3:10, H4:15, total:72}
- `pdf_baseline`: {H1:10, H2:21, H3:6, H4:17, total:54}
- `warnings`: ["level=null", "view=null", "export_scope != active_view"]
- `required_exporter_fields`: ["level", "view", "sheet", "schedule_membership"]

> **Note:** In the current prototype, `control_points.py` is not the active calibration path. The RANSAC hold-down calibration (`ransac_holdown.py`) replaced it because it doesn't require manual PDF point entry.

---

### 6.9 `ransac_holdown.py` — Mark-Constrained RANSAC

**Purpose:** Derive the Revit→PDF similarity transform automatically from hold-down correspondences, without requiring manual grid point entry.

**Key insight:** Same-mark hold-downs (H1↔H1, H2↔H2, etc.) are natural candidate correspondences. Even though there are more Revit items than PDF items (72 vs 54), the true correspondences form a consistent spatial consensus that RANSAC can find.

**`ransac_calibrate(ai_revit, ai_pdf, distance_threshold_pt, iterations, restarts)`:**

1. **Build candidate pairs:**
   - For each mark (H1, H2, H3, H4):
     - Cross-product all Revit assemblies of that mark with all PDF detections of that mark
   - For Madera: 22×10 + 25×21 + 10×6 + 15×17 = 220 + 525 + 60 + 255 = **1,060 candidate pairs**

2. **RANSAC loop (4000 iterations × 20 restarts):**
   - Randomly sample 2 pairs from the candidate set (minimum for similarity transform)
   - Constraint: the 2 pairs must be from different marks OR sufficiently far apart (to avoid degeneracy)
   - Compute candidate transform from the 2 pairs
   - Apply transform to ALL candidate pairs
   - Count inliers: pairs where `distance(transformed_revit, pdf) ≤ distance_threshold_pt` (default 16pt)
   - Track best inlier set across all iterations and restarts

3. **Refit:**
   - Take the best inlier set (32 pairs for Madera)
   - Refit the similarity transform using least-squares on all 32 inliers
   - Recompute residuals, RMS, max residual

4. **Quality assessment:**
   - `calibration_source = "holdown_ransac"` (in `VERIFIED_SOURCES`)
   - Confidence: high/medium/low based on RMS
   - `match_allowed = True` if confidence is high/medium

5. **Output:**
   - `ok: True`
   - `calibration`: full registration-calibration/2.0 payload
   - `summary`: {candidate_pair_count, inlier_pair_count, iterations, restarts}

**Current Madera results:**
- Candidate pairs: 1,060
- Inliers: 32
- Transform: scale=17.97 pt/ft, rotation=0.05°, reflection=true
- RMS: 6.22 pt
- Max residual: 14.8 pt
- Confidence: high
- Match allowed: true

**Why reflection=true:** PDF coordinate system has Y pointing down (top-left origin), while Revit has Y pointing up. The transform includes a reflection to account for this.

---

### 6.10 `compare.py` — Comparison Engine (510 lines)

**Purpose:** Compare Revit and PDF hold-downs using the registered transform, producing evidence-backed verdicts.

**Verdicts:**
```python
VERDICTS = ("MATCH", "PDF_ONLY", "REVIT_ONLY", "TYPE_MISMATCH", "LOCATION_MISMATCH", "NEEDS_REVIEW")
```

**Main entry: `compare(ai_revit, ai_pdf, calibration)`:**

1. **Group by mark:**
   - Revit: `canonical_holdown_assemblies[]` grouped by `pdf_mark_candidate`
   - PDF: `holdowns[]` grouped by `normalized_mark`

2. **Check registration status:**
   - `usable = registration_usable(calibration)` — True if verified source + high/medium confidence + no validation failure
   - If usable → location-aware matching (MATCH possible)
   - If `diagnostic_only` (auto_extent) → diagnostic matching (distances shown but no MATCH)
   - If not usable → type-only fallback (everything NEEDS_REVIEW)

3. **Location-aware matching (`_match_with_location`):**
   For each mark (H1, H2, H3, H4):
   
   a. **Pre-transform Revit points** into PDF space using `registration.apply_transform(matrix, x, y)`
   
   b. **Build candidate pairs:** For each Revit point × PDF point of the same mark, if distance ≤ 40pt, add to candidates list.
   
   c. **Sort candidates by distance ascending.**
   
   d. **Greedy one-to-one assignment:**
   - Iterate sorted candidates
   - Skip if Revit or PDF item already used
   - Assign:
     - distance ≤ 16pt → MATCH (confidence = `max(0.6, 0.95 - dist/(2×16))`)
     - 16pt < distance ≤ 40pt → LOCATION_MISMATCH (confidence=0.5)
   
   e. **Leftovers:**
   - PDF items not paired → PDF_ONLY (confidence=0.6)
   - Revit items not paired → REVIT_ONLY (confidence=0.6)
   - Each leftover gets `nearest_candidates` (top 3 nearest same-mark items) for debugging
   
   f. **Revit items with missing coordinates** → NEEDS_REVIEW immediately

4. **Diagnostic mode (`diagnostic=True`):**
   - Same as above but ALL paired items get `NEEDS_REVIEW` instead of MATCH/LOCATION_MISMATCH
   - Distances are still computed and shown
   - Used when calibration source is `auto_extent_estimate`

5. **Type-only fallback (`_match_type_only`):**
   - No usable registration
   - Pairs by mark type only (min(revit_count, pdf_count) pairs)
   - All pairs → NEEDS_REVIEW ("Type matches; location not evaluated")
   - Surplus → PDF_ONLY or REVIT_ONLY

6. **Blockers:**
   - `REGISTRATION_MISSING` — no calibration
   - `REGISTRATION_FAILED` — couldn't solve (fewer than 3 pairs or collinear)
   - `REGISTRATION_VALIDATION_FAILED` — holdout residuals exceeded limits
   - `REGISTRATION_LOW_CONFIDENCE` — verified source but RMS too high
   - `AUTO_EXTENT_CALIBRATION_DIAGNOSTIC_ONLY` — auto_extent, MATCH forbidden
   - `COUNT_MISMATCH` — per-mark Revit vs PDF counts differ (warning, not blocking)

7. **LLM advisory (`_llm_assessment`):**
   - Sends per-mark results + registration status + blockers to OpenRouter
   - LLM assesses whether MATCH is justified
   - Returns `{match_justified, overall_verdict, reasoning}`

8. **Output: `ai_compare_report.json`:**
```json
{
  "schema_version": "ai-compare-report/2.1",
  "generated_at": "2026-07-05T...",
  "inputs": {"revit_source": "...", "pdf_source": "..."},
  "registration": {
    "status": "available",
    "calibration_source": "holdown_ransac",
    "match_allowed": true,
    "message": "Verified registration..."
  },
  "summary": {
    "pdf_holdown_total": 54,
    "revit_assembly_total": 72,
    "matched_items": 32,
    "full_match_achieved": false,
    "verdict_counts": {"MATCH": 32, "LOCATION_MISMATCH": 4, ...},
    "per_mark": [...]
  },
  "attempts": [...],
  "blockers": [...],
  "final_verdicts": [
    {
      "pdf_holdown_id": "s-201_h1_022_2",
      "revit_assembly_id": "rev_asm_011",
      "mark": "H1",
      "pdf_point": {"x": 307.04, "y": 702.66},
      "revit_point": {"x": 0.56, "y": 3.89, "space": "revit_internal_feet"},
      "revit_point_transformed_to_pdf": {"x": 311.2, "y": 700.1},
      "distance_pdf_points": 4.15,
      "verdict": "MATCH",
      "reason": "Same mark H1; registered distance 4.1pt <= 16pt.",
      "confidence": 0.82
    },
    ...
  ],
  "honesty_statement": "MATCH is only issued when...",
  "llm_assessment": {...},
  "openrouter_call_status": {...}
}
```

---

### 6.11 `review_overlay.py` — S-201 Manual Review Overlay

> **NEW module** — Renders discrepancy boxes directly on the S-201 drawing.

**Purpose:** Take the comparison verdicts and draw them as colored boxes on the actual PDF page, so a structural reviewer can see exactly where problems are.

**Constants:**
```python
BOX_HALF_PT = 20          # 40pt square centered on point
RENDER_DPI = 150          # Page render resolution
RED = "#ef4444"           # LOCATION_MISMATCH
BLUE = "#3b82f6"          # PDF_ONLY
ORANGE = "#f97316"        # REVIT_ONLY
GREEN = "#22c55e"         # MATCH
```

**Functions:**

1. **`render_s201_page_png(pdf_path, page_index, out_path, dpi)`**
   - Uses `page.get_pixmap(matrix=fitz.Matrix(dpi/72, dpi/72), alpha=False)`
   - Returns `(path, width_pt, height_pt)` — page dimensions in PDF points

2. **`build_review_items(compare_report, page_w, page_h)`**
   - Iterates `final_verdicts[]`
   - For each verdict, builds an item spec:
     - LOCATION_MISMATCH → red `box` at `pdf_point` + red `connector` from `revit_point_transformed_to_pdf` to `pdf_point`
     - PDF_ONLY → blue `box` at `pdf_point`
     - REVIT_ONLY → orange `box` at `revit_point_transformed_to_pdf` **only if on-sheet** (0 ≤ x ≤ w, 0 ≤ y ≤ h)
     - MATCH → green `circle` at `pdf_point`, `default_hidden=True`
   - If any coordinate is `None` or outside page bounds → `drawable=False`
   - Returns: `{schema_version, page, counts, items, undrawable_ids}`

3. **`build_overlay_svg(items_payload, show_match=False)`**
   - SVG with `viewBox="0 0 {w} {h}"` (raw PDF coordinates, no transform)
   - Dashed rectangles (`stroke-dasharray="8 5"`)
   - Red connector `<line>` for LOCATION_MISMATCH
   - Text labels: "LOCATION MISMATCH · distance: X pt"
   - Green `<circle>` only when `show_match=True`
   - Skips all `drawable=False` items (no faked boxes)

4. **`render_annotated_png(page_png_path, items, out_path, dpi, show_match)`**
   - Burns boxes/lines onto the PNG using `PIL.ImageDraw`
   - Scales PDF coordinates to pixels by `dpi/72`
   - Static exportable artifact

5. **`build_and_save(compare_report, pdf_path, page_index, artifact_dir)`**
   - Orchestrator: render page → build items → build SVG → render annotated PNG → write JSON
   - Writes 4 files: `s201_review_page.png`, `s201_review_overlay.svg`, `s201_review_overlay.png`, `s201_review_items.json`

**Current output (Madera):**
- Total items: 90
- Drawable: 90 (all on-sheet)
- Undrawable: 0
- By verdict: {MATCH: 32, PDF_ONLY: 18, REVIT_ONLY: 36, LOCATION_MISMATCH: 4}

---

### 6.12 `openrouter.py` — LLM Client

**Purpose:** Thin client for OpenRouter API with call logging and status tracking.

**Configuration:**
- Model: `deepseek/deepseek-v4-pro`
- Base URL: `https://openrouter.ai/api/v1`
- API key from `.env`

**`call_llm(system_prompt, user_prompt, purpose)`:**
- If no API key → returns `{called: False, ok: False, error: "OPENROUTER_API_KEY missing"}`
- Otherwise: POST to `/chat/completions` with messages
- Logs every call to `openrouter_call_log.json` with: timestamp, purpose, model, latency, usage (tokens), status_code, content
- Returns: `{called, ok, model, timestamp, purpose, error, usage, content, latency_ms, status_code, message}`

**Call log:** Persistent JSON file tracking all LLM calls. Current state: 38 entries, 28 successful, 26,425 total tokens.

---

### 6.13 `main.py` — FastAPI Application

**Purpose:** All API endpoints, artifact I/O, and static file serving.

**Endpoints (20+):**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Status, artifacts present, OpenRouter config, registration status |
| POST | `/api/revit/ai-convert` | Upload Revit JSON → AIConvert_revit.json |
| POST | `/api/pdf/page-intelligence` | Upload PDF → pdf_page_intelligence.json |
| POST | `/api/pdf/ai-convert` | PDF → AIConvert_pdf.json |
| POST | `/api/compare/ai` | Run comparison → ai_compare_report.json |
| POST | `/api/registration/manual` | Manual point-pair calibration |
| GET | `/api/registration` | Load current calibration |
| DELETE | `/api/registration` | Delete calibration |
| POST | `/api/revit/control-points` | Extract Revit grid intersections |
| GET | `/api/revit/control-points` | Get saved Revit control points |
| POST | `/api/pdf/control-points` | Save PDF control points |
| GET | `/api/pdf/control-points` | Get saved PDF control points |
| POST | `/api/registration/auto-grid` | Auto-calibrate from grid labels |
| POST | `/api/registration/auto-holdown` | RANSAC calibration from hold-downs |
| POST | `/api/revit/scope-diagnostics` | Rebuild scope diagnostics |
| GET | `/api/revit/scope-diagnostics` | Get scope diagnostics |
| POST | `/api/review/build` | Build review overlay (NEW) |
| GET | `/api/review/items` | Get review items JSON (NEW) |
| GET | `/api/review/page.png` | Get rendered S-201 page (NEW) |
| GET | `/api/review/overlay.png` | Get annotated PNG (NEW) |
| GET | `/api/review/overlay.svg` | Get SVG overlay (NEW) |
| GET | `/api/artifacts` | List all artifacts |
| GET | `/api/artifacts/{filename}` | Download any artifact |
| GET | `/api/openrouter/log` | Full OpenRouter call log |

**Helper functions:**
- `_save_artifact(key, data)` — Write JSON to artifact path
- `_load_artifact(key)` — Read JSON from artifact path (409 if missing)

**Static file serving:** Frontend mounted at `/` (last, so `/api/*` wins).

---

## 7. Coordinate Registration Mathematics

### The Problem

Revit model coordinates are in **internal feet** with origin at the Revit project base point. PDF coordinates are in **points** (1/72 inch) with origin at the top-left corner, Y pointing down. These two coordinate systems have different:

- **Units:** feet vs points (~17.97 pt/ft for Madera)
- **Origin:** Revit project base vs PDF top-left
- **Y direction:** Revit Y-up vs PDF Y-down (requires reflection)
- **Rotation:** Small rotational offset (~0.05° for Madera)

### The Transform Model

A 2D similarity transform with reflection:

```
PDF_x = a × Revit_x - b × Revit_y + tx
PDF_y = b × Revit_x + a × Revit_y + ty
```

Where:
- `scale = sqrt(a² + b²)`
- `rotation = atan2(b, a)`
- `reflection = True` when `det([[a, -b], [b, a]]) = a² + b²` would be positive, BUT the actual sign comes from the solve — if the system needs reflection, `b` picks up a sign flip

Matrix form:
```
[PDF_x]   [a  -b] [Revit_x]   [tx]
[PDF_y] = [b   a] [Revit_y] + [ty]
```

### Least-Squares Solution

Given N ≥ 3 point pairs `(revit_x_i, revit_y_i) → (pdf_x_i, pdf_y_i)`:

Build the 2N×4 system:
```
[revit_x_1  -revit_y_1  1  0] [a ]   [pdf_x_1]
[revit_y_1   revit_x_1  0  1] [b ] = [pdf_y_1]
[revit_x_2  -revit_y_2  1  0] [tx]   [pdf_x_2]
[revit_y_2   revit_x_2  0  1] [ty]   [pdf_y_2]
...                             
```

Solve via normal equations: `A^T A x = A^T b`.

### Quality Metrics

- **RMS residual:** `sqrt(mean(residual_x² + residual_y²))` — average error in PDF points
- **Max residual:** Largest single-point error
- **Confidence levels:**
  - high: RMS ≤ 8pt (≈0.11 inch — very tight)
  - medium: RMS ≤ 20pt (≈0.28 inch — acceptable)
  - low: RMS > 20pt (too noisy for MATCH)

### Validation Holdout

If `validation_pairs` are provided (known correspondences NOT used in the solve):
- Apply the solved transform to each validation pair
- Compute residuals
- If `validation_max > 20pt` or `validation_rms > 15pt` → `validation_failed = True` → `match_allowed = False`

This prevents a transform that fits the calibration points well but doesn't generalize.

---

## 8. RANSAC Hold-down Calibration

### Why RANSAC?

Manual grid-point entry is tedious and error-prone. The old `control_points.py` path required an operator to read PDF page-point coordinates off the drawing and type them in. RANSAC automates this by using the hold-downs themselves as correspondences.

### Algorithm

**Input:** 72 Revit assemblies + 54 PDF detections, grouped by mark.

**Step 1: Build candidate pairs**
- For each mark M in {H1, H2, H3, H4}:
  - For each Revit assembly with `pdf_mark_candidate == M`:
    - For each PDF detection with `normalized_mark == M`:
      - Add pair `(revit_point, pdf_point)` to candidates
- Result: 1,060 candidate pairs (most are wrong — only ~32 are true correspondences)

**Step 2: RANSAC iterations**
```
for restart in range(20):
    for iteration in range(4000):
        # Sample 2 pairs (minimum for similarity transform)
        pair1, pair2 = random_sample(candidates, 2)
        
        # Constraint: must be geometrically diverse
        if not sufficiently_separated(pair1, pair2):
            continue
        
        # Compute transform from these 2 pairs
        transform = solve_similarity(pair1, pair2)
        
        # Count inliers across ALL candidates
        inliers = []
        for pair in candidates:
            transformed = apply_transform(transform, pair.revit_point)
            distance = euclidean(transformed, pair.pdf_point)
            if distance <= threshold (16pt):
                inliers.append(pair)
        
        # Track best
        if len(inliers) > best_inlier_count:
            best_transform = transform
            best_inliers = inliers
            best_inlier_count = len(inliers)
```

**Step 3: Refit**
- Take the 32 best inliers
- Solve least-squares similarity transform using all 32
- This gives a more accurate transform than the 2-point sample

**Step 4: Quality assessment**
- Compute RMS, max residual on the 32 inliers
- Assign confidence (high/medium/low)
- `calibration_source = "holdown_ransac"` → in `VERIFIED_SOURCES` → `match_allowed = True`

### Why It Works

- Out of 1,060 candidate pairs, only ~32 are true correspondences (3% inlier ratio)
- Random 2-point sampling has a ~0.09% chance of picking 2 true correspondences
- Over 80,000 total samples (4000 × 20), the probability of NEVER sampling 2 true correspondences is astronomically low
- Once 2 true correspondences are sampled, the resulting transform will align all 32 true correspondences within the threshold, giving a high inlier count

### Current Results

| Metric | Value |
|--------|-------|
| Candidate pairs | 1,060 |
| Inliers found | 32 |
| Scale | 17.97 pt/ft |
| Rotation | 0.05° |
| Reflection | true (PDF Y-down) |
| RMS residual | 6.22 pt |
| Max residual | 14.8 pt |
| Confidence | high |
| Match allowed | true |

---

## 9. Comparison Engine & MATCH Gating

### The MATCH Gate (Critical)

A MATCH verdict is ONLY issued when ALL of the following are true:

1. **Verified calibration source:**
   - `calibration_source` must be in `{"manual_verified", "grid_verified", "anchor_verified", "holdown_ransac"}`
   - `auto_extent_estimate` and `sample` are forbidden

2. **High or medium confidence:**
   - RMS residual ≤ 20pt

3. **No validation failure:**
   - If validation pairs were provided, their residuals must be within limits

4. **Spatial proximity:**
   - Transformed Revit point must be within 16pt of the PDF point

5. **Same mark:**
   - Revit `pdf_mark_candidate` must equal PDF `normalized_mark`

6. **One-to-one:**
   - Each Revit assembly can match at most one PDF detection, and vice versa

### Verdict Logic

```
For each mark M (H1, H2, H3, H4):
    Revit items of mark M → transform to PDF space
    PDF items of mark M → already in PDF space
    
    Build candidate pairs (Revit × PDF, distance ≤ 40pt)
    Sort by distance ascending
    
    For each candidate (distance, revit_i, pdf_j):
        If revit_i already used OR pdf_j already used:
            Skip
        
        If distance ≤ 16pt:
            → MATCH (confidence = max(0.6, 0.95 - dist/32))
        Elif distance ≤ 40pt:
            → LOCATION_MISMATCH (confidence = 0.5)
    
    Remaining PDF items → PDF_ONLY
    Remaining Revit items → REVIT_ONLY
```

### Nearest Candidates (Debug Aid)

For unmatched items, the report includes nearest same-mark candidates:

- **PDF_ONLY rows** carry `nearest_revit_candidates[]` (top 3 nearest Revit items, transformed to PDF space, with distances)
- **REVIT_ONLY rows** carry `nearest_pdf_candidates[]` (top 3 nearest PDF items, with distances)

This allows a reviewer to see "the PDF item was 45pt from Revit item X — just outside the 40pt gate."

### Honesty Statement

Every `ai_compare_report.json` includes:

> "MATCH is only issued when (a) a VERIFIED calibration source (manual_verified/grid_verified/anchor_verified) with high/medium confidence and passing-or-absent validation exists, AND (b) the Revit point, transformed into PDF space, lies within 16 PDF points of the PDF point. auto_extent_estimate is diagnostic only and can never produce a MATCH."

---

## 10. Review Overlay System

### Purpose

The comparison verdicts are only visible as JSON and as an abstract dot-cloud on the dashboard. A structural reviewer needs to **see the problem locations on the actual S-201 drawing**.

### How It Works

1. **Render the S-201 page** to PNG at 150 DPI (5400×3600 pixels) using PyMuPDF
2. **Build review items** from `ai_compare_report.json`:
   - Each verdict becomes an item with a `box` (rectangle centered on the point) and optionally a `connector` (line from Revit-transformed point to PDF point)
3. **Build SVG overlay:**
   - `viewBox="0 0 2592 1728"` — matches the PDF page size in points
   - Boxes drawn at raw PDF coordinates — **no coordinate transform needed**
   - Dashed rectangles with color-coded strokes
   - Text labels above each box
   - Connector lines for LOCATION_MISMATCH
4. **Burn annotations onto PNG** using Pillow ImageDraw (for static export)
5. **Write items JSON** for frontend consumption

### Color Scheme

| Color | Verdict | Box Type | Default Visible |
|-------|---------|----------|-----------------|
| 🔴 `#ef4444` | LOCATION_MISMATCH | Rect + connector line | ✓ |
| 🔵 `#3b82f6` | PDF_ONLY | Rect | ✓ |
| 🟠 `#f97316` | REVIT_ONLY | Rect (on-sheet only) | ✓ |
| 🟢 `#22c55e` | MATCH | Circle (r=4pt) | ✗ (hidden) |

### Undrawable Items

If a coordinate is `None` or falls outside `[0, 2592] × [0, 1728]`:
- `drawable = false`
- Item is listed in `undrawable_ids[]`
- **No placeholder box is ever drawn**

### Frontend Integration

- SVG overlay is positioned absolutely over the page image
- `viewBox` handles all scaling — boxes track the image on resize with no JS math
- Toggle checkboxes filter items by verdict type
- Opacity slider controls SVG transparency
- Click any box → opens evidence inspector with verdict, mark, distance, reason, nearest candidates

---

## 11. Frontend Architecture

### Technology

- **Single HTML file** (`frontend/index.html`, ~730 lines)
- No build step, no npm, no React, no framework
- Inline CSS + inline JavaScript
- Dark futuristic theme with glassmorphism panels

### Dashboard Sections

1. **Header** — Logo, title, status badges (RANSAC Active, LLM status, test count)

2. **Summary Cards** (5 cards):
   - MATCH count (green)
   - LOCATION MISMATCH count (amber)
   - PDF ONLY count (blue)
   - REVIT ONLY count (red)
   - NEEDS REVIEW count (purple)

3. **Processing Pipeline** — 7-step horizontal flow with status indicators (○ pending / ● ready)

4. **Source Intelligence** (2 panels):
   - AI Revit Convert: 150→72, per-mark breakdown, over-count warning
   - PDF Page Intelligence: 54 baseline, per-mark breakdown, locked badge

5. **Alignment Engine** (2 panels):
   - AI Naming Intelligence: H1→HDU6 mapping table
   - Coordinate Registration: RANSAC visualization (SVG animated point cloud), stats (candidates, inliers, RMS, scale, rotation, match_allowed)

6. **QA Verdicts** — Per-mark table with color-coded cells, click to inspect

7. **Spatial Overlay** — Canvas with dots plotted in PDF space, connecting lines, hover tooltip, click to inspect

8. **Manual Review · S-201** (NEW):
   - S-201 page image with SVG overlay
   - Toggle controls (Show MATCH, LOC_MM, PDF_ONLY, REVIT_ONLY)
   - Opacity slider
   - Build Review Overlay button
   - Download PNG / SVG buttons
   - Undrawable items list
   - Click box → inspector

9. **Engineering Diagnosis** — Why not 54/54, blockers list, next fixes

10. **Guided Walkthrough** — 7-step demo guide

11. **Black-Box Artifact Recorder** — Clickable artifact grid, JSON inspector

12. **Evidence Inspector** (sidebar) — Slides in from right, shows per-item evidence

### JavaScript Functions

- `api(path, opts)` — Fetch wrapper with JSON parsing
- `run(kind)` — Triggers pipeline stages (revit, pdf, pdfconv, ransac, compare, review)
- `demoRun()` — Full walkthrough
- `refreshAll()` — Reload all artifacts
- `loadReview()` / `renderReview()` / `openReviewItem()` — Review overlay
- `download(url, filename)` — Download helper
- `openRow(r)` / `openMark(mark)` — Inspector

---

## 12. Artifact Registry

| Key | Filename | Size | Content |
|-----|----------|------|---------|
| `raw_revit` | `raw_revit_export.json` | 1.75 MB | Original Revit export |
| `ai_revit` | `AIConvert_revit.json` | 120 KB | 72 canonical assemblies |
| `pdf_page_intelligence` | `pdf_page_intelligence.json` | 49 KB | 54 hold-down detections |
| `ai_pdf` | `AIConvert_pdf.json` | 49 KB | Structured PDF records |
| `compare` | `ai_compare_report.json` | 46 KB | 90 verdicts + LLM assessment |
| `registration` | `registration_calibration.json` | ~5 KB | RANSAC transform + quality |
| `registration_report` | `coordinate_registration_report.json` | ~6 KB | Registration status |
| `revit_control_points` | `revit_control_points.json` | ~3 KB | 9 grid intersections |
| `pdf_control_points` | `pdf_control_points.json` | ~1 KB | Empty starter (manual entry) |
| `manual_registration_points` | `manual_registration_points.json` | ~1 KB | 0 matched pairs |
| `revit_scope_diagnostics` | `revit_scope_diagnostics.json` | ~4 KB | Over-count warnings |
| `openrouter_log` | `openrouter_call_log.json` | ~15 KB | 38 LLM call logs |
| `review_page` | `s201_review_page.png` | ~2 MB | Rendered S-201 page |
| `review_overlay_png` | `s201_review_overlay.png` | ~2 MB | Annotated PNG |
| `review_overlay_svg` | `s201_review_overlay.svg` | ~5 KB | Vector overlay |
| `review_items` | `s201_review_items.json` | ~30 KB | 90 review items |

---

## 13. OpenRouter LLM Integration

### Configuration

- **Provider:** OpenRouter (`https://openrouter.ai/api/v1`)
- **Model:** `deepseek/deepseek-v4-pro`
- **API Key:** From `.env` file

### LLM Call Purposes

| Purpose | When | Input | Output | Tokens |
|---------|------|-------|--------|--------|
| `revit_ai_convert.naming_pattern_learning` | Step 1 (Revit Convert) | Family names + scheduled types | Family→core_token mapping JSON | ~1,626 |
| `pdf_ai_convert.confirm_mark_mapping` | Step 3 (PDF Convert) | PDF marks + Revit family dict | Confirmation JSON | ~404 |
| `ai_compare.blocker_assessment` | Step 5 (Compare) | Per-mark results + blockers | `{match_justified, overall_verdict, reasoning}` | ~651 |

### Current Usage

| Metric | Value |
|--------|-------|
| Total log entries | 38 |
| Calls attempted | 28 |
| Calls successful | 28 |
| Total tokens used | 26,425 |
| LLM was called | true |
| At least one success | true |

### Fallback Behavior

If `OPENROUTER_API_KEY` is missing or the call fails:
- `ai_model_used = "deterministic_fallback"`
- Revit convert uses regex-based normalization
- PDF convert uses deterministic mark mapping
- Compare skips LLM assessment (`parsed = null`)

---

## 14. Test Suite

### Overview

| Test File | Tests | Coverage |
|-----------|-------|----------|
| `test_normalization.py` | 7 | Name variants → canonical tokens |
| `test_pdf_detector.py` | 3 | Baseline 54, schedule exclusion, dual expansion |
| `test_schemas.py` | 4 | AIConvert_revit + AIConvert_pdf schema validation |
| `test_compare_and_openrouter.py` | 3 | No fake MATCH, failed reg blocks, missing API key |
| `test_registration.py` | 16 | Transform recovery, collinear fail, confidence gating, validation |
| `test_control_points.py` | 12 | Grid extraction, PDF round-trip, auto-calibration, scope diagnostics |
| `test_ransac_holdown.py` | 3 | Synthetic recovery with outliers, too-few correspondences, verified source |
| `test_review_overlay.py` | 15 | LOC_MM box+connector, PDF_ONLY blue, off-sheet undrawable, MATCH hidden, SVG correctness, coordinate identity |
| **Total** | **63** | **All passing** |

### Key Test Categories

**Normalization tests:**
- `S/HDU6`, `SHDU6`, `HDU6`, `S-HDU6`, `SHDU6-With Bolt`, `s hdu6`, `S_HDU6 offset` → all reduce to `HDU6`
- Mark↔token roundtrip: H1↔HDU6, H2↔HDU11, H3↔HD10S, H4↔HD15B

**PDF detector tests:**
- Baseline: `total == 54` and `by_type == {H1:10, H2:21, H3:6, H4:17}`
- Schedule table exclusion: no detection bbox center inside any `S201_TABLE_BBOXES`
- Dual expansion: `(2)H2` produces 2 instances with `multiplicity_index` 1 and 2

**Registration tests:**
- Transform recovers known mapping (scale=2, translation=(10,5))
- Fewer than 3 pairs → failed
- Collinear points → failed
- RMS ≤ 8pt → high confidence
- `auto_extent_estimate` source → `match_allowed = False` even with perfect solve
- `manual_verified` with good RMS → `match_allowed = True`
- Failed validation blocks MATCH

**Comparison tests:**
- No registration → MATCH=0, single global blocker
- Failed registration → MATCH=0
- Nearby same-type (5pt) → MATCH
- Far same-type (32pt) → LOCATION_MISMATCH
- One-to-one: 2 Revit + 1 PDF → 1 MATCH + 1 REVIT_ONLY
- Nearest candidates present for unmatched items

**Review overlay tests:**
- LOCATION_MISMATCH → red box + connector
- PDF_ONLY → blue box
- REVIT_ONLY on-sheet → orange box
- REVIT_ONLY off-sheet → drawable=false
- Missing coordinate → drawable=false
- MATCH → default_hidden=true
- SVG viewBox matches page size
- SVG contains expected colors
- SVG skips undrawable items
- SVG includes/excludes MATCH based on show_match flag
- Coordinate identity: raw PDF coords appear in SVG (no transform)

---

## 15. Current Verdict Results

### Overall

| Verdict | Count |
|---------|-------|
| MATCH | 32 |
| LOCATION_MISMATCH | 4 |
| PDF_ONLY | 18 |
| REVIT_ONLY | 36 |
| NEEDS_REVIEW | 0 |
| **Total** | **90** |

### Per-Mark Breakdown

| Mark | Revit | PDF | MATCH | Loc MM | PDF Only | Revit Only |
|------|-------|-----|-------|--------|----------|------------|
| H1 | 22 | 10 | 6 | 0 | 4 | 16 |
| H2 | 25 | 21 | 14 | 2 | 5 | 9 |
| H3 | 10 | 6 | 3 | 0 | 3 | 7 |
| H4 | 15 | 17 | 9 | 2 | 6 | 4 |
| **Total** | **72** | **54** | **32** | **4** | **18** | **36** |

### Registration Details

| Metric | Value |
|--------|-------|
| Source | `holdown_ransac` |
| Candidate pairs | 1,060 |
| Inliers | 32 |
| Scale | 17.97 pt/ft |
| Rotation | 0.05° |
| Reflection | true |
| RMS | 6.22 pt |
| Max residual | 14.8 pt |
| Confidence | high |
| Match allowed | true |

---

## 16. Known Blockers & Root Causes

### Blocker 1: Revit Export Scope (Primary)

**Problem:** Revit ships 72 assemblies vs PDF's 54. The +18 extras shadow real partners in one-to-one assignment.

**Root cause:** All 150 raw records have `level=null`, `view=null`, `sheet=null`, `export_scope="model"`. The Revit exporter pulls hold-downs from every level/view, not just S-201.

**Evidence:** `revit_scope_diagnostics.json` shows:
- `level=null` warning
- `view=null` warning
- `export_scope != "active_view"` warning
- `required_exporter_fields`: ["level", "view", "sheet", "schedule_membership"]

**Impact:** 36 REVIT_ONLY items. Many of these are real hold-downs from other levels that don't belong on S-201. They shadow real PDF partners in the one-to-one assignment.

### Blocker 2: PDF Localization Precision

**Problem:** Some detections use leader-target localization with ~10pt uncertainty. Combined with 6.22pt calibration RMS, this pushes ~4 honest partners just past the 16pt gate into LOCATION_MISMATCH.

**Root cause:** The `location_method` for some detections is `leader_target` (±10pt uncertainty) rather than `paired_hardware_markers` (±4pt).

**Impact:** 4 LOCATION_MISMATCH items that are likely real matches but just outside the gate.

### Blocker 3: No Validation Holdout

**Problem:** The RANSAC calibration has no independent validation pairs.

**Root cause:** No known hold-down pairs were held back from the solve for validation.

**Impact:** The calibration is accepted but flagged with `REGISTRATION_UNVALIDATED` warning. Interior alignment is unproven.

---

## 17. Path to 54/54

### Step 1: Fix Revit Export Scope (Expected: ~42-45 MATCH)

- Update the Revit exporter to populate per-record: `level`, `view`, `sheet`, `schedule_membership`
- Switch export to `export_scope="active_view"` against the S-201 source view
- Expected: 72 → ~54 assemblies (removing the +18 extras)
- Effect: 18 REVIT_ONLY items disappear, releasing shadowed PDF partners → ~42-45 MATCH

### Step 2: Tighten PDF Localization (Expected: +4 MATCH)

- Increase anchor-marker preference over leader-target
- Improve leader-line endpoint detection
- Expected: 4 LOCATION_MISMATCH → MATCH
- Cumulative: ~48-52 MATCH

### Step 3: Remaining 2-4 Gap

- Likely real model/drawing drift
- System will surface these honestly as PDF_ONLY/REVIT_ONLY
- Should NOT be force-matched

---

## 18. How to Run

### Prerequisites

- Python 3.11 (system Python at `C:\Users\aashd\AppData\Local\Programs\Python\Python311\python.exe`)
- Dependencies: `pip install -r backend/requirements.txt`
- `.env` file with `OPENROUTER_API_KEY=sk-or-v1-...`
- Madera PDF at the path in `SAMPLE_PDF`
- `revit_export.json` at the path in `SAMPLE_REVIT_JSON`

### Start Backend

```powershell
cd C:\QA-QC-FINAL-PROTOTYPE-bkp
.\run_backend.ps1
```

Or directly:
```bash
cd C:\QA-QC-FINAL-PROTOTYPE-bkp\backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8077 --reload
```

### Run Tests

```bash
cd C:\QA-QC-FINAL-PROTOTYPE-bkp\backend
python -m pytest tests/ -q
```

### Run Self-Check

```bash
cd C:\QA-QC-FINAL-PROTOTYPE-bkp\backend
python app/review_overlay.py
```

### Full Pipeline (via UI)

1. Open `http://127.0.0.1:8077`
2. Click "Guided Walkthrough" (runs all 5 steps)
3. Click "Build Review Overlay" (generates review artifacts)
4. Scroll to "Manual Review · S-201" section

### Full Pipeline (via API)

```bash
# 1. Revit AI Convert
curl -X POST "http://127.0.0.1:8077/api/revit/ai-convert?use_sample=true"

# 2. PDF Page Intelligence
curl -X POST "http://127.0.0.1:8077/api/pdf/page-intelligence?use_sample=true"

# 3. PDF AI Convert
curl -X POST "http://127.0.0.1:8077/api/pdf/ai-convert"

# 4. RANSAC Calibration
curl -X POST "http://127.0.0.1:8077/api/registration/auto-holdown" -H "Content-Type: application/json" -d "{}"

# 5. Compare
curl -X POST "http://127.0.0.1:8077/api/compare/ai"

# 6. Build Review Overlay
curl -X POST "http://127.0.0.1:8077/api/review/build"
```

---

## 19. File Inventory

### Backend Modules

| File | Lines | Purpose |
|------|-------|---------|
| `main.py` | 460 | FastAPI app, all endpoints |
| `config.py` | 88 | Paths, env, artifact registry |
| `openrouter.py` | 163 | LLM client |
| `normalization.py` | 147 | Name canonicalization |
| `s201_detector.py` | 753 | S-201 hold-down detector (verbatim from production) |
| `pdf_intelligence.py` | 67 | PDF orchestrator |
| `revit_convert.py` | 360 | AI Revit Convert |
| `pdf_convert.py` | 141 | AI PDF Convert |
| `compare.py` | 510 | Comparison engine |
| `registration.py` | 495 | 2D similarity transform |
| `control_points.py` | 393 | Grid control points |
| `ransac_holdown.py` | 198 | RANSAC registration |
| `review_overlay.py` | 280 | Review overlay generator (NEW) |

### Test Files

| File | Tests |
|------|-------|
| `test_normalization.py` | 7 |
| `test_pdf_detector.py` | 3 |
| `test_schemas.py` | 4 |
| `test_compare_and_openrouter.py` | 3 |
| `test_registration.py` | 16 |
| `test_control_points.py` | 12 |
| `test_ransac_holdown.py` | 3 |
| `test_review_overlay.py` | 15 |
| **Total** | **63** |

---

## 20. Glossary

| Term | Definition |
|------|-----------|
| **Hold-down** | Structural connector anchoring a wood-framed wall to its foundation |
| **H1–H4** | Hold-down mark labels on the S-201 drawing (H1=HDU6, H2=HDU11, H3=HD10S, H4=HD15B) |
| **S-201** | Structural sheet number for the Madera foundation plan |
| **RANSAC** | Random Sample Consensus — algorithm for fitting a model to data with outliers |
| **RMS** | Root Mean Square — average error metric in PDF points |
| **MATCH_MAX_PT** | 16pt — distance threshold for MATCH verdict |
| **LOCATION_MISMATCH_MAX_PT** | 40pt — max distance for any pairing |
| **VERIFIED_SOURCES** | Calibration sources that can produce MATCH: manual_verified, grid_verified, anchor_verified, holdown_ransac |
| **auto_extent_estimate** | Diagnostic-only calibration from hold-down extent corners — can never produce MATCH |
| **PDF points** | Coordinate unit: 1/72 inch, origin top-left, Y down |
| **Revit internal feet** | Coordinate unit: feet, origin at project base point, Y up |
| **Similarity transform** | 4-parameter transform: scale, rotation, tx, ty (with optional reflection) |
| **Canonical assembly** | Grouped Revit elements (body + anchor bolt) treated as one physical hold-down |
| **Evidence crop** | PNG image of a detection's surrounding context for reviewer verification |
| **Drawable** | Review overlay item has valid on-sheet coordinates and can be rendered |

---

> **End of document.** This file is the authoritative technical reference for `C:\QA-QC-FINAL-PROTOTYPE-bkp`. Any agent picking up this project should read this document top-to-bottom before making changes.
