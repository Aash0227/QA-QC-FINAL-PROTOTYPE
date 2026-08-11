# Backend Deep-Read Report — `backend/app/`

**Generated**: 2026-08-06  
**Scope**: 33 core Python modules, ~380 KB total  
**Purpose**: Structured per-file analysis for ponytail audit

---

## Table of Contents
1. [main.py](#1-mainpy)
2. [config.py](#2-configpy)
3. [compare.py](#3-comparepy)
4. [registration.py](#4-registrationpy)
5. [device_match.py](#5-device_matchpy)
6. [wall_match.py](#6-wall_matchpy)
7. [review.py](#7-reviewpy)
8. [review_overlay.py](#8-review_overlaypy)
9. [pdf_convert.py](#9-pdf_convertpy)
10. [pdf_intelligence.py](#10-pdf_intelligencepy)
11. [revit_convert.py](#11-revit_convertpy)
12. [revit_v3_adapter.py](#12-revit_v3_adapterpy)
13. [element_registry.py](#13-element_registrypy)
14. [element_detector.py](#14-element_detectorpy)
15. [ransac_holdown.py](#15-ransac_holdownpy)
16. [leader_anchor.py](#16-leader_anchorpy)
17. [s201_detector.py](#17-s201_detectorpy)
18. [normalization.py](#18-normalizationpy)
19. [schedule_tables.py](#19-schedule_tablespy)
20. [scene3d.py](#20-scene3dpy)
21. [teach.py](#21-teachpy)
22. [chat_agent.py](#22-chat_agentpy)
23. [openrouter.py](#23-openrouterpy)
24. [benchmarks.py](#24-benchmarkspy)
25. [benchmark_workflow.py](#25-benchmark_workflowpy)
26. [control_points.py](#26-control_pointspy)
27. [export_watch.py](#27-export_watchpy)
28. [generic_page_intelligence.py](#28-generic_page_intelligencepy)
29. [phase_summary.py](#29-phase_summarypy)
30. [progress.py](#30-progresspy)
31. [maintenance.py](#31-maintenancepy)
32. [revit_bridge.py](#32-revit_bridgepy)
33. [revit_ids.py](#33-revit_idspy)
34. [Ponytail Audit Summary](#ponytail-audit-summary)

---

## 1. main.py
**Purpose**: FastAPI app assembly — thin orchestrator that builds the app, installs middleware (auth + progress), registers routers, mounts frontend.

**Key Functions/Classes**:
- `create_app()` → builds FastAPI with auth middleware + progress middleware
- `_step_headline(step)` → reads artifact to produce one-line summary per pipeline step
- Re-exports at bottom for test-suite backward compatibility

**Dependencies**: `config`, `maintenance`, `progress`, `routers.*`

**Data Flow**:
- Reads: artifacts via `load_artifact()` for progress headlines
- Writes: nothing directly (delegates to routers)

**Ponytail Findings**:
- None — genuinely thin, appropriate delegation

---

## 2. config.py
**Purpose**: Central configuration — paths, project scoping via ContextVar, artifact file map, OpenRouter config, .env loader, legacy migration.

**Key Functions/Classes**:
- `slugify(name)` → filesystem-safe project slug
- `active_project()` → reads persisted active project preference
- `bind_project(slug)` → per-request ContextVar project binding
- `set_active_project(slug)` → bind + persist preference
- `artifact_path(key)` → resolved path for a named artifact
- `memory_path()` → cross-project teach memory path
- `sheet_calibration_path(sheet)` → per-sheet calibration artifact
- `_load_dotenv()` → minimal .env loader (stdlib only)
- `openrouter_config_status()` → health-check dict

**Dependencies**: `os`, `json`, `pathlib`, `contextvars`, `threading`

**Data Flow**:
- Reads: `.env`, `active_project.json`, env vars
- Writes: `active_project.json` (persisted preference)

**Ponytail Findings**:
- `_dir()` helper is a one-line `getattr(sys.modules[__name__], name)` — trivial wrapper but needed for monkeypatch-shadow semantics. Acceptable.
- `_migrate_legacy_layout()` runs at import time — side-effect at module load, but guarded by marker file.

---

## 3. compare.py
**Purpose**: Core comparison engine — matches Revit hold-down assemblies against PDF detections using registered coordinates. Produces verdicts (MATCH/PDF_ONLY/REVIT_ONLY/LOCATION_MISMATCH/NEEDS_REVIEW).

**Key Functions/Classes**:
- `compare(ai_revit, ai_pdf, calibration)` → main entrypoint, returns full report
- `_match_with_location(...)` → location-aware matching using transform matrix
- `_match_type_only(...)` → fallback when no registration available
- `_group_revit(ai_revit)` → groups assemblies by pdf_mark_candidate
- `_group_pdf(ai_pdf)` → groups holdowns by normalized_mark
- `_nearest_revit_candidates(...)` / `_nearest_pdf_candidates(...)` → debug helpers
- `_llm_assessment(...)` → OpenRouter advisory call
- `_revit_count_diagnostics(ai_revit)` → display-only over-count analysis
- `_project_pdf_baseline()` → reads expected counts from pdf_page_intelligence

**Dependencies**: `openrouter`, `registration`, `config` (local import)

**Data Flow**:
- Reads: `AIConvert_revit.json`, `AIConvert_pdf.json`, `registration_calibration.json`, `pdf_page_intelligence.json`
- Writes: `ai_compare_report.json` (via caller)

**Ponytail Findings**:
- `_verdict_counts_template()` is a one-line dict comprehension — trivial but used in 2 places. Acceptable.
- `_xy()` is a 7-line null-safe coordinate extractor — used ~8 times. Justified.
- `_project_pdf_baseline()` does a local import of `config` to avoid a module-level dep — comment explains why. Fine.

---

## 4. registration.py
**Purpose**: Coordinate registration — computes Revit→PDF similarity transforms from point pairs (manual, grid, RANSAC, benchmark). Gates whether MATCH verdicts are allowed.

**Key Functions/Classes**:
- `compute_calibration(point_pairs, source, validation_pairs)` → main solve from manual pairs
- `compute_calibration_from_benchmarks(...)` → exact 2-point solve from BM-1/BM-2
- `apply_transform(matrix, x, y)` → affine transform application
- `_fit_variant(src, dst, reflect)` → least-squares 2D similarity via complex numbers
- `_is_collinear(points)` → rank-deficiency check
- `_invert_matrix(matrix)` → 6-element affine inverse
- `registration_usable(calibration)` → MATCH gate check
- `registration_status(calibration)` → coarse status string
- `save_calibration()` / `load_calibration()` / `delete_calibration()` → persistence
- `build_registration_report(calibration)` → human-readable report
- `save_registration_report(calibration)` → persist report

**Dependencies**: `config`, `math`, `json`

**Data Flow**:
- Reads: point pairs (from API or RANSAC)
- Writes: `registration_calibration.json`, `coordinate_registration_report.json`

**Ponytail Findings**:
- `_fit_variant` is a 40-line complex-number least-squares solver — hand-rolled but mathematically correct and self-contained. No numpy needed for 2D similarity.
- Legacy aliases (`rms_residual_pt`, `reason`) kept alongside new keys (`solve_rms_residual_pt`, `confidence_reason`) — documented as backward compat.
- `build_registration_report` + `save_registration_report` could be one function but separation is clean.

---

## 5. device_match.py
**Purpose**: Physical-device matching layer — inverse-projects PDF callouts to model space, clusters same-mark points across sheets into physical devices, does global one-to-one assignment against Revit assemblies.

**Key Functions/Classes**:
- `run(element_rows, calibrations, assemblies, walls)` → full device pass
- `build_devices(rows, inverse_by_sheet, prefix)` → cluster sheet callouts into devices
- `assign(devices, targets, distance, ...)` → greedy one-to-one assignment
- `inverse_from_calibration(cal)` → exact inverse from stored matrix
- `fit_inverse(point_pairs)` → fallback inverse fit (needs ≥3 pairs)
- `point_distance(d, t)` / `segment_distance(d, t)` → geometry helpers
- `sw_token(text)` → extract SW-N token from wall type name

**Dependencies**: `math`, `re`, `collections.Counter`

**Data Flow**:
- Reads: element rows, per-sheet calibrations, Revit assemblies, walls
- Writes: `device_registry.json` (via caller)

**Ponytail Findings**:
- `__main__` block has ~80 lines of self-checks — thorough but could be pytest. Acceptable for prototype.
- `_annotate_reasons()` appends tails to reasons without touching status — clean separation.
- `row_z_ft()` is dormant (no rows carry elevation today) but plumbing is ready.

---

## 6. wall_match.py
**Purpose**: Shear-wall matching — PDF SW-x callouts vs Revit wall centerlines using point-to-segment distance. Handles leader-line anchor correction.

**Key Functions/Classes**:
- `match_shear_walls(sheet_marks, revit_walls, calibration, leader_segments)` → greedy one-to-one SW matching
- `extract_leader_segments(page)` → straight vector segments sized like leaders
- `leader_tips(anchor, segments)` → far endpoints of segments starting at bubble
- `sw_token(type_name)` → normalize 'SW1' / 'SW-2' → 'SW-1' / 'SW-2'
- `point_to_segment_distance(p, a, b)` → clamped-projection distance

**Dependencies**: `registration` (for `registration_usable`, `apply_transform`), `math`, `re`, `fitz`

**Data Flow**:
- Reads: element intelligence marks, Revit walls, calibration, PDF page (for leaders)
- Writes: per-sheet wall-match report (consumed by element_registry)

**Ponytail Findings**:
- `point_to_segment_distance` duplicates `device_match.segment_distance` conceptually but operates on raw tuples vs dict. Minor duplication.
- `__main__` self-check is ~50 lines — thorough.

---

## 7. review.py
**Purpose**: Human-review workspace — review queue, comments (fed to teach engine), dispositions, evidence crops, v2 analysis/evaluate/resolve flow for LOCATION_MISMATCH devices.

**Key Functions/Classes**:
- `add_comment(element, comment, author)` → store comment + run teach
- `set_disposition(element_id, disposition)` → confirmed-issue/false-alarm/fixed-in-model
- `build_queue(element_list)` → all elements needing review
- `render_evidence_crop(...)` → PNG crop with PDF+Revit rings + gap line
- `analyze(element_id, element_list, registry)` → deterministic mismatch analysis
- `evaluate(element_id, comment, analysis)` → LLM judges reviewer's logic
- `resolve(element_id, action, comment, ...)` → apply human decision
- `apply_stored_resolutions(element_list, registry)` → re-apply prior accepts

**Dependencies**: `config`, `teach`, `openrouter`, `math`, `fitz`

**Data Flow**:
- Reads: `element_list.json`, `device_registry.json`, `review_comments.json`
- Writes: `review_comments.json`

**Ponytail Findings**:
- `__main__` block is ~50 lines of sandboxed self-check — good.
- `evaluate()` falls back to deterministic facts when LLM unavailable — honest.

---

## 8. review_overlay.py
**Purpose**: S-201 manual-review overlay generator — renders PDF page with discrepancy overlays (red/blue/orange/green boxes + connectors).

**Key Functions/Classes**:
- `render_s201_page_png(pdf_path, page_index, out_path, dpi)` → full page to PNG
- `build_review_items(compare_report, page_w, page_h)` → per-verdict overlay specs
- `build_overlay_svg(items_payload, show_match)` → SVG overlay string
- `render_annotated_png(page_png, items_payload, out_path)` → burn overlays onto PNG
- `build_and_save(compare_report, pdf_path, page_index, artifact_dir)` → full orchestrator

**Dependencies**: `fitz`, `PIL`, `json`

**Data Flow**:
- Reads: compare report, source PDF
- Writes: `s201_review_page.png`, `s201_review_overlay.svg`, `s201_review_overlay.png`, `s201_review_items.json`

**Ponytail Findings**:
- `_make_box()` is a 6-line dict builder — used 3 times. Fine.
- `__main__` self-check is ~80 lines with synthetic data — thorough.
- Hardcoded color constants (RED/BLUE/ORANGE/GREEN) — fine for this scope.

---

## 9. pdf_convert.py
**Purpose**: PDF AI conversion — enriches page-intelligence detections with LLM-confirmed mark→core-token mapping, produces AIConvert_pdf.json.

**Key Functions/Classes**:
- `convert_pdf(page_intelligence, revit_ai_memory)` → main entrypoint
- `_llm_confirm_mapping(revit_ai_memory)` → OpenRouter call to confirm mapping

**Dependencies**: `openrouter`, `normalization`

**Data Flow**:
- Reads: `pdf_page_intelligence.json`, `AIConvert_revit.json` (optional)
- Writes: `AIConvert_pdf.json` (via caller)

**Ponytail Findings**:
- `MARK_TO_CORE_TOKEN` is hardcoded to Madera {H1:HDU6, H2:HDU11, H3:HD10S, H4:HD15B} — **ponytail: hardcoded client vocabulary**. The generic path (revit_v3_adapter) is data-driven; this legacy path is not.
- `_llm_confirm_mapping` calls LLM just to confirm a deterministic mapping — the LLM result is never authoritative. **ponytail: YAGNI / theater** — the deterministic mapping is already correct; the LLM call adds latency and cost for a confirmation that's ignored.

---

## 10. pdf_intelligence.py
**Purpose**: S-201 focused page intelligence — locates the S-201 foundation plan page, runs the focused holdown detector, produces pdf_page_intelligence.json.

**Key Functions/Classes**:
- `run_page_intelligence(pdf_path)` → main entrypoint

**Dependencies**: `config`, `s201_detector`

**Data Flow**:
- Reads: source PDF
- Writes: `pdf_page_intelligence.json` (via caller)

**Ponytail Findings**:
- `baseline = {"H1": 10, "H2": 21, "H3": 6, "H4": 17}` is **hardcoded Madera-specific** — **ponytail: hardcoded client constants**. The generic path (`generic_page_intelligence.py`) correctly avoids this.
- Thin wrapper around `s201_detector` — appropriate.

---

## 11. revit_convert.py
**Purpose**: Revit AI conversion — classifies families into body/evidence_member, groups into canonical assemblies, calls LLM for naming-pattern learning.

**Key Functions/Classes**:
- `convert_revit(raw_json, source_file)` → main entrypoint
- `_build_family_dictionary(records)` → family → core_token mapping
- `_learned_key_points(records, family_dict, raw_json)` → metadata block
- `_llm_enrichment(family_dict)` → OpenRouter naming-pattern call
- `_classify_family(family)` → body vs evidence_member

**Dependencies**: `openrouter`, `normalization`

**Data Flow**:
- Reads: `raw_revit_export.json`
- Writes: `AIConvert_revit.json` (via caller)

**Ponytail Findings**:
- `pdf_baseline = {"H1": 10, "H2": 21, "H3": 6, "H4": 17}` — **hardcoded Madera** — **ponytail: hardcoded client constants**.
- `_llm_enrichment` is called but its result is only used as cross-check (deterministic stays source of truth). **ponytail: LLM theater** — adds cost/latency for a result that's never authoritative.
- `MEMBER_KEYWORDS` tuple and `_classify_family` are clean.

---

## 12. revit_v3_adapter.py
**Purpose**: Adapter for schema v3.x exports — converts v3 format to raw_revit-compatible dict and builds AIConvert_revit-compatible output using PDF schedule specs (data-driven, no hardcoded vocabulary).

**Key Functions/Classes**:
- `adapt_raw(v3)` → v3 export → raw_revit-compatible dict
- `build_ai_revit(v3, spec_to_mark)` → cluster hold-downs into assemblies with PDF-schedule-driven marks
- `holdown_variant_key(text)` → extract Simpson product key from family name
- `spec_to_mark_map(element_intelligence)` → variant key → plan mark from schedule rows
- `spec_map_from_pdf_tables(element_intelligence, pdf_path)` → fallback from PDF geometry
- `normalize_point_mark(mark)` → 'P-01' → 'P-1'
- `is_v3(raw)` → schema version check

**Dependencies**: `re`, `fitz` (for fallback), `datetime`

**Data Flow**:
- Reads: v3 export JSON, element_intelligence (for spec map), PDF (for fallback)
- Writes: nothing directly (returns dicts)

**Ponytail Findings**:
- Well-designed, data-driven — no hardcoded vocabulary. The "correct" generic path.
- `__main__` self-check is ~90 lines — thorough.
- `HOLDOWN_CATEGORIES` tuple is the only hardcoded list but it's a Revit category boundary, not client-specific.

---

## 13. element_registry.py
**Purpose**: Joins every extraction/matching output into one unified element list with honest statuses.

**Key Functions/Classes**:
- `build_element_list(element_intelligence, compare_report, wall_reports, ...)` → main builder
- `scope_warnings(device_summary, raw_revit)` → R-07: detect hidden categories
- `_holdown_element(row, sheet, page_index, vocab_specs)` → row builder
- `_vocab_specs(element_intelligence)` → (category, mark) → spec cells
- `_counts(elements)` → by_category/by_status/by_sheet

**Dependencies**: `datetime`

**Data Flow**:
- Reads: element_intelligence, compare_report, wall_reports, holdown_sheet_reports, point_reports
- Writes: `element_list.json` (via caller)

**Ponytail Findings**:
- Complex but honest — every status is derived from real pipeline outcomes.
- `NO_REVIT_CATEGORIES = ("post", "steel_column")` — hardcoded but documented as awaiting exporter support.

---

## 14. element_detector.py
**Purpose**: Generic multi-category element mark detector — two-pass scan (tables → vocabulary → plan marks) for any structural PDF.

**Key Functions/Classes**:
- `scan_pdf(pdf_path, overrides)` → full two-pass scan
- `detect_marks(words, vocab, table_bboxes, ...)` → plan-area mark instances
- `detect_sheet_number(words, page_width)` → title-block sheet detection
- `_category_for(token, vocab, overrides)` → classify token → (category, listed, mark, taught_by)
- `_count_consistency(marks, vocab)` → per-(category,mark) QA

**Dependencies**: `fitz`, `progress`, `schedule_tables`

**Data Flow**:
- Reads: source PDF
- Writes: `element_intelligence.json` (via caller)

**Ponytail Findings**:
- Well-generalized from s201_detector — no hardcoded vocabulary.
- `__main__` self-check is ~30 lines — adequate.

---

## 15. ransac_holdown.py
**Purpose**: Mark-constrained RANSAC similarity registration — uses same-mark hold-down correspondences to auto-calibrate when no manual points exist.

**Key Functions/Classes**:
- `ransac_calibrate(ai_revit, ai_pdf, ...)` → main entrypoint
- `_gather(records, mark_key)` → collect points by mark
- `_score(matrix, rev_by_mark, pdf_by_mark, threshold)` → count inliers

**Dependencies**: `registration`, `math`, `random`

**Data Flow**:
- Reads: `AIConvert_revit.json`, `AIConvert_pdf.json`
- Writes: `registration_calibration.json` (via registration.save_calibration)

**Ponytail Findings**:
- Multi-seed restarts (20 × 4000 iterations) — computationally heavy but documented as necessary for consensus space.
- Respects benchmark-verified precedence — won't downgrade.

---

## 16. leader_anchor.py
**Purpose**: Leader-dot anchor snap — re-anchors holdown callouts at their leader's target dot (the physical device location) instead of the label text.

**Key Functions/Classes**:
- `snap_holdowns(ai_pdf, pdf_path)` → re-anchor AIConvert_pdf holdowns
- `snap_element_marks(intel, pdf_path)` → same for element_intelligence marks
- `_page_vectors(page)` → extract dots + segments from vector layer
- `_snap_one(label, dots, segs)` → find the dot a leader connects to

**Dependencies**: `fitz`, `math`, `pathlib`

**Data Flow**:
- Reads: AIConvert_pdf or element_intelligence, source PDF vector layer
- Writes: mutates input dict in place

**Ponytail Findings**:
- Clean, focused module. No issues.
- `__main__` self-check creates a synthetic PDF — thorough.

---

## 17. s201_detector.py
**Purpose**: S-201 focused hold-down detector — the proven Madera-specific detector that reproduces the 54-baseline (H1=10, H2=21, H3=6, H4=17). Frozen.

**Key Functions/Classes**:
- `detect_s201_holdowns(pdf_path, page_index, ...)` → main detection
- `locate_s201_page(pdf_path)` → find S-201 page by sheet token + mark cluster
- `detect_holdowns_on_page(page, ...)` → per-page detection
- `summarize_focused_holdowns(detections)` → count summary
- `_extract_holdown_schedule(page)` → parse Madera schedule table
- `_label_hits(words, table_bboxes, ...)` → find H1-H4 labels
- `_leader_target_points(...)` → follow leaders to filled markers
- `_build_detection_plan(hit, vector_context)` → assemble detection strategy
- Many geometry helpers (~30 private functions)

**Dependencies**: `fitz`, `math`, `re`, `dataclasses`

**Data Flow**:
- Reads: source PDF (text + vector layer)
- Writes: evidence crops to evidence_dir

**Ponytail Findings**:
- **797 lines** — largest detector. Frozen by design (copied verbatim from production).
- Hardcoded Madera bboxes (`PLAN_BBOX`, `S201_TABLE_BBOXES`, `HOLDOWN_ROW_BANDS`) — **ponytail: hardcoded client constants**, but frozen/legacy path.
- `DEFAULT_HOLDOWN_SCHEDULE` is Madera-specific — **ponytail: hardcoded client data**.
- `_detection_to_entity()` is ~55 lines of field mapping — **ponytail: wrapper that only delegates/reshapes**. Could be simplified but it's frozen.

---

## 18. normalization.py
**Purpose**: Hold-down type/mark normalization — maps family names and marks to core tokens (HDU6/HDU11/HD10S/HD15B) and PDF marks (H1-H4).

**Key Functions/Classes**:
- `normalize_holdown_type(value)` → family name → HoldownNormalization
- `normalize_holdown_mark(value)` → plan mark → HoldownNormalization
- `holdown_types_equivalent(left, right)` → core-token equality check
- `mapped_mark_for_core_token(core_token)` → HDU6 → H1
- `expected_core_token_for_mark(mark)` → H1 → HDU6
- `_extract_core_token(cleaned)` → strip prefixes/suffixes to find token
- `_strip_known_suffixes(cleaned)` → remove WITHBOLT/ANCHOR/etc.

**Dependencies**: `re`, `dataclasses`

**Data Flow**:
- Reads: nothing (pure functions)
- Writes: nothing

**Ponytail Findings**:
- `CORE_TOKEN_TO_MARK` and `MARK_TO_CORE_TOKEN` are **hardcoded Madera vocabulary** — **ponytail: hardcoded client constants**. The v3 adapter path is data-driven; this is the legacy path.
- `HoldownNormalization` dataclass has 8 fields — `bolt_variant` and `structural_token` are rarely used downstream. **ponytail: over-engineering** — could be simplified to (core_token, mapped_mark, known, confidence).

---

## 19. schedule_tables.py
**Purpose**: Generic schedule-table discovery and parsing — discovers tables by header text, infers columns from sub-headers, learns mark vocabulary from MARK column.

**Key Functions/Classes**:
- `discover_tables(words, overrides)` → full pipeline on one page
- `learned_vocabulary(tables)` → {category: {mark: spec}} from parsed tables
- `find_schedule_headers(words, overrides)` → find schedule-table headers
- `detect_columns(subheader)` → cluster sub-header words into columns
- `parse_rows(lines, columns, subheader, category)` → walk lines, assign to columns
- `lines_from_words(words)` → cluster word tuples into text lines

**Dependencies**: `re`

**Data Flow**:
- Reads: PyMuPDF word tuples
- Writes: nothing (pure functions)

**Ponytail Findings**:
- Well-generalized — no hardcoded bboxes or y-bands.
- `__main__` self-check is ~30 lines — adequate.
- `CATEGORY_HEADERS` and `CATEGORY_MARK_RE` are the only hardcoded patterns but they're generic structural categories, not client-specific.

---

## 20. scene3d.py
**Purpose**: 3D scene payload for frontend Three.js view — walls, holdowns, grids, openings, category elements, framing boxes.

**Key Functions/Classes**:
- `build_scene(raw_revit, element_list, ai_revit)` → main builder

**Dependencies**: `wall_match.sw_token`, `datetime`

**Data Flow**:
- Reads: `raw_revit_export.json`, `element_list.json`, `AIConvert_revit.json`
- Writes: `scene3d.json` (via caller)

**Ponytail Findings**:
- `ASSUMED_WALL_HEIGHT_FT = 10.0` with `height_assumed` flag — honest.
- Clean, focused module. No issues.

---

## 21. teach.py
**Purpose**: Teach-the-AI memory — humans explain non-standard conventions, rules persist, next extraction applies them.

**Key Functions/Classes**:
- `teach(message, context)` → one chat turn: parse → save → confirm
- `build_overrides(memory)` → produce overrides dict for extraction pipeline
- `load_memory()` / `_save_memory(memory)` → persistence
- `add_entry(instruction, rule, reply)` → append rule
- `delete_entry(entry_id)` → remove rule
- `_fallback_parse(message)` → deterministic NLU when LLM unavailable
- `_llm_parse(message)` → OpenRouter rule extraction
- `unrecognized_report(element_intelligence)` → what should AI ask about?

**Dependencies**: `config`, `openrouter`, `schedule_tables.CATEGORY_MARK_RE`, `re`, `json`

**Data Flow**:
- Reads: `memory/global.json`, element_intelligence (for report)
- Writes: `memory/global.json`

**Ponytail Findings**:
- `LLM_SYSTEM_PROMPT` is ~15 lines — verbose but necessary for structured output.
- `_fallback_parse` is a genuine fallback, not theater — works without API key.
- `CATEGORY_WORDS` dict duplicates category names from `schedule_tables` — **ponytail: minor duplication**.

---

## 22. chat_agent.py
**Purpose**: Agentic chatbot — OpenRouter function-calling loop over read-mostly toolbox. Answers questions about QA-QC results AND acts on UI via ui_actions. **Now unified with teach.py logic** (duplicated internally).

**Key Functions/Classes**:
- `run_chat(message, history, llm)` → one chat turn with tool loop
- `TOOL_IMPLS` → dict of tool name → implementation
- `_tool_get_counts()` / `_tool_query_elements()` / `_tool_get_device()` / etc.
- `_leaked_tool_calls(content)` → parse/scrub leaked textual tool-call markup
- Teach memory: `_load_memory()`, `_save_memory()`, `_add_entry()`, `_build_overrides()`, `_teach_internal()`, `_fallback_parse()`, `_llm_parse()` — **all duplicated from teach.py**
- Public API: `load_memory()`, `save_rule()`, `build_overrides()`, `list_rules()`, `delete_rule()`

**Dependencies**: `config`, `openrouter`, `schedule_tables`, `fastapi.HTTPException`, `json`, `re`

**Data Flow**:
- Reads: all artifacts (element_list, device_registry, etc.)
- Writes: `memory/global.json`, `chat_pipeline_audit.json`

**Ponytail Findings**:
- **MAJOR: teach.py logic is fully duplicated inside chat_agent.py** (~200 lines). The module docstring says "unified with teach-the-AI memory" but both modules still exist independently. **ponytail: delete/stdlib** — one of the two should be removed; chat_agent should import from teach.py.
- `MAX_TOOL_ROUNDS = 6` is defined twice (lines 26 and 342) — **ponytail: dead code / duplication**.
- `PIPELINE_WHITELIST` is defined twice (lines 29 and 345) — **ponytail: dead code / duplication**.
- `LLM` type alias defined twice (lines 31 and 347) — **ponytail: dead code / duplication**.
- `ChatUnavailable` class defined twice (lines 33 and 350) — **ponytail: dead code / duplication**.
- `SYSTEM_PROMPT` defined twice (lines 36 and 354) — **ponytail: dead code / duplication**.
- `LLM_SYSTEM_PROMPT` defined twice — **ponytail: dead code / duplication**.
- All teach constants (`SCHEMA_VERSION`, `RULE_KINDS`, `CATEGORIES`, `CATEGORY_WORDS`, `_TOKEN`, `ALIAS_RE`, `IS_CATEGORY_RE`, `_EXCLUDE_RE`) defined twice — **ponytail: massive duplication**.
- All teach functions (`_load_memory`, `_save_memory`, `_add_entry`, `_delete_entry`, `_build_overrides`, `_category_from_words`, `_category_for_mark`, `_fallback_parse`, `_llm_parse`, `_teach_internal`, `_unrecognized_report`) defined twice — **ponytail: massive duplication**.
- **This file is the #1 ponytail target** — ~300 lines of pure duplication.

---

## 23. openrouter.py
**Purpose**: OpenRouter HTTP client — `call_llm()` for single-turn JSON, `call_chat()` for multi-turn with tools, call logging, status summary.

**Key Functions/Classes**:
- `call_llm(system_prompt, user_prompt, purpose, ...)` → single-turn completion
- `call_chat(messages, tools, purpose, ...)` → multi-turn with function calling
- `read_call_log()` → read persisted log
- `call_status_summary()` → aggregate view for health/UI
- `_append_log(entry)` → append to log file

**Dependencies**: `config`, `urllib.request`, `json`, `time`

**Data Flow**:
- Reads: env vars (API key, model, base URL)
- Writes: `openrouter_call_log.json`

**Ponytail Findings**:
- Uses `urllib.request` instead of `httpx`/`requests` — **ponytail: stdlib** — appropriate for a prototype (no extra deps).
- `call_llm` and `call_chat` share ~80% of their code (payload construction, error handling, logging). **ponytail: shrink** — could extract a `_call_api(payload, purpose)` helper.
- `NOT_CALLED_MESSAGE` constant is used in 3 places — fine.

---

## 24. benchmarks.py
**Purpose**: Back-compat shim — re-exports from `benchmark_workflow` for legacy import paths.

**Key Functions/Classes**:
- Re-exports: `ANNOT_TYPES`, `BM_MARK_RE`, `EXTRACT_SCHEMA_VERSION`, `VECTOR_R_MAX`, `VECTOR_R_MIN`, `VECTOR_TEXT_NEAR_PT`, `_annotation_pass`, `_now_iso`, `_vector_pass`, `extract_pdf_benchmarks`

**Dependencies**: `benchmark_workflow`

**Data Flow**:
- Reads: nothing
- Writes: nothing

**Ponytail Findings**:
- Pure re-export shim — **ponytail: delete** if no callers still use `from app.benchmarks import ...`. The docstring says "New code should import directly from app.benchmark_workflow." If all callers have been updated, this file can be deleted.

---

## 25. benchmark_workflow.py
**Purpose**: Benchmark Autopilot — PDF benchmark extraction (BM-1/BM-2) + 11-state workflow state machine for zero-click 2-benchmark registration.

**Key Functions/Classes**:
- `extract_pdf_benchmarks(pdf_path, page_index, marks)` → find benchmark points
- `_annotation_pass(page, want)` → primary pass: PDF annotations (Bluebeam stamps)
- `_vector_pass(page, want)` → fallback: drawn crosshair symbols
- `load()` / `save(wf)` / `transition(wf, to_state, actor, ...)` → state machine
- `propose_from_geometry(pdf_points, revit_points, ...)` → auto-pick max-diagonal pair
- `propose_from_points(...)` → manual variant
- `verify_stamped_benchmarks(proposal, extracted)` → verify stamping landed correctly
- `bubble_row_positions(words, page_w, page_h, grid_labels)` → crowded-sheet grid-bubble detector
- `resolve_pdf_grid_points(words, revit_points, tol_pt)` → axis-agnostic grid-intersection resolver
- `pick_max_diagonal_pair(points)` → max-spread pair selection

**Dependencies**: `config`, `fitz`, `math`, `re`, `json`

**Data Flow**:
- Reads: source PDF (annotations + vector layer + text), grid control points
- Writes: `benchmark_workflow.json`, `pdf_benchmarks.json`

**Ponytail Findings**:
- Two coupled concerns in one module (extraction + state machine) — documented as intentional.
- `__main__` self-check is ~30 lines — adequate.
- `TRANSITIONS` dict is exhaustive and well-documented.

---

## 26. control_points.py
**Purpose**: Revit grid control points + PDF control points + label-matched calibration + scope diagnostics.

**Key Functions/Classes**:
- `extract_revit_control_points(raw_revit)` → compute grid intersections
- `save_revit_control_points(payload)` → persist
- `empty_pdf_control_points()` / `load_or_init_pdf_control_points()` / `save_pdf_control_points()` → PDF side
- `build_pairs_from_labels(revit_cp, pdf_cp)` → label-matched pair builder
- `auto_calibrate_from_grids(raw_revit, pdf_cp, validation_pairs)` → end-to-end auto-cal
- `build_scope_diagnostics(raw_revit, ai_revit)` → Revit scope analysis
- `save_scope_diagnostics(raw_revit, ai_revit)` → persist diagnostics

**Dependencies**: `config`, `registration`, `json`, `collections.Counter`

**Data Flow**:
- Reads: `raw_revit_export.json`, `AIConvert_revit.json`, `pdf_control_points.json`
- Writes: `revit_control_points.json`, `pdf_control_points.json`, `manual_registration_points.json`, `revit_scope_diagnostics.json`

**Ponytail Findings**:
- `_pdf_baseline()` calls `compare._project_pdf_baseline()` — cross-module coupling but documented.
- `_line_intersection()` is a standard 2D line intersection — hand-rolled but trivial.
- `__main__` self-check is ~30 lines — adequate.

---

## 27. export_watch.py
**Purpose**: Zero-upload auto-ingest watcher — scans directories for fresh Revit exports, detects new files by SHA-256.

**Key Functions/Classes**:
- `scan(manifest, dirs)` → {pending, path, mtime, sha, reason}
- `watch_dirs()` → directories to scan
- `candidates(dirs)` → all export-shaped files, newest first
- `newest(dirs)` → single newest file
- `file_sha(path)` → SHA-256 of file bytes
- `load_manifest()` → active project's manifest
- `export_model_title(raw)` → model name from export
- `titles_match(a, b)` → case-insensitive substring compare
- `ingest_record(sha, mtime, model_title)` → stamp for successful ingest

**Dependencies**: `config`, `hashlib`, `json`, `os`, `pathlib`

**Data Flow**:
- Reads: filesystem (watch dirs), `project_manifest.json`
- Writes: nothing (scan only; ingest is done by caller)

**Ponytail Findings**:
- Clean, focused module. No issues.
- `__main__` self-check uses tempfile — thorough.

---

## 28. generic_page_intelligence.py
**Purpose**: Generic hold-down page intelligence for non-Madera drawing sets — derives sheet + mark family from element_intelligence, calls s201_detector with additive parameters.

**Key Functions/Classes**:
- `run_generic_page_intelligence(pdf_path, element_intelligence)` → main entrypoint
- `choose_foundation_sheet(element_intelligence)` → sheet with most holdown marks
- `_mark_alternation(element_intelligence, sheet)` → build regex alternation from vocabulary

**Dependencies**: `config`, `s201_detector`, `re`

**Data Flow**:
- Reads: `element_intelligence.json`, source PDF
- Writes: `pdf_page_intelligence.json` (via caller)

**Ponytail Findings**:
- Clean, focused module. No issues.
- `__main__` self-check is ~20 lines — adequate.

---

## 29. phase_summary.py
**Purpose**: Per-phase plain-English summaries for the live pipeline log — deterministic, no LLM, no estimation.

**Key Functions/Classes**:
- `upload(manifest, element_intelligence, page_intelligence)` → upload summary
- `auto_benchmark(proposal, stamped)` → benchmark summary
- `revit_placement(proposal, payload)` → placement summary
- `registration(calibration)` → registration summary
- `match(element_list, systematic, sampled)` → match summary
- `count_systematic(element_list, registry, cap)` → count systematic mismatches
- `record(phase, text)` → emit + persist summary
- `load()` → read persisted summaries

**Dependencies**: `config`, `progress`, `review`, `json`

**Data Flow**:
- Reads: all artifacts (for summary generation)
- Writes: `phase_summaries.json`, progress bus events

**Ponytail Findings**:
- Clean, honest module — every sentence built from existing numbers.
- `SYSTEMATIC_SAMPLE_CAP = 30` — documented rationale.
- `record()` never raises — commentary must not break pipeline. Good design.

---

## 30. progress.py
**Purpose**: In-memory pipeline progress bus + SSE stream — ring buffer, no persistence.

**Key Functions/Classes**:
- `emit(step, kind, message, data)` → add event
- `events_since(seq)` → get events after sequence number
- `sse_stream(poll_s)` → async generator for StreamingResponse

**Dependencies**: `asyncio`, `json`, `threading`, `time`

**Data Flow**:
- Reads: nothing (in-memory)
- Writes: nothing (in-memory ring buffer)

**Ponytail Findings**:
- Clean, minimal module. No issues.
- `_MAX_EVENTS = 500` — reasonable ring buffer size.

---

## 31. maintenance.py
**Purpose**: Startup hardening — rotating structured log file + artifact-retention GC for evidence crops.

**Key Functions/Classes**:
- `run_startup()` → called once from create_app()
- `setup_logging(log_file)` → rotating file handler + secret redaction
- `gc_evidence_crops(cap_mb)` → trim oldest evidence PNGs per project
- `RedactSecretsFilter` → logging filter to redact token=/key=/api_key= values

**Dependencies**: `config`, `logging`, `os`, `re`, `pathlib`

**Data Flow**:
- Reads: env vars, filesystem (evidence dirs)
- Writes: log file, deletes old evidence crops

**Ponytail Findings**:
- Clean, focused module. No issues.
- `RedactSecretsFilter` is a genuine security need — good.

---

## 32. revit_bridge.py
**Purpose**: Revit bridge — drives Nonica's RevitMCPConnection.exe directly from backend. Deterministic MCP tool sequence for benchmark placement, live element reads, selection, 3D massing. Also supports open-source revit-mcp plugin via TCP socket.

**Key Functions/Classes**:
- `place_benchmarks(proposal, family)` → live BM-1/BM-2 placement
- `place_sequence(call, proposal, family, tolerance_ft)` → deterministic placement (pure over injected async call)
- `status()` / `status_cached(ttl_s, force)` → live connection status
- `select_elements(element_ids)` → set Revit selection
- `get_selection()` → current selection
- `element_location(element_id)` → (x,y) for one element
- `live_connection_locations(force)` → cached Structural Connection locations
- `get_selected_element_full()` → richest source first (revit-mcp → Nonica)
- `live_scene_geometry(force)` → cached live box massing
- `scene_geometry_sequence(call, ...)` → pure over injected async call
- `connection_locations_sequence(call)` → pure over injected async call
- `benchmark_family(override)` → resolve family name
- `BridgeError` → Revit-side failure exception
- `_revit_mcp_call(method, params, timeout)` → TCP JSON-RPC to revit-mcp add-in
- Many response-parsing helpers (`_first_xyz`, `_element_ids`, `_looks_disconnected`, etc.)

**Dependencies**: `asyncio`, `json`, `logging`, `math`, `os`, `re`, `socket`, `mcp` (ClientSession, StdioServerParameters, stdio_client)

**Data Flow**:
- Reads: Revit model (via MCP)
- Writes: Revit model (copies elements, sets parameters)

**Ponytail Findings**:
- **805 lines** — largest module. Complex but well-documented with live findings.
- Two bridges (Nonica MCP + revit-mcp TCP) — documented as intentional fallback.
- `_STATUS_CACHE`, `_CONN_CACHE`, `_SCENE_CACHE` — three separate caches with different TTLs. **ponytail: shrink** — could unify into one cache manager, but each has different semantics so separation is defensible.
- `__main__` self-check uses fake async call — thorough.

---

## 33. revit_ids.py
**Purpose**: Revit UniqueId ↔ ElementId decoding — the trailing 8 hex is XOR'd with the GUID's last 8 hex, not a direct hex decode.

**Key Functions/Classes**:
- `unique_id_to_element_id(unique_id)` → correct decode
- `_make_unique_id(guid_last_group, element_id)` → inverse (for tests)

**Dependencies**: none

**Data Flow**:
- Reads: nothing (pure functions)
- Writes: nothing

**Ponytail Findings**:
- Tiny, focused module (47 lines). No issues.
- Fixes a real bug (BUG-05) — the naive decode was silently wrong.

---

# Ponytail Audit Summary

## Biggest Cuts (Ranked)

### 1. **chat_agent.py: Massive teach.py duplication** — `delete`
- ~300 lines of teach.py logic duplicated verbatim inside chat_agent.py
- All constants, regexes, functions, classes duplicated
- **Fix**: chat_agent should `from .teach import ...` and delete all internal copies
- **Savings**: ~300 lines, one source of truth

### 2. **chat_agent.py: Quadruple-defined constants** — `delete`
- `MAX_TOOL_ROUNDS`, `PIPELINE_WHITELIST`, `LLM` type, `ChatUnavailable`, `SYSTEM_PROMPT`, `LLM_SYSTEM_PROMPT` all defined twice
- **Fix**: delete second definitions (lines 340-368)
- **Savings**: ~30 lines

### 3. **pdf_convert.py + revit_convert.py + pdf_intelligence.py: Hardcoded Madera baseline** — `stdlib/native`
- `{"H1": 10, "H2": 21, "H3": 6, "H4": 17}` appears in 3 files
- `MARK_TO_CORE_TOKEN = {"H1": "HDU6", ...}` appears in 2 files
- **Fix**: these legacy paths should use the data-driven approach from revit_v3_adapter, or be clearly marked as Madera-only and not run for other projects
- **Savings**: eliminates silent wrong answers for non-Madera projects

### 4. **pdf_convert.py + revit_convert.py: LLM theater** — `yagni`
- `_llm_confirm_mapping()` and `_llm_enrichment()` call OpenRouter but their results are never authoritative — deterministic code is the source of truth
- **Fix**: either make the LLM result authoritative (and handle failures) or remove the calls (and just log that deterministic mode was used)
- **Savings**: 2 API calls per pipeline run, ~$0.01-0.05 per run

### 5. **openrouter.py: call_llm / call_chat duplication** — `shrink`
- ~80% shared code (payload construction, error handling, logging)
- **Fix**: extract `_call_api(payload, purpose, base_dict)` helper
- **Savings**: ~60 lines

### 6. **benchmarks.py: Back-compat shim** — `delete` (if no callers)
- Pure re-export from benchmark_workflow
- **Fix**: grep for `from app.benchmarks` / `import app.benchmarks`; if zero callers, delete file
- **Savings**: 1 file, 36 lines

### 7. **normalization.py: Over-engineered dataclass** — `shrink`
- `HoldownNormalization` has 8 fields; `bolt_variant` and `structural_token` rarely used
- **Fix**: audit downstream consumers; if unused, remove fields
- **Savings**: 2 fields, simpler API

### 8. **s201_detector.py: Frozen but hardcoded** — document only
- 797 lines with hardcoded Madera bboxes, schedule, vocabulary
- **Fix**: already frozen by design; generic path (element_detector + generic_page_intelligence) is the correct replacement. Document that this module is Madera-only and should not be extended.
- **Savings**: none (frozen), but prevents future sprawl

### 9. **revit_bridge.py: Three separate caches** — `shrink` (low priority)
- `_STATUS_CACHE`, `_CONN_CACHE`, `_SCENE_CACHE` with different TTLs
- **Fix**: could unify into `_Cache` class with per-key TTL, but each has different semantics
- **Savings**: ~30 lines, marginal

### 10. **review_overlay.py: Hardcoded color constants** — accept
- RED/BLUE/ORANGE/GREEN as hex strings — fine for this scope, not worth abstracting

## Files with No Issues
- `main.py`, `progress.py`, `maintenance.py`, `revit_ids.py`, `export_watch.py`, `scene3d.py`, `generic_page_intelligence.py`, `phase_summary.py`, `leader_anchor.py` — clean, focused, appropriate scope.

## Architecture Observations
1. **Two parallel paths**: legacy Madera-specific (s201_detector, pdf_intelligence, revit_convert, pdf_convert, normalization) vs. generic data-driven (element_detector, generic_page_intelligence, revit_v3_adapter, schedule_tables). The generic path is correct; the legacy path is frozen.
2. **Artifact-based pipeline**: every step reads/writes JSON artifacts — clean, debuggable, replayable.
3. **Honest by construction**: statuses are derived from real outcomes, never forced. MATCH is gated on verified registration + distance thresholds.
4. **LLM calls are mostly advisory**: deterministic code is the source of truth; LLM confirms/confirms. This is correct for a QA-QC system.
5. **ContextVar project scoping**: BUG-03 fix is solid — per-request isolation without global state.
