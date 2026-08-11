Do NOT touch code yet.

---

# 📋 PHASE 2 — FULL HARDCODED-VALUE AUDIT (READ-ONLY)

**Goal:** Build an exhaustive list of every Madera- or Dogwood-specific hardcoded value in the codebase.

Scan for:
- `"Madera"`, `"Dogwood"`, `"Country Side"`, `"country-side-ct"`, `"dogwood-lane"` as string literals
- Hardcoded PDF baselines (H1=10, H2=21, H3=6, H4=17)
- Hardcoded sheet names (`"S-201"`, `"S-205"`)
- Hardcoded file paths in source (not in `.env` or manifest)
- Hardcoded Element IDs, UniqueIds, or coordinates
- Hardcoded grid intersections (`"A/1"`, `"C/3"`, etc.)
- `pdf_baseline` constants
- Regex patterns that specifically match only Madera family names
- Tests that assert Madera-specific numbers

Produce a **`HARDCODING_AUDIT.md`** file listing each finding with file:line and whether it's (a) demo-safe, (b) blocks new projects, or (c) cosmetic.

**STOP. Output the audit summary. Do NOT fix anything yet.**

---

# 📋 PHASE 3 — DE-HARDCODE THE PIPELINE (DEMO-CRITICAL)

**Goal:** Any new project PDF+JSON pair should flow through the pipeline without modification. Fix the (b) blockers from Phase 2 audit ONLY — leave cosmetic ones alone.

Priority targets:
1. **PDF baseline** — read from the PDF's own schedule tables (already exist in `element_intelligence`). Drop the Madera-specific fallback.
2. **Sheet detection** — if `pdf_intelligence.py` already generalizes, verify it works on Dogwood. If not, fix the path that only picks up S-201.
3. **`CORE_TOKEN_TO_MARK` / spec maps** — must be derived from the PDF's own schedule or loaded from project config, not hardcoded. Check `normalization.py` and `revit_v3_adapter.py`.
4. **Registration calibration sources** — RANSAC + benchmarks. Verify benchmarks flow works without being Madera-stamped. Auto-benchmark injection (see Phase 6) should be the primary path but RANSAC must still work as fallback.
5. **`pdf_baseline` field in `ai_revit.json`** — make it per-project, stored in the project manifest.
6. **Tests** — any test asserting on `"Madera"` or Madera-specific numbers should use a fixture PDF or be moved to a `_slow` marker that only runs on the real Madera artifacts.

After each fix:
- Run the matching test
- Run the FULL pytest suite and confirm still 190+ green
- Re-run `POST /api/elements/match` on Madera and Dogwood and confirm verdict counts match pre-fix

**STOP. Output what changed, the new pytest count, and the new Madera/Dogwood verdict counts.**

---

# 📋 PHASE 4 — 3D VIEWER: LIVE MCP-DRIVEN (NOT HARDCODED)

**Goal:** The 3D pane next to the PDF must display the CURRENTLY-OPEN Revit model in real time, not a frozen scene3d JSON snapshot. Works on any model the user opens.

**Current state (investigate first):**
- `backend/app/scene3d.py` builds a scene JSON from the export's `walls`, `grids`, `category_elements`, `framing`, `holdowns`
- `frontend/src/panels/viewer3d.js` renders it via Three.js

**What to build:**
1. **Hybrid 3D**: on viewer load, try to fetch live geometry from Nonica+Revit MCP first. If both off, fall back to the export-derived scene3d JSON (existing). Surface the source in the UI ("Live Revit" vs "Export snapshot").
2. **Live refresh endpoint** `POST /api/revit-live/refresh-3d` — re-queries the open model's walls/frames/columns/holdowns and updates the viewer via WebSocket or polling.
3. **Generic project support**: the 3D viewer must not assume Madera-specific bounding boxes, wall counts, or hold-down family names. Derive bounds from the live geometry or export `bounds` field.
4. **Status-color mapping**: keep the existing status colors (MATCH=green, LOCATION_MISMATCH=orange, PDF_ONLY=blue, REVIT_ONLY=red) but apply them dynamically using the current project's device registry, not hardcoded assembly IDs.

