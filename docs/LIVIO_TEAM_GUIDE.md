# Livio QA-QC Intelligence — Team Guide

**For:** Livio QA-QC reviewers · **Updated:** 2026-07-28
**What it does:** compares a client's permit drawing set (PDF) against their
Revit model export and tells you — element by element — what matches, what's
in the wrong place, what's missing from the model, and what's missing from
the drawings. No fake matches, ever: a MATCH requires a verified coordinate
registration plus distance gates.

---

## 1 · Start the software

1. Open a terminal in `backend\` and run:
   ```
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8077
   ```
2. Open **http://127.0.0.1:8077** in Chrome/Edge.
3. Sanity check: the header shows the active project, and STATS shows
   element counts. `GET /api/health` returns `"status":"ok"`.

---

## 2 · Start a NEW project (any client — not just Madera)

Every project lives in its own workspace; projects never contaminate each
other. You need **two files** from the client (third optional):

| File | What it is | How to get it |
|---|---|---|
| Drawing set PDF | The permit/structural set (S-sheets) | From the client |
| Revit export JSON | v3 export from our pyRevit **Livio QA-QC → Export** button (schema v3.1+ includes benchmarks) | Run in the client's model |
| IFC (optional) | IFC export of the same model | Revit → Export → IFC — **must be exported from the same model/version as the JSON** |

Upload (one command, or use the upload controls in the UI's project panel):

```
curl -X POST "http://127.0.0.1:8077/api/upload?project=<client-name>" ^
  -F "pdf=@C:\path\drawings.pdf" ^
  -F "revit_json=@C:\path\export.json" ^
  -F "ifc=@C:\path\model.ifc"
