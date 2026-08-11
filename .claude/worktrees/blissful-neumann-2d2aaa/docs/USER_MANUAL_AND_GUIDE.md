# Livio QA-QC Intelligence — Complete User Manual & Feature Guide

**Product:** Automated Revit ↔ PDF structural QA-QC verification
**Company:** Livio Building Systems Inc.
**Version:** Production-hardened prototype (2026-07) — modular frontend, agentic chat, IFC 3D, Benchmark Autopilot
**Audience:** QA-QC engineers, reviewers, project managers, and power users

---

## PART A — USER MANUAL (step by step)

### A1. What this tool is (30-second version)

You give it two files:

1. A **Revit export** — a `.json` file produced by the "Export QA-QC JSON" pyRevit button inside Revit (schema v3.1+).
2. A **PDF drawing set** — the stamped structural sheets (S-201, S-202, ...).

The tool reads both, mathematically aligns the drawing coordinates to the model coordinates, and tells you — for every hold-down, shear wall, post and steel column — whether the drawing and the model **agree (green)** or **disagree (red/orange)**. You review the discrepancies and export a punch-list CSV for the site team.

What used to be ~8 days of manual cross-checking per project becomes a queue of specific, explained discrepancies.

**The one rule everything is built on: it never fakes a match.** A MATCH is only declared when a verified coordinate alignment exists AND the two positions fall within an explicit distance gate. Anything uncertain is flagged honestly instead of guessed.

---

### A2. Requirements & installation (one time)

| Requirement | Detail |
|---|---|
| OS | Windows (same machine as Revit if you use the live Revit bridge) |
| Python | **3.11 exactly** (`C:\Users\aashd\AppData\Local\Programs\Python\Python311\python.exe`). The project vendors PyMuPDF/PIL compiled for 3.11; Python 3.14 will crash. |
| Project folder | `C:\QA-QC-FINAL-PROTOTYPE-bkp` |
| Dependencies | `cd backend` then `python -m pip install -r requirements.txt` |
| OPENROUTER_API_KEY (optional) | In the project's `.env` file. Only the 💬 Chat copilot needs it — everything else runs fully offline. |
| NONICA_MCP_EXE (optional) | Path to Nonica's `RevitMCPConnection.exe`. Only needed for live Revit placement in the Benchmark Autopilot wizard. |

### A3. Starting the application

Open PowerShell:

```powershell
cd C:\QA-QC-FINAL-PROTOTYPE-bkp
.\run_backend.ps1
```

Leave that window open — it is the server. You will see `Uvicorn running on http://127.0.0.1:8077`.

Open your browser at:

```
http://127.0.0.1:8077
```

That is the whole start procedure. One process serves both the API and the dashboard.

**To stop:** close the PowerShell window (or Ctrl+C).

### A4. The dashboard at a glance

The header has four labelled zones, left to right:

| Zone | Buttons | What they do |
|---|---|---|
| Project | ☰ list toggle, 📁 project dropdown, live stats badge | Switch between projects (madera, country-side-ct, dogwood-lane...). Each project's files and results are fully separate. |
| Pipeline | ▶ Pipeline, ① Extract, ② Match | Run the processing steps (see A5). |
| Views | ▤ Table, ◎ Autopilot, ⚖ Runs, ⚠ Review (badge = open items) | Open the results table, the benchmark wizard, the run-comparison view, and the human-review queue. |
| AI | 💬 Chat | The agentic chat copilot (see B6). |

Below the header are the three main panes:

- **Left — element list.** Every element grouped by category → mark (e.g. HD2 (49), SW-1 (21)) with coloured status dots, a search box, and status/sheet filters.
- **Middle — DRAWING · PDF.** The actual drawing with sheet tabs, coloured rings on every detected callout, plus 📏 measure, Layers, ⛶ fit and ⤢ expand buttons.
- **Right — REVIT MODEL · 3D.** Three.js view of the exported model; coloured status balls on each device. Buttons: ◆ Revit IFC (load real geometry), SW only, Top view, Reset, ⤢ expand.

Slide-in drawers appear from the right when needed: the **Evidence Inspector** (element details), the **⚠ Review** queue, and the **💬 Chat** panel.

### A5. Running a project end to end (the step-by-step happy path)

