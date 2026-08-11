---
name: benchmark-autopilot
description: Drive the zero-click 2-benchmark PDF-to-Revit registration workflow (BM-1/BM-2) end-to-end via Nonica MCP + the webapp's benchmark_workflow state machine. Use when the user asks to run/automate benchmark registration, place BM-1/BM-2 markers, or "run the benchmark autopilot" on a project.
---

# Benchmark Autopilot

Drives `backend/app/benchmark_workflow.py`'s state machine
(`idle -> proposing -> awaiting_pdf_approval -> stamping -> awaiting_revit ->
placing_markers -> awaiting_revit_approval -> awaiting_export ->
calibrating -> done`) end-to-end: agent proposes + stamps + places markers,
human approves twice, backend verifies + calibrates. The backend can never
drive Revit itself — only a Claude session with Nonica MCP can — so this
skill is that agent side.

Server must be running (`python -m uvicorn app.main:app --host 127.0.0.1
--port 8077` from `backend/`) with the target project active
(`POST /api/projects/activate {"slug": "<project>"}`).

## Step 0 — Nonica connection checklist (BEFORE any set_/create_ tool call)

1. Revit must be open with the target model, **A.I. Connector enabled**, and
   **NonicaTab PRO** active — the Free tier blocks all `set_`/`create_`
   tools silently or with a generic error. If any `mcp__Revit__set_*` or
   `mcp__Revit__create_*` call fails oddly, check this first.
2. Call `mcp__Revit__get_active_view_in_revit` first, every time, to confirm
   the connector is live before touching the model. If it times out or
   errors, stop — do not attempt marker placement against a stale/no
   connection.

## Step 1 — Propose

```
POST /api/benchmark-workflow/propose {}
```

Reads labeled PDF grid intersections (falls back to
`benchmark_workflow.bubble_row_positions` internally when the sheet has
noisy edge-band text — no action needed on your part), joins them to Revit
grid points, picks the max-diagonal pair, renders evidence crops. Returns
`wf.proposal.benchmarks[]` with `mark`, `grid_label`, `pdf_point_pt`,
`revit_point_ft` for BM-1 and BM-2. If this 409s with "only N labeled grid
intersections", the project's PDF/Revit export don't have enough matching
grid labels — report this honestly, do not invent grid points.

## Step 2 — Human approves the proposal

`POST /api/benchmark-workflow/approve {"approved": true}` (or via the
wizard's "◎ Autopilot" button in the dashboard). Do not proceed past this
gate without an explicit approval — either a human clicking Approve in the
wizard, or an explicit instruction from the user in this conversation.

## Step 3 — Stamp the PDF

```
POST /api/benchmark-workflow/stamp {}
```

This is a REAL backend action — it writes the BM-1/BM-2 circle annotations
at the approved `pdf_point_pt` (never re-derive coordinates yourself),
backs up the PDF first (`.pre_benchmarks.bak.pdf` pattern), and verifies by
reading the stamps back before advancing. If it 409s with a verification
failure, the state stays at `stamping` — do not call `/advance
{"step":"stamped"}` to force past a failure; the guard exists specifically
because a fabricated report can't be told apart from a real one otherwise.

(Historical note: before this endpoint existed, stamping was a standalone
script — `backend/run_benchmark_acceptance.py` — that hand-derived PDF
coordinates from a saved calibration matrix instead of the proposal. That
script is now superseded for new runs; use `/stamp`.)

## Step 4 — Place markers in Revit (live Nonica MCP work)

State is now `awaiting_revit`. Report you've connected:
```
POST /api/benchmark-workflow/advance {"step": "revit_connected"}
```

Then, per benchmark mark:

1. **Exact coordinates come from `raw_revit_export.json`'s `grids[]` line
   endpoints** (or `wf.proposal.benchmarks[i].revit_point_ft`), NOT from the
   2-decimal display in `get_location_for_element_ids` — that's rounded and
   will fail the tolerance check.
2. Find or place a benchmark family instance (family name contains
   "Benchmark", or set Mark to BM-1/BM-2 directly). If copying an existing
   pinned benchmark family (e.g. a pinned `GM0`/reference point):
   **pinned-element copy trick** — `mcp__Revit__set_copy_elements` fails
   with "Element is Pinned" on a zero-vector copy. Copy WITH a translation
   vector first (to the 2nd grid point), then copy that result back by the
   reverse vector to land on the 1st point. Validate the vector length
   against the known grid spacing (e.g. framing dimensions like `58'-8"` /
   `57'-5.5"`) before trusting the placement.
3. Set the Mark parameter: `set_parameter_value_for_elements` with
   `idParameter: -1001203` sets the built-in **Mark** parameter to `"BM-1"`
   / `"BM-2"`.
4. Snap to the grid intersection exactly (Revit's `SI` snap-intersection
   equivalent — verify via `get_location_for_element_ids` after placement,
   understanding its 2-decimal rounding per point 1 above).

Read back what was actually placed with `get_location_for_element_ids`,
then report:
```
POST /api/benchmark-workflow/advance {
  "step": "markers_placed",
  "data": {
    "element_ids": ["<id1>", "<id2>"],
    "readback": {"BM-1": {"x": ..., "y": ...}, "BM-2": {"x": ..., "y": ...}}
  }
}
```
The `readback` field drives the wizard's delta table (green if within
0.05 ft of the intended point) — always include it, never omit it to make a
placement look cleaner than it was.

