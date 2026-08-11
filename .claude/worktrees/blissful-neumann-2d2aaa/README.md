# QA-QC Automated System — Prototype

AI-assisted **Revit ↔ PDF** QA/QC comparison. It compares a structural permit
PDF against a Revit model and gives a verdict for every device: `MATCH`,
`LOCATION_MISMATCH`, `MARK_MISMATCH`, `PDF_ONLY` (in the drawings, not the
model), or `REVIT_ONLY` (in the model, not the drawings) — each with a
plain-English "Why this verdict?" explanation. This is a fresh prototype: it
does not reuse the old Livio frontend or the `structural-schedule-mvp`
static dashboard, and it does not modify the production code in `C:\qa-qc`.
It ships with a bundled Madera sample project so it can be tried with no
files of your own.

## Quick Start

1. **Upload your files** in the webapp — the permit PDF and the Revit JSON
   export. The system reads the PDF's own grid intersections and proposes
   two benchmark registration points (BM-1/BM-2) automatically; approve
   them in the banner that appears, or pick two grid intersections manually
   if the auto-proposal looks wrong.
2. **Open the same model in Revit and turn on both connectors:**
   - NonicaTab PRO — turn the **A.I. Connector** ON.
   - The open-source **revitMCP** add-in — click **Open Server** on its
     ribbon.
   Both are optional if you're only reviewing a static export, but required
   for every "live" feature below (Show in Revit, the Revit ID drawer, live
   3D).
3. **Review the results** in the webapp: the element list, the PDF pane,
   and the 3D pane stay in sync — click a row in any pane and the other two
   follow.

```powershell
# 1) (first time) install deps
cd C:\QA-QC-FINAL-PROTOTYPE-bkp\backend
python -m pip install -r requirements.txt

# 2) ensure C:\QA-QC-FINAL-PROTOTYPE-bkp\.env has OPENROUTER_API_KEY (see .env.example)

# 3) start backend + UI
cd C:\QA-QC-FINAL-PROTOTYPE-bkp
.\run_backend.ps1
# open http://127.0.0.1:8077
```

## Pipeline

```
Revit raw JSON ─▶ AI Revit Convert ─▶ AIConvert_revit.json
                                          │ (learned key points / AI memory)
PDF ─▶ Page Intelligence ─▶ AI PDF Convert ─▶ AIConvert_pdf.json
                                          │
AIConvert_revit.json + AIConvert_pdf.json ─▶ AI Compare ─▶ ai_compare_report.json
```

The Revit add-in is **not** read directly for the comparison math. That flow
is: `Revit model → existing exporter button → raw revit_export.json → AI
analyzer → AIConvert_revit.json`. The Revit-live connectors (below) are a
separate, additional path used for interaction, not for the verdict math.

## Features

- **Verdicts with reasons.** Every mismatch shows the offset in feet
  against the 2 ft MATCH gate, a compass direction, and — when several
  nearby mismatches shift the same way — a note that this looks like a
  systematic drawing offset rather than an isolated error, plus a suggested
  next step ("Why this verdict?" on the row).
- **🎯 Show in Revit.** Click it on any hold-down and the matching element
  is selected in the live Revit model. Revit's API has no zoom-to-selection
  call, so the tool tells you to press **BX** (Selection Box, a default Revit shortcut) in Revit afterward.
- **🔎 Revit ID drawer.** Paste an ElementId, or click **Use current Revit
  selection** to pull whatever is currently selected in Revit with one
  click — either way you get the assembly, its paired PDF device, and the
  plain-English verdict explanation.
