# PROMPT: Implement Revit-Live Explainability System for QA-QC Prototype

You are picking up a critical feature for the Livio QA-QC AI prototype at:
`C:\QA-QC-FINAL-PROTOTYPE-bkp`

Read this prompt **top-to-bottom** before touching any code.

---

## READ THESE FILES IN ORDER (MANDATORY)

Before any coding, read and internalize:

1. **`C:\QA-QC-FINAL-PROTOTYPE-bkp\AGENT_HANDOFF.md`**
   — Master status of the project, frozen modules, environment, conventions.

2. **`C:\QA-QC-FINAL-PROTOTYPE-bkp\docs\REVIT_LIVE_WORKFLOW_ARCHITECTURE.md`**
   — The complete architecture for what you're building. 43KB, 17 sections +
   appendices. This is your bible. FOLLOW IT.

3. **`C:\QA-QC-FINAL-PROTOTYPE-bkp\docs\NONICA_PRO_FEASIBILITY_EVALUATION.md`**
   — What the Nonica PRO MCP API can do. Confirms feasibility of the plan.

4. **`C:\Users\aashd\REVIT_PIPELINE_EXPLAINABILITY_FLAWS.md`**
   — The 21 explainability flaws this work fixes. Prioritized by impact.

5. **`C:\QA-QC-FINAL-PROTOTYPE-bkp\production-grade-plan-final.md`**
   — The production roadmap this fits into.

