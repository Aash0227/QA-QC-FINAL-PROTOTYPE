# Hardcoding Audit — QA-QC Prototype

Scope: `backend/app/**/*.py`, `frontend/src/**/*.js`. `backend/tests/` noted separately at the end.
Read-only audit. Goal: every project-specific (Madera/Dogwood/Country-Side) literal, with a triage class and a note on whether the containing module is in the FROZEN set (`compare.py`, `registration.py`, `s201_detector.py`, `pdf_intelligence.py`, `review_overlay.py`, `normalization.py`, `revit_convert.py`, `pdf_convert.py`).

Triage classes:
- **(a) demo-safe** — a fallback/default only; a generic/learned path exists and is actually used first.
- **(b) BLOCKS new projects** — load-bearing; a new client's data will silently misbehave or hard-fail.
- **(c) cosmetic** — label, docstring, filename, or test-only literal; no behavioral effect.

---

## (b) BLOCKS new projects — load-bearing hardcodes

| # | File:line | Literal | What breaks on a new project | Frozen? |
|---|-----------|---------|-------------------------------|---------|
| 1 | `backend/app/revit_bridge.py:35,76,449` | `DEFAULT_BENCHMARK_FAMILY = "mwfBenchmark"`, used with **no override path** from `routers/revit.py:356` (`revit_bridge.place_benchmarks(proposal)` — no `family` param passed) | Live "Show-in-Revit" / benchmark-stamping (`POST /api/benchmark-workflow/place-markers`) calls `get_all_elements_of_specific_families(["mwfBenchmark"])` and raises `BridgeError: No 'mwfBenchmark' family instance to copy in the model.` for any Revit model that doesn't happen to contain a family with that exact (apparently firm-internal) name. No API param or UI control exposes an override. | No |
| 2 | `backend/app/s201_detector.py:21-33,59-84` | `PLAN_BBOX`, `S201_TABLE_BBOXES`, `HOLDOWN_ROW_BANDS` (absolute PDF-point pixel coordinates tuned to Madera's exact S-201 page layout/size); `HOLDOWN_RE` (`H[1-4]` only); `DEFAULT_HOLDOWN_SCHEDULE` (Simpson Strong-Tie specs for H1-H4 only) | `pdf_intelligence.run_page_intelligence()` (frozen, the pipeline's default/first-tried path) calls `locate_s201_page()`, which matches ANY sheet whose text contains `S-?201` **and** has `H[1-4]` marks. A new project whose foundation sheet happens to be named "S-201" and uses H1-H4 as its mark family (a common convention) but has a **different page size / table layout / product schedule** will be "found" successfully (no `error` key), so `routers/pipeline.py:166-176`'s fallback to the generic, learned-vocabulary detector (`generic_page_intelligence.py`) **never triggers** — the pixel-hardcoded bboxes silently produce wrong/garbage detections instead of an honest error. Only projects whose sheet name or mark family differ from Madera's are safely routed to the generic path. | **Yes** |
| 3 | `backend/app/normalization.py:6-13` | `CORE_TOKEN_TO_MARK = {"HDU6":"H1","HDU11":"H2","HD10S":"H3","HD15B":"H4"}` and its inverse | `normalize_holdown_type()` / `normalize_holdown_mark()` can only recognize these four Simpson product tokens as "known" (`known=True`, confidence 0.9+); every other manufacturer/product token gets `known=False`, confidence ≤0.15. Consumed by `revit_convert.py` (frozen, the **legacy v2 Revit-export path** — used whenever a client's exporter is not on schema v3) for hold-down family→mark classification. Any client stuck on the v2 export schema with non-Simpson-H1-4 hardware gets systematically unclassified hold-downs. (The newer `revit_v3_adapter.py` path is data-driven and bypasses this, so the blast radius is limited to v2-schema clients.) | **Yes** |
| 4 | `backend/app/pdf_convert.py:13,32-45` | `MARK_TO_CORE_TOKEN = {"H1":"HDU6","H2":"HDU11","H3":"HD10S","H4":"HD15B"}`; `_llm_confirm_mapping()`'s `system_prompt` literally instructs the LLM to confirm "PDF plan marks (H1-H4)" against "canonical core tokens (HDU6, HDU11, HD10S, HD15B)" | `convert_pdf()` (frozen) always sends this Madera-specific prompt to the LLM regardless of the actual project's detected marks, on every run. For a non-Madera project the LLM is asked to reconcile a mapping that has nothing to do with the real data; the resulting `llm_mapping_confirmation` field (surfaced to reviewers) is nonsensical or misleading rather than merely absent. | **Yes** |
| 5 | `frontend/src/panels/pdf.js:157` | `sheet === "S-201" ? await api("/api/registration") : await api(\`/api/registration/sheet/${sheet}\`)` | The backend picks its "compare sheet" dynamically per project (`routers/pipeline.py` reads it from the `pdf_page_intelligence` artifact — it need not be "S-201"). The frontend's ruler/measure-tool scale lookup (`ensureSheetScale`) hardcodes "S-201" as the sheet that owns the *global* registration calibration; every other sheet — including a non-Madera project's actual primary/compare sheet — is queried against `/api/registration/sheet/{sheet}` (a per-sheet artifact that was never written for the compare sheet). Result: the measure tool silently reports "scale unverified" on a project's main sheet even though registration succeeded. Degrades a UI feature; does not crash. | No |

## Fix order for shipping today ((b) items only)

1. **revit_bridge.py `mwfBenchmark`** — highest blast radius for the flagship "Revit-live" feature: add a `family` query/body param to the `place-markers` endpoint (and `benchmark_workflow.py`'s propose step) so any client can supply their own benchmark-family name; keep `"mwfBenchmark"` only as the last-resort default.
2. **s201_detector.py silent-success-on-wrong-layout** — cheapest fix is a call-site wrapper in `pdf_intelligence.run_page_intelligence()` (or its caller in `routers/pipeline.py`) that sanity-checks the detection count/geometry (e.g., detections found vs. table rows found) and forces the generic fallback when they disagree, instead of trusting "no `error` key" as the success signal. Do not edit `s201_detector.py` itself — it's frozen.
3. **pdf.js `sheet === "S-201"`** — replace with "is this sheet the backend's current compare sheet" (already available via the `pdf_page_intelligence` / `element_list` artifacts) instead of a literal string compare.
4. **normalization.py / pdf_convert.py Simpson vocabulary** — lower priority since the v3/generic pipeline already bypasses both for the primary flow; wrap with a call-site fallback (e.g., skip the LLM-confirm prompt or make its vocabulary data-driven from `element_intelligence`'s learned marks) only if v2-schema exports remain a real, near-term client scenario.

---

## (a) demo-safe — fallback only, generic/learned path exists

| File:line | Literal | Note |
|---|---|---|
| `backend/app/config.py:63,102-111` | `active_project()` defaults to `"madera"`; one-time legacy-layout migration targets `artifacts/projects/madera/` | Only matters when `active_project.json` doesn't exist yet (fresh checkout) or the pre-multi-project flat-artifact layout is detected. Any real upload creates/activates a real project slug immediately. |
| `backend/app/routers/pipeline.py:45-48` | `_uploaded_pdf()` returns `config.ARTIFACT_DIR / "uploaded_madera.pdf"` | Dead-ish: the real `/api/upload` flow (`routers/projects.py:81`) writes `UPLOAD_DIR/"input.pdf"` generically. This function only fires on the alternate direct-file-upload branch of `/api/pdf/page-intelligence`, and even then the filename is cosmetic (already inside the project-scoped `ARTIFACT_DIR`). |
| `backend/app/routers/pipeline.py:389-393` | `compare_sheet = "S-201"` default | Immediately overwritten from the `pdf_page_intelligence` artifact's real `sheet_number` when present (lines 390-393). |
| `backend/app/element_registry.py:31`, `control_points.py:112,140`, `pdf_convert.py:65`, `pdf_intelligence.py:35,45,54`, `s201_detector.py:153,166`, `routers/registration.py:98` | `sheet_number: str = "S-201"` default params | All are default-argument fallbacks used before real data is loaded, or literal defaults for the frozen S-201-only path (which itself has a generic fallback wired in — see blocker #2 above for the one case where that fallback doesn't trigger). |
| `backend/app/registration.py:337-351` | `BENCHMARK_MIN_SEP_PT/FT`, `expected_scale_pt_per_ft: float | None = 18.0`, `marks: tuple = ("BM-1","BM-2")` | Overridable parameters with sane engineering defaults (BM-1/BM-2 is the documented 2-point benchmark convention, not client vocabulary); `expected_scale_pt_per_ft` is a cross-check only (warn/block on drift), not a hard requirement. |
| `backend/app/wall_match.py:20-22` | `SW_MATCH_MAX_PT = 60.0`, `SW_LOCATION_MISMATCH_MAX_PT = 120.0` | Explicitly flagged in-code: `# ponytail: tuned on Madera S-202 ground truth; knobs, not gospel.` Distance thresholds, not client vocabulary; reasonable generic defaults for a points-based PDF drawing. |
| `backend/app/revit_bridge.py:29-32` | `NONICA_EXE` default path `C:\NONICAPRO\...\RevitMCPConnection.exe` | Env-overridable (`NONICA_MCP_EXE`); a per-machine install path, not per-project. |
| `backend/app/control_points.py:20,286,313-339` | `PDF_BASELINE = {"H1":10,"H2":21,"H3":6,"H4":17,"total":54}`, `revit_by_mark` restricted to H1-H4 keys | Feeds only the diagnostic `revit_scope_diagnostics.json` artifact (recommendations/summary text) — does not gate MATCH/verdicts. Misleading rather than blocking: for a non-H1-H4 project it will always show 0-count "H1..H4" rows and a bogus "delta vs PDF baseline" recommendation. |
| `backend/app/compare.py:501-509` (**frozen**) | `_revit_count_diagnostics()`'s `pdf_baseline = {"H1":10,...}`, `by_mark` restricted to H1-H4 | Same as above: purely the `revit_count_diagnostics` display block inside the compare report, not the actual verdict/MATCH computation (`_group_revit`/`_group_pdf` + `MATCH_MAX_PT` handle real matching mark-agnostically). Misleading display text for non-Madera marks, not a functional blocker. |

## (c) cosmetic — labels, docstrings, filenames, comments, test-only data

| File:line | Literal | Note |
|---|---|---|
| `backend/app/element_detector.py:4,15,37`, `generic_page_intelligence.py:1`, `schedule_tables.py:3,8,26,33`, `revit_v3_adapter.py:27-28,364`, `revit_ids.py:6`, `wall_match.py` docstring | "Madera"/"Dogwood" mentioned only in docstrings/comments explaining *why* a generalized detector exists (contrasted with the frozen client-specific one) | No behavioral effect; these are the modules that correctly generalize. |
| `backend/app/element_registry.py:233` | Comment: `(the Dogwood shear-wall bug)` | Comment only. |
| `backend/app/review_overlay.py` (**frozen**) | Module docstring "S-201 Manual-Review Overlay Generator", artifact filenames `s201_review_*.png/svg/json` | The actual rendering logic (`build_review_items`, `build_overlay_svg`, etc.) takes `page_w`/`page_h`/a compare report as plain parameters and has no S-201-specific geometry — it works for whatever sheet/page is passed in. Only the naming (module title, artifact filenames wired via `config.ARTIFACT_FILES`) is S-201-flavored. |
| `frontend/src/app.js:108` | `"The Madera sample is used when nothing is uploaded."` | UI help text describing the bundled demo/sample data. |
| `frontend/src/app.js:114,132`, `frontend/src/panels/chat.js:118,157-158` | `"H1–H4"`, `"HD3 means H3"`, `"S-201"`, `"H2"` in help/placeholder copy | Example strings in onboarding/chat placeholder text, illustrating the teach-mode workflow — not executable logic. |
| `backend/app/device_match.py:363-384`, `wall_match.py:249-296`, `revit_v3_adapter.py:359-426`, `s201_detector.py` self-check callers, `control_points.py:364-393`, `review.py:375-451`, `revit_bridge.py:475-484`, `revit_convert.py` / `pdf_intelligence.py` docstrings | Inline `if __name__ == "__main__":` self-check blocks using Madera-flavored fixture data (H1-H4, S-201, BM-1/BM-2, "10510 Madera Dr…") | Test-only; never executed in production requests. |
| `backend/app/routers/pipeline.py:48,276` | `"uploaded_madera.pdf"` filename, comment `# v2 (Madera baseline preserved: forcing it costs 32 -> 29 MATCH there)` | Filename is dead-ish (see (a) table); comment documents historical tuning rationale only. |

---

## backend/tests/ — Madera-specific assertions (test-only, not shipped code)

A full inventory was out of scope for the line-by-line pass above, but `backend/tests/` contains numerous tests that assert exact Madera counts (MATCH totals like 106/107, `H1=10,H2=21,H3=6,H4=17,total=54`, specific sheet names). These are regression gates protecting the one known-good baseline and are expected/appropriate for a project that ships with a bundled Madera sample — they do not themselves need to generalize, but they should not be mistaken for evidence that the underlying code generalizes. Flagged here only so they aren't confused with production hardcoding; no line-by-line list produced (test-only, out of shipping-blocker scope).

---

## Summary counts

- **(b) BLOCKS new projects:** 5 findings (2 in frozen modules: `s201_detector.py` via `pdf_intelligence.py`, `normalization.py`+`pdf_convert.py`)
- **(a) demo-safe:** 9 findings/groups (2 in frozen modules: `registration.py` defaults, `compare.py`'s diagnostic block)
- **(c) cosmetic:** 7 findings/groups (1 in a frozen module: `review_overlay.py` naming)

Top 5 blockers (file:line):
1. `backend/app/revit_bridge.py:35` — `DEFAULT_BENCHMARK_FAMILY = "mwfBenchmark"`, no override path (not frozen)
2. `backend/app/s201_detector.py:21-33,59-84` — pixel-hardcoded S-201 bboxes/schedule can silently "succeed" on a differently-laid-out sheet named S-201 with H1-H4 marks (**frozen**)
3. `backend/app/normalization.py:6-13` — `CORE_TOKEN_TO_MARK` blocks v2-schema clients with non-Simpson-H1-4 hardware (**frozen**)
4. `backend/app/pdf_convert.py:13,32-45` — LLM prompt hardcodes H1-H4/Simpson vocabulary every run (**frozen**)
5. `frontend/src/panels/pdf.js:157` — `sheet === "S-201"` breaks the measure-tool scale lookup for any project whose compare sheet isn't literally S-201 (not frozen)
