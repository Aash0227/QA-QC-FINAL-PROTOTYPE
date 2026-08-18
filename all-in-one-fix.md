# QA-QC Automation — Consolidated Engineering Fix Plan

**Generated:** 2026-08-18, via full-codebase Phase 1 (understand) + Phase 2 (audit) pass.
**Method:** Documentation sweep, then verification of every claim against actual source (call-site tracing, not docstring trust).
**Overall verdict:** The generic-first / opt-in-Madera architecture and hardcode removal described in `agent-new-handoff.md` are real and correctly wired. The issues below are what remains — none contradict that baseline, they sit on top of it.

---

## Critical Issues

### C1. Unresolved chirality/mirror-flip risk in `device_match.fit_inverse` (R-01, flagged CRITICAL in `docs/REVIT_SIDE_FLAW_REPORT.md`)
- **What:** With only 2 point pairs, the PDF↔model coordinate fit can pick the wrong mirror chirality (`flip = 1.0` vs `-1.0`), silently producing garbage verdicts for every element on that sheet.
- **Where:** `backend/app/device_match.py::fit_inverse`.
- **Why it's critical:** The flaw report says this was "being fixed tonight" (2026-07-28) with no later doc confirming completion, and **no test exercises this function's chirality-resolution path** — a regression here would be silent (wrong verdicts, not a crash).
- **What happens:** A registration built from a sparse/ambiguous control-point set could flip the whole sheet's coordinate space, turning every MATCH into a false LOCATION_MISMATCH or vice versa.
- **Fix:** Add a dedicated regression test that pins the current chirality-resolution behavior (both fits attempted, lower-RMS kept, refusal below 3 pairs). Confirm in code review whether the actual fix from 07-28 landed — the current code does try both chiralities, but there's no test proving that's stable across edge cases (collinear points, near-symmetric point sets).

### C2. Two divergent stage-dispatch code paths
- **What:** `backend/app/routers/pipeline.py::_run_stage` (line ~776) and `backend/app/run_engine.py::_exec_stage` (line ~214) both implement "call the stage handler for key X" — but only `run_engine._exec_stage` is wired to the live `/api/pipeline/run` endpoint.
- **Why it's wrong:** `pipeline._run_stage` wraps the sync `pdf_page_intelligence` handler in `asyncio.run(...)` unnecessarily, indicating it's either stale/dead code or a second orchestration path that could silently diverge from the one actually running in production.
- **What happens:** If anything still calls `pipeline._run_stage` (a test, a script, a forgotten endpoint), pipeline behavior could differ from what `/api/pipeline/run` produces, with no obvious signal to a developer that two implementations exist.
- **Fix:** Grep all callers of `_run_stage`. If none exist outside `run_engine`, delete it. If something calls it, unify onto `run_engine._exec_stage`.

### C3. Single-worker-only run lock silently breaks under scale-out
- **What:** `run_engine._ACTIVE_THREADS` / `_RUN_LOCKS` are process-local in-memory dicts, not backed by any shared store.
- **Why it's wrong:** The whole 409-duplicate-run / stale-thread-recovery scheme depends on a single process seeing all runs. Already documented as a known limitation (`ponytail:` comment), and the deployment is currently `--workers 1`, so it's not live-broken — but nothing prevents someone from bumping `--workers` for throughput and silently breaking duplicate-run detection (each worker gets its own registry, so two workers could both accept a run for the same project).
- **Fix:** Either hard-enforce single-worker at the uvicorn launch script level with a startup assertion, or move the lock to the filesystem (`run_state.json` + an OS-level file lock) so it's correct regardless of worker count. Given current scale, the cheap fix is the launch-script assertion + a code comment; don't build distributed locking pre-emptively.

---

## Logic Issues

### L1. `device_match`/`wall_match` dual-verdict overwrite is not explainable to the reviewer
- **What:** `wall_match.py` computes a per-sheet verdict in PDF points; `device_match.py` then computes an independent cross-sheet verdict in model feet and **overwrites** `row["status"]` with its own result, keeping the original only as `sheet_status` (audit-only, not shown by default).
- **Why it's wrong:** A shear wall can show `MATCH` in `sheet_status` and `LOCATION_MISMATCH` in the final `status` (or vice versa) with no single threshold a reviewer can point to as "why." This is a real explainability gap for an engineer trying to trust a NEEDS_REVIEW/MISMATCH verdict.
- **Fix:** Surface `sheet_status` alongside `status` in the review UI when they disagree, with a one-line reason ("per-sheet call said MATCH, cross-sheet device reconciliation moved it to LOCATION_MISMATCH because two other sheets place this device further away").