6. **Existing modules** you must understand before touching:
   - `backend/app/revit_bridge.py` — already drives Nonica via MCP (USE THIS, don't reinvent)
   - `backend/app/device_match.py` — physical device matching (KEEP UNCHANGED — the verdict logic is FROZEN)
   - `backend/app/compare.py` — the FROZEN math of coordinate comparison
   - `backend/app/registration.py` — the FROZEN transform math
   - `backend/app/routers/revit.py` — existing Revit endpoints you extend
   - `backend/app/chat_agent.py` + `backend/app/openrouter.py` — existing LLM infrastructure you reuse
   - `backend/app/review.py` — existing review system you extend (not replace)

---

## ENVIRONMENT (NON-NEGOTIABLE)

- Python: `C:\Users\aashd\AppData\Local\Programs\Python\Python311\python.exe`
- Server: `cd C:\QA-QC-FINAL-PROTOTYPE-bkp\backend && python -m uvicorn app.main:app --host 127.0.0.1 --port 8077`
- Tests: `cd C:\QA-QC-FINAL-PROTOTYPE-bkp\backend && python -m pytest -q`
  - **Baseline: 165 tests green before you start. Must stay green or grow.**
- Module: the Python package is `app` (inside `backend/app/`)
- Working directory: always start Python commands from `backend/`

---

## CORE PRINCIPLES (DO NOT VIOLATE)

1. **Frozen math stays frozen**: NEVER modify `compare.py`, `registration.py`,
   `s201_detector.py`, `pdf_intelligence.py`, `review_overlay.py`,
   `normalization.py`, `revit_convert.py`, `pdf_convert.py`. Additive
   parameters only. No changing the transform math, no changing the
   distance gates, no changing the MATCH threshold.

2. **No fake matches ever**: Every MATCH must trace back to verified
   registration + explicit distance gate. The explainability layer is
   **descriptive, not prescriptive** — it explains verdicts, it doesn't
   invent them.

3. **Backward compatible**: Existing API endpoints must keep working.
   Additive endpoints only. Existing artifacts (device_registry.json,
   compare_report.json, etc.) must still be valid JSON that existing
   consumers can read.

4. **Honesty first**: If the Revit bridge is offline, the UI must
   surface that truthfully, not silently fall back or lie. Explainability
   failures (LLM down) should degrade to plain-English template
   strings, never crash.

---

## WHAT YOU'RE BUILDING (3 Phases)

### Phase 1 — Visual Verification (PRIMARY GOAL)

Build these endpoints/features:

1. **`GET /api/revit-live/status`**: Returns connection state to live Revit
   model. Uses `revit_bridge.py` (already exists!). Returns:
   ```json
   {
     "connected": true,
     "model_name": "Madera_Structural.rvt",
     "view_name": "{3D}",
     "last_checked": "2026-07-27T..."
   }
   ```

2. **`GET /api/revit-live/match/{assembly_id}`**: Takes a Revit assembly ID
   from `device_registry.json` and returns the live ElementId in the open
   model (unique IDs can drift between exports). Uses the existing
   coordinate-matching logic in `routers/revit.py`. Extends it, doesn't
   rewrite it.

3. **`POST /api/revit-actions/highlight`**: Takes a list of ElementIds,
   calls `mcp__revit_mcp__operate_element` with action="Highlight" (or
   SelectionBox to zoom in). Returns success/failure per ID.

4. **"Show in Revit" frontend button** — next to every element in:
   - Results table (`frontend/src/panels/table.js`)
   - Review drawer (`frontend/src/` wherever renderReviewer lives)
   - Inspector panel (`frontend/src/panels/inspector.js`)

   Button behavior:
   - If Revit is connected → call `/api/revit-actions/highlight` with the
     element's live ID → toast success
   - If Revit is offline → button is greyed out, tooltip says "Open Revit
     and enable the A.I. Connector"
   - Loading state while highlighting happens (~1s)

5. **"Paste Revit ID → show element + reasoning" tool** — a new panel in
   the webapp (similar to Chat drawer, simpler). User pastes any Revit
   Element ID, backend looks it up in the device registry + compare report,
   returns the element's verdict + explanation.

### Phase 2 — AI Explanations

1. **`explain_verdict(device_id)` API** — a new endpoint that aggregates
   the full traceability chain into plain English. Returns a
   `reasoning` field alongside every verdict in the device registry.
   Use existing `chat_agent.py` infrastructure + OpenRouter.
   Explanation format:
   > "This hold-down (H2-015) is located 2.1 ft from the Revit model,
   > offset to the northeast. 15 other mismatches on S-201 show similar
   > shifts, suggesting a systematic coordinate offset rather than a
   > modeling error. Registration quality: 95% confidence — trust this
   > verdict. Recommended action: accept as systematic PDF offset."

2. **Surface registration quality per verdict**: Add `registration_quality`
   field to every verdict in `device_registry.json`:
   ```json
   "registration_quality": {
     "confidence": "high",
     "rms_residual_pt": 2.1,
     "inlier_count": 32,
     "source": "benchmark_verified"
   }
   ```
   DO NOT change the verdict logic. Just add a metadata field.

3. **Spatial context in verdicts**: Add `spatial_context` field:
   ```json
   "spatial_context": {
     "nearest_grid_intersection": "A-3",
     "level": "Level 1",
     "elevation_ft": 0.0,
     "nearby_elements": ["rev_asm_009", "rev_asm_013"]
   }
   ```
   Get this from the live Revit bridge when possible.

### Phase 3 — Bidirectional Sync

1. **WebSocket at `/ws/revit-sync`** — broadcast verdict confirmations to
   all connected clients in real-time.

2. **`POST /api/revit-actions/update-status`** — write `qa_status` shared
   parameter (e.g., `CONFIRMED_MATCH`, `FALSE_ALARM`, `INVESTIGATE`) back
   to the live Revit element. Use `mcp__revit_mcp__send_code_to_revit`
   with a C# snippet.

3. **`GET /api/revit-actions/sync`** — read back all elements with
   `qa_status` set, update local compare_report.json accordingly.

4. **Batch operations UI** — multi-select elements in the table, bulk-accept
   as "systematic offset" or "design change" with one comment.

---

## FOUNDATION REQUIREMENTS

Before adding new features:

1. **Read the 5 context docs** listed above. Take notes on frozen modules.
2. **Run pytest** (`python -m pytest -q`) and confirm 165 green baseline.
3. **Read `backend/app/revit_bridge.py`** end-to-end. Understand how it spawns
   `RevitMCPConnection.exe` and calls the 52+ MCP tools. Don't rewrite it.
4. **Read `backend/app/routers/revit.py`** end-to-end. Understand existing
   endpoints. You extend these, you don't replace them.

---

## BACKEND DEVELOPMENT

1. Add `get_revit_status()` to `revit_bridge.py` that calls
   `get_active_view_in_revit` and returns connection state.

2. Add new router file `backend/app/routers/revit_live.py` with:
   - `GET /api/revit-live/status`
   - `GET /api/revit-live/match/{assembly_id}`

3. Add new router file `backend/app/routers/revit_actions.py` with:
   - `POST /api/revit-actions/highlight`

4. Register both routers in `backend/app/main.py` `create_app()`.

5. Write tests in `backend/tests/test_revit_live.py` using the existing
   fake-MCP-server pattern from `test_revit_bridge.py`. Target: +20 tests.

6. Run `python -m pytest -q` — expect 185+ green.

---

## FRONTEND DEVELOPMENT

1. Add "Show in Revit" button to the results table.
   - Located: `frontend/src/panels/table.js` (render method).
   - Calls `/api/revit-actions/highlight` with `element.revit_ref.id`.
   - Loading/success/error states, toast notifications.

2. Add the same button to the review drawer (wherever renderReviewer
   lives in `frontend/src/panels/`).

3. Add the same button to the inspector panel (`review_detail` view).

4. Build a new "Revit ID Lookup" panel (simpler than Chat drawer):
   - Text input for Element ID
   - Calls `/api/revit-live/match/{id}` and displays verdict + explanation

5. Run Playwright smoke suite: `cd frontend && npx playwright test`
   - Assert: button exists, works when mocked, shows disabled state offline.

---

## POLISH & INTEGRATION

1. End-to-end test with the Madera project (if Revit is open).
2. Update `README.md` and `docs/USER_GUIDE.md` with the new features.
3. Update `AGENT_HANDOFF.md` "Status checkpoint" section with what shipped.

---

## ACCEPTANCE CRITERIA

Before declaring Phase 1 done, verify LIVE (not just tests):

1. ✅ Start server: `python -m uvicorn app.main:app --host 127.0.0.1 --port 8077`
2. ✅ Open http://127.0.0.1:8077 in browser
3. ✅ Activate Madera project
4. ✅ Run full pipeline (PDF + Revit JSON + Match) — 107 MATCH baseline intact
5. ✅ Open Revit with Madera model + Nonica A.I. Connector enabled
6. ✅ Click "Show in Revit" on a mismatch row → Revit zooms to that element
7. ✅ Paste a known Element ID into the lookup panel → shows verdict
8. ✅ Disconnect Revit (close A.I. Connector) → buttons grey out with honest
   tooltip, no errors logged
9. ✅ Run `python -m pytest -q` — 185+ green, no regressions on 165 existing
10. ✅ Run Playwright smoke — MATCH=107 baseline preserved, new buttons render

---

## WHAT NOT TO DO

❌ DO NOT rewrite `compare.py` or its verdict logic
❌ DO NOT change the 16-point MATCH threshold
❌ DO NOT change the 2ft/6ft device-match thresholds
❌ DO NOT remove any frozen module (even if you think it's cleaner)
❌ DO NOT add new PyPI dependencies without asking — prefer reusing what's
   in `requirements.txt` (fastapi, uvicorn, pymupdf, mcp, httpx)
❌ DO NOT add React or any frontend framework — we use vanilla ES modules
❌ DO NOT break backward compatibility of any existing JSON artifacts
❌ DO NOT make explainability hallucinate — if LLM is offline, use templates
❌ DO NOT modify IFC code — we removed it, don't re-add it

---

## WHAT TO ASK ABOUT

If anything in this prompt is unclear, STOP and ask. Specifically ask if:

- You're unsure whether a module is frozen or not
- A change feels like it might alter a verdict (it probably does — ask first)
- You need a new PyPI dependency
- You're unsure about Nonica MCP tool names (check the bridge)
- You're unsure about frontend conventions (check existing panels/*.js)

---

## DELIVERABLES

When you're done, produce:

1. **Code**: All new modules, updated files, tests
2. **Docs updated**:
   - `AGENT_HANDOFF.md` — update "Status checkpoint" section
   - `docs/USER_GUIDE.md` — document the new "Show in Revit" workflow
   - `docs/REVIT_LIVE_WORKFLOW_ARCHITECTURE.md` — mark implemented sections
     with ✅ DONE
3. **Tests**: +20 new tests covering Phase 1 endpoints, frontend smoke test
   updates
4. **Summary report**: What's implemented, what's deferred to Phase 2/3,
   any blockers or surprises hit during implementation

---

## FINAL CHECKLIST (SELF-VERIFY BEFORE REPORTING DONE)

- [ ] All existing pytest tests pass (165+)
- [ ] New tests cover every new endpoint
- [ ] Frozen modules are literally byte-identical to before
- [ ] Existing JSON artifacts still parse without changes
- [ ] Frontend buttons work when Revit is open, degrade gracefully offline
- [ ] `AGENT_HANDOFF.md` is updated with current state
- [ ] No hardcoded personal paths in source (BUG-02 was fixed — don't regress)
- [ ] No secrets/keys committed to code

---

Start by reading the 5 context docs. Then reply with a brief plan confirming
your understanding before writing any code. Go.