- **Live hybrid 3D pane.** Renders the export snapshot instantly, then
  fetches the live open-model geometry in the background and swaps it in,
  with a **LIVE**/**SNAPSHOT** badge and a **⟳ live** refresh button so it's
  always obvious which one you're looking at.
- **Honesty features:**
  - A scope-warning banner when a category has PDF callouts but zero Revit
    targets, so an "everything is missing" result isn't misread as a
    modeling problem before checking whether the export view just hid the
    category.
  - Per-sheet registration quality and the classification chain (which PDF
    schedule row a family/mark was matched against) shown per element.
  - Per-device run-over-run diffs in the Runs drawer when a new export
    lands.
  - 🤖 AI phase summaries in the pipeline log after every stage.
  - Revit-live buttons grey out honestly when Revit is offline, instead of
    silently failing.
  - Comparison never emits `MATCH` on name/type agreement alone — without a
    verified coordinate registration, type-aligned pairs are
    `NEEDS_REVIEW` and surpluses are `PDF_ONLY` / `REVIT_ONLY`.
- **Review workflow.** Mismatches can be commented on and resolved: accept a
  false alarm and it becomes MATCH with an audit trail; reject a confirmed
  mismatch and it stays a discrepancy. Resolutions persist across re-runs.

## Two-connector operator setup

Some Revit-live features (element selection, live geometry) need Nonica;
others (the richest per-element read, including parameters and level) need
the open-source revitMCP connector, which the backend tries first, falling
back to Nonica. For full functionality, with the model open in Revit, run
both:

1. **NonicaTab PRO → A.I. Connector → On.**
2. **revitMCP ribbon → Open Server** (the open-source
   `mcp-servers-for-revit` add-in).

If neither is running, the webapp still works against the last export —
Revit-live buttons simply grey out with a reason instead of erroring.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `NONICA_MCP_EXE` | `C:\NONICAPRO\OtherFiles\System\Core\net8.0-windows\RevitMCPConnection.exe` | Path to Nonica's connector executable on this machine. |
| `REVIT_MCP_ADDR` | `127.0.0.1:8080` | Host:port of the open-source revitMCP socket. |
| `OPENROUTER_API_KEY` | (none) | Enables the LLM-backed chat/teach features. Without it, the deterministic fallback paths still work; the tool says so honestly. |
| `OPENROUTER_REASONING_MODEL` | `deepseek/deepseek-v4-pro` | Model used for LLM calls. |
| `BIND_HOST` | `127.0.0.1` | Set to `0.0.0.0` to expose the server on the LAN (pair with `QAQC_AUTH_TOKEN` if you do). |
| `QAQC_BENCHMARK_FAMILY` | `mwfBenchmark` | Revit family name copied when placing BM-1/BM-2 markers in the live model. Can also be passed per request as `"family"` in the place-markers payload. |

## Honesty guarantees

- PDF coordinates are 2D page points; any Z is flagged `z_is_inferred=true`
  and is **not** a real Revit elevation.
- Raw Revit counts are **not** forced to equal PDF counts.
- If no LLM call was ever attempted, the status reports: **"LLM was not
  called. Running deterministic/demo mode."** Every call is logged to
  `artifacts/openrouter_call_log.json`.

## Tests

```powershell
cd C:\QA-QC-FINAL-PROTOTYPE-bkp\backend
python -m pytest -q
```

300 tests as of this writing (Python 3.11). Frontend is vanilla ES modules
with no build step; Playwright smoke tests live in `frontend/tests/`.

## Limitations

- **No zoom API.** Revit's MCP surface has no "zoom to selection" call. Show
  in Revit selects the element; you press **BX** (Selection Box) in Revit yourself to jump
  to it.
- **Live 3D caps very large categories** and says so in the pane rather
  than silently truncating without a note.
- **ElementIds drift.** Central-model operations can renumber Revit
  ElementIds, so live lookups match by coordinate (nearest live element
  within a small radius of the export point), not by ID. The response
  tells you which method was used, and export-time IDs are returned as an
  honest fallback when there is no live match.
- **The export snapshot is the source of truth for the math.** All
  verdicts, distances, and MATCH/mismatch decisions are computed from the
  Revit JSON export, not the live model. The live connectors are for
  interaction (selecting and inspecting elements, seeing current geometry)
  — re-export and re-run the pipeline to update the actual comparison.
- **Benchmark marker family** defaults to `mwfBenchmark`; override with
  the `QAQC_BENCHMARK_FAMILY` env var or a `"family"` field in the
  place-markers request. If the configured family has no instance in the
  model, placement fails with a clear error that lists any families whose
  name contains "benchmark" as suggestions — it never silently picks one.

## Reference files reused from `C:\qa-qc` (read-only)

- `backend/app/services/s201_holdown_detector.py` → `app/s201_detector.py`
  (copied verbatim; only the `DrawingIntelligenceGraph` import + its two
  helpers were removed and replaced with a standalone `locate_s201_page`).
- `structural-schedule-mvp/.../holdown_normalization.py` →
  `app/normalization.py`.
- `structural-schedule-mvp/output/s201_holdown_summary.json` — baseline
  proof (54).
