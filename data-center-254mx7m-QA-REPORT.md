# QA Report — Generic Pipeline Test on New Project `data-center-254mx7m`
Date: 2026-08-07 · Backend: http://127.0.0.1:8077 · PDF: "Data center-254mx7m- Structural permit set.pdf" (4.6 MB)

## Ground truth (independent fitz scan of the PDF)
- 17 pages. Sheets: S-101 (cover), S-102 (gen. notes), **S-201-A/B/C (FOUNDATION PLANS + FOOTING SCHEDULE)**, S-202-A/B/C (wall framing + SHEAR WALL SCHEDULE), S-203-A/B/C (roof framing), S-204-A/B, S-301 (foundation details), S-401/S-402 (typical details), S-501 (wall-to-wall).
- Real mark vocabulary (counts): **H2×83, H1×43, P3×39, P1×11, P2×7**, PSF×11, HD15S×3, SW-1×3, F1554×9 (anchor spec, not a mark), C-part-numbers.
- Schedules present: FOOTING SCHEDULE (pp.3–5), SHEAR WALL SCHEDULE (pp.6–8, 15).

## Per-step results

| Step | Endpoint | Verdict |
|---|---|---|
| Upload | POST /api/upload?project=data-center-254mx7m | **PASS** |
| Element extraction | POST /api/elements/extract | **FAIL** |
| Page intelligence | POST /api/pdf/page-intelligence?use_saved=true | **FAIL** (fallback path correct) |
| PDF AI convert | POST /api/pdf/ai-convert | **FAIL** + Madera leakage |

### 1. Upload — PASS
Manifest: 17 pages, correct filename, workspace `artifacts/projects/data-center-254mx7m/` created. PDF only; no Revit JSON ingested (no sample-export contamination).

### 2. Element extraction — FAIL
- HTTP 200 in 0.6 s, `source_file` = this project's PDF (no wrong-file leakage).
- **Only 5 of ~16 sheets kept**: S-101, S-301, S-401, S-402, S-501 (cover + detail sheets). **All 12 plan/notes pages dropped.**
- **Root cause (proven)**: `element_detector.py:38` `SHEET_NUMBER_RE = ^[A-Z]{1,3}-?\d{1,3}(?:\.\d{1,2})?$` rejects letter-suffixed sheet numbers. Regex test: `S-201-A → no match`, `S-301 → match`. Pages with no sheet number are skipped with all their tables and marks.
- Marks extracted: **1 total** (`marks_by_category: {post: 1}`). Vocabulary learned: `{post:[P1], wall_type:["1"], holdown:[H2]}` — vs. real vocab H1/H2/P1/P2/P3/SW-1. `wall_type:["1"]` is spurious garbage.
- Schedule discovery: **missed both real schedules** (they live on the dropped S-201-A..C / S-202-A..C sheets). Surviving "tables" are junk: empty columns/rows, header texts like "@BOTTOM PER SCHEDULE".
- `applied_memory_rules: 3` — **global teach memory from other projects** (HD3→H3 alias ×2 from country-side-ct, drafting notes from madera) was applied to this fresh project. No token collision this time (no HD3 in this PDF), but the cross-project application is a design risk.

### 3. Page intelligence — FAIL (mechanics correct)
- Frozen S-201 detector errored (this set's foundation sheets are `S-201-A/B/C`, not literal `S-201`) → generic fallback engaged (`intelligence_source: "generic"`). Fallback wiring works as designed.
- Generic detector then failed: `"No sheet with hold-down plan marks found by extraction. Teach the AI this client's hold-down convention, then re-run Extract."` — pure cascade from step 2. `sheet_number: null`, holdowns: 0.
- API footgun: without `use_saved=true` the endpoint runs ONLY the frozen S-201 detector; the generic path is unreachable via the direct-upload branch.

### 4. PDF AI convert — FAIL + MADERA LEAKAGE
- 0 holdowns, `source_sheet: "unknown"`, `used_revit_memory: false` (clean).
- **Leakage**: saved artifact contains `mark_to_core_token: {"H1":"HDU6","H2":"HDU11","H3":"HD10S","H4":"HD15B"}` — Madera's mapping. This project has NO H3/H4 marks. Source: `normalization.py:36-41` — comment says verbatim *"Falls back to the original Madera mapping when no project config exists"*. It is the global default for every new project.
- The LLM call (deepseek-v4-pro, 350 tokens, $0.0008) was asked to "confirm" that Madera mapping and echoed it back — confident garbage, paid for.

## Madera / hardcoding leakage inventory (code-confirmed)
1. `normalization.py:36-41` — Madera H1-H4↔HDU table is the global fallback (active leak, hit in this run).
2. `revit_convert.py:97–133` — LLM prompts cite HDU6/HDU11/HD10S/HD15B as examples (would bias any project's Revit-side conversion).
3. `s201_detector.py:70–78` — frozen Madera path (documented as intentional; kept as default).
4. Global teach memory (`memory_path() = MEMORY_DIR/global.json`, scope "global") applies other projects' rules to new projects.
5. `page-intelligence` default branch is frozen-S-201-only.

## What did NOT leak
- Extraction ran on the correct uploaded PDF; no Madera sheet content, marks, or artifacts in the data-center workspace.
- No sample/old Revit export was used (none exists in the new workspace; `used_revit_memory: false`).

## .rvt limitation
The 173 MB .rvt cannot be processed directly (binary Revit format) — the QA-QC exporter must run inside Revit to produce the Revit JSON. This is the one pipeline side that requires the user's Revit session.

## Verdict
The generic pipeline does **not** yet work end-to-end on a new project. Primary blocker: sheet-number regex (letter-suffixed sheets) — a one-pattern fix (`-?[A-Z]?` suffix group) that should restore plan sheets, schedule discovery, vocabulary learning, and downstream steps. Secondary: eliminate/guard the Madera fallback mapping and HDU prompt hints before deployment.