After changes:
- Dogwood Lane open in Revit → 3D pane shows Dogwood geometry, not Madera
- Madera open → 3D pane shows Madera geometry with same 106 MATCH
- PDF + export only (no Revit open) → graceful fallback to snapshot with banner

**STOP. Report before/after screenshots (describe them textually) and test results.**

---

# 📋 PHASE 5 — "SHOW IN REVIT" + ID LOOKUP (DUAL-MCP FLOW)

**Goal:** Click any element in the webapp → it highlights in Revit (blue selection). This already exists from commit `d62b17b` but has a parser bug with large selections.

1. **Fix the Nonica response parser** (R-34) — it truncates many-element selections into a "selected N of M" form. Parse that correctly.
2. **Add `/api/revit/selected-element` integration** with the open-source revit-mcp (port 8080). When a user clicks **"Use current Revit selection"** in the Revit ID drawer, fetch the selected element's ID via rev-mcp, then look up its verdict in the device registry.
3. **Dual-server fallback**: prefer rev-mcp for reading (richer data), prefer Nonica for writing (highlighting). Surface in the UI which served each call.
4. **Verify on Dogwood lane**: click an element, confirm Revit highlights it. Click rev-mcp lookup, confirm the webapp shows the element's context.
5. **Tests:** add tests for (a) large selection parsing, (b) fallback when only one MCP is up, (c) mismatch between export-time and live IDs.

**STOP. Report.**

---

# 📋 PHASE 6 — AUTO-BENCHMARK + AI SUMMARIES PER PHASE

**Goal:** After PDF upload, the system automatically adds two benchmark registration points (no manual BM-1/BM-2 step for the user). After every pipeline phase, an AI summary describes what happened.

1. **Auto-benchmark injection:**
   - After PDF upload, extract grids from the PDF.
   - Pick 2 well-separated intersections (max diagonal, axis-agnostic — already shipped in BUG-01 fix).
   - Place BM-1/BM-2 in the PDF via `benchmark_workflow.stamp()` on the user's behalf.
   - Surface in the webapp: a banner *"I've automatically proposed 2 benchmark registration points at A/3 & C/1. Approve to continue."* with Approve/Edit buttons.
   - On approve: prompt the user to place the same 2 benchmark families at those coordinates in the live Revit model (Nonica bridge can do this automatically if the connector is on).
   - Fallback: if no Revit connection, skip benchmarks and do RANSAC hold-down registration instead (existing flow).

2. **AI summary per phase:**
   - After Upload: *"PDF opened: 12 sheets, 3 structural plans detected. Schedule tables: hold-down, shear wall, column."*
   - After auto-benchmark: *"2 benchmarks proposed at grid intersections A/3 and C/1 (max diagonal spread). PDF stamped."*
   - After Revit-bridge benchmark placement: *"BM-1 placed at (X,Y)ft, BM-2 at (X,Y)ft. Read-back verified within 0.02 ft."*
   - After registration: *"Calibration: scale 17.97 pt/ft, rotation 0.05°. Quality: HIGH (32 inliers). Match allowed: true."*
   - After compare/match: *"354 elements compared. 106 MATCH, 20 LOCATION_MISMATCH, 228 other. 15/20 mismatches are systematic (same direction, same magnitude) — likely a drafting offset, not modeling error."*