1. **Start the server and open the dashboard** (A3).
2. **Click ▶ Pipeline.** A full-screen modal opens with one card per stage, each with its own Run button, plus **▶ Run full pipeline** to do everything in order.
3. **Stage 0 — Upload project.** Provide the client's PDF and the Revit JSON (either or both; you can also upload an optional IFC model for the 3D view). This creates/updates the project workspace under `artifacts/projects/<slug>/`.
4. **Stage 1 — Revit convert.** Groups the raw export's loose parts (a hold-down body plus its anchor bolt) into single physical assemblies and assigns each the mark your drawings use — read from YOUR hold-down schedule table.
5. **Stage 2 — PDF intelligence.** Finds the foundation/anchorage plan page and every hold-down callout on it, following leader lines to true locations.
6. **Stage 3 — PDF convert.** Restructures the PDF detections into the same canonical shape as the Revit data.
7. **Stage 4 — Registration (the math).** Automatically solves how model feet map onto paper points (RANSAC over same-mark hold-downs; grid-intersection fallback; or exact 2-point benchmark calibration — see A7). If a sheet cannot be registered, nothing on it is allowed to MATCH. That is the honesty guarantee, not an error.
8. **Stage 5 — Compare.** Pairs Revit and PDF hold-downs one-to-one; within tolerance = MATCH; everything else flagged honestly.
9. **Stage 6 — Extract ALL elements.** Scans every sheet, discovers every schedule table by title, reads the MARK column to learn the valid vocabulary, and finds those marks on the plans. Applies any taught rules.
10. **Stage 7 — Teach (optional).** Save recognition rules for non-standard labels (now done conversationally via 💬 Chat — see A8).
11. **Stage 8 — Match everything.** Registers each sheet independently, matches shear walls to Revit wall centrelines, groups all callouts into physical devices, and builds the unified element list.
12. **Stage 9 — Review & export.** Work the ⚠ Review queue, then export the punch-list CSV and annotated overlays.

> **Day-to-day shortcut:** after the first full run, you normally just use **① Extract** (after teaching a rule) and **② Match** (after a new Revit export). Each is one click.

### A6. Reading the results — the colour language

| Status | Colour | Meaning | What YOU do |
|---|---|---|---|
| MATCH | green | Same mark, same place (within gate), verified alignment | Nothing — verified |
| LOCATION_MISMATCH | orange | Same device on both sides but positions differ beyond the gate | Review it — your main queue |
| MARK_MISMATCH | pink | A device IS there, but drawn with a different mark than modeled | Check callout vs family — one is mislabeled |
| PDF_ONLY | blue | On the drawing; no model device found near it | Modeling gap OR detection gap — verify |
| REVIT_ONLY | red | Modeled; no drawing callout found anywhere | Often a missed callout or over-modeling |
| NOT_IN_SCHEDULE | grey | The mark is not in any schedule table the tool could read | Teach the mapping (A8) |
| NO_REVIT_DATA | grey | The export contained nothing of this category | Re-export with the category visible |
| NOT_EVALUATED | grey | Sheet could not be registered (e.g. detail sheets) | Informational |

**Key concept — physical devices, not drawing symbols.** The same anchor bolt appears on 2–3 different sheets. The tool groups all appearances into ONE physical device with ONE verdict, measured in **feet in model space** (MATCH ≤ 2 ft, LOCATION_MISMATCH 2–6 ft). This eliminates phantom "missing" items caused by per-sheet double counting.

**Clicking any element** (list row, PDF ring, 3D ball, or table row) synchronises all three panes: the PDF flies to the callout and dims everything else, the 3D view highlights the same device, and the list scrolls to the row. The Evidence Inspector shows the full device block: matched Revit assembly id, distance in feet, every sheet appearance (each clickable), and the zoomed evidence crop. Press **Esc** to clear.

### A7. Benchmark Autopilot (◎) — exact 2-point registration

For production-grade, deterministic alignment, stamp two crosshair benchmarks (BM-1 / BM-2) on the PDF and place two matching benchmark family instances in Revit at the SAME two diagonal grid intersections. The **◎ Autopilot** wizard walks the whole thing:

1. **Propose** — the tool auto-picks the two farthest-apart grid intersections (max diagonal), or you click **Pick manually** and click two grid intersections on the PDF pane yourself (clicks snap to detected intersections).
2. **Approve** — you approve the proposal (evidence crops shown).
3. **Stamp** — the backend stamps BM-1/BM-2 into the PDF itself and verifies them.
4. **Place markers** — if the Nonica MCP bridge is configured and Revit is open, the backend places the benchmark families in the live model and verifies the placement by reading back the coordinates. The wizard shows a live connected/disconnected pill.
5. **Save + export** — you save the Revit model and run the Livio exporter (guided card); uploading the fresh JSON auto-advances the wizard.
6. **Calibrate** — gated 2-point solve. It refuses to save a calibration that fails validation (scale drift, chirality conflict, swapped marks are all caught).

Manual alternative without the wizard: stamp in Bluebeam Revu using `tools/stamps/BM-1.pdf` / `BM-2.pdf` — full SOP in `docs/BENCHMARK-SOP.md`. Rules that make or break it: two DIAGONAL intersections far apart, same physical spot on both sides, each mark stamped exactly once.

### A8. Teaching the AI (via 💬 Chat)

Every client labels drawings differently. Instead of re-programming, you teach in plain English:

1. Open **💬 Chat**.
2. Type the convention: `HD3 means H3`, `TD-1 is a holdown`, `the STUD SCHEDULE is the post table`.
3. The assistant confirms and saves the rule to teach memory (rules are visible, deletable, and apply to future projects too).
4. Click **① Extract** to re-scan with the rule active. Elements recognised via a taught rule carry a brain marker.

**Hard limit by design:** teaching only changes what gets *recognised*. It can never manufacture a MATCH — the distance math is untouched. You cannot talk the tool into a false pass.

### A9. Human review (⚠) — your main workflow

Open the ⚠ Review drawer → the list of every item needing judgment. Per item:

1. **Evidence crop** — solid green ring = drawing position; dashed red ring = model position; the line between = the gap, with distance in feet and a plain-language reason.
2. **AI analysis (deterministic, measured not guessed)** — offset distance + compass direction, plus the **systematic-shift test**: if 15 of 19 other mismatches moved the same direction and magnitude, it tells you this is ONE sheet-wide drafting/registration offset, not 20 modeling errors.
3. **Your reasoning box** — write WHY you accept/reject; the AI checks your logic against its measurements.
4. **✓ Accept / ✕ Reject** — Accept turns the device MATCH everywhere at once (list, overlays, 3D, punch list) with a permanent audit block (who, when, why, original status and distance). Reject keeps it a real defect. Accepts persist across re-matches.
5. **Dispositions** — Confirmed issue / False alarm / Fixed in model: quick tags that do NOT change status.
6. **🔍 Investigate** — copies a complete technical brief for a Claude session connected to the live Revit model.

### A10. Comparing runs (⚖) and exporting

- **⚖ Runs** — before/after table between the saved baseline run and the current run per category × status. Use after re-exports or teaching to prove improvement. "Save as baseline" snapshots the current run.
- **Exports (Stage 9):** punch-list CSV (every non-MATCH element with status, sheet, distance, disposition, comments), review-overlay PNG/SVG (the marked-up plan), and `element_list.json` (full machine-readable results).

### A11. Troubleshooting

| Symptom | Fix |
|---|---|
| Browser can't connect | Server window closed — re-run `.\run_backend.ps1`. |
| Server crashes on start mentioning PIL | Wrong Python. Must be 3.11 (the run script finds it automatically). |
| "No data yet — open Pipeline" | Run the pipeline once (Stage 0–9). |
| A whole sheet shows everything NOT_EVALUATED | The sheet couldn't be registered (too few shared hold-downs / grids). Honest behaviour — use benchmark calibration (A7). |
| Chat says LLM unavailable | `OPENROUTER_API_KEY` missing from `.env`. Only chat needs it. |
| Wizard stuck "disconnected" | Revit not open, or Nonica A.I. Connector not enabled, or `NONICA_MCP_EXE` wrong. |
| Benchmark calibrate refuses | Read the message: duplicate stamps, marks swapped, intersections too close, or scale mismatch — each has a specific fix in `docs/BENCHMARK-SOP.md`. |
| 3D shows boxes, not real members | Click **◆ Revit IFC** after uploading the project IFC; boxes are the honest no-IFC fallback. |