```

This creates and activates the workspace. The project switcher (folder
dropdown, top bar) moves between projects at any time.

---

## 3 · Run the pipeline

Click **▶ Pipeline** (top right) → **Run full pipeline**, or run stages
individually top to bottom. Watch the **Live log** panel as it runs — after
every stage a 🤖 line summarizes in plain English what that stage just did
(not raw numbers or JSON). What the stages do:

1. **Revit AI-convert** — normalizes the export.
2. **PDF page intelligence** — finds S-sheets, schedules, callouts.
3. **PDF AI-convert** — extracts hold-downs, shear walls, posts, columns,
   wall types from plans + schedule tables.
4. **Registration** — solves the Revit↔PDF coordinate transform. Three
   strategies, best first:
   - **4b Benchmark (2-point)** — best. Uses BM-1/BM-2 markers placed in the
     model + stamped on the PDF (see §5 Autopilot). Once verified it is
     **never silently overwritten** — re-running stage 4 keeps it and just
     reports agreement.
   - **Hold-down RANSAC** — automatic, no markers needed.
   - Grid/manual — fallback.
5. **Compare + Match** — element-by-element statuses with distance gates
   (MATCH ≤2 ft · LOCATION_MISMATCH 2–6 ft) and physical-device grouping.

**Re-running the pipeline is safe and idempotent** — results only change if
inputs or teach rules changed.

---

## 4 · Read the results (the three panes)

- **Left — element list**: grouped by category/mark with status dots.
  Filters: search box, status dropdown, sheet dropdown. Click any row → the
  PDF flies to the callout and the 3D highlights the element.
- **Middle — PDF**: sheet tabs, status-layer chips + opacity, measure tool
  (click two points), fullscreen.
- **Right — 3D**: box massing colored by status. `SW only` / `Top view` /
  `Reset`. **◆ Revit IFC** swaps in the real exported geometry (needs the
  IFC upload) and colors what it can map — the note reports
  "status-mapped: N of M tracked elements" honestly; hardware families
  (hold-downs) usually aren't in an IFC, so walls map best.

Statuses: 🟢 MATCH · 🟠 LOCATION_MISMATCH · 🔵 PDF_ONLY (in drawings, not
model) · 🔴 REVIT_ONLY (in model, not drawings) · MARK_MISMATCH ·
NOT_EVALUATED.

**Views row:** **Table** (sortable full listing) · **Autopilot** (§6) ·
**Runs** (baseline vs current run deltas; "Save as baseline" snapshots the
current run) · **Review** (§7) · **Chat** (§8).

### Clicking a mismatch and reading "Why this verdict?"

Click any orange (LOCATION_MISMATCH) or green (MATCH) row. Under the
element's details, expand **"Why this verdict?"**. It tells you, in plain
sentences:

- The offset in feet between where the PDF shows the device and where the
  Revit model has it, and which compass direction it's off (e.g. "0.87 ft
  to the northeast").
- Whether that offset is inside or outside the 2 ft MATCH gate.
- If several nearby mismatches all shift the same way, it says so — that's
  usually a systematic drawing offset, not a modeling error on that one
  device.
- A suggested next step (e.g. re-check the callout leader line, or check
  whether the drawing or the model needs the correction).

### The scope-warning banner

If a whole category (say, all posts) has PDF callouts but zero matching
targets in the Revit model, an amber **⚠ Export scope** banner appears above
the table. This usually means the Revit export view had that category
hidden, not that the model is genuinely missing everything in it — check
the export view before assuming a modeling gap. You can dismiss the banner
once you've read it.

---

## 5 · Revit-live: Show in Revit & the Revit ID drawer

These features need Revit open with **both** connectors running (§1): the
NonicaTab PRO **A.I. Connector** switched **On**, and the open-source
**revitMCP** add-in's ribbon button **Open Server** clicked. If either is
off, the related buttons grey out on their own — that's expected, not a
bug.

### 🎯 Show in Revit

On any hold-down's detail panel, click **🎯 Show in Revit**. The matching
element gets selected inside the live Revit model — switch to the Revit
window and you'll see it highlighted. There is no automatic zoom (Revit's
connector doesn't support one), so **press BX** (Selection Box) in Revit right after — and don't click the drawing area first, that clears the selection — to
zoom to your selection.

### 🔎 Revit ID drawer

Click **🔎 Revit ID** in the top bar to open the lookup drawer. Two ways to
use it:

1. **Paste an ElementId** you already have (e.g. from a Revit warning or
   schedule) into the box and look it up.
2. **Click "⇱ Use current Revit selection"** — one click reads whatever you
   currently have selected in the open Revit model and looks it up for you,
   no typing required.

Either way you get: which hold-down assembly the element belongs to, the
paired PDF device (if any), and the same plain-English verdict explanation
as the "Why this verdict?" panel.

---

## 6 · Benchmark Autopilot (best-quality registration)

For production-grade registration, the model and the PDF share two physical
benchmark markers:

1. **Autopilot → Propose** — the system picks two grid intersections
   visible on both sides and shows evidence crops. Don't like them? Use
   **manual grid picking**: click two intersections on the sheet preview
   (snaps to detected grids).
2. **Approve** — with the Revit **Nonica A.I. Connector ON** and the model
   open, the workflow places BM-1/BM-2 marker families in the model and
   stamps the PDF (originals are backed up; failed stamps auto-roll back).
3. Re-export the Revit JSON (now contains the benchmarks), re-run stage 4b →
   calibration becomes `benchmark_verified`.

---

## 7 · Human Review — confirming a mismatch or marking a false alarm

Open **Review** (badge = open item count):

1. Click an item — every pane syncs; you get an evidence crop and a
   deterministic analysis (offset in ft, direction, isolated vs systematic —
   the same facts as the "Why this verdict?" panel in §4).
2. **You must write your reasoning first.** Type why you think this is a
   false alarm or a real mismatch — the AI cross-checks your logic against
   the numbers and tells you if your reasoning and the measurements
   disagree.
3. **Accept (false alarm)** → the status becomes MATCH (`via: human_review`,
   original distance kept) everywhere: list, PDF overlay, 3D, punch list.
   **Reject (confirmed mismatch)** → it stays a discrepancy. Either way the
   full audit trail persists in `review_comments.json` and survives
   re-matching — resolving an item once does not get silently undone by
   the next pipeline run.

---

## 8 · Chat copilot (and teaching the AI)

Open **Chat**. It answers from real data (never invents counts) and drives
the UI: *"how many holdowns?"*, *"show LOCATION_MISMATCH on S-201"*,
*"highlight H2"*, *"re-run match"*.

**Teach it client conventions** — these persist as rules and apply on the
next Extract:
- Alias: *"HD3 means H3"*
- Category: *"TD-1 is a holdown"*
- **Exclude:** *"ignore H6 — dummy placements"* → H6 is dropped from
  extraction and comparison entirely.

Rules are visible and deletable via `GET /api/teach`. If the assistant
can't turn your sentence into a rule it says so honestly (saved as a note).

---

## 9 · Deliverables

- **Punch list CSV**: `GET /api/export/punch-list.csv` — the discrepancy
  list for the client.
- **Runs compare**: before/after table when a new model export lands.
- Screenshots of PDF overlay + 3D for the report.

---

## 10 · 10-minute acceptance test (run before any demo)

| # | Step | Expect |
|---|---|---|
| 1 | Load http://127.0.0.1:8077 | No console errors; stats populated |
| 2 | Switch project A→B→A | Counts change per project and restore |
| 3 | Click an element row | PDF flies + ring; 3D highlights |
| 4 | Filter status=MATCH + one sheet | Counts shrink; reset restores |
| 5 | Pipeline → Run full | All stages 200; counts stable on re-run |
| 6 | `GET /api/health` | `registration.calibration_source` unchanged (benchmark stays benchmark) |
| 7 | Autopilot → Propose → Reset | Two benchmarks + evidence; reset returns to idle |
| 8 | Review: comment → accept/reject | AI verdict appears; buttons only after comment |
| 9 | Chat: "how many holdowns?" | Real table, no raw JSON/markup in the reply |
| 10 | 3D → ◆ Revit IFC | Real geometry; note reports mapped/tracked honestly |

Baseline reference (Madera): 354 elements · 107 MATCH · holdown devices
44 M / 16 LM / 4 PO / 1 MM / 11 RO.

---

## 11 · Troubleshooting

- **"Only 0 labeled grid intersections…"** — sheet's grid orientation or
  labels unusual; use manual grid picking (§6).
- **IFC note says "does not match the current Revit export"** — the IFC was
  exported from a different model version; re-export from the same model.
- **A mark the client says is fake keeps showing** — teach an exclude rule
  (§8), then re-run Extract.
- **409 "upload first"** — that stage's input artifact is missing; run the
  earlier stage or upload the file (§2).
- **Show in Revit / Revit ID drawer buttons are greyed out** — one or both
  Revit connectors are off (§5); this is expected honest behavior, not a
  bug. Turn on the Nonica A.I. Connector and/or click revitMCP's Open
  Server, then retry.
- **Server logs**: `logs\app.log` at the repo root (rotating, 5 MB × 5
  backups). Bugs: file them in `Bugs.md`
  with repro + expected/actual.