### L2. Greedy nearest-neighbor matching, not optimal assignment
- **What:** `compare._match_with_location`, `device_match._claim`, and `wall_match.match_shear_walls` all use greedy nearest-distance assignment per mark, not an optimal bipartite matching (e.g. Hungarian algorithm).
- **Why it's wrong:** In dense clusters of same-mark elements (e.g. 4+ hold-downs of the same mark close together), greedy assignment can produce a locally suboptimal pairing — one true match gets displaced and reported as a false LOCATION_MISMATCH while a worse pairing is accepted elsewhere.
- **What happens:** False positives (spurious mismatches) specifically in dense layouts — likely underrepresented in the Madera/dogwood-lane baselines if those projects don't have tight clustering, meaning this risk is invisible in current test coverage.
- **Fix:** Not urgent to rewrite as Hungarian algorithm (real complexity cost for likely-rare benefit), but flag it in code with a `ponytail:`-style comment noting the known limitation, and add one test with an intentionally dense same-mark cluster to characterize current behavior.

### L3. `pdf_intelligence.run_page_intelligence` has no internal profile gate
- **What:** The function itself unconditionally calls the Madera-specific `locate_s201_page`/`detect_s201_holdowns`. Every current caller in `routers/pipeline.py` correctly checks `profile.detection_profile() == "madera"` before calling it — but the gate lives entirely at the call site, not inside the function.
- **Why it's wrong:** This is a single point of failure by omission. Any future caller (a new endpoint, a script, a test) that forgets the gate will silently run the Madera-hardcoded path against a non-Madera project.
- **Fix:** Move the `detection_profile() == "madera"` check inside `run_page_intelligence()` itself (raise/return early otherwise), so correctness doesn't depend on every present-and-future caller remembering to check.

---

## Revit / MCP Issues