---

## PART B — FEATURE GUIDE (everything, how it works, what to do)

### B1. Architecture in one paragraph

A Python/**FastAPI** backend (`backend/app/`, split into routers: projects, pipeline, elements, registration, workflow, revit, chat, system) serves a modular vanilla-JS frontend (`frontend/src/` — one token system, a pub/sub store, one SSE event bus, and panels: list, pdf, viewer3d, table, wizard, chat, inspector). All results are plain JSON artifacts under `artifacts/projects/<slug>/` — a complete audit trail on disk. **PyMuPDF** reads the drawings; **Three.js + web-ifc** render the 3D; an optional OpenRouter LLM powers chat (with deterministic fallbacks everywhere else). The backend can drive Revit live through the **Nonica MCP bridge** (`revit_bridge.py` spawns `RevitMCPConnection.exe` over stdio) — no Claude in the product loop.

### B2. The pipeline internals (what each stage really does)

| Stage | Module(s) | Output artifact |
|---|---|---|
| Upload | routers/projects | project manifest, `uploads/` |
| Revit convert | `revit_v3_adapter.py`, `revit_convert.py` (frozen) | `AIConvert_revit.json` — clustered assemblies, spec map from YOUR schedule |
| PDF intelligence | `pdf_intelligence.py` (frozen), `s201_detector.py` (frozen), generic fallback | `pdf_page_intelligence.json` + evidence crops |
| PDF convert | `pdf_convert.py` (frozen) | `AIConvert_pdf.json` |
| Registration | `registration.py` (frozen math), `ransac_holdown.py`, `grid_registration.py`, `benchmarks.py` | `registration_calibration.json` (+ per-sheet variants) |
| Compare | `compare.py` (frozen) | `ai_compare_report.json` |
| Extract all | `element_detector.py`, `schedule_tables.py`, `teach.py` overrides | `element_intelligence.json` |
| Match | `element_registry.py`, `device_match.py`, `wall_match.py`, `scene3d.py` | `element_list.json`, `device_registry.json`, 3D scene |
| Review/export | `review.py`, `review_overlay.py` (frozen) | `review_comments.json`, `punch_list.csv`, overlay PNG/SVG |

"Frozen" modules are a project law: their logic is never edited, so the verified math can never drift.

### B3. Registration — the mathematical heart

Revit uses feet from a project origin; PDFs use points from the page corner with Y flipped. The tool solves a 2D similarity transform (PDF = A × Revit + T) three ways, in order of preference:

1. **Benchmark 2-point (best)** — exact, deterministic, from the BM-1/BM-2 pair (A7). Saves only when the solve passes validation; never overwrites a working calibration with a failed one.
2. **Mark-constrained RANSAC** — the hold-downs themselves are the anchors: same-mark devices on both sides are candidate correspondences; RANSAC finds the transform that aligns the most of them and rejects outliers. On Madera this recovered scale 17.97 pt/ft at ~6 pt RMS and took MATCHes from 0 to 32.
3. **Grid-intersection fallback** — for sheets without enough hold-downs, detected grid bubbles are label-paired with Revit grid intersections (axis-agnostic — letters may run either direction).

Every calibration records its **provenance** (`benchmark_verified`, `holdown_ransac`, `grid_verified`, `manual`...). Unverified sources can never gate a MATCH. Quality is validated with holdout residuals; both chiralities (Y-flip) are always tried.

### B4. The MATCH gate & device-level matching

A MATCH requires ALL of: verified calibration source + acceptable confidence + no validation failure + within distance gate + same normalized mark + one-to-one assignment. `normalization.py` canonicalises names (HDU2 / HD2 / HTT4-with-schedule-mapping all resolve via the schedule's own MARK column).

`device_match.py` then re-accounts everything at the **physical-device level**: it inverse-projects every sheet callout into model feet, clusters appearances into one record per real device, and performs one global 1:1 assignment against Revit assemblies (MATCH ≤ 2 ft; LOCATION_MISMATCH 2–6 ft; MARK_MISMATCH = same place, different mark; REVIT_ONLY only when no callout exists anywhere). Shear walls match by point-to-segment distance against Revit wall centrelines. Result on Madera: 122 hold-down rows → 65 physical devices → 44 MATCH / 16 LM / 4 PDF_ONLY / 1 MM / 11 REVIT_ONLY, zero phantoms; overall MATCH=107 is the standing regression baseline.

### B5. Generic sheet intelligence (works on any client's drawings)

Nothing client-specific is hard-coded. The tool discovers schedule tables by their **titles**, reads the **MARK column** to learn which element names are valid on this project, then finds those marks on the plans (leader-line following, title-block sheet-number detection, count-consistency checks). The original Madera S-201 detector is kept as a verbatim frozen port and used only when it applies; everything else goes through the generic path. Taught rules (B7) plug in as extraction overrides.

### B6. The agentic chat copilot (💬)

`chat_agent.py` runs an OpenRouter function-calling loop with a **whitelisted toolbox**: get_counts, query_elements, get_device, get_run_comparison, get_workflow_state, run_pipeline_step (extract|match|compare only), save_teach_rule, focus_element. Ask "how many holdowns?" and it queries the real data and answers with a count card and per-mark table; ask it to "show me SW-1 on sheet S-202" and it returns a `ui_action` the frontend executes — the three panes actually fly to the element. Everything destructive is out of the toolbox by design; every pipeline action it takes is audit-logged. Without an API key, chat reports itself honestly unavailable — the rest of the app is unaffected.

### B7. Teach memory

`teach.py` stores plain-English rules (alias mappings, category assignments, table-title classifications) as visible, deletable entries in a cross-project memory. Rules become extraction overrides on the next ① Extract. Review comments containing conventions ("HD3 means H3") are also harvested into rules. Guarantee: recognition only — never a MATCH.

### B8. Human Review v2

`review.py`: `analyze()` computes deterministic offset + direction + the systematic-shift test; `evaluate()` checks the reviewer's stated reasoning against the measurements (the LLM only phrases the verdict — the numbers decide); `resolve()` applies Accept/Reject and propagates everywhere with a permanent audit block (via:human_review, original_status, distance, comment, timestamp); `apply_stored_resolutions()` re-applies accepts automatically on every re-match while the same device pairing exists. Nothing is ever silently erased.

### B9. The 3D view

Default is an honest box-massing scene built ONLY from real export geometry (`scene3d.py`): walls extruded from centrelines, hold-downs as spheres at real elevations, framing, grids with labels; wall height labelled as assumed 10 ft. Upload the project's **IFC** and click **◆ Revit IFC** to load real member geometry via web-ifc (WASM), with status colours mapped by the standard IFC GlobalId ↔ Revit UniqueId decode (never the naive hex-suffix shortcut, which maps to wrong elements). Unmapped elements are reported honestly as "unmapped: N". Live Revit reads via the bridge remain available as a spot-verify validation tool.

### B10. Projects, runs, artifacts

- **Multi-project workspaces:** each project lives in `artifacts/projects/<slug>/` with its own uploads, calibrations, results and teach effects. Requests are project-scoped (X-Project header/param) — no cross-tab races.
- **⚖ Runs:** `run_baseline.json` vs current, per category × status, with green/red deltas; "Save as baseline" promotes the current run.
- **Key artifacts:** `element_list.json` (master results), `device_registry.json` (per-device evidence), `ai_compare_report.json` (verdicts + distances + reasons), `ai_teach_memory.json` (rules), `review_comments.json` (audit trail), `punch_list.csv`, overlay PNG/SVG, `openrouter_call_log.json` (every LLM call logged).

### B11. Security & deployment

- Localhost-only by default (`BIND_HOST=127.0.0.1`). To expose on the LAN set `QAQC_AUTH_TOKEN` — every `/api/*` route then requires `Authorization: Bearer <token>`.
- Secrets live in `.env` (gitignored) — never hardcoded, never committed.
- **Never as a Windows service** (NSSM / `sc create`): services run in session 0 and cannot reach the interactive Revit UI the bridge drives — every Revit-live feature breaks silently while the HTTP API keeps answering. Auto-start instead via a Startup-folder shortcut (`Win+R` → `shell:startup`) to `run_backend.ps1 -Prod`, Run: Minimized, on the same machine as Revit; upgrade to a Task Scheduler task "At log on of \<user\>" with "Run only when user is logged on" when restart-on-crash matters. Exactly **one** uvicorn worker — the artifact store and bridge lock are single-process by design.
- Ops hardening: rotating structured log (`logs/app.log`, 5 MB × 5), evidence-crop cache GC at startup (`QAQC_EVIDENCE_CAP_MB`, default 512 MB per project).
- Full details: `docs/DEPLOY.md`.

### B12. Testing & quality gates

- **pytest** (from `backend/`): `python -m pytest -q` — 126 green. Covers frozen-math regression, registration gates, benchmark workflow state machine, device matching, chat tool loop (faked LLM), MCP bridge (scripted fake stdio server), teach memory, schema validation.
- **Playwright smoke** (from `frontend/`): `npx playwright test` — loads the app and asserts the Madera MATCH=107 baseline plus the 3-pane select sync, wizard and chat flows.
- Live-Revit tests are marked `revit_live` and auto-skip unless the connector answers.
- Standing rule for any change: suite green + Madera MATCH=107 byte-identical device summary.

### B13. What the software will NEVER do (the honesty contract)

- Never declare MATCH without verified registration + the distance gate.
- Never force Revit counts to equal PDF counts.
- Never silently change a status — only YOUR accept does, and it leaves a permanent audit block.
- Never hide a failure: unreadable schedules, unregistrable sheets and missing export categories are labelled exactly as that.
- Never invent geometry: missing coordinates → "not drawable", never a placeholder.

---

## PART C — RUN EVERYTHING FROM ONE PLACE (cheat sheet)

### C1. Full run via the UI

```
.\run_backend.ps1  →  open http://127.0.0.1:8077  →  ▶ Pipeline  →  ▶ Run full pipeline
→ review ⚠ queue → teach via 💬 if needed → ① Extract → ② Match → export punch list
```

### C2. Full pipeline via API (scriptable, no browser)

```powershell
# upload your files once (or omit and use an existing project)
curl -X POST http://127.0.0.1:8077/api/upload -F "pdf=@plan.pdf" -F "revit_json=@revit_export.json"

curl -X POST http://127.0.0.1:8077/api/revit/ai-convert
curl -X POST http://127.0.0.1:8077/api/pdf/page-intelligence
curl -X POST http://127.0.0.1:8077/api/pdf/ai-convert
curl -X POST http://127.0.0.1:8077/api/registration/auto-holdown
curl -X POST http://127.0.0.1:8077/api/compare/ai
curl -X POST http://127.0.0.1:8077/api/elements/extract
curl -X POST http://127.0.0.1:8077/api/elements/match

# results
curl http://127.0.0.1:8077/api/elements
curl -O http://127.0.0.1:8077/api/export/punch-list.csv
```

Benchmark calibration instead of RANSAC: `POST /api/pdf/benchmarks` then `POST /api/registration/benchmarks`. Health: `GET /api/health`. Live Revit: `GET /api/revit/status`. Devices: `GET /api/devices`.

### C3. Tests

```powershell
cd C:\QA-QC-FINAL-PROTOTYPE-bkp\backend;  python -m pytest -q
cd C:\QA-QC-FINAL-PROTOTYPE-bkp\frontend; npx playwright test
```

### C4. Where to read more

| Doc | Content |
|---|---|
| `docs/USER_GUIDE.md` | Original end-user walkthrough |
| `docs/QA_REVIEWER_GUIDE.md` | Reviewer's screen-by-screen guide |
| `docs/BENCHMARK-SOP.md` | Bluebeam/Revit benchmark stamping SOP |
| `docs/DEPLOY.md` | Service install, env vars, security posture |
| `docs/COMPLETE_TECHNICAL_REFERENCE.md` | Exhaustive module-by-module reference |
| `docs/PROJECT_SUMMARY.md` | Management summary with headline numbers |
| `production-grade-plan-final.md` | The architecture plan this build implements |
| `graphify-out/graph.html` | Interactive knowledge-graph map of the codebase |

---

*Generated 2026-07-21 from the project's documentation set and the graphify knowledge graph (1,665 nodes / 3,004 edges, built from commit 0483fe3). No code was modified.*