3. **Where to show:** a running log panel (reuse the existing pipeline modal's live log, which already uses SSE — just append to it).

**STOP. Report. This is the most complex phase — if anything breaks, revert and ask before pushing forward.**

---

# 📋 PHASE 7 — REMAINING FLAW FIXES (R-IDs)

Now tackle the rest of the 33-flaw list, in priority order:

- [ ] **R-19** — surface `classification_reason` everywhere (trivial copy)
- [ ] **R-24** — registration quality per verdict (trivial copy)
- [ ] **R-26** — systematic-shift analysis in every view
- [ ] **R-27** — remove hardcoded Madera baseline (deferred from Phase 3 if still open)
- [ ] **R-22** — fix `distance_pdf_points` CSV column
- [ ] **R-03** — level/elevation gate in device_match (RISKY — add tests first)
- [ ] **R-30** — disconnect detection via structural check not substring
- [ ] **R-10** — add `"Generic Models"` to hold-down categories
- [ ] **R-21** — MARK_MISMATCH in accuracy denominator

**For each:** write the fix → add test → run pytest → confirm green grows. Commit after every 2-3 fixes.

---

# 📋 PHASE 8 — FINAL SMOKE TEST ON DOGWOOD LANE

**Goal:** Prove the whole thing works end-to-end on a non-Madera project.

1. Activate the Dogwood Lane project.
2. Verify the 3D pane shows Dogwood geometry (from live Revit MCP since Dogwood is currently open).
3. Pick a random hold-down from the device list, click **"Show in Revit"** — confirm Revit highlights it.
4. In Revit, select a different element manually. Click **"Use current Revit selection"** in the webapp — confirm the correct verdict explanation appears.
5. Run `POST /api/elements/match`. Record verdicts.
6. Re-run. Confirm counts are deterministic.
7. Check the Runs drawer — verify baseline comparison works.

**STOP. Report a DOGWOOD ACCEPTANCE CHECKLIST with pass/fail per item.**

---

# 📋 PHASE 9 — AUDIT EVERY LINE (READ-ONLY REPORT)

**Goal:** A final senior-engineer review of the entire codebase as it stands after Phases 1-8.

For every `.py` file in `backend/app/` and every `.js` file in `frontend/src/`:
- Count lines of code
- List public functions with 1-line purpose
- Flag any remaining hardcoded paths, string literals, Madera-specific logic
- Flag dead code (functions never called)
- Flag missing tests (functions with no test coverage)
- Flag any inconsistency between docstring and actual behavior

Produce `CODEBASE_AUDIT_REPORT.md` in `docs/`. This is the "senior engineer's eyes" review.

**STOP. Output summary: total LOC, N files, N dead-code items, N missing-test items, N remaining-hardcode items.**

---

# 📋 PHASE 10 — COMMIT & HANDOFF

1. `git add -A` everything changed.
2. `git ci -m "feat(ship): generic pipeline + live MCP 3D + auto-benchmarks + AI phase summaries"`
3. Update `AGENT_HANDOFF.md`:
   - Status checkpoint with every phase marked done
   - New workflow section: "User uploads PDF → auto-benchmarks → user opens Revit → live 3D + show-in-revit"
4. Update `README.md` with the new 3-step user workflow:
   1. Upload PDF + Revit JSON
   2. Open Revit model, enable Nonica AI Connector + open-source revit-mcp server
   3. Review in webapp
5. Update `LIVIO_TEAM_GUIDE.md` — the user-facing manual.

**FINAL STOP. Report: commit SHA, pytest count, Madera verdict diff vs baseline, Dogwood verdict counts, anything still TODO.**

---

# ⚠️ IF YOU GET STUCK

- A test fails that you didn't write → **stop and show me the failure** rather than rewriting the test.
- A frozen module seems to need editing → **stop and ask first**. There's often a wrapper or call-site you can change instead.
- MCP calls timeout or return wrong data → **fall back to the export-derived path** and report which tool failed.
- You're unsure if a change breaks Madera invariance → **run `/api/elements/match` on Madera and compare**. Numbers must match the baseline.

---

# 🚀 START NOW

Begin Phase 1. Do not read ahead past Phase 1 until you've reported Phase 1 status.
**Respond with your Phase 1 STATUS BLOCK only when ready.**