## Step 5 — Human approves placement, then saves + re-exports

`POST /api/benchmark-workflow/approve {"approved": true}` (or via the
wizard). State becomes `awaiting_export`.

**This step needs the user, not you**: the model is unsaved (markers are
session-only), so the user must:
1. Save the Revit model (Ctrl+S).
2. Run the Livio QA-QC exporter — the dialog must show **"Benchmarks: 2"**.
   If it shows 0, the family/Mark wasn't recognized (see the failure table
   below) — do not proceed, tell the user to fix it in Revit and re-export.
3. Upload the fresh export JSON (`POST /api/upload` or via the dashboard).

The workflow **auto-advances** `awaiting_export -> calibrating` the moment
an uploaded export's `benchmarks[]` list covers both proposed marks — no
manual `/advance` call needed for this step. If it doesn't auto-advance,
the upload didn't carry both marks; check the export dialog count again.

## Step 6 — Calibrate

```
POST /api/pdf/benchmarks {}
POST /api/registration/benchmarks {}
```

This is the ONLY path that ever mints a transform — the workflow module
itself never computes one. Expect `saved: true`, quality `medium` or
`high`, derived scale within 0.5% of the title-block scale, and (if a prior
trusted calibration existed) agreement to ~1e-5 pt.

Then report:
```
POST /api/benchmark-workflow/advance {"step": "calibrated"}
```
This has its own guard rail — it re-reads `registration_calibration.json`
and refuses `done` unless it's genuinely `benchmark_verified` and
`registration_usable`. If your calibrate call didn't actually save (quality
gates failed), this call will honestly 409 — do not skip straight to
reporting `done`.

## Failure table (from docs/BENCHMARK-SOP.md)

| Message | Cause | Fix |
|---|---|---|
| `Mark(s) not found: BM-…` | stamp missing, wrong Subject, or a FreeText comment instead of a real stamp annotation | re-stamp with the correct Subject field |
| `found on multiple pages` / duplicate | mark stamped more than once | delete the extras |
| `Benchmarks too close` | intersections not diagonal enough (solver rejects <200pt paper / <10ft model) | pick a farther-apart pair; re-propose |
| `BENCHMARK_SCALE_MISMATCH` | wrong sheet stamped, or sheet scale differs from expected | verify sheet + title-block scale |
| `BENCHMARK_CHIRALITY_CONFLICT` | PDF/model mirrored relative to assumption | check BM-1/BM-2 aren't swapped between PDF and Revit |
| `Revit export has no benchmarks` | family not named "Benchmark" and Mark isn't BM-x, or an old exporter (<v3.1) | fix Mark parameter, re-export |

## Honesty rules (non-negotiable)

- Never call `/advance` for a step you didn't actually perform. The state
  machine's guard rails (on `stamped` and `calibrated`) exist to catch
  fabricated reports — respect them, don't route around them.
- Never invent Revit element IDs, coordinates, or a `readback` value.
- If you're dry-running or testing this skill against a project that has no
  live Revit connection available, stop at Step 3 (stamp) and say so
  explicitly — do not simulate Steps 4-6 and report `done`. (A prior
  session did this by accident during UI testing and had to delete the
  fabricated `benchmark_workflow.json` afterward — don't repeat that.)