### R1. Response parsing from Nonica MCP is all regex over free text, not structured JSON
- **What:** `revit_bridge.py`'s `_element_ids`, `_parse_id_locations`, `_parse_bboxes`, `_parse_category_blocks` all regex-match Nonica's tool-output strings (e.g. `r"(\d+\.?\d*)"`, `r"ElementIdsOfCategory\s*\[\d+\]"`).
- **Why it's wrong:** There's no schema contract with Nonica's connector. A Nonica version update that reformats its text output would silently break parsing — the R-30 "unrecognized response" guard catches some of this, but not all format drift (e.g. a reordered field would parse successfully into wrong values, not trigger the unrecognized-response path).
- **Fix:** Not fixable without Nonica exposing structured output (out of this repo's control). Mitigate by widening the R-30 guard's sanity checks (e.g. bounds-check parsed coordinates against the model's known bounding box) so silently-wrong parses are more likely to be caught as "unrecognized" rather than accepted.

### R2. Structural-connection-centric defaults assume a specific building type
- **What:** `STRUCT_CONNECTIONS_CAT = -2009030` and the holdown-assembly-centric live-status logic (`_live_lookup`, `_assembly_status_index`) assume the flagged elements are structural connections/holdowns.
- **Why it's wrong:** A project QA-ing a different element category (e.g. framing-only, or non-light-gauge-steel) gets silently empty live-status joins — no error, just nothing shows up, which reads to a user as "the live Revit feature is broken" rather than "this project's category isn't wired."
- **Fix:** When `_assembly_status_index` returns empty for a project, surface an explicit UI message ("live status not available for this element category") instead of leaving the join silently blank.

### R3. Magic Revit built-in-parameter ID never validated at runtime
- **What:** `MARK_PARAM_ID = -1001203` in `revit_bridge.py` is used for element Mark lookups without validation against the live session.
- **Why it's wrong:** Flagged in `docs/REVIT_SIDE_FLAW_REPORT.md` (R-33) as unverified; if wrong for a given Revit version/locale, Mark lookups would silently return nothing rather than erroring.
- **Fix:** Add a one-time sanity check on connect (look up a known element's Mark via this param ID and confirm it returns a non-empty string of the expected shape) and log/surface a warning if it doesn't.

### R4. Export/live title matching is substring-based and can false-positive
- **What:** `export_watch.py::titles_match()` does `lo_a in lo_b or lo_b in lo_a`.
- **Why it's wrong:** Two differently-scoped models sharing a short common name segment (e.g. "Building A" vs "Building A - Structural") could match when they shouldn't, in a multi-project environment.
- **Fix:** Require exact match or a more specific similarity check (e.g. normalized equality after stripping known suffixes), not raw substring containment.

### R5. `AI_STATUS_MODEL` default (`x-ai/grok-4.20`) looks like a placeholder/typo
- **What:** `routers/pipeline.py:830` — this doesn't match a known real model slug, and is independent of `config.py`'s `OPENROUTER_REASONING_MODEL` default (`deepseek/deepseek-v4-pro`, also unverified).
- **Why it matters:** Low severity — both fail over gracefully to a deterministic canned string on API failure — but it means the "AI status" feature silently never works out of the box unless someone notices and sets the env override.
- **Fix:** Verify both model slugs against the current OpenRouter catalog and correct if stale; document why two independent model configs exist (main reasoning vs. cheap status blurb) so it's not mistaken for a bug on next read.

---

## QA/QC Issues

### Q1. Fixed (non-configurable) feet-based thresholds in `device_match`/`wall_match`
- **What:** `CLUSTER_TOL_FT=3.0`, `MATCH_FT=2.0`, `MISMATCH_FT=6.0`, `LEVEL_DELTA_FT=8.0` (device_match.py) and `SW_MATCH_MAX_PT`/`SW_LOCATION_MISMATCH_MAX_PT` (wall_match.py) are explicitly commented "tuned on Madera S-202 ground truth" but are **not env-configurable**, unlike `compare.py`'s point thresholds which are.
- **Why it's wrong:** For a tool meant to be project-agnostic, a different building's drafting conventions or element spacing could make these specific feet/point values wrong, with no way to adjust per-project without a code change.
- **Fix:** Make these env-overridable the same way `compare.py`'s `MATCH_MAX_PT`/`LOCATION_MISMATCH_MAX_PT` already are. Small, mechanical fix — same pattern already exists in the codebase to copy from.

### Q2. `wall_type` and `unknown` categories can never be flagged from plan callouts
- **What:** `element_detector._category_for()` intentionally excludes these categories from plan-token matching (reasoning: bare digits are likely dimension/grid text, not element marks).
- **Why it matters:** This is a real, documented heuristic tradeoff, not a bug — but it means wall-type marks can only ever appear as `SPEC_ONLY` schedule rows, never `PDF_ONLY`/`NEEDS_REVIEW`. Worth confirming this matches the engineering team's expectation, since it's an invisible ceiling on what the tool can catch for that category.
- **Fix:** No code change needed unless the team wants wall-type plan-callout detection — if so, that's new scope (matches the "expand beyond hold-downs" task already noted in `AGENT_HANDOFF.md`), not a bug fix.

---

## AI / Agent Issues

### A1. No prompt-injection or bounds hardening on the one live LLM call
- **What:** `compare._llm_assessment()` is confirmed advisory-only (never read by verdict logic) — good design — but there's no note on what happens if the OpenRouter call returns malformed/oversized/adversarial content into `report["llm_assessment"]`, which does get displayed to the user in the review UI.
- **Why it matters:** Low risk since it's advisory text only, not executable, but if this field is ever rendered as raw HTML anywhere in the frontend it becomes an XSS vector.
- **Fix:** Confirm the frontend renders `llm_assessment`/AI-status text as plain text (not `innerHTML`), not as a code-execution risk assessment — a quick grep-and-confirm, not a redesign.

### A2. Two independently-configured model defaults with no shared source of truth
- Covered under R5 above — restated here because it's genuinely both an AI-config issue and a Revit-adjacent one. Fix once, applies to both call sites.

---

## Hardcoded / Project-Specific Issues

**Overall: the "3 safe residues" claim in `docs/PHASE1_VERIFICATION_REPORT.md` and `agent-new-handoff.md` holds and is verified accurate** (docstring in `generic_page_intelligence.py`, 10 frozen `test_normalization.py` failures, diagnostic-copy S-201 strings in `control_points.py`). One item from that doc (`control_points.py:128,156` function-signature defaults) appears to have already been fixed since the doc was written — current code has `sheet_number: str | None = None`, not `"S-201"`.

Two items not previously flagged, both low severity:

### H1. `vite.config.js` header comment references a nonexistent `react.html`
- **What:** Comment says "the sandbox for the Phase 3+ Pipeline UI migration... served at `/react.html`" — the actual entry file is `pipeline.html`.
- **Why it matters:** Purely cosmetic, but `docs/INTEGRATION_AUDIT_MASTER.md` flagged this as a LOW-priority fix item that was never applied — worth closing out since it's a one-line comment edit.
- **Fix:** Update the comment to match reality.

### H2. Frontend duplicates a backend threshold constant by comment reference only
- **What:** `frontend/src/*` (revit_live.js) has `MATCH_GATE_FT = 2` mirroring `device_match.py`'s `MATCH_FT=2.0`, tied together only by a code comment, not a shared source.
- **Why it's wrong:** If the backend threshold changes (see Q1 fix above, which would make it env-configurable), the frontend's copy has to be updated by hand or the "why this verdict" explanation text in the UI will describe the wrong number.
- **Fix:** Have the frontend read this threshold from a backend endpoint (e.g. `/api/health` or a small `/api/config` response) instead of hardcoding it, especially once Q1 makes the backend value configurable.

---

## Architecture Issues

### AR1. Orphaned vanilla pipeline-modal code (~300 LOC dead code)
- **What:** `frontend/src/app.js` lines ~130-297 (`renderPipeline()`, `startRun()`, `pollRunState()`, `pdfUpload()`, `revitUpload()`, `showRevitOnly()`) are unreachable — `#btn-pipe` now redirects to `/pipeline.html` instead of opening the modal these functions drive.
- **Why it matters:** Already listed as a known deferred item in `agent-new-handoff.md` §11, confirmed still present. Risk: this dead code could drift out of sync with the real run flow (`run-context.tsx`) and confuse a future maintainer into thinking there are two live pipeline-trigger paths.
- **Fix:** Delete it. Already scoped as next-step #2 in the handoff doc — this audit confirms it's safe to remove (verified zero live callers).

### AR2. `elements_match()` handler is ~260 lines, `pipeline.py` is 919 lines
- **What:** `routers/pipeline.py::elements_match` combines calibration lookup, leader-line extraction, three separate compare-and-merge passes, device-registry reconciliation, and human-review reapplication in one function. The file itself is 919 lines, well past the project's own 800-line/50-line style targets.
- **Why it matters:** Not a correctness bug — the logic is well-commented — but it's a real maintainability risk for a file this central to the pipeline.
- **Fix:** Split `elements_match()` into named sub-steps (calibration lookup → per-category compare → device reconciliation → review reapplication) as separate functions in the same or an adjacent module. Mechanical refactor, not a redesign — do this before adding more element categories (per the "expand beyond hold-downs" roadmap item), since that work will make this function worse if done now.

### AR3. Two parallel SSE client implementations (vanilla `sse.js` vs React `use-pipeline-events.ts`)
- **What:** Both frontends independently implement the same "one EventSource, parse events, idle-timeout fallback poll" pattern.
- **Why it matters:** Not a bug, but duplicate infrastructure that could drift (e.g. vanilla's 8s idle-fallback-poll behavior vs React's reliance on native `EventSource` auto-reconnect only) — worth knowing if/when the vanilla dashboard is eventually retired.
- **Fix:** No action needed now; note for whoever eventually consolidates onto one frontend.

### AR4. `common.py::save_artifact` clears the artifact read-cache globally on every write
- **What:** `_read_artifact.cache_clear()` runs for **all projects**, not just the one being written to.
- **Why it matters:** Correctness is unaffected (the cache is mtime-keyed and would self-invalidate anyway), but it's an unnecessary cross-project side effect from a request-scoped write — worth knowing if per-project isolation guarantees are ever load-bearing elsewhere.
- **Fix:** Low priority. If touched, scope the cache clear to the written project's artifacts only.

---

## Error Handling / Reliability

### E1. `main.py::_step_headline()` swallows all headline-generation errors into a generic "completed" string
- **What:** Broad `except Exception` around SSE headline text generation, logged at warning level only.
- **Why it matters:** Purely cosmetic (SSE progress text), but a malformed artifact schema drift would be silently masked here except via log review — no user-facing signal.
- **Fix:** Low priority given it's cosmetic-only; if picked up, promote to a more specific exception type where feasible and keep the fallback string, just don't let it hide a genuinely new class of error.

### E2. Hand-rolled `.env` parser silently skips malformed lines
- **What:** `config.py::_load_dotenv()` skips any line without `=` with no warning.
- **Why it matters:** A malformed `.env` line (typo, stray character) fails silently — someone could set an env var wrong and never know why it didn't take effect.
- **Fix:** Log a warning (not an error — don't block startup) when a non-comment, non-blank line is skipped for lacking `=`.

### E3. No login/token-entry UI despite real bearer-token auth support
- **What:** `main.py` implements genuine constant-time bearer-token auth (`QAQC_AUTH_TOKEN`), and both frontends read the token from `localStorage.getItem("qaqc_token")` — but nothing in the frontend ever *sets* that key. There's no login form anywhere.
- **Why it matters:** Fine for local-only dev (auth is off by default), but if this tool is ever deployed somewhere non-localhost with the token enabled, there is currently no way for a user to authenticate through the UI — it would require manual devtools localStorage injection.
- **Fix:** Not urgent while deployment stays localhost-only per current install target (Windows desktop app via Inno Setup). Flag as a blocker specifically if/when network deployment is ever considered.

---

## Testing Issues

### T1. `device_match.fit_inverse` (the CRITICAL chirality function, C1 above) has no dedicated test
- Restated from C1 — the single highest-value test gap in the suite. Add first.

### T2. `profile.py` has no direct test file
- **What:** Only exercised indirectly via `monkeypatch.setattr(profile_mod, "detection_profile", ...)` in other test files — no test covers `profile.py`'s own logic (reading from a real manifest, `KNOWN_PROFILES` validation, malformed-value handling).
- **Fix:** Add `test_profile.py` covering: valid `"madera"` value, unknown profile string, missing manifest, malformed JSON.

### T3. No test for `revit_ids.py`'s UniqueId→ElementId decoder
- **What:** This module fixed a documented previously-shipped bug (naive hex-suffix decode was wrong for 4/7 real elements) — it has a self-test assertion inline but no pytest file pinning the fix as a regression test.
- **Fix:** Promote the inline self-check into a real `test_revit_ids.py` so CI catches a regression, not just a manual run.

### T4. No test for `review.py`'s confirm/false-alarm workflow
- **What:** Per `docs/REVIT_SIDE_FLAW_REPORT.md`, this is "~90% already built" functionality (offset/systematic-shift explainability) with no dedicated test file.
- **Fix:** Add coverage once the feature's current behavior is confirmed intentional — don't write tests against unclear behavior; clarify with the team first.

### T5. `scene3d.py` has no test coverage
- **What:** Flagged in the Phase 0 audit as a performance hotspot (built in the request thread); no test verifies the caching fix mentioned in later docs actually works.
- **Fix:** Add a test asserting repeated calls within the cache TTL don't re-trigger the expensive build path.

---

## Deployment Issues

### D1. `AGENT_HANDOFF.md` and `agent-new-handoff.md` are both currently untracked/uncommitted
- **What:** Per `git status`, `agent-new-handoff.md` is untracked. These are the most authoritative context docs for the project.
- **Why it matters:** If the branch is merged or the machine changes, this context is lost unless explicitly committed.
- **Fix:** Commit these (or move sensitive/ephemeral parts to `memory/` per the project's own operating-manual convention) before merging `fix/integration-runcheck` → `main`.

### D2. Stop/Report buttons on the React pipeline page are disabled placeholders
- **What:** No backend endpoint exists to stop a running pipeline or generate a report.
- **Why it matters:** Already listed as known/deferred in the handoff doc — restating here because it's a real UX gap for production use (a user who starts a run against the wrong project currently has no way to stop it short of a backend restart).
- **Fix:** Already on the roadmap (`agent-new-handoff.md` §17 item 4) — no new finding, just confirming it's still open and worth prioritizing before wider rollout, since "can't stop a bad run" is a real day-one usability issue for non-technical users.

### D3. Test-isolation flake in `_ACTIVE_THREADS` singleton across test modules
- **What:** Already documented (`test_run_state`/`test_upload_attach` intermittent full-suite ordering issue, pass standalone).
- **Fix:** Already scoped as next-step #6 in the handoff doc. Restating priority: fix before relying on full-suite CI runs as a merge gate, since a flaky test erodes trust in the whole suite.

---

## Recommended Fix Priority (if doing these in order)

1. **C1** — pin `device_match.fit_inverse` chirality behavior with a test (verify or fix the underlying CRITICAL flaw).
2. **T1/T2/T3** — close the test gaps that back already-fixed critical bugs, so regressions get caught automatically.
3. **C2** — resolve the duplicate stage-dispatch code path (delete or unify).
4. **L3** — move the Madera profile gate inside `run_page_intelligence()` for defense-in-depth.
5. **AR1** — delete the ~300 LOC of dead vanilla pipeline-modal code.
6. **Q1** — make `device_match`/`wall_match` thresholds env-configurable (mechanical, matches existing pattern).
7. **D1** — commit the handoff docs before merging to main.
8. Everything else (L1, L2, R1–R5, H1–H2, AR2–AR4, E1–E3, D2–D3) — lower severity, fix opportunistically or when touching the relevant file for other reasons.
