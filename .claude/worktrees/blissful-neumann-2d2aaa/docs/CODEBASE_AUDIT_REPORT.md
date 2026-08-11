# Codebase Audit Report — QA-QC Prototype

Read-only senior-engineer audit. Scope: every `.py` in `backend/app/` (incl. `routers/`) and every `.js` in `frontend/src/` (incl. `panels/`). Tests used for coverage mapping only.

Method: full read of all 56 source files; `python -m pytest -q --collect-only` (278 tests collected); AST-driven public-symbol extraction cross-referenced against `backend/tests/` and `frontend/tests/`; repo-wide grep for dead symbols, secrets, path joins, and unescaped HTML interpolation. Every `file:line` below was opened and read — no finding is inferred from a docstring alone.

Cross-check baseline: `HARDCODING_AUDIT.md` (status of its 5 blockers in [§7](#7-hardcoding_auditmd-status)).

---

## 1. Backend — core pipeline modules

### backend/app/compare.py — 548 LOC

| Function | Purpose |
|---|---|
| `compare(ai_revit, ai_pdf, calibration)` | Entrypoint: groups both sides by mark, picks registered/diagnostic/type-only matching, emits `ai-compare-report/2.1`. |
| `_match_with_location` | Transforms Revit points to PDF space; greedy nearest-first one-to-one pairing per mark. |
| `_match_type_only` | No-registration fallback: pairs by mark count only, every pair `NEEDS_REVIEW`. |
| `_project_pdf_baseline` | Reads expected PDF mark counts from the `pdf_page_intelligence` artifact. |
| `_revit_count_diagnostics` | Display-only raw→canonical→by-mark count chain vs the PDF baseline. |

- **DOCSTRING-MISMATCH (significant)** `compare.py:490-491` — claims R-27 "replaces a hardcoded Madera `{H1:10,H2:21,H3:6,H4:17}`". The lookup at `compare.py:504` prefers `intel["expected_baseline"]`, but `pdf_intelligence.py:49` writes *exactly that literal* into that field on every project. The literal moved; it did not go away. See [§6 CRITICAL-2](#6-critical-findings).
- **HARDCODE** `compare.py:23-24` — `MATCH_MAX_PT = 16.0` / `LOCATION_MISMATCH_MAX_PT = 40.0`; the same `16.0` is re-declared unlinked at `ransac_holdown.py:86`.
- **ERROR-GAP** `compare.py:502` — `except (OSError, ValueError, KeyError): return None`. A corrupt artifact is reported as "No PDF baseline available for this project" (`compare.py:542`) — indistinguishable from the artifact genuinely not existing.
- **ERROR-GAP** `compare.py:333,352` — `calibration["transform"]["matrix"]` indexed with no key check; a calibration with `transform: {}` and `match_allowed: true` raises `KeyError`.

### backend/app/registration.py — 749 LOC

| Function | Purpose |
|---|---|
| `apply_transform(matrix, x, y)` | Applies the 6-element affine. |
| `compute_calibration(pairs, source, validation_pairs)` | Least-squares 2D similarity from ≥3 pairs; sets the `match_allowed` gate. |
| `compute_calibration_from_benchmarks(...)` | Exact 2-point similarity from stamped BM-1/BM-2 with separation/scale/chirality/holdout checks. |
| `save_calibration` / `load_calibration` / `delete_calibration` | Artifact persistence. |
| `calibration_source(cal)` | Provenance string readback. |
| `registration_usable(cal)` | True only when `quality.match_allowed` — the single MATCH gate. |
| `registration_status(cal)` | missing / failed / diagnostic_only / low_confidence / available. |
| `build_registration_report` / `save_registration_report` | `coordinate-registration-report/2.0` with blockers and required inputs. |
| `_fit_variant` | Complex-number least-squares fit with/without reflection. |

- **HARDCODE** `registration.py:346` — `expected_scale_pt_per_ft: float | None = 18.0`, a sheet-scale assumption with no named constant, driving the blocking `BENCHMARK_SCALE_MISMATCH` at `registration.py:430`.
- **HARDCODE** `registration.py:351` — `marks: tuple[str,str] = ("BM-1","BM-2")`; `registration.py:441` — inline `0.5`-degree orthogonality tolerance beside four *named* constants at `:337-341`.
- **ERROR-GAP** `registration.py:602-604` — `load_calibration` catches only `JSONDecodeError`; `OSError`/`UnicodeDecodeError` escape a call every caller treats as a nullable read.
- **ERROR-GAP (contract)** `registration.py:213-231` — `_fail()` persists `transform: None`. That is a valid saved artifact shape that crashes `wall_match.py:130` ([§6 CRITICAL-4](#6-critical-findings)).

### backend/app/s201_detector.py — 784 LOC *(frozen)*

| Function | Purpose |
|---|---|
| `locate_s201_page(pdf_path)` | Finds the page with an `S-201` token plus the densest `H1-H4` cluster. |
| `build_focused_s201_holdown_entities(...)` | Wraps detection into reviewer-facing entities. **Dead** — see [§5](#5-dead-code). |
| `detect_s201_holdowns(...)` | Opens the PDF, extracts the schedule, delegates to `detect_holdowns_on_page`. |
| `detect_holdowns_on_page(page, ...)` | Core detector: label hits → vector context → detection plans → rows with evidence crops. |
| `summarize_focused_holdowns(detections)` | Total + per-mark counts. |
| `LineSegment` / `FilledMarker` / `DetectionPlan` | Geometry records and the mutable per-label plan. |

- **HARDCODE (load-bearing)** `s201_detector.py:21-33` — `PLAN_BBOX`, four `S201_TABLE_BBOXES`, `HOLDOWN_ROW_BANDS`: absolute point rectangles for one sheet.
- **HARDCODE (load-bearing)** `s201_detector.py:52-84` — `MARK_TO_CORE_TOKEN` + `DEFAULT_HOLDOWN_SCHEDULE` bake in Simpson products (`S/HDU6`, `SABR`) and one project's fastener/embedment strings.
- **CRITICAL** `s201_detector.py:201` + `:221` — `schedule = schedule or DEFAULT_HOLDOWN_SCHEDULE`, then `sched = schedule.get(label, DEFAULT_HOLDOWN_SCHEDULE.get(label, {}))`. See [§6 CRITICAL-1](#6-critical-findings).
- **HARDCODE** `s201_detector.py:334,337-340` — schedule reader pinned to `1780 <= x <= 2235` and four literal column windows; `:351-352`, `:364-366` — one-sheet OCR spelling repairs; `:725` — *any* page over 2000×1500 gets this project's four table rectangles masked out.
- **HARDCODE** `s201_detector.py:12` — comment embeds the absolute path `C:\qa-qc\backend\app\services\s201_holdown_detector.py`.
- **DOCSTRING-MISMATCH** `s201_detector.py:467` — `_nearby_count_prefix` reads as a generic count-prefix finder; `:479-480` hard-rejects every count except exactly `2`, so `(3)H2` silently collapses to one instance.
- **ERROR-GAP** `s201_detector.py:119-121` — `locate_s201_page` contract is "returns None when not found", but a corrupt/encrypted PDF raises out of the unguarded `fitz.open`.
- **ERROR-GAP** `s201_detector.py:146-148` — returns `[]` for both "page not found" and "file missing"; the caller cannot distinguish a scoping failure from an empty sheet.
- **Magic numbers, no constants:** `:486`, `:502`, `:514-521`, `:539-545`, `:599`, `:635-637`, `:644`, `:657`, `:663-664`, `:680`, `:705`, `:713-718`, `:737`, `:748`.

### backend/app/pdf_intelligence.py — 67 LOC *(frozen)*

| Function | Purpose |
|---|---|
| `run_page_intelligence(pdf_path)` | Locates the S-201 page, runs the frozen detector, returns `pdf-page-intelligence/1.0` (or an error artifact). |

- **CRITICAL HARDCODE** `pdf_intelligence.py:49` — `baseline = {"H1":10,"H2":21,"H3":6,"H4":17}` written into `expected_baseline` for every project; `:66` compares `total == 54`. This is the literal `compare.py:491` claims was removed.
- **HARDCODE** `pdf_intelligence.py:35,45,54` — `"S-201"` in the error message, the detector call, and the output.
- **DOCSTRING-MISMATCH** `pdf_intelligence.py:25-26` — states the function "Reproduces the Madera baseline …" as a property of the code; the code re-asserts a literal against whatever was found and reports a boolean.
- **ERROR-GAP** `pdf_intelligence.py:42-47` — `detect_s201_holdowns` unguarded, while the "page not found" branch one above returns a structured error. Inconsistent failure contract at one call site.

### backend/app/pdf_convert.py — 141 LOC *(frozen)*

| Function | Purpose |
|---|---|
| `convert_pdf(page_intelligence, revit_ai_memory)` | Normalizes detector output into `pdf-aiconvert/1.0` with center points, spec fields, LLM mapping confirmation. |
| `_llm_confirm_mapping` | OpenRouter call asking the model to confirm the deterministic mapping. |

- **HARDCODE** `pdf_convert.py:13` — `MARK_TO_CORE_TOKEN` (3rd copy of the Simpson table); `:35-37` — the LLM system prompt names `H1-H4` and `HDU6/HDU11/HD10S/HD15B` inline, sent on every project; `:65` — `"S-201"` default.
- **DOCSTRING-MISMATCH** `pdf_convert.py:21-25` — the parsed LLM verdict is written to `llm_mapping_confirmation` (`:129`) with **no** consistency check against `MARK_TO_CORE_TOKEN`; a disagreeing answer is published beside the deterministic map with nothing flagging the conflict.
- **ERROR-GAP** `pdf_convert.py:70` — `"deterministic_fallback"` implies a fallback path; none exists. The field is misleading on both paths.

### backend/app/normalization.py — 147 LOC *(frozen)*

| Function | Purpose |
|---|---|
| `HoldownNormalization` | Frozen record: tokens, mapped mark, confidence, known. |
| `normalize_holdown_type(value)` | Revit type name → core token + mapped mark. |
| `normalize_holdown_mark(value)` | PDF mark → core token. |
| `holdown_types_equivalent(left, right)` | Same-known-core-token test. **Dead** — see [§5](#5-dead-code). |
| `mapped_mark_for_core_token` / `expected_core_token_for_mark` | The two lookup directions. |

- **HARDCODE (load-bearing)** `normalization.py:6-11` — `CORE_TOKEN_TO_MARK` is the Simpson vocabulary; "known", confidence, and equivalence are all defined relative to it. `:61` — `re.fullmatch(r"H[1-4]", cleaned)`.
- **HARDCODE** `normalization.py:38-43,71,81` — confidence literals `0.95/0.9/0.15/0.0/0.98`; `:132-140` — literal Revit type-name suffix list from one export.

### backend/app/element_detector.py — 325 LOC

| Function | Purpose |
|---|---|
| `detect_sheet_number(words, page_width)` | Sheet number from the rightmost title strip. |
| `detect_marks(words, vocab, table_bboxes, ...)` | Plan-area mark instances; excludes tables/title strip, expands `(2)` prefixes. |
| `scan_pdf(pdf_path, overrides)` | Two-pass scan → global vocabulary, then per-sheet marks + count consistency. |

- **HARDCODE** `element_detector.py:37` — comment pins the regex to "S-201 / S240 / SD14 (Madera style)".
- **HARDCODE** `element_detector.py:143,148,151,155` — a ±6-word neighbour window and 2×/3× radius multipliers as unnamed literals atop the one named `NEIGHBOR_RADIUS_PT = 18.0`.
- **DOCSTRING-MISMATCH** `element_detector.py:14-16` — `expanded_synthetic` is set as `total > 1` (`:175`), so it is also true for genuinely-multiple marks never synthesized from a prefix. The flag does not mean what the docstring says.
- **DOCSTRING-MISMATCH** `element_detector.py:209-210` — "pages with … (marks or tables)" is satisfied by header-only tables (`schedule_tables.py:379,383`), so content-free pages are emitted as sheets.
- **ERROR-GAP** `element_detector.py:212` — `fitz.open` sits outside the `try/finally`; the caller gets a raw `fitz` error rather than a structured artifact, unlike `generic_page_intelligence.py:59`.

### backend/app/element_registry.py — 324 LOC

| Function | Purpose |
|---|---|
| `build_element_list(...)` | Joins compare verdicts, per-sheet runs, wall reports and generic extraction into `element-list/1.0`. |
| `scope_warnings(device_summary, raw_revit)` | Display-only warning when a category has PDF callouts but zero Revit targets. |

- **HARDCODE** `element_registry.py:31` — `compare_sheet: str | None = "S-201"`, keying the authoritative hold-down branch (`:42-45`, `:142`); `:233` — comment names "the Dogwood shear-wall bug"; `:24` — `NO_REVIT_CATEGORIES = ("post","steel_column")` is a static export-capability list that will keep forcing `NO_REVIT_DATA` (`:155-156`) once the exporter ships posts.
- **ERROR-GAP** `element_registry.py:79,109` — `row["pdf_mark_id"]` / `w["revit_wall_id"]` indexed, not `.get()`; a `KeyError` mid-build discards the whole artifact. Same at `:138-141` while sibling reads on the same dict use `.get()` (`:179`).
- **DOCSTRING-MISMATCH** `element_registry.py:3` — "compare.py stays byte-identical". It is not: `_project_pdf_baseline` and `_revit_count_diagnostics` (`compare.py:485-548`) were added, including a lazy import whose own comment admits it changes frozen `compare.py`.

### backend/app/control_points.py — 393 LOC

| Function | Purpose |
|---|---|
| `extract_revit_control_points(raw_revit)` | Grid letter×number intersections with per-grid warnings. |
| `save_revit_control_points(payload)` | Writes the artifact. |
| `empty_pdf_control_points(sheet, page_index)` | Empty payload with an instructional warning. |
| `load_or_init_pdf_control_points()` | Loads persisted PDF control points or the empty payload. |
| `save_pdf_control_points(points, ...)` | Validates and persists manual PDF points. |
| `build_pairs_from_labels(revit_cp, pdf_cp)` | Label-intersection pairing → `grid_verified` pairs. |
| `save_manual_pairs(payload)` | Writes `manual_registration_points`. |
| `auto_calibrate_from_grids(...)` | extract → pair → `compute_calibration` → save calibration + report. |
| `build_scope_diagnostics` / `save_scope_diagnostics` | Revit scope breakdown vs the PDF baseline. |

- **HARDCODE (load-bearing)** `control_points.py:20` — `PDF_BASELINE = {"H1":10,"H2":21,"H3":6,"H4":17,"total":54}` consumed unconditionally at `:313,314,326,339`. There is **no** artifact lookup here equivalent to `compare._project_pdf_baseline` — this is the fix that did not propagate.
- **HARDCODE (silently wrong)** `control_points.py:286-287` — `revit_by_mark` restricted to `("H1","H2","H3","H4")`, so any other mark is dropped from `revit_total` (`:312`) and the `delta` reported at `:314-316,326` understates the real count, reported as fact with no warning.
- **HARDCODE** `control_points.py:112,140` — `"S-201"` defaults; `:283` — 1-ft elevation bucket with no constant.
- **ERROR-GAP** `control_points.py:132-135` — `except JSONDecodeError: pass` → falls through to `empty_pdf_control_points()`, so a corrupted file tells the user to enter points that already exist on disk. `OSError` uncaught.
- **ERROR-GAP** `control_points.py:230-242` — the `< MIN_PAIRS` early return has already written two artifacts (`:224`, `:228`); a failed auto-calibration leaves partial state with `ok: False`.

### backend/app/device_match.py — 477 LOC

| Function | Purpose |
|---|---|
| `inverse_from_calibration(cal)` | pdf→model closure from the stored `transform.inverse_matrix`. |
| `fit_inverse(point_pairs)` | Refits the inverse from ≥3 pairs, trying both chiralities; refuses at n<2. |
| `row_z_ft(row)` | Model-space Z when the row carries an explicit elevation. |
| `build_devices(rows, inverse_by_sheet, prefix)` | Clusters cross-sheet callouts into physical devices in model feet. |
| `assign(devices, targets, distance, ...)` | Greedy one-to-one: same-mark pass, then mark-blind → `MARK_MISMATCH`. |
| `point_distance` / `segment_distance` | Distances in feet. |
| `sw_token(text)` | `…SW1` → `SW-1`. |
| `run(element_rows, calibrations, assemblies, walls)` | Full device pass → `device-registry/1.0`. |

- **HARDCODE** `device_match.py:305` — `match_ft=4.0, mismatch_ft=12.0` as bare literals for shear walls while the hold-down equivalents are the named `MATCH_FT`/`MISMATCH_FT` (`:24-25`). Two gate systems, one named, in one call chain.
- **DOCSTRING-MISMATCH** `device_match.py:169-170` — the same-mark pass is gated at `mismatch_ft` (`:176`) but the mark-blind pass at `match_ft` for both arguments (`:184`); the docstring gives no hint the passes use different radii.
- **DOCSTRING-MISMATCH** `device_match.py:35-37` — "chirality already resolved by registration.py". `compute_calibration_from_benchmarks` pins chirality by convention via `assume_reflection` (`registration.py:348,355-360`) and only reports a conflict as evidence. "Resolved" overstates it.
- **DOCSTRING-MISMATCH** `device_match.py:52-54` — the stated invariant ("`run()` never reaches this path") is false: `inverse_matrix` is `None` whenever `_invert_matrix` degenerates (`registration.py:115-116,525`), so `run()` *does* fall through to `fit_inverse`, which correctly refuses. The safety net is what holds, not the invariant.
- **ERROR-GAP** `device_match.py:283-286` — `a["center_point"]["x"]` indexed on every assembly; one null `center_point` kills the whole device pass. `compare.py:45-54` handles exactly this defensively via `_xy`.
- **ERROR-GAP** `device_match.py:206,342` — `assign` writes `_claimed` into caller-owned dicts and `run` pops it; a second `_run_category` over the same list sees pre-polluted state.

### backend/app/wall_match.py — 296 LOC

| Function | Purpose |
|---|---|
| `extract_leader_segments(page)` | Leader-sized straight vector segments. |
| `leader_tips(anchor, segments)` | Far endpoints of segments attached to a callout bubble. |
| `sw_token` / `normalize_sw_mark` | Revit type name / PDF mark → `SW-n`. |
| `point_to_segment_distance(p, a, b)` | Clamped-projection distance. |
| `match_shear_walls(...)` | Greedy one-to-one SW matching per sheet; MATCH gated on `registration_usable`. |

- **CRITICAL ERROR-GAP** `wall_match.py:130` — `(calibration or {}).get("transform", {}).get("matrix")`. See [§6 CRITICAL-4](#6-critical-findings).
- **ERROR-GAP** `wall_match.py:47-48` — `except Exception: return []` silently degrades every callout to bubble anchoring; a page whose vector layer failed to parse is indistinguishable from a page with no leaders, and rows then report `anchor_method: "bubble"` as if it were a measurement.
- **ERROR-GAP** `wall_match.py:236` — `counts["REVIT_ONLY"] = len(unmatched_walls)` overwrites rather than adds, discarding any `REVIT_ONLY` already tallied at `:234-235`.
- **ERROR-GAP** `wall_match.py:123-127` — `m["id"]` / `m["mark"]` hard-indexed while `.get()` guards sit in the same expression.
- **HARDCODE** `wall_match.py:20-22` — `SW_MATCH_MAX_PT = 60.0` / `SW_LOCATION_MISMATCH_MAX_PT = 120.0`, self-documented as "tuned on Madera S-202 ground truth", with no per-project override; `:28-31` — four point-space leader tolerances valid only at the tuned sheet scale.

### backend/app/leader_anchor.py — 176 LOC

| Function | Purpose |
|---|---|
| `snap_holdowns(ai_pdf, pdf_path)` | Re-anchors `AIConvert_pdf` holdowns at their proven leader dots, in place. |
| `snap_element_marks(intel, pdf_path)` | Same snap for `element_intelligence` sheet marks. |

- **HARDCODE** `leader_anchor.py:25` — `SEARCH_RADIUS_PT = 45.0` documented as "~2.5 ft @ 3/16" scale"; nothing in the module reads the actual scale, which `registration.py:346` proves is available.
- **ERROR-GAP** `leader_anchor.py:37-41` — `d["rect"]` / `d["items"]` hard-indexed in an unguarded loop, unlike the sibling at `wall_match.py:39-48`. One malformed drawing aborts the pass **after** some holdowns were already mutated in place (`:97-99`), leaving `ai_pdf` half-snapped with no stats block written (`:102` unreached).
- **ERROR-GAP** `leader_anchor.py:38` — `d.get("fill") is not None` accepts any fill including white, contradicting the docstring's claim (`:13-15`) that anchoring happens "ONLY when the vector layer proves the link". `s201_detector.py:514` solves the same problem correctly with `max(fill) < 0.25`.
- **ERROR-GAP** `leader_anchor.py:86-88,121-122` — an out-of-range page index increments `kept` with no diagnostic, reading as "no leaders on this sheet".

### backend/app/ransac_holdown.py — 237 LOC

| Function | Purpose |
|---|---|
| `ransac_calibrate(ai_revit, ai_pdf, threshold, iterations, seed, restarts)` | Mark-constrained RANSAC similarity fit over hold-down centers; hands inliers to `compute_calibration` and saves unless a benchmark calibration outranks it. |

- **CRITICAL ERROR-GAP** `ransac_holdown.py:174-176` + `:229-230` — see [§6 CRITICAL-5](#6-critical-findings).
- **HARDCODE** `ransac_holdown.py:5-7` — docstring hardcodes this project's facts ("PDF S-201 has 54 hold-downs… Revit has 72") as the module's premise; `:86` — `distance_threshold_pt: float = 16.0` duplicates `compare.MATCH_MAX_PT` as an unlinked literal even though `:17` promises they are the same number; `:31-32,88-89` — `SCALE_MIN/MAX`, `iterations=4000`, `seed=42`, `restarts=20` unexplained.
- **DOCSTRING-MISMATCH** `ransac_holdown.py:156-157` — the no-consensus message reports `f"over {iterations} iterations"` but the loop at `:119-121` runs `restarts × iterations` (80,000). The reported number is 20× low.
- **ENCAPSULATION** `ransac_holdown.py:125,128,140` — calls `registration._is_collinear` and `registration._fit_variant` across a module boundary. This is the only one of seven sibling modules with no `__main__` self-check.
- **ERROR-GAP** `ransac_holdown.py:200` — `existing["transform"]["matrix"]` indexed after only `registration_usable(existing)`, which does not guarantee a `matrix` key.

### backend/app/schedule_tables.py — 468 LOC

| Function | Purpose |
|---|---|
| `lines_from_words(words, y_tol)` | Clusters words into y-sorted text lines. |
| `find_schedule_headers(words, overrides)` | Locates schedule header runs (taught → built-in → generic). |
| `detect_columns(subheader)` | Clusters sub-header words into columns on x. |
| `parse_rows(lines, columns, subheader, category, stop_y)` | Assigns cells, merges wrapped continuations, anchors on a mark token. |
| `discover_tables(words, overrides)` | headers → columns → rows → bbox. |
| `learned_vocabulary(tables)` | Union of MARK-column tokens per category. |
| `discover_tables_on_page(page)` | fitz wrapper. **Dead** — see [§5](#5-dead-code). |

- **DOCSTRING-MISMATCH (significant)** `schedule_tables.py:8` — "The mark vocabulary … is LEARNED … nothing is hardcoded to Madera." `learned_vocabulary` filters every candidate through `CATEGORY_MARK_RE` (`:418,427-430`), which **is** a hardcoded family list. A client mark outside those patterns is dropped from the learned vocabulary entirely — the opposite of the claim. Repeated at `:412-414`.
- **HARDCODE** `schedule_tables.py:33-35` — `^(?:H|HD|HDU|HTT|TD)-?\d{1,2}$` bakes in Simpson families; `:26` names Madera; `:45` — `GENERIC_MARK_RE` tuned against two literal strings from one client's schedule.
- **HARDCODE** `schedule_tables.py:280,318,320` — inline `16.0` floor and unnamed scan windows beside the named `ROW_GAP_STOP_FACTOR`; `:147` — `SUBHEADER_X_MARGIN_PT` defined mid-file, away from `:51-54`.
- **ERROR-GAP** `schedule_tables.py:244,360` — invariants held only by construction (`r[i]` column-count, `prev["cells"]["row_text"]`), neither asserted nor enforced by the signature.

### backend/app/generic_page_intelligence.py — 124 LOC

| Function | Purpose |
|---|---|
| `choose_foundation_sheet(element_intelligence)` | Sheet with the most plan hold-down marks (ties → lowest page index). |
| `run_generic_page_intelligence(pdf_path, ei)` | Derives sheet, mark alternation and table bboxes from generalized extraction, then calls the frozen detector. |

- **DOCSTRING-MISMATCH (significant)** `generic_page_intelligence.py:6-13` — claims "Same artifact schema as the frozen path". Two fields the frozen path emits are absent: `expected_baseline` and `matches_expected_baseline` (`pdf_intelligence.py:64-66`). `compare._project_pdf_baseline` (`compare.py:504`) then falls back to `summary.by_type`, so on the generic path the "expected baseline" **is** the observed counts — the comparison in `_revit_count_diagnostics` becomes self-referential and can never report a PDF-side discrepancy, while still emitting `"likely_issue"` and `"required_next_fix"` as if it had.
- **DOCSTRING-MISMATCH** `generic_page_intelligence.py:14` — "No fake data". Passing `mark_pattern` forces `s201_detector.py:175` down the `else: {}` branch, which `:201` converts back into `DEFAULT_HOLDOWN_SCHEDULE`. See [§6 CRITICAL-1](#6-critical-findings).
- **HARDCODE** `generic_page_intelligence.py:28` — `TITLE_STRIP_FRACTION = 0.12  # keep in sync with element_detector`; hand-duplicated from `element_detector.py:43` instead of imported.
- **ERROR-GAP** `generic_page_intelligence.py:50` — `_mark_alternation` returns `""` when vocabulary and plan marks are both empty; `s201_detector._holdown_re_for` treats `""` as falsy (`:44`) and silently reverts to the frozen `HOLDOWN_RE`. Unreachable today only because `choose_foundation_sheet` requires ≥1 mark — an undocumented invariant holding an unguarded fallback in place.
- **ERROR-GAP** `generic_page_intelligence.py:73-74` — `sheet["page_index"]` / `["page_size_pt"]` hard-indexed on a dict the function accepts unvalidated.

---

## 2. Backend — service and infrastructure modules

### backend/app/main.py — 153 LOC

| Function | Purpose |
|---|---|
| `create_app()` | Runs startup maintenance, installs bearer-auth + progress middlewares, includes 8 routers, mounts `frontend/` at `/`. |
| `_step_headline(step)` | Reads the just-written artifact for a step and returns a one-line summary for the SSE bus. |
| re-exports `:146-151` | Router handlers aliased so tests can import them as `app.main.<name>`. |

- **SECURITY** `main.py:98` — `/api/health` exempt from auth, and `system.py:31` returns `openrouter.call_status_summary()` → `config.openrouter_config_status()` → `api_key_preview` (`config.py:196-200`). See [§6 CRITICAL-3](#6-critical-findings).
- **SECURITY** `main.py:102-103` — `?token=` accepted as the full credential; `maintenance.setup_logging` attaches a file handler to `uvicorn.access` (`maintenance.py:67-68`), so every such URL writes the bearer token in cleartext to `logs/app.log`. No way to disable the query-param path.
- **SECURITY** `main.py:104` — `supplied != AUTH_TOKEN` is a non-constant-time comparison; should be `hmac.compare_digest`.
- **SECURITY** `main.py:37` — `AUTH_TOKEN` empty by default, so the middleware no-ops and every endpoint including all deletes and all model-mutating Revit calls is fully open.
- **ERROR-GAP** `main.py:85-87` — `except Exception: pass` → `return "completed"`. Any artifact read failure is reported to the live UI as the step having completed — a fake-success headline on the honesty-critical progress stream.
- **HARDCODE** `main.py:40-50` — `STEP_BY_PATH` duplicates route strings declared in the routers; a rename silently drops instrumentation.

### backend/app/config.py — 207 LOC

| Function | Purpose |
|---|---|
| `__getattr__(name)` | PEP-562 resolver: `ARTIFACT_DIR` etc. from the `_PROJECT_SLUG` ContextVar. |
| `slugify(name)` | Lowercase, non-alnum→`-`, truncate to 48. Also the path-traversal sanitizer for project names. |
| `active_project()` | Persisted slug, else `"madera"`. |
| `bind_project(slug)` | Binds this request context and mkdirs the four dirs. |
| `set_active_project(slug)` | `bind_project` + persists under `_ACTIVE_LOCK`. |
| `memory_path()` | Cross-project teach memory. |
| `sheet_calibration_path(sheet)` | Per-sheet calibration path; sanitizes to `[A-Z0-9-]`. |
| `openrouter_config_status()` | Key-present flag, key preview, model, base URL. |
| `artifact_path(key)` | `ARTIFACT_DIR / ARTIFACT_FILES[key]`. |

- **SECURITY** `config.py:196-200` — `api_key_preview` reconstructs 12 characters of the live key and is served unauthenticated.
- **HARDCODE** `config.py:63` — default slug `"madera"`, no env override; `:104,106` — legacy migration target literally `PROJECTS_DIR / "madera"`; `:131-134` — `review_*` artifact keys map to `s201_*` filenames for every project and every sheet.
- **HARDCODE (env-overridable — OK)** `config.py:186` `"deepseek/deepseek-v4-pro"` (`OPENROUTER_REASONING_MODEL`); `:189` base URL (`OPENROUTER_BASE_URL`).
- **ERROR-GAP** `config.py:58-62` — `except Exception: pass`; a corrupt `active_project.json` silently redirects every artifact write to `madera`.
- **ERROR-GAP** `config.py:114-115` — `_migrate_legacy_layout()` and `set_active_project()` run at **import time**, so importing `app.config` renames directories and writes a file as a side effect. `item.rename()` (`:111`) is unguarded — a locked file aborts the migration midway with no rollback.

### backend/app/progress.py — 76 LOC

| Function | Purpose |
|---|---|
| `emit(step, kind, message, data)` | Append to the 500-entry ring under a lock. Never raises. |
| `events_since(seq)` | Events newer than `seq`. |
| `sse_stream(poll_s=0.25)` | Async generator yielding `text/event-stream` frames. |

- **ERROR-GAP** `progress.py:45-46` — documented deliberate swallow, but a broken ring is indistinguishable from an idle pipeline.
- `progress.py:59-64` — unbounded `while True` with no client-disconnect check; relies entirely on Starlette cancelling the generator.

### backend/app/maintenance.py — 78 LOC

| Function | Purpose |
|---|---|
| `gc_evidence_crops(cap_mb)` | Deletes oldest `evidence/*.png` until under the cap. |
| `setup_logging(log_file)` | Idempotent rotating handler on root + three uvicorn loggers. |
| `run_startup()` | Called once from `create_app()`. |

- **HARDCODE (all env-overridable — OK)** `maintenance.py:16-19` — `QAQC_EVIDENCE_CAP_MB`, `QAQC_LOG_FILE`, `QAQC_LOG_MAX_BYTES`, `QAQC_LOG_BACKUPS`.
- **ERROR-GAP (boot-blocking)** `maintenance.py:34-38` — `p.stat()` in the sort key and the size sum are outside the `try`; only `png.unlink()` is guarded. A file deleted between glob and stat raises `FileNotFoundError` out of `run_startup()` → `create_app()` → **the server fails to boot**.
- **SECURITY (low)** `maintenance.py:67-68` — attaching the handler to `uvicorn.access` is what turns `?token=` into a durable on-disk credential leak.

### backend/app/openrouter.py — 253 LOC

| Function | Purpose |
|---|---|
| `call_llm(...)` | One single-turn completion; returns a status dict and logs every attempt. |
| `call_chat(...)` | Multi-turn variant with function-calling `tools`; powers `chat_agent`. |
| `read_call_log()` | Parse the call log. |
| `call_status_summary()` | Aggregate for `/api/health` and the UI panel. |
| `_append_log(entry)` | Read-whole-file → append → rewrite-whole-file, per call. |

- **ERROR-GAP** `openrouter.py:20-31` — O(n²) growth with no cap or rotation; `write_text` (`:31`) unguarded, so a disk-full error kills a request whose LLM call already succeeded.
- **ERROR-GAP** `openrouter.py:219-227` — `read_call_log` catches only `JSONDecodeError`; an `OSError` escapes into `/api/health`.
- **HARDCODE** `openrouter.py:91,181` — `"HTTP-Referer": "https://localhost/qa-qc-final-prototype"` on every request, no env override; `:40-42,134-136` — `max_tokens`, `temperature`, `timeout` as bare defaults.
- Timeouts *are* passed to `urlopen` (`:99,189`); single attempt, no retry storm. Good.

### backend/app/chat_agent.py — 775 LOC

| Function | Purpose |
|---|---|
| `ChatUnavailable` | Raised when the LLM is unreachable. **Defined twice** (`:33`, `:350`). |
| `load_memory` / `save_rule` / `build_overrides` / `apply_on_extract` / `list_rules` / `delete_rule` | Teach-memory surface over `_`-prefixed copies of teach.py's engine. |
| `run_chat(message, history, llm=)` | Tool loop: system prompt → LLM(tools) → execute → feed back, capped at `MAX_TOOL_ROUNDS`. |
| `TOOLS` / `TOOL_IMPLS` | 8 tool schemas and implementations. |
| `_tool_get_counts` … `_tool_focus_element` | The read-mostly toolbox. |
| `_unrecognized_report(ei)` | Proactive "teach me this" items. |
| `_leaked_tool_calls(content)` | Scrubs textual tool-call markup some models emit as prose. |
| `_default_llm(messages, tools)` | Adapter onto `openrouter.call_chat`. |

- **DEAD CODE / DUPLICATION** `chat_agent.py:340-368` — `MAX_TOOL_ROUNDS`, `PIPELINE_WHITELIST`, `LLM`, `class ChatUnavailable`, `SYSTEM_PROMPT` defined a **second** time, byte-identical to `:26-50` including the duplicated comment. Verified by grep: `:26/:342`, `:29/:345`, `:31/:347`, `:33/:350`, `:36/:354`. The first `ChatUnavailable` class object is shadowed at `:350`.
- **DOCSTRING-MISMATCH** `chat_agent.py:6-9` — "the teach.py logic … is here as internal methods". It was **copied**, not moved: `teach.py` remains the live implementation for the HTTP surface (`routers/pipeline.py:373,643,648,654,660,699`), and `:95-336` is a near-verbatim duplicate of `teach.py:68-343`. Two divergent copies of one rules engine writing the same file.
- **ERROR-GAP** `chat_agent.py:571` — `json.loads(base_path.read_text(...))` unguarded; a truncated baseline 500s the chatbot, contradicting its own contract at `:467` ("narrates missing data, never 409s").
- **ERROR-GAP** `chat_agent.py:606-612` — audit log grows unbounded with the same read-append-rewrite pattern; `write_text` unguarded.
- **HARDCODE** `chat_agent.py:568,603` — `"run_baseline.json"` and `"chat_pipeline_audit.json"` bypass `config.ARTIFACT_FILES`, so `/api/artifacts` never lists them.
- `chat_agent.py:764` — `impl(**args)` with LLM-supplied kwargs is safe only because every `_tool_*` signature ends in `**_`.

### backend/app/teach.py — 371 LOC

| Function | Purpose |
|---|---|
| `load_memory()` | Reads global memory, one-time-migrating the legacy per-project file. |
| `add_entry(instruction, rule, reply, scope)` | Appends with a `max+1` id. |
| `delete_entry(entry_id)` | Removes by id. |
| `build_overrides(memory=None)` | Compiles entries into extractor overrides; drops invalid regexes. |
| `teach(message, context=None)` | LLM parse → deterministic fallback → persist → confirm. |
| `unrecognized_report(ei)` | Proactive teachable items. |

- **DOCSTRING-MISMATCH** `teach.py:1-3` — "rules persist to `ai_teach_memory.json`". They do not: `_save_memory` (`:88-89`) writes `config.memory_path()` = `artifacts/memory/global.json`; the named file is read once as a legacy source (`:72-79`) and never written again.
- **ERROR-GAP** `teach.py:89` — non-atomic whole-file write of the **cross-project** rules file; `load_memory` (`:83-84`) silently returns empty on `JSONDecodeError`, so a torn write erases every taught convention with no error surfaced.
- **ERROR-GAP** `teach.py:242-247` + `:225-230` — when the LLM returns junk, the fallback always succeeds with `kind="note"`. Net effect: `teach()` can never report failure.
- **HARDCODE** `teach.py:30-38` — `CATEGORIES` and English trade vocabulary fixed in source; `:40` — `_TOKEN` caps recognizable marks at 4 letters + 3 digits.

### backend/app/review.py — 413 LOC

| Function | Purpose |
|---|---|
| `load()` | Reads `review_comments.json` or a fresh skeleton. |
| `add_comment(element, comment, author)` | Stores a comment **and** runs it through `teach.teach()`. |
| `set_disposition(element_id, disposition)` | confirmed-issue / false-alarm / fixed-in-model. |
| `build_queue(element_list)` | Review items joined with comments and dispositions. |
| `render_evidence_crop(pdf, page, pdf_pt, revit_pt, dpi)` | PyMuPDF PNG crop with PDF/Revit rings and a gap line. |
| `analyze(element_id, element_list, registry)` | Deterministic mismatch analysis; no LLM. |
| `evaluate(element_id, comment, analysis)` | LLM judges the reviewer's explanation against the deterministic facts. |
| `resolve(element_id, action, comment, ...)` | Human accept/reject; accept flips every appearance to MATCH. |
| `apply_stored_resolutions(element_list, registry)` | Re-applies prior accepts after a fresh match run. |

- **HARDCODE** `review.py:205` — `dot / (na*nb) >= 0.8 and 0.5 <= nb/na <= 2.0`: three unnamed magic numbers deciding whether a mismatch is "systematic", which produces the "accepting as a match is defensible" language at `:214-219`. `:207` — `max(2, len(peers)//2)`; `:222` — `dist <= 3.0` ft. All unnamed, beside the *named* `CROP_HALF_PT` and `MEMBER_ATTACH_MAX_FT`.
- **ERROR-GAP (audit integrity)** `review.py:270-274` — on unparseable LLM JSON the reasoning is prefixed "LLM unavailable", which is false: the LLM *was* called and *did* answer. The distinction matters for an audit trail that exists to prove whether the LLM ran.
- **ERROR-GAP** `review.py:46` + `:38-41` — non-atomic whole-file write; `load` silently returns an empty skeleton on `JSONDecodeError`, so a torn write erases every human disposition and accepted resolution.
- **ERROR-GAP** `review.py:302-326` — when `device is None`, `resolve()` returns a success-shaped `{"action":"accept", "updated_element_ids": []}` for an accept that changed nothing and was never persisted.
- `review.py:60` + `teach.py` finding above — every reviewer comment mints a **global cross-project** memory rule.
- `review.py:63` — comment ids use the `len+1` pattern that `teach.add_entry:96-97` documents as a bug.

### backend/app/review_overlay.py — 469 LOC *(frozen)*

| Function | Purpose |
|---|---|
| `render_s201_page_png(pdf, page_index, out, dpi)` | Rasterizes one page; returns `(path, w_pt, h_pt)`. |
| `build_review_items(compare_report, page_w, page_h)` | Per-verdict overlay specs, drawable accounting, counts. |
| `build_overlay_svg(items_payload, show_match)` | SVG in PDF-point space. |
| `render_annotated_png(page_png, items, out, dpi, show_match)` | Burns overlays onto the PNG with PIL. |
| `build_and_save(...)` | Writes the four `s201_*` artifacts. |

- **HARDCODE** `review_overlay.py:2-11,32,38,163,167,354-380` — "S-201" in the module name, docstring, function name, schema string, and all four output filenames, while `build_and_save` takes an arbitrary `page_index` (`:347`) and happily renders any sheet.
- **ERROR-GAP** — the module has **zero** exception handling. `fitz.open` (`:39`), `pix.save` (`:47`), `Image.open` (`:301`), `img.save` (`:341`), `write_text` (`:373,381`) are all unguarded, and `build_and_save` writes four files in sequence with no rollback: a failure at step 4 leaves a page PNG and an SVG on disk disagreeing with an absent items JSON.
- **ERROR-GAP** `review_overlay.py:269` — `f"{item['distance_pt']:.1f}"` guarded only by `is not None`; a string distance raises `ValueError` mid-render.
- `review_overlay.py:88` — multiple rows lacking both ids collapse to `"unknown"`, making `undrawable_ids` ambiguous.

### backend/app/phase_summary.py — 245 LOC

| Function | Purpose |
|---|---|
| `upload(manifest, ei, pi)` | Page/sheet/table counts and the detected plan sheet. |
| `auto_benchmark(proposal, stamped)` | The two chosen intersections, their spread, stamp verification. |
| `revit_placement(proposal, payload)` | Per-mark read-back coordinates and worst Δ. |
| `registration(calibration)` | Scale, rotation, source, confidence, RMS, MATCH allowed. |
| `match(element_list, systematic, sampled)` | Totals by status plus shared-shift fraction. |
| `count_systematic(element_list, registry, cap)` | `(systematic, sampled)` over LOCATION_MISMATCH rows, capped. |
| `load()` / `record(phase, text)` | Read; emit + persist (never raises). |

- **ERROR-GAP** `phase_summary.py:189-191` — `except Exception: continue`. If `review.analyze` raises for every row, `sampled` stays 0 and `match()` omits the sentence — the summary reads as if analysis ran and found nothing.
- **ERROR-GAP** `phase_summary.py:231-232` — documented deliberate swallow, but it also hides the write failure, so the file can silently stop updating.
- **HARDCODE** `phase_summary.py:36` — `SYSTEMATIC_SAMPLE_CAP = 30` (named, with rationale); `:25-31` — `PHASE_STEPS` hand-mirrored by `app.js:175-176`.
- Docstring claim at `:5-6` ("no LLM, no estimation, no project-specific constants") is **accurate** — verified across all six builders.

### backend/app/benchmarks.py — 36 LOC

| Function | Purpose |
|---|---|
| (module) | Back-compat shim re-exporting the benchmark surface from `benchmark_workflow`. |

- **DEAD** — the only repo-wide hit for `import benchmarks` is the untracked `backend/_merge_teach.py`. `:19-21,32-34` also re-export three **private** helpers, contradicting the "legacy public surface" framing at `:5-6`.

### backend/app/benchmark_workflow.py — 610 LOC

| Function | Purpose |
|---|---|
| `extract_pdf_benchmarks(pdf, page_index, marks)` | Annotation pass then vector-crosshair fallback; duplicate mark across pages = hard error. |
| `default_state()` / `load()` / `save(wf)` | The persisted workflow document. |
| `transition(wf, to_state, actor, note, payload)` | Validated state change; raises `ValueError` on an illegal edge. |
| `bubble_row_positions(...)` | Crowded-sheet grid-bubble detector. |
| `resolve_pdf_grid_points(...)` | Axis-agnostic intersection resolver joined against Revit grid ids. |
| `pick_max_diagonal_pair(points)` | The two furthest-apart points. |
| `propose_from_geometry(...)` / `propose_from_points(...)` | Automatic and manual proposals. |
| `verify_stamped_benchmarks(...)` | Reads the PDF back, checks each mark landed within tolerance of the approved point. |

- **ERROR-GAP** `benchmark_workflow.py:289-293` — `load()` calls `json.loads` with **no** try/except, unlike every other loader in the codebase. A corrupt workflow file 500s the whole autopilot wizard instead of resetting to `idle`.
- **ERROR-GAP** `benchmark_workflow.py:296-299` — non-atomic whole-file write of the audit-trail document. Torn write + unguarded load = unrecoverable.
- **ERROR-GAP** `benchmark_workflow.py:156-159` — a PyMuPDF failure on one annotation is indistinguishable from "not a benchmark", so a page whose annotations all fail reports "Mark(s) not found" (`:110-112`) rather than "could not read annotations". Same shape at `:171-173`.
- **HARDCODE** `benchmark_workflow.py:47-52,62` — mark pattern, `ANNOT_TYPES`, radii, and a hardwired exactly-two-benchmarks assumption (`propose_from_points:536` rejects anything else); `:186,200,203,210` — four unnamed geometric tolerances in the crosshair detector, in contrast to the named `VECTOR_R_MIN/MAX` directly above; `:355-356,398` — band/tolerance literals.
- **PERF** `:375-388` and `:409-422` are O(n²) over every candidate word, and `richest` is called twice then cross-producted (`:427-428`). Unbounded by input size.

### backend/app/scene3d.py — 207 LOC

| Function | Purpose |
|---|---|
| `build_scene(raw_revit, element_list, ai_revit)` | Walls, hold-downs, openings, v3 category elements, framing, benchmarks, grids, bounds, counts, `z0` datum. |

- **DOCSTRING-MISMATCH** `scene3d.py:5-7` — "Wall height is NOT in the export — it is emitted with `height_assumed=true` … never presented as model truth." `:56,62-63` read `w.get("height_ft")`, which `revit_v3_adapter.adapt_raw:184` populates from real v3 exports, and set `height_assumed = not real_height`. For a v3 export the docstring states the opposite of what the code does; only the inline comment at `:56` is current.
- **HARDCODE (unflagged default)** `scene3d.py:59` — `w.get("thickness") or 0.5`: an unnamed 0.5 ft wall thickness substituted for missing data with **no** `assumed` flag, unlike `ASSUMED_WALL_HEIGHT_FT` (`:18`) which is both named and surfaced to the UI.
- **HARDCODE** `scene3d.py:133-134` — unnamed 0.15 ft minimum framing-box dimension; `:69` — `"base_ft": 0.0` for every wall regardless of actual base.
- **ERROR-GAP** `scene3d.py:43-46,118` — `ref["kind"]` and `e["status"]` direct subscripts fail the whole 3D payload rather than skipping the row, contrasting the defensive `.get()` used elsewhere in the same loop. No exception handling in the module; float coercions at `:73-74,94-95,143,165-166` raise on a null coordinate.

### backend/app/revit_bridge.py — 738 LOC

| Function | Purpose |
|---|---|
| `BridgeError` | Revit-side failure (family missing, copy failed, connector off). |
| `benchmark_family(override)` | arg → `QAQC_BENCHMARK_FAMILY` → built-in default, read at call time. |
| `place_sequence(call, proposal, family, tol)` | Locate template → copy per benchmark → set Mark → read back → verify. |
| `connection_locations_sequence(call)` | Live Structural-Connection ids + (x, y). |
| `live_connection_locations(force)` | 5-min-cached wrapper; never raises. |
| `select_elements` / `get_selection` / `element_location` | Live selection and single-element location. Never raise. |
| `get_selected_element_full()` | Richest-source-first: revit-mcp socket, else Nonica. |
| `scene_geometry_sequence(call, max_per_cat, chunk)` | Per-category bounding-box massing with chunking. |
| `live_scene_geometry(force)` | 60 s-cached wrapper; never raises. |
| `status()` | Connection status. |
| `place_benchmarks(proposal, family)` | Live BM-1/BM-2 placement; probes the connector first. |

- **SECURITY** `revit_bridge.py:32-34` — `NONICA_EXE` defaults to an absolute machine path and its env override (`NONICA_MCP_EXE`) is the **only** control over which executable the backend spawns (`:664`). Anyone who can set the process environment chooses the binary. No `shell=True`, no request-time argv.
- **HARDCODE (best-handled in the file)** `revit_bridge.py:38` — `DEFAULT_BENCHMARK_FAMILY = "mwfBenchmark"` now has both an argument and `QAQC_BENCHMARK_FAMILY` (`:44-49`) plus an operator hint at `:40-41`. **This is `HARDCODING_AUDIT.md` blocker #1, now FIXED.**
- **HARDCODE** `revit_bridge.py:36,227,494-500` — `MARK_PARAM_ID`, `STRUCT_CONNECTIONS_CAT`, four `SCENE_CATEGORIES` ids: named, no env override. `:37,229,501-504,655,660,401` — tolerances/TTLs/timeouts, named, no override. `:397` `REVIT_MCP_ADDR` **has** an override.
- **HARDCODE (comment)** `revit_bridge.py:97` — cites the model title `'10510 Madera Dr…'`; `:393` — cites the operator's own `%APPDATA%\Autodesk\Revit\Addins\...` path.
- **ERROR-GAP** `revit_bridge.py:462-463` — `except Exception: pass` swallows *every* revit-mcp failure including a malformed `res["Id"]` (`:426`), so a genuine data bug is indistinguishable from "server not started" — which is all the comment names.
- **ERROR-GAP (info leak)** `revit_bridge.py:290-292,329-331,352-353,370-371,644-645` — five handlers surface the raw exception text to the API caller; on a spawn failure that string contains the full `NONICA_EXE` filesystem path.
- **ERROR-GAP** `revit_bridge.py:408-417` — `_revit_mcp_call`'s read loop is `while True` bounded only by the socket timeout; a peer streaming non-JSON without closing grows `buf` unbounded for 10 s. No size cap.
- **ERROR-GAP (self-check)** `revit_bridge.py:752` — `assert benchmark_family() == DEFAULT_BENCHMARK_FAMILY  # no env set here` fails whenever `QAQC_BENCHMARK_FAMILY` is set — the exact configuration the feature exists to support.
- **Good:** `_looks_connected_payload` / `_unrecognized` (`:68-81`) refuse to report "the model has none" from an unparseable response, applied consistently at `:142,257,262,572`.

### backend/app/revit_convert.py — 360 LOC *(frozen, v2 path)*

| Function | Purpose |
|---|---|
| `convert_revit(raw_json, source_file)` | family dictionary → body/member split → LLM enrichment → nearest-body attachment → QA warnings → `AIConvert_revit`. |
| `_llm_enrichment(family_dict)` | Asks OpenRouter to classify each family; degrades to `parsed=None`. |
| `_learned_key_points(records, family_dict, raw)` | The `learned_key_points` block emitted into every artifact. |
| `_build_family_dictionary(records)` | Per-family counts, classification, core token, mapped mark. |

- **HARDCODE (load-bearing, unfixed)** `revit_convert.py:268,270,321,323` — `pdf_baseline = {"H1":10,"H2":21,"H3":6,"H4":17}` applied unconditionally to **every** project, emitting a QA warning per mark and re-embedding the dict into `revit_count_diagnostics` of every artifact. `compare.py:490-491` documents this exact dict as removed under R-27; `convert_revit` is still live at `routers/pipeline.py:94,144`, so the fix never reached this call path.
- **DOCSTRING-MISMATCH** `revit_convert.py:92-99` — the field `naming_patterns_observed` inside `learned_key_points` is a **static** three-element list of prose literals naming SHDU11/SHDU6/SHD10S/SHD15B. Nothing is observed and nothing is learned; it is a constant emitted as if it were a finding. Same for `:100` `core_token_to_pdf_mark` (a static import) under "learned".
- **DOCSTRING-MISMATCH** `revit_convert.py:110-113` — "proof the AI layer was actually invoked". The parsed result is written only to side fields (`:165-168,172`) and never influences classification, grouping, marks, or warnings, while `ai_model_used` (`:159,340`) reports the model name for a pure no-op cross-check.
- **HARDCODE** `revit_convert.py:128-131` — the system prompt enumerates the Simpson token set for every client; `:21,24,203` — `MEMBER_KEYWORDS`, `MEMBER_ATTACH_MAX_FT`, and an unnamed `0.9 / 0.4` confidence pair.
- **ERROR-GAP** `revit_convert.py:238` — `if dist <= best_dist:` with `best_dist` initialized to the attach threshold (`:227`) makes an evidence member exactly 3.0 ft from two bodies attach non-deterministically w.r.t. record order.

### backend/app/revit_ids.py — 47 LOC

| Function | Purpose |
|---|---|
| `unique_id_to_element_id(unique_id)` | Trailing 8 hex XOR the last 8 hex of the GUID's final group; raises on a non-UniqueId. |

- **Clean.** The one place in the codebase that deliberately refuses a fallback: it raises rather than returning a plausible-but-wrong id, and the self-check (`:32-46`) asserts the naive decode *would* have been wrong.
- `revit_ids.py:22` — `parts[-2][-8:]` assumes the standard 5-group GUID shape; a differently-grouped GUID silently decodes against the wrong bytes (the `:18-20` guard only checks `len(parts) >= 2`).
- **HARDCODE (comment only)** `revit_ids.py:7` — provenance note naming Madera elements.

### backend/app/revit_v3_adapter.py — 461 LOC

| Function | Purpose |
|---|---|
| `is_v3(raw)` | `schema_version` starts with "3". |
| `holdown_variant_key(text)` | `'SHDU15S-WITH BOLT'` → `'HD15S'`. |
| `spec_to_mark_map(element_intelligence)` | Variant key → plan mark, learned from parsed schedule rows. |
| `spec_map_from_pdf_tables(ei, pdf_path)` | Geometry fallback re-reading words inside each table bbox. |
| `normalize_point_mark(mark)` | `'P-01'` → `'P-1'`. |
| `adapt_raw(v3)` | v3 export → `raw_revit`-compatible dict. |
| `build_ai_revit(v3, spec_to_mark)` | Clusters hold-down records by plan proximity, splits multi-body clusters, assigns marks. |

- **DOCSTRING-MISMATCH** `revit_v3_adapter.py:14-15` — "Data-driven: no hardcoded client vocabulary." Simpson vocabulary is hardcoded in three places: `HOLDOWN_FAMILY_RE` (`:30`), `BOLT_FAMILY_RE` (`:32`), `_SCHED_MARK_RE` (`:78`), and `:27-29` names both source clients. Mark *assignment* is data-driven; *recognition* is not — an unrecognized prefix makes `_holdown_records` (`:259-260`) skip the element and the whole report reads PDF_ONLY.
- **ERROR-GAP (fabricated coordinate)** `revit_v3_adapter.py:260` — `point = (e.get("location") or {}).get("point") or [0,0,0]`. A hold-down with no exported location is silently assigned the model origin, clustered at (0,0) with every other location-less hold-down (`:288-297`), and emitted with `center_point {x:0,y:0}` into distance-gated MATCH logic. Should be skipped or flagged, not defaulted.
- **ERROR-GAP** `revit_v3_adapter.py:98` — unguarded `fitz.open` inside a function whose entire purpose is to be a fallback; contrast the `ImportError` path two lines above (`:94-96`) which returns `{}`.
- **HARDCODE** `revit_v3_adapter.py:33,128,305,347` — `CLUSTER_TOL_FT`, an unnamed 4.0 row-band tolerance, an `"offset" not in fam.lower()` string heuristic deciding body vs companion, and an unnamed `0.9 / 0.5` confidence pair. `:243-248` — four Revit category literals, correctly surfaced as `searched_categories` (`:366`) so "0 found" is readable.
- `revit_v3_adapter.py:290-297` — greedy first-fit clustering: membership depends on iteration order, and a chain each 2 ft from the last absorbs into one cluster. Partially compensated by the per-body split at `:307-325`.

---

## 3. Backend — routers

### backend/app/routers/common.py — 88 LOC

| Function | Purpose |
|---|---|
| `project_context(request)` | Route dependency: `X-Project` header → `?project=` → persisted active → `config.bind_project`. |
| `make_router()` | `APIRouter(dependencies=[Depends(project_context)])`. |
| `save_artifact(key, data)` / `load_artifact(key)` | Write / read JSON artifact (409 if absent). |
| `project_pdf_path()` | Manifest PDF → env sample → 409. |

- **ERROR-GAP (systemic)** `common.py:71` — existence is checked (`:65-70`) but **validity is not**. A truncated artifact raises `JSONDecodeError` → HTTP 500 on every endpoint calling `load_artifact`: `/api/elements`, `/api/devices`, `/api/review/queue`, `/api/compare/ai`, `/api/elements/match`, `/api/pdf/ai-convert`, `/api/registration/auto-holdown`, `/api/registration/benchmarks`, `/api/revit/element-ids/*`, `/api/review/build`, `/api/export/punch-list.csv`. `OSError`/`UnicodeDecodeError` likewise. **This one guard is the single highest-leverage error-handling fix in the backend.**
- **ERROR-GAP** `common.py:78` — corrupt `project_manifest.json` → 500 instead of the intended 409.

### backend/app/routers/system.py — 79 LOC

| Endpoint | Purpose |
|---|---|
| `GET /api/health` (`:19`) | Status, artifact presence, OpenRouter summary, registration state. |
| `GET /api/artifacts` (`:47`) | Registry listing with sizes and URLs. |
| `GET /api/artifacts/{filename}` (`:63`) | Serves one artifact. |
| `GET /api/openrouter/log` (`:74`) | Summary + full call log. |

- **SECURITY (traversal — correctly guarded)** `system.py:66-67` — `safe = Path(filename).name`. The **only** endpoint that sanitizes a URL-supplied filename. Note it serves any file in the artifact dir, not just `ARTIFACT_FILES` names.
- **SECURITY** `system.py:29,39-42` — `/api/health` is auth-exempt and leaks the absolute `artifact_dir` and sample-input paths, plus the API-key preview via `:31`.

### backend/app/routers/projects.py — 132 LOC

| Endpoint | Purpose |
|---|---|
| `GET /api/projects` (`:19`) | Workspace listing. |
| `POST /api/projects/activate` (`:49`) | Persists the active slug. |
| `POST /api/upload` (`:62`) | Multipart PDF + Revit JSON; writes the manifest. |

- **ERROR-GAP** `projects.py:85` — `fitz.open(pdf_path)` unguarded: a non-PDF or corrupt upload → **HTTP 500**. The sibling Revit-JSON branch does it right (`:92-94` → 400).
- **ERROR-GAP** `projects.py:78,103,106` — corrupt manifest, and `adapt_raw` / `_maybe_auto_advance_export` unguarded against malformed-but-valid-JSON v3 payloads.
- **SECURITY** `POST /api/upload` unconditionally overwrites `uploads/input.pdf` and `uploads/input_revit.json` (`:81-82,95-96`) and mutates global active-project state (`:75`), with no auth by default and **no file-size limit** — `await pdf.read()` (`:82`) loads the whole upload into memory.
- **SECURITY (traversal — guarded)** `projects.py:75` + `config.slugify` (`config.py:48-52`), and `:55-57` slugify + `is_dir()`. Both safe.

### backend/app/routers/pipeline.py — 701 LOC

| Endpoint / Function | Purpose |
|---|---|
| `_uploaded_pdf()` (`:46`) | Path to `ARTIFACT_DIR/uploaded_madera.pdf`. |
| `_spec_map_with_fallback(ei)` (`:52`) | Schedule spec→mark map with PDF-geometry fallback. |
| `POST /api/revit/ai-convert` (`:69`) | v2 or v3 Revit conversion. |
| `POST /api/pdf/page-intelligence` (`:159`) | Frozen S-201 detector with generic fallback. |
| `POST /api/pdf/ai-convert` (`:208`) | PDF normalization + LLM mapping confirmation. |
| `POST /api/compare/ai` (`:281`) | Hold-down compare, optional A2 re-fit. |
| `POST /api/elements/extract` (`:369`) | Generalized multi-element extraction. |
| `GET /api/elements/intelligence` (`:382`) | The extraction artifact. |
| `POST /api/elements/match` (`:387`) | Per-sheet matching + unified element list. |
| `POST /api/teach/chat` (`:638`) · `GET/DELETE /api/teach/memory` (`:646,652`) · `GET /api/teach/unrecognized` (`:657`) | Teach surface. |
| `GET /api/pipeline/events` (`:666`) · `GET /api/pipeline/status` (`:678`) | SSE stream and snapshot. |

- **HARDCODE** `pipeline.py:49` — `"uploaded_madera.pdf"`, still the write target for the direct-upload branch (`:185-186`). Note the split: `/api/upload` writes `uploads/input.pdf` (`projects.py:81`) but this branch writes elsewhere — two different "the project PDF" paths.
- **HARDCODE** `pipeline.py:399,402` — `compare_sheet = "S-201"` default in two places, even though `elements.py:73-75` documents that the primary sheet is project-specific; `:413` — `V3_POINT_CATEGORIES` hardcoded mark prefixes; `:226,318` — `MIN_REFIT_PAIRS = 8`, `ELEVATION_BAND_GAP_FT = 6.0` (named, undocumented).
- **DOCSTRING-MISMATCH** `pipeline.py:169-170` — comment claims the fallback is for "Not an S-201/H1-H4 drawing set", but the branch condition is simply `result.get("error")`. **`HARDCODING_AUDIT.md` blocker #2 remains open**: there is still no sanity check, so a wrong-layout sheet that "succeeds" never reaches the generic path.
- **DOCSTRING-MISMATCH** `pipeline.py:389-390` — "Run shear-wall matching … and build the unified element list" understates a large side-effecting write path: per-sheet holdown compares (`:491-511`), **writes** per-sheet calibrations (`:508-510`), posts/columns compares (`:513-534`), the device pass (`:551`), in-place row mutation (`:556-570`), REVIT_ONLY deletion (`:574-580`), resolution re-application (`:616`), and four artifacts plus a phase summary (`:626-631`).
- **ERROR-GAP (500 on malformed artifact)** `:85-86`, `:114`, `:127-128`, `:175`, `:214`, `:293`, `:302`, `:396`, `:401` — all `.exists()`-guarded only.
- **ERROR-GAP (KeyError → 500)** `:458-459`, `:466`, `:496-497`, `:525-527` — direct subscripts on artifact data.
- **ERROR-GAP** `:62-63` `except Exception: mapping = {}`; `:485-486` `except Exception: segments = None` (documented, but hides all `fitz` failures); `:446-447` `except JSONDecodeError: pass`.
- **CORRECTNESS** `pipeline.py:350-351` — `kept = [...]` then `in_band = kept`, so `assemblies_in_band` and `assemblies_kept` (`:357-358`) are always identical and the "in band" figure is meaningless.
- **SECURITY** `pipeline.py:508-510` — `config.sheet_calibration_path` sanitizes to `[A-Z0-9-]`. Safe. `POST /api/teach/chat` (`:638`) forwards an arbitrary client dict into `teach.teach` unvalidated. `DELETE /api/teach/memory/{entry_id}` is destructive with no auth by default (id is compared, never path-joined).

### backend/app/routers/elements.py — 465 LOC

| Endpoint / Function | Purpose |
|---|---|
| `GET /api/elements` (`:20`) · `GET /api/devices` (`:25`) · `GET /api/scene3d` (`:31`) | Artifact reads (scene3d builds on demand). |
| `GET /api/sheets/{sheet}/page.png` (`:46`) | Renders and caches any sheet's page. |
| `GET /api/sheets/primary` (`:67`) | The project's compare sheet. |
| `POST /api/review/build` (`:86`) | Builds the overlay artifacts. |
| `GET /api/review/items` (`:120`) | Items JSON, built on demand. |
| `GET /api/review/page.png|overlay.png|overlay.svg` (`:148,160,172`) | Overlay artifacts. |
| `_find_element(element_id)` (`:187`) | Lookup or 404. |
| `GET /api/review/queue` (`:195`) | The review queue. |
| `POST /api/review/{id}/comment|disposition|evaluate|resolve` (`:200,209,229,244`) | Human review actions. |
| `GET /api/review/{id}/analysis` (`:218`) · `evidence.png` (`:270`) | Deterministic analysis; PDF crop. |
| `GET /api/metrics/accuracy` (`:287`) | Honest accuracy/coverage. |
| `POST /api/runs/baseline` (`:343`) · `GET /api/runs/compare` (`:363`) | Baseline save and diff. |
| `GET /api/export/punch-list.csv` (`:427`) | Actionable non-MATCH CSV. |

- **SECURITY (path traversal — unguarded join)** `elements.py:50` — `cache = config.PAGES_DIR / f"{sheet}_{dpi}.png"` with `sheet` straight from the URL (only `.upper()` at `:49`). No `Path(...).name` guard as in `system.py:66`. When `cache.exists()` the function returns at `:64` **without ever consulting** `element_intelligence.json`, so the sheet-existence check at `:53-57` is not a security control. Exploitability is limited (Starlette's `{sheet}` does not match `/`, and the target must be named `<X>_<72..300>.png`), but on Windows a `%5C` segment is a separator and the join itself is unvalidated.
- **SECURITY (artifact-controlled absolute path)** `elements.py:101,104` — `pdf_path = Path(source_file)` then `Path(root) / source_file`, where `source_file` is read from `pdf_page_intelligence.json` (`:95`) with no containment check; an absolute value resolves outright. Same at `:132-138`. Artifact-derived today, but `/api/upload` is unauthenticated and feeds the pipeline that writes it.
- **SECURITY (missing auth, all default-open)** `POST /api/runs/baseline` (`:343`), `POST /api/review/{id}/resolve` (`:244`, rewrites three artifacts), `POST /api/review/{id}/disposition` (`:209`), `POST /api/review/build` (`:86`), and `GET /api/export/punch-list.csv` (`:427`) — which **writes to disk on a GET** (`:437-439`), a non-idempotent GET.
- **HARDCODE** `elements.py:93,128` — `page_intel.get("page_index", 4)`. A magic default: an artifact missing `page_index` silently renders page 5 of an unrelated PDF rather than erroring.
- **HARDCODE** `elements.py:157,169,181` — download filenames hardcoded `s201_*` regardless of the actual primary sheet; `:358,366,437` — `"run_baseline.json"` and `"punch_list.csv"` bypass `config.ARTIFACT_FILES`, so `/api/artifacts` never lists them; `:438,462-463` — inline status policy and truncation literals.
- **ERROR-GAP** `elements.py:60-63` — `doc[entry["page_index"]]` with no guard between an artifact-supplied index and the document: a stale `element_intelligence.json` after re-upload → `IndexError` → **500**.
- **ERROR-GAP** `elements.py:297,304` — `el["counts"]["by_status"]` / `["total"]` direct subscripts → **500** whenever `element_list.json` predates the `counts` block.
- **ERROR-GAP** `elements.py:450-463` — unguarded subscripts inside the CSV loop, with the file opened for write at `:439` — a `KeyError` mid-loop leaves a **truncated `punch_list.csv` on disk**.
- **ERROR-GAP** `elements.py:37,40,43,79,145,369,420-421,435` — `.exists()`-only or direct-subscript reads → 500.
- **DOCSTRING-MISMATCH** `elements.py:88,149,161,173` — all four say "S-201" while serving project-generic artifacts for whatever primary sheet the project has, which `:73-75` explicitly documents is often not S-201; the `filename=` kwargs bake the same wrong claim into the download. `:429` — "every actionable non-MATCH element" also skips `SPEC_ONLY` and `NOT_EVALUATED` (`:438`).

### backend/app/routers/registration.py — 293 LOC

| Endpoint / Function | Purpose |
|---|---|
| `POST /api/registration/manual` (`:27`) | Calibration from manual pairs. |
| `GET /api/registration` (`:50`) · `DELETE` (`:113`) | Global calibration read / delete. |
| `_primary_sheet()` (`:64`) | Compare sheet from `pdf_page_intelligence`. |
| `GET /api/registration/sheet/{sheet}` (`:76`) | Per-sheet calibration in the same shape. |
| `POST/GET /api/revit/control-points` (`:120,128`) · `/api/pdf/control-points` (`:138,154`) | Control-point CRUD. |
| `POST /api/registration/auto-grid` (`:159`) · `auto-holdown` (`:172`) | Grid and RANSAC calibration. |
| `POST/GET /api/pdf/benchmarks` (`:196,211`) · `POST /api/registration/benchmarks` (`:223`) | Benchmark extraction and 2-point calibration. |
| `POST/GET /api/revit/scope-diagnostics` (`:275,283`) | Scope diagnostics. |

- **SECURITY** `DELETE /api/registration` (`:113-117`) — destructive, unauthenticated by default; deletes the verified calibration and blanks the report with no confirmation, soft-delete, or audit record.
- **SECURITY (DoS)** `registration.py:180,184` — `iterations` is caller-controlled and unbounded, feeding a RANSAC loop on a sync (threadpool) endpoint. `{"iterations": 10**9}` is a trivial CPU DoS.
- **SECURITY** `/manual` (`:45-46`) writes the global calibration unconditionally with no auth, so any caller can overwrite a verified transform with garbage pairs. `/benchmarks` at least gates the write on `registration_usable` (`:267-270`).
- **SECURITY (traversal — correctly guarded)** `registration.py:81` — `config.sheet_calibration_path(sheet)` sanitizes to `[A-Z0-9-]` before the join.
- **HARDCODE** `registration.py:148` — `str(payload.get("sheet_number") or "S-201")`: a client omitting the field files its control points under S-201; `:179-180` — `16.0` / `4000` duplicated across both branches of one expression; `:262` — `expected_scale_pt_per_ft` default `18.0`; `:254` — magic minimum `3`.
- **ERROR-GAP (400 → 500)** `registration.py:183-184,205` — `float(threshold)` / `int(iterations)` / `int(page_index)` taken verbatim from the request body; `{"iterations":"lots"}` → `ValueError` → 500 instead of 400.
- **ERROR-GAP** `registration.py:40-44` — only `isinstance(point_pairs, list)` is checked (`:30`), so `[1,2,3]` reaches the math module → 500.
- **ERROR-GAP** `registration.py:236,249,252` — `.get` on `load_artifact("raw_revit")` assumes a dict; a top-level list → `AttributeError` → 500.
- **ERROR-GAP** `registration.py:256-257` — `except HTTPException: pass` around the chirality block catches only the 409; a `JSONDecodeError` from the same calls escapes and 500s, defeating the "best effort" intent at `:246`.
- **ERROR-GAP** `registration.py:135,220,290` — the three getters return a friendly `present: False` when the file is *missing* but 500 when it is *malformed*.

### backend/app/routers/revit.py — 388 LOC

| Endpoint / Function | Purpose |
|---|---|
| `_creation_element_ids(unique_ids)` (`:21`) | XOR-decode export ElementIds. |
| `_assemblies()` (`:33`) · `_optional_artifact(key)` (`:37`) · `_live_lookup(...)` (`:45`) | Artifact and live-lookup helpers. |
| `GET /api/revit/status` (`:79`) | Connector status. |
| `_assembly_status_index()` (`:89`) · `_with_connection_status(...)` (`:112`) · `_live_scene(...)` (`:132`) | Status join onto the live scene. |
| `GET /api/revit-live/scene` (`:137`) · `POST /api/revit-live/refresh-3d` (`:146`) | Live massing. |
| `GET /api/revit/element-ids/{assembly_id}` (`:152`) | Export vs live ids. |
| `POST /api/revit/highlight` (`:180`) | Selects elements in the live model. |
| `GET /api/revit/selection` (`:215`) · `lookup/{element_id}` (`:316`) · `selected-element` (`:323`) | Selection and explanation. |
| `_plain_english(...)` (`:221`) · `_explain_element(...)` (`:249`) | Deterministic explanation strings. |
| `POST /api/benchmark-workflow/place-markers` (`:343`) | Creates benchmark geometry in the live model. |

- **SECURITY** `POST /api/revit/highlight` (`:180`) mutates the live Revit selection from arbitrary caller-supplied ids, and `POST /api/benchmark-workflow/place-markers` (`:343`) **creates geometry in the user's live model** — both unauthenticated by default. `family` (`:357`) and `actor` (`:356`) are unvalidated free text; `actor` is written into the workflow audit trail (`:380-385`). Not shell injection (MCP transport is `StdioServerParameters(command=NONICA_EXE, args=[])`).
- **Good:** `place-markers` state guards at `:360-364`, `:366-367`, `:373-379` (409 on failed read-back verification, state left unchanged) make it the best-guarded handler in the router set.
- **DOCSTRING-MISMATCH** `revit.py:184-185` — "Connector off is an honest `ok:false`, **never a 500**". Contradicted in the same handler: `:190` `[int(i) for i in ...]` raises `ValueError`/`TypeError` → **500** on a malformed `element_ids`, and `:195` deliberately raises 404. The claim holds for connector state only. Same shape at `:328-329` vs `:336`.
- **ERROR-GAP** `revit.py:122-123` — `el["bbox_ft"]` then `b[0]..b[4]` on bridge data → 500 on `GET /api/revit-live/scene`.
- **ERROR-GAP** `revit.py:41-42` — `except HTTPException: return {}` in `_optional_artifact` catches only the 409; a corrupt artifact raises `JSONDecodeError` right through it, so the "artifact the lookup can live without" contract fails exactly when the file is damaged.
- **ERROR-GAP (silent)** `revit.py:26-29` — `except ValueError: pass` drops undecodable UniqueIds, so `creation_element_ids` can be shorter than `unique_ids` with no indication in the response (`:172-176`).
- **HARDCODE** `revit.py:86,153,182,249,317,324` — four different default proximity radii (`1.0`, `0.75`, `2.0`) across five endpoints, none explained relative to each other; `:18,70` — UI copy in the API layer.

### backend/app/routers/chat.py — 35 LOC

| Endpoint | Purpose |
|---|---|
| `POST /api/chat` (`:18`) | Agentic chat: reply, blocks, `ui_actions`. |

- **ERROR-GAP** `chat.py:27-28` — wrapped **only** for `ChatUnavailable`. Any network error, OpenRouter 4xx/5xx, JSON decode failure, or tool-loop exception → **HTTP 500**, contradicting the "honest, non-fatal" intent at `:29`.
- **SECURITY** `chat.py:23-25` — `history` is accepted with only `isinstance(..., list)` and fed straight into the LLM tool loop, so a client can forge prior assistant/tool turns and steer tool calls. No length or size cap on `message` or `history`. No auth by default on an endpoint that spends API credits and drives `ui_actions`.

---

## 4. Frontend

Entry: `frontend/index.html:256` → `<script type="module" src="src/app.js">`. Native ESM, no build step. `three` via importmap (`index.html:11-16`), `gsap` as a **non-module global** (`index.html:10`), used unimported in `util.js`, `pdf.js`, `viewer3d.js`, `chat.js`.

### frontend/src/api.js — 38 LOC

| Export | Purpose |
|---|---|
| `authToken()` | Reads `localStorage["qaqc_token"]`. |
| `tokenized(url)` | Appends `?token=` for EventSource / `<img>` / `window.open`. |
| `setProjectHeader(slug)` | Sets the `X-Project` header. **Dead** — see [§5](#5-dead-code). |
| `api(path, opts)` | fetch wrapper; unwraps `{detail}`, throws `Error`. |

- **ERROR-GAP** `api.js:32` — `catch { j = { raw: t } }` then `:35` falls through `j.detail` → `j.reason` → `r.status`, so a non-JSON error body loses its content and the user sees a bare status code.

### frontend/src/app.js — 302 LOC

| Export / Function | Purpose |
|---|---|
| `loadAll(first)` | Loads elements, intelligence, benchmarks into the store; drives every panel render. |
| `runExtract()` | POST extract + match, then `loadAll`. |
| `loadProjects()` | Fills the project switcher; activates and reloads. |
| `STEPS` | 11 pipeline step descriptors (icons, titles, endpoints, copy). |
| `replaySummaries()` | Replays `phase_summaries.json` into freshly-rendered step logs. |
| `openPipeline()` / `renderPipeline()` / `runStep(i)` | Pipeline modal render and step execution with endpoint fallback. |

- **XSS** `app.js:30` — `<option value="${x.slug}" …>📁 ${x.display_name…}</option>`: `slug` unescaped **in an attribute**, `display_name` unescaped in text. `app.js` does not import `esc` at all. `:214` — `${status.memory_rules || 0}`.
- **HARDCODE** `app.js:108,114,123` — "Madera sample", "H1–H4", "BM-1/BM-2" + `docs/BENCHMARK-SOP.md` in UI copy; `:175-176` — `PHASE_STEPS` hand-mirrors `phase_summary.PHASE_STEPS`, drift is silent; `:30,35,166` — magic `26`, `600`, `40`.
- **ERROR-GAP** `app.js:31-36` — the project-switch `await api(...)` is unguarded: on failure the toast and reload are skipped but the `<select>` still shows the new value, so **the UI lies about which project is active**.
- **ERROR-GAP** `app.js:37,61,62,180,198` — five bare `catch {}`; `:45-49` — `el.elements` / `el.counts.by_status.*` chained with no fallback, so a shape error is misreported as "no data yet".

### frontend/src/sse.js — 42 LOC

| Export | Purpose |
|---|---|
| `onStep(step, cb)` / `onAny(cb)` | Subscribe to one step / all events; return unsubscribe. |
| `startFallbackPoll(cb, ms=8000)` | Interval safety net. |
| `ensure()` | Lazily opens the single `EventSource`. |

- **ERROR-GAP** `sse.js:21` — `es.onerror = () => {}`: a permanently-dead stream is indistinguishable from an idle one. `:22` — outer `catch {}` around `new EventSource`; only the wizard has a fallback poll, so the pipeline modal (`app.js:144`) goes permanently silent.

### frontend/src/store.js — 39 LOC

| Export | Purpose |
|---|---|
| `store` | Mutable singleton: elements, sheets, cc, scene, filters, layers, drawer, sort. |
| `subscribe(key, fn)` / `emit(key, ...)` | Listener registry; `emit` swallows per-listener throws into `console.error`. |
| `select(id, origin)` | The one selection mutation; auto-opens groups, emits `"select"`. |

### frontend/src/util.js — 28 LOC

| Export | Purpose |
|---|---|
| `$(s)` | `querySelector` alias. |
| `esc(s)` | HTML-escapes `& < > " '` — **the only escaping helper in the app**. |
| `toast(msg, err)` | Transient toast via `textContent` (safe). |
| `COL`, `CATS`, `CAT_LABEL`, `DEFAULT_LAYERS`, `BENCHMARK_COLOR`, `RUN_STATUSES` | Status colors and category vocabulary. |

### frontend/src/panels/chat.js — 163 LOC

| Export / Function | Purpose |
|---|---|
| `initChat()` | Greeting + unrecognized-items card. |
| `bubble(who, html)` | Appends a `.msg` div via `innerHTML`. |
| `statusPill(status, n)` / `renderBlock(b)` / `renderBlocks(...)` | Pill markup; `count_card` / `status_breakdown` / `table` blocks; row → `select()` wiring. |
| `openPanel(panel)` / `applyUiAction(a)` | Executes bot `ui_actions`. |
| `loadUnknownCard()` / `send()` | Unrecognized card; POST `/api/chat` with last-8 history. |

- **XSS** `chat.js:31,37,38,60` — `${n}`, `<b>${v}</b>`, `${b.total}`, `${b.shown}` unescaped.
- **DEAD IMPORT** `chat.js:8` — `toast` imported, never called.
- **ERROR-GAP** `chat.js:111` — silent `catch` drops the whole unrecognized-items card.
- **HARDCODE** `chat.js:86-87` panel→button map; `:140` `history.slice(-8)`.

### frontend/src/panels/inspector.js — 320 LOC

| Export / Function | Purpose |
|---|---|
| `openDrawer(name)` | Shared open/close for inspector / chat / review / runs / revitlookup. |
| `renderInspector(e)` | Evidence panel: mark, ids, points, spec, reason, nearest candidates. |
| `renderCC()` | Count-consistency table for the active sheet. |
| `window.__fetchRevitId(asmId)` | Live ElementId lookup with cache-age disclosure. |
| `runDelta(a,b)` / `initRuns()` | Baseline-vs-current comparison table. |
| `initReview()` / `openReviewItem(i)` / `renderThread()` / `sendReviewComment()` | Review queue, detail, AI analysis, comment thread. |

- **XSS (CRITICAL — JS-context breakout)** `inspector.js:51` — `onclick="window.__fetchRevitId('${esc(e.revit_ref.id)}')"`. See [§6 CRITICAL-6](#6-critical-findings).
- **XSS (stored)** `inspector.js:122` — `<b>${r.baseline.label}</b>` unescaped, and `label` is user-supplied via `prompt()` at `:150`, round-tripped through the server. The clearest stored-XSS path in the app.
- **XSS** `inspector.js:41,43,49,98,116,118,123,140,162,170,172,173,185,186,196,203,204,205` — 18 further unescaped interpolations of API data.
- **ERROR-GAP** `inspector.js:208` — `.catch(() => { $("#rev-ai").innerHTML = ""; })`: the reviewer cannot distinguish "no analysis exists" from "the analysis request errored". The most consequential silent catch in the UI.
- **ERROR-GAP** `inspector.js:150-155` — a failed baseline save shows no error and no toast; `:306` — the review badge silently keeps its `0` placeholder.
- **ERROR-GAP** `inspector.js:43,172,185-186` — no guards on `e.status` / `e.category` before `.replaceAll` / `.replace`.
- **HARDCODE** `inspector.js:84` "no live device within 0.75 ft"; `:191` "MATCH needs ≤16pt"; `:240` "MATCH gate: 16pt; mismatch band ends 40pt" — backend thresholds duplicated as UI prose.

### frontend/src/panels/list.js — 86 LOC

| Export / Function | Purpose |
|---|---|
| `visibleElements()` | Applies search/status/sheet filters. |
| `renderList()` | Two-level collapsible cat → mark → row tree. |
| `renderFilters()` / `dotBar(items)` | Filter options; per-group status dots. |

- **XSS** `list.js:48,49,70,71` — `${e.distance_pdf_points}`, `${e.status.replaceAll(...)}`, and `<option>${s}</option>` for every distinct API status and sheet name.
- **Good:** `list.js:46` uses `esc(e.id)` for `data-id` — the correct form that `table.js:44` omits.

### frontend/src/panels/pdf.js — 211 LOC

| Export / Function | Purpose |
|---|---|
| `renderTabs()` / `showSheet(sheet, instant)` / `fitView()` | Sheet strip, page load + overlay sizing, camera fit. |
| `syncIsolation()` / `renderLayerToggles()` | Isolation class and focus ring; status-layer chips. |
| `renderOverlay()` / `renderBenchmarkMarkers()` / `flyToPoint()` | SVG boxes, mismatch leaders, BM crosshairs, camera fly. |
| `primarySheet()` / `ensureSheetScale(sheet)` | Caches the calibration-owning sheet; per-sheet measure-tool scale. |

- **XSS** `pdf.js:16` — `data-s="${s}"` **and** `>${s}<`: sheet names raw in both attribute and text; `:52,54,58,62,74-77,91-92` — coordinates raw into SVG attributes; `:64` — `${e.status}` inside `<title>` while mark and reason on the same line *are* escaped.
- **HARDCODE (now correct)** `pdf.js:160-161` — the primary sheet is fetched from `/api/sheets/primary`. **`HARDCODING_AUDIT.md` blocker #5 is FIXED**; only the comment at `:155-157` still names the per-project sheets, which is now stale documentation rather than live behavior.
- **ERROR-GAP** `pdf.js:160-161` — `primarySheet()` caches `.catch(() => null)` in a module-level promise for the page's lifetime, so **one transient failure at boot permanently routes every sheet down the per-sheet branch** (`:168`).
- **ERROR-GAP** `pdf.js:170` — the swallow makes "scale unverified" (`:145`) ambiguous between uncalibrated and request-failed; `:26` — `img.onerror = res` resolves identically to success, so a missing sheet PNG leaves the previous page image under the new sheet's overlay, silently misaligned.
- **HARDCODE** `pdf.js:24,36` default page size `[2592,1728]`; `:26` `dpi=150`; `:11,38,51,54,97,121,191-201` — nine unnamed layout/zoom constants.

### frontend/src/panels/revit_live.js — 243 LOC

| Export / Function | Purpose |
|---|---|
| `showInRevitBtn(e)` / `whyBlock(e)` / `analysisHtml(a)` | "Show in Revit" markup; collapsible verdict shell; shared analysis renderer. |
| `wireRevitLive(root)` | Post-innerHTML wiring: clicks, connector-status painting, details toggle. |
| `initRevitLookup()` / `connStatus()` | Lookup drawer init; 15 s-cached status. |
| `showInRevit(btn)` / `paintRevitButtons(root)` | POST highlight; enable/disable by connector state. |
| `lookupHtml(r)` / `regQualityHtml(rq, dev)` / `doLookup(id)` | Lookup render and registration-trust line. |

- **Good:** the only file that fully honours its own "every server string goes through `esc()`" claim.
- **HARDCODE** `revit_live.js:11` — `MATCH_GATE_FT = 2` while `inspector.js:191,240` write the same backend threshold as `16pt`. Two representations, two units, two files, one source constant.

### frontend/src/panels/table.js — 76 LOC

| Export / Function | Purpose |
|---|---|
| `renderTable()` | Sortable results table from `visibleElements()`. |
| `renderScopeBanner()` | Dismissible export-scope warning. |

- **XSS** `table.js:44` — `data-id="${e.id}"` raw in an attribute (`list.js:46` escapes the identical construct); `:21,22,48` — `${w.pdf_count}`, `${w.revit_count}`, `${e.status.replaceAll(...)}` while `e.status_detail` on `:52` **is** escaped — inconsistent within one template.
- **HARDCODE** `table.js:16-23,52` — banner and pill colors inline rather than in `tokens.css`.

### frontend/src/panels/viewer3d.js — 435 LOC

| Export / Function | Purpose |
|---|---|
| `loadScene()` / `loadLiveScene(force)` | Snapshot-first load, then live; `force` busts the 60 s backend cache. |
| `resize3D()` / `resetView3D()` | Renderer/camera resize; global camera + isolation reset. |
| `sceneFromLive(live)` | Live payload → snapshot scene shape. |
| `build3D()` | Full Three.js rebuild: walls, holdowns, openings, grids, boxes, framing, benchmarks, picking, tooltip, legend. |
| `makeLabelSprite(text)` / `highlight3D(e, origin)` | Grid label; emissive pulse + camera fly. |

- **XSS** `viewer3d.js:303-304,348,353,355,358` — tooltip `${u.status}`, `<b>${name}</b>`, `${u.type}`, and the counts/truncated/status/height note lines, all from `/api/scene3d` or `/api/revit-live/scene`.
- **ERROR-GAP** `viewer3d.js:118,137,159` — `sc.walls` / `sc.holdowns` / `sc.grids` iterated with **no** `|| []`, while `sc.openings` (`:148`), `sc.category_elements` (`:174`), `sc.live_boxes` (`:195`), `sc.framing` (`:214`), `sc.benchmarks` (`:235`) are all guarded. Inconsistent within one function; a payload missing `walls` throws mid-build after the renderer is already attached to the DOM (`:94`).
- **ERROR-GAP** `viewer3d.js:19` — `try { … } catch { }`: a scene-load failure leaves the 3D pane showing its placeholder forever, with no toast and no console output.
- **HARDCODE** `viewer3d.js:23,96,100,103,171-172,179-182,266-271,313,332,358` — eleven unnamed rendering constants; `:332` legend duplicates a subset of `RUN_STATUSES`.

### frontend/src/panels/wizard.js — 325 LOC

| Function | Purpose |
|---|---|
| *(no exports — pure side-effect module, kept alive by `import "./panels/wizard.js"` at `app.js:15`)* | |
| `bmRail()` / `bmCards()` | 9-step progress rail; state-machine card renderer + button wiring. |
| `bmProposalCard(p)` / `bmReadbackCard()` / `bmVerificationCard(wf)` | Proposal crops, Revit read-back deltas, PDF stamp verification. |
| `bmPickCard()` / `bmStartPick()` / `bmPickClick(svg, ev)` | Manual grid-intersection picking with nearest-point snap. |
| `bmRevitPill()` / `bmPaintRevit()` / `bmMaybeCheckRevit()` | Debounced connector status. |
| `bmBanner()` / `bmRefresh()` / `bmAction(url, body)` / `bmLog(e)` | Approval banner; workflow GET/POST + live log. |

- **XSS (attribute)** `wizard.js:199,201` — `style="aspect-ratio:${w}/${h}"` and `viewBox="0 0 ${w} ${h}"` from `/api/benchmark-workflow/grid-points`, raw into a `style` attribute and an SVG attribute.
- **XSS** `wizard.js:54,86,151,190-191` — separation figures, deltas, `scale ${cal.scale}`, and point coordinates.
- **ERROR-GAP** `wizard.js:294` — `bmRefresh()` returns silently on failure; with the 8 s fallback poll (`:315`) this can fail every 8 seconds indefinitely with zero signal.
- **ERROR-GAP** `wizard.js:39,83` — `p.benchmarks.map` / `v.checks.map` unguarded, and `bmCards()` is called without a catch around the render; `:224` — `svg.getScreenCTM().inverse()` returns `null` for a non-rendered SVG.
- **HARDCODE** `wizard.js:10-20` — `BM_STEPS` mirrors backend state-machine names; `:73` read-back tolerance `0.05`; `:200` `dpi=150`; `:259` `12000`.

---

## 5. Dead code

Verified by repo-wide grep across `backend/`, `frontend/` (incl. `index.html`), and `docs/`, accounting for FastAPI route decorators, `window.*` assignments, generated `onclick=` strings, `subscribe()` callbacks, and dynamic dispatch.

| # | Item | Evidence |
|---|---|---|
| 1 | `holdown_types_equivalent` | `normalization.py:86` — one definition, zero references repo-wide. |
| 2 | `build_focused_s201_holdown_entities` | `s201_detector.py:138` — one definition, zero references. |
| 3 | `discover_tables_on_page` | `schedule_tables.py:435` — one definition, zero references. |
| 4 | `backend/app/benchmarks.py` (whole module, 36 LOC) | The only `import benchmarks` hit is the **untracked** `backend/_merge_teach.py`. |
| 5 | `chat_agent.py:340-368` duplicate constant block | `MAX_TOOL_ROUNDS`, `PIPELINE_WHITELIST`, `LLM`, `ChatUnavailable`, `SYSTEM_PROMPT` redefined byte-identically over `:26-50`. |
| 6 | `setProjectHeader` | `api.js:22` — the only other repo hit is the doc comment at `api.js:10`. `projectHeader` is permanently `null`, so the `X-Project` branch at `api.js:28` is **unreachable**. |
| 7 | `toast` import in `chat.js:8` | Imported, never called in the file. |
| 8–14 | Dead *exports* (function used, but only inside its own module — the `export` keyword has no consumer) | `emit` `store.js:26`; `authToken` `api.js:14`; `analysisHtml` `revit_live.js:83`; `renderInspector` `inspector.js:38`; `fitView` `pdf.js:35`; `loadLiveScene` `viewer3d.js:50`; `runExtract` `app.js:75`. |

**Explicitly NOT dead** (verified reachable via non-import paths, listed so they are not mistakenly removed): `tokenized` (`window.tokenized` at `app.js:22` → three generated `onclick=` strings at `app.js:220-222`); `window.__fetchRevitId` (`inspector.js:64` → generated `onclick=` at `inspector.js:51`); every `wizard.js` function (side-effect module).

**Total: 14 dead-code items.**

---

## 6. CRITICAL findings

### CRITICAL-1 — Fabricated engineering specifications stamped onto client detections
`s201_detector.py:201` `schedule = schedule or DEFAULT_HOLDOWN_SCHEDULE` and `:221` `sched = schedule.get(label, DEFAULT_HOLDOWN_SCHEDULE.get(label, {}))`.

`detect_s201_holdowns:175` passes `schedule={}` whenever `mark_pattern` is supplied — i.e. on **every generic (non-Madera) run** routed through `generic_page_intelligence.run_generic_page_intelligence`. The falsy `{}` is then replaced by Madera's `DEFAULT_HOLDOWN_SCHEDULE` (`:59-84`). Any client whose marks happen to be named `H1`–`H4` — a common convention — receives Madera's Simpson Strong-Tie values written into `schedule_type_raw`, `anchor_bolt`, `fasteners`, `embedment` and `normalized_core_token` (`:237-246`), and surfaced to a structural reviewer as detected fact with no flag distinguishing them from a real schedule read. On the frozen path the same per-label default fires whenever the schedule reader misses a row.

This is not a hardcode; it is fabricated engineering data (anchor bolt diameters, embedment depths) presented as measured. It also directly contradicts `generic_page_intelligence.py:14` ("No fake data").

**Fix:** pass `schedule=None` explicitly and make the substitution opt-in, or tag every defaulted field with `spec_source: "default_schedule"` so the UI can refuse to display it as measured.

### CRITICAL-2 — The Madera baseline was moved, not removed
`pdf_intelligence.py:49` writes `{"H1":10,"H2":21,"H3":6,"H4":17}` into `expected_baseline` on **every** project. `compare.py:490-491`'s R-27 docstring claims this literal was replaced by an artifact lookup — but `compare.py:504` reads exactly the field that literal is written into. The same baseline is still hardcoded and **unfixed** at `control_points.py:20` (drives `revit_scope_diagnostics` recommendations) and `revit_convert.py:268,270,321,323` (emits a QA warning per mark and embeds the dict into every v2 artifact).

Compounding it: on the *generic* path `expected_baseline` is absent entirely (`generic_page_intelligence.py` never writes it), so `compare._project_pdf_baseline` falls back to `summary.by_type` — the observed counts. The baseline comparison becomes self-referential and can never report a PDF-side discrepancy, while still emitting `"likely_issue"` and `"required_next_fix"` as if it had.

### CRITICAL-3 — Unauthenticated OpenRouter API-key prefix disclosure
`config.py:196-200` builds `api_key_preview` = first 8 + last 4 characters of the live key. It flows through `openrouter.call_status_summary()` (`openrouter.py:241`) into `GET /api/health` (`system.py:31`), and `main.py:98` **explicitly exempts `/api/health` from bearer auth**. The same response leaks the absolute `artifact_dir` and sample-input paths. Separately, `main.py:102-103` accepts the bearer token as a `?token=` query parameter and `maintenance.py:67-68` attaches a file handler to `uvicorn.access`, writing every such token in cleartext to `logs/app.log`. Token comparison at `main.py:104` is non-constant-time.

### CRITICAL-4 — Guaranteed crash on the exact input the code was written to survive
`wall_match.py:130` — `(calibration or {}).get("transform", {}).get("matrix") if calibration else None`. `.get("transform", {})` returns the *stored* value, and a failed calibration stores `transform: None` (`registration.py:214`, `:574`). `None.get("matrix")` raises `AttributeError`. The very next line (`:133`) is the correct `if matrix is None` handling. `device_match.py:36` uses the correct `(… or {})` idiom for the same read.

### CRITICAL-5 — RANSAC reports success after persisting a failed calibration
`ransac_holdown.py:174-176` never checks `calibration["quality"]["confidence"] == "failed"`. If the inliers are collinear or `_invert_matrix` degenerates, `compute_calibration` returns `transform: None` (`registration.py:214`) and the function still calls `save_calibration` / `save_registration_report` (`:229-230`) and returns `{"ok": True, "saved": True}`. That persisted `transform: None` artifact is precisely the input that crashes CRITICAL-4.

### CRITICAL-6 — Stored XSS with arbitrary script execution
`inspector.js:51` — `onclick="window.__fetchRevitId('${esc(e.revit_ref.id)}')"`. `esc()` is the **wrong escaper for a JS context**: it converts `'` to `&#39;`, which the HTML parser decodes back to `'` *before* the inline script is compiled, so the value breaks out of the JS string literal. Combined with `inspector.js:122` (`<b>${r.baseline.label}</b>`, where `label` comes from the `prompt()` at `:150` and is round-tripped through the server), there is a full stored-XSS path. About 70 further unescaped interpolations are listed in [§4](#4-frontend); `table.js:44` (`data-id="${e.id}"`) is an attribute-context instance of the same class, escaped correctly one file over at `list.js:46`.

**Fix for `:51`:** replace the inline handler with a `data-` attribute plus a listener in `wireRevitLive`, matching the pattern already used elsewhere in the file.

### CRITICAL-7 — Zero HTTP-layer test coverage
All 278 collected tests are unit tests importing module functions directly. Grep for `TestClient` / `httpx` / `create_app` across `backend/tests/` returns **nothing**; `main.py:141-151` exists specifically so tests can call a handful of handlers as plain functions. **54 of 71 routes are never exercised by any backend test** — including `POST /api/upload`, `POST /api/elements/match`, `POST /api/compare/ai`, every `/api/review/*` endpoint, every `/api/registration/*` endpoint, and `GET /api/artifacts/{filename}`. Consequently none of the ~40 "500 on malformed artifact" gaps catalogued above are caught by CI, and the path-traversal join at `elements.py:50` has no regression test.

---

## 7. `HARDCODING_AUDIT.md` status

| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | `revit_bridge.py` `mwfBenchmark`, no override path | **FIXED** | `revit_bridge.py:38-49` — `benchmark_family(override)` resolves arg → `QAQC_BENCHMARK_FAMILY` → default; `routers/revit.py:353-357` passes `body.get("family")`. Operator hint at `:40-41`. |
| 2 | `s201_detector.py` silent success on a wrong-layout S-201 | **OPEN** | `routers/pipeline.py:167` still branches solely on `result.get("error")`. No detection-count/geometry sanity check was added. |
| 3 | `normalization.py` `CORE_TOKEN_TO_MARK` | **OPEN** | `normalization.py:6-11` unchanged; `:61` still `re.fullmatch(r"H[1-4]", …)`. |
| 4 | `pdf_convert.py` H1-H4/Simpson LLM prompt | **OPEN** | `pdf_convert.py:13,35-37` unchanged. |
| 5 | `pdf.js` `sheet === "S-201"` | **FIXED** | `pdf.js:160-168` resolves the primary sheet from `GET /api/sheets/primary`; `routers/registration.py:76` implements `/api/registration/sheet/{sheet}`; `routers/elements.py:67` implements `/api/sheets/primary`. Only the comment at `pdf.js:155-157` is now stale. |

**Also fixed since that audit:** `compare.py:485-512` made the compare-report baseline artifact-driven — but see [CRITICAL-2](#critical-2--the-madera-baseline-was-moved-not-removed): the literal simply relocated to `pdf_intelligence.py:49`, and the sibling copies at `control_points.py:20` and `revit_convert.py:268` were never touched.

**New (b)-class blockers found by this audit, not in `HARDCODING_AUDIT.md`:**

| # | File:line | Literal | What breaks |
|---|---|---|---|
| 6 | `s201_detector.py:201,221` | `DEFAULT_HOLDOWN_SCHEDULE` substitution | **FIXED** 2026-07-28 — an explicitly-passed empty schedule (the generic path) no longer falls back to Madera's values; every record now carries `schedule_source` (`detected` / `default_madera` / `none`). Madera's S-201 path re-verified byte-identical (54 detections, all `detected`). See CRITICAL-1. |
| 7 | `control_points.py:20,286` | `PDF_BASELINE` + H1–H4 restriction | **FIXED** 2026-07-28 — `build_scope_diagnostics` runs on **both** the v2 and v3 paths (`routers/pipeline.py:97,136,148`), so this hardcode was load-bearing on the generic path, not legacy. Now reads the project's own `expected_baseline` via `compare._project_pdf_baseline` and reports `pdf_baseline: null` when there is none; marks come from the baseline, else from what Revit actually holds. |
| 8 | `revit_convert.py:268,321` | `pdf_baseline` | **Known, legacy v2-path only** — reachable solely through `revit_convert.convert_revit`, which `routers/pipeline.py:94,144` calls only when `revit_v3_adapter.is_v3()` is false. All three current projects (Madera, Country Side, Dogwood) export v3, so no live project reaches it. Still fabricates Madera's numbers for any future v2 upload; left alone deliberately (`revit_convert.py` is frozen). |
| 9 | `routers/elements.py:93,128` | `page_intel.get("page_index", 4)` | An artifact missing `page_index` renders page 5 of an unrelated PDF instead of erroring. |
| 10 | `schedule_tables.py:33-45` | `CATEGORY_MARK_RE` / `GENERIC_MARK_RE` | Contradicts the module's own "nothing is hardcoded" claim; marks outside the Simpson family list are dropped from the learned vocabulary. |
| 11 | `revit_v3_adapter.py:30,32,78` | `HOLDOWN_FAMILY_RE` / `BOLT_FAMILY_RE` / `_SCHED_MARK_RE` | An unrecognized product prefix makes the whole report read PDF_ONLY. |
| 12 | `config.py:131-134` | `s201_*` artifact filenames | Every project and every sheet writes `s201_review_*`. |

---

## 8. Security notes for open-sourcing

| # | Severity | Finding | Evidence |
|---|---|---|---|
| 1 | **Critical** | JS-context XSS via `esc()` misuse in an inline `onclick` | `inspector.js:51` |
| 2 | **Critical** | Unauthenticated API-key prefix + absolute-path disclosure on `/api/health` | `config.py:196-200`, `system.py:29,31,39-42`, `main.py:98` |
| 3 | **High** | ~70 unescaped `innerHTML` interpolations; stored-XSS path via the baseline label | `inspector.js:122` + `:150`; full list in [§4](#4-frontend) |
| 4 | **High** | Attribute-context injection | `table.js:44`, `app.js:30`, `wizard.js:199,201`, `pdf.js:16` |
| 5 | **High** | Bearer token accepted in the query string and written to `logs/app.log` | `main.py:102-103`, `maintenance.py:67-68` |
| 6 | **High** | Auth off by default — all destructive endpoints open | `main.py:37`; `DELETE /api/registration` (`registration.py:113`), `POST /api/revit/highlight` (`revit.py:180`), `POST /api/benchmark-workflow/place-markers` (`revit.py:343`, writes geometry into the user's live model), `DELETE /api/teach/memory/{id}` (`pipeline.py:652`) |
| 7 | **High** | `C:\Users\aashd\…` in **14 tracked files** | `.claude/settings.json:9,18`; `backend/tests/test_pdf_detector.py:14`; `backend/tests/test_review_overlay.py:227`; `run_backend.ps1:11`; `scripts/enrich_madera_export.py:13,15`; `scripts/recover_frontend.py:7`; `backend/run_benchmark_acceptance.py:34`; `backend/app/AUTOPILOT_PLAN.md:471`; plus `AGENT_HANDOFF.md`, `Bugs.md`, `NEW_SESSION_PROMPT.md`, `docs/COMPLETE_TECHNICAL_REFERENCE.md`, `docs/PROMPT_FOR_REVIT_LIVE_IMPLEMENTATION.md`, `docs/USER_MANUAL_AND_GUIDE.md` |
| 8 | **Medium** | Path traversal — unsanitized join from a URL path parameter | `elements.py:50` (`config.PAGES_DIR / f"{sheet}_{dpi}.png"`, no `Path(...).name` guard) |
| 9 | **Medium** | Artifact-controlled absolute path join | `elements.py:101,104,132-138` (`source_file` from `pdf_page_intelligence.json`, no containment check) |
| 10 | **Medium** | Non-constant-time token comparison | `main.py:104` |
| 11 | **Medium** | CPU DoS — unbounded caller-controlled RANSAC iterations | `registration.py:180,184` |
| 12 | **Medium** | Unbounded upload read into memory, no size limit | `projects.py:82` |
| 13 | **Medium** | `POST /api/chat` accepts an unvalidated `history` array, letting a client forge prior assistant/tool turns | `chat.py:23-25` |
| 14 | **Medium** | Client name `country-side-ct` committed in tracked teach memory | `artifacts/memory/global.json` (tracked despite `.gitignore`) |
| 15 | **Low** | Runtime logs tracked in git despite `.gitignore` | `server-out.log`, `server-err.log`, `test-progress.log` |
| 16 | **Low** | `NONICA_MCP_EXE` is the sole control over which binary the backend spawns | `revit_bridge.py:32-34,664` |
| 17 | **Low** | Raw exception text (incl. full `NONICA_EXE` path) returned to API callers | `revit_bridge.py:290-292,329-331,352-353,370-371,644-645` |
| 18 | **Low** | Three CDN dependencies with no SRI and no local fallback | `index.html:9-14` (fonts.googleapis.com, gsap@3.12.5, three@0.160.0) |

**Clean:** no CORS middleware anywhere (verified by grep for `CORSMiddleware`/`allow_origins`); no `shell=True` and no user-controlled argv reaching a subprocess; no hardcoded secrets or API keys in source (`OPENROUTER_API_KEY` is env-only, `config.py:184`); `system.py:66`, `config.py:48-52`, `config.py:157`, and `workflow.py:402` all sanitize correctly.

---

## 9. Summary

```
TOTALS
  Source files ................ 56          (backend 43 · frontend 13)
  Source LOC .................. 15,756      (backend 13,448 · frontend 2,308)
    backend/app/*.py .......... 10,774      (33 files)
    backend/app/routers/*.py ..  2,674      (10 files)
    frontend/src/*.js .........    449      ( 5 files)
    frontend/src/panels/*.js ..  1,859      ( 8 files)
  Test LOC .................... 4,751       (backend 4,540 · frontend 211)
  Tests collected ............. 278         (pytest -q --collect-only)

FINDINGS
  Dead-code items ............. 14          (5 backend · 9 frontend)
  Missing-test items .......... 111         (57 non-route public functions
                                             + 54 routes with zero coverage)
  Remaining-hardcode items .... 50 project-specific / config literals
                                + ~90 unnamed magic-number sites
  Security notes .............. 18          (2 critical · 5 high · 6 medium · 5 low)
  Docstring/behavior conflicts. 24
  Error-handling gaps ......... 96          (~40 are "500 on malformed artifact")

HARDCODING_AUDIT.md ........... 2 of 5 FIXED (#1 mwfBenchmark, #5 pdf.js)
                                3 of 5 OPEN  (#2 s201 fallback, #3 normalization,
                                              #4 pdf_convert prompt)
                                7 new (b)-class blockers found

TOP 10 — FIX BEFORE OPEN-SOURCING (ranked by risk)
   1. s201_detector.py:201,221 — DEFAULT_HOLDOWN_SCHEDULE substitution stamps
      fabricated Simpson anchor-bolt/embedment specs onto any client using H1-H4
      marks, presented to a structural reviewer as detected fact. Safety issue,
      not a style issue. Pass schedule=None explicitly and tag defaulted fields.
   2. inspector.js:51 — esc() is the wrong escaper inside an inline onclick;
      the HTML parser decodes &#39; back to ' before the JS compiles, giving
      arbitrary script execution. Stored-XSS path via inspector.js:122 + :150.
      Replace with a data- attribute + listener.
   3. config.py:196-200 + system.py:31 + main.py:98 — OPENROUTER_API_KEY prefix
      (first 8 + last 4 chars) and absolute filesystem paths served on the
      auth-exempt /api/health. Drop api_key_preview; keep api_key_present.
   4. 14 tracked files contain C:\Users\aashd\... (incl. .claude/settings.json,
      two test files, three scripts, six docs). Also tracked: server-out.log,
      server-err.log, test-progress.log, and artifacts/memory/global.json
      carrying the client name "country-side-ct". Scrub + git-rm before publish.
   5. main.py:37,102-104 — auth off by default, token accepted in the query
      string, written to logs/app.log by maintenance.py:67-68, and compared
      non-constant-time. Every destructive endpoint (DELETE /api/registration,
      POST /api/revit/highlight, POST .../place-markers) is open by default.
   6. routers/common.py:71 — load_artifact checks existence but not validity, so
      one truncated JSON file 500s eleven endpoints. Single highest-leverage
      error-handling fix in the backend; ~40 sibling gaps share the shape.
   7. Zero HTTP-layer tests — 54 of 71 routes never exercised (no TestClient
      anywhere in backend/tests/). None of the 500-on-malformed-artifact gaps or
      the elements.py:50 traversal join have a regression test.
   8. wall_match.py:130 + ransac_holdown.py:174-176 — a paired defect: RANSAC
      persists a failed calibration while returning {"ok":true,"saved":true},
      and wall_match then AttributeErrors on transform:None, the exact input
      line :133 was written to survive.
   9. pdf_intelligence.py:49 + control_points.py:20 + revit_convert.py:268 —
      the Madera baseline {H1:10,H2:21,H3:6,H4:17} lives in three places; R-27
      relocated one copy and compare.py:491 claims it was removed. On the
      generic path the baseline degenerates to the observed counts, so the
      comparison is self-referential yet still emits "likely_issue".
  10. elements.py:50 (unsanitized PAGES_DIR join from a URL path param, no
      Path().name guard) and elements.py:101,104 (absolute artifact-supplied
      source_file joined with no containment check).
```

**Also worth scheduling, below the top 10:** the `teach.py` / `chat_agent.py:95-336` duplicate rules engine (two live copies writing one file); the six non-atomic whole-file JSON writers whose readers all silently return empty defaults on `JSONDecodeError`, so a torn write erases audit state with no error anywhere; `maintenance.py:34-38`, where an unguarded `p.stat()` can prevent the server from booting; and `revit_v3_adapter.py:260`, which assigns the model origin to location-less hold-downs and feeds that fabricated coordinate into distance-gated MATCH logic.
