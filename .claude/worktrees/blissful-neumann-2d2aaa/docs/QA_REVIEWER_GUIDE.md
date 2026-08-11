# Livio QA-QC Intelligence — Reviewer's Complete Guide

*For the QA-QC engineer. Everything on the screen, what it means, and how to
work a project end to end. Updated 2026-07-15 (Dogwood demo build).*

---

## 1. What this software does (one paragraph)

You give it two things: the **stamped structural drawing set (PDF)** and the
**Revit model export (JSON)** made with our "Export QA-QC JSON" button inside
Revit. It then finds every hold-down, shear wall, post and steel column in
BOTH sources, aligns the drawing coordinates to the model coordinates
mathematically, and tells you — element by element — whether the model
matches the drawings. What used to be ~8 days of manual cross-checking
becomes a queue of specific, explained discrepancies for you to judge.

**The one rule everything is built on: it never fakes a match.** A MATCH is
only declared when a verified coordinate alignment exists AND the two
positions fall within an explicit distance gate. Everything the software is
unsure about is flagged honestly instead of guessed.

---

## 2. The statuses (the color language of the whole app)

| Status | Color | Meaning | What YOU do |
|---|---|---|---|
| **MATCH** | 🟢 green | Same mark, same place (within gate), verified alignment | Nothing — verified |
| **LOCATION_MISMATCH** | 🟠 orange | Same mark exists on both sides but positions differ beyond the gate | Review it — this is your main queue |
| **MARK_MISMATCH** | 🟣 pink | A device IS there, but drawn with a different mark than modeled | Check the callout or the family — one is mislabeled |
| **PDF_ONLY** | 🔵 blue | Drawing shows it; no model device found near it | Modeling coverage gap OR detection gap — verify |
| **REVIT_ONLY** | 🔴 red | Modeled, but no drawing callout found for it anywhere | Often a callout our detector missed, or over-modeling |
| **NOT_IN_SCHEDULE** | grey | The mark isn't in any schedule table we could read | Teach the AI the mapping (see §7) |
| **NO_REVIT_DATA** | grey | The export contained nothing of this category | Re-export with the category visible |
| **NOT_EVALUATED** | grey | Sheet couldn't be registered (e.g. detail sheets) | Informational — not an error |

**Key concept — physical devices, not drawing symbols.** The same anchor
bolt appears on 2–3 different sheets. Older approaches count each appearance
separately and produce phantom "missing" items. This software groups all
appearances into ONE physical device and gives it ONE verdict. Distances are
measured in **feet in model space**, not pixels.

---

## 3. Top toolbar, left to right

- **☰** — hide/show the left element list.
- **Project dropdown (📁)** — switches projects (madera, country-side-ct,
  dogwood-lane…). Each project's files and results are fully separate.
- **Stats badge** — live totals: elements · MATCH count · discrepancies.
- **▶ Pipeline** — the step-by-step pipeline panel (see §4). Use it to run
  a new project or re-run a step; each step shows a live log and its real
  result when done.
- **🧠 Teach AI (badge = rule count)** — chat drawer where you teach the
  system conventions in plain English (see §7).
- **⚠ Review (badge = open items)** — your work queue: every
  LOCATION_MISMATCH / NEEDS_REVIEW element (see §6).
- **⚖ Runs** — before/after comparison between the saved baseline run and
  the current run, per category × status. Use after re-exports or teaching
  to prove improvement (green/red deltas on MATCH). "Save as baseline"
  snapshots the current run as the new reference.
- **① Extract** — re-scans the whole PDF: schedule tables, mark vocabulary,
  every callout on every sheet. Run after teaching.
- **② Match** — re-runs the full comparison; rebuilds results list, PDF
  overlays and 3D colors. Run after ① or after a new export.

## 4. ▶ Pipeline panel — the steps in order

1. **Upload project** — PDF + Revit JSON (either or both).
2. **Revit convert** — turns the raw export into "assemblies" (an HTT4 body
   + its anchor bolt = one hold-down device) and assigns each the mark your
   drawings use, read from YOUR hold-down schedule (Dogwood: HD2 = HTT4 was
   read straight off the schedule table on S-05).
3. **PDF intelligence** — finds the anchorage plan page and every hold-down
   callout on it.
4. **PDF convert** — canonical list of drawing-side devices.
5. **RANSAC registration** — the math that aligns drawing to model: solves
   scale/rotation/offset from same-mark devices, rejects outliers, records
   the residual error. If this fails, NOTHING is allowed to match — that is
   the honesty guarantee.
6. **Extract all** — §3's ① across all sheets and categories.
7. **Teach** — apply your saved rules.
8. **Match everything** — §3's ② full comparison.
9. **Review/export** — punch list CSV + overlay PNG/SVG for the site team.

## 5. The three main panes

**Left — element list.** Every element grouped by category → mark
(HD2 (49), SW-1 (21)…) with colored status dots. Search filters by mark, id
or status; dropdowns filter by status and sheet. Click any row: the PDF
jumps to the exact callout and the 3D flies to the device.

**Middle — DRAWING·PDF.** The actual drawing set with sheet tabs (S-01…).
Colored rings mark every detected callout (color = status). An orange ring
plus a second marker = a mismatch showing BOTH claimed positions and the gap
between them. Buttons: Layers (toggle overlays), 📏 measure, ⛶ fit page,
⤢ expand.

**Right — REVIT MODEL·3D.** The real exported model geometry (framing,
walls, hold-downs, grid labels). Colored balls sit on each comparison
device — same status colors. Hover = tooltip (mark + status), click =
selects it everywhere. Buttons: SW only, Top view, Reset, ⤢. Legend below.

## 6. ⚠ Human review — your main workflow (the important part)

Open the drawer → list of every item needing judgment; one click opens the
detail view:

1. **Evidence crop** — zoomed PDF cutout: solid green ring = where the
   drawing says the device is; dashed red ring = where the model says it
   is; the line between = the gap. Plus a plain-language reason and the
   distance in feet.
2. **🤖 AI analysis (deterministic)** — measured, not guessed: offset
   distance + compass direction, and the **systematic-shift test** — if 15
   of 19 other mismatched devices moved the SAME direction and magnitude,
   it tells you this is one sheet-wide drafting/registration offset, NOT 20
   individual modeling errors. If the offset is unique it says "isolated —
   genuine deviation candidate".
3. **Your reasoning box** — type WHY you accept or reject ("callout leader
   lands on the stud face; device modeled at anchor centerline"). The AI
   checks your logic against its measurements and answers whether the
   numbers support it.
4. **✓ Accept / ✕ Reject** (animated buttons)
   - **Accept** → the device becomes MATCH **everywhere at once** — every
     sheet it appears on, the PDF overlay, the 3D ball, the punch list —
     with a permanent audit block (who, when, why, original status,
     original distance). Nothing is silently erased.
   - **Reject** → stays a real defect on the punch list, comment attached.
   - Accepts persist: re-running ② Match re-applies them automatically
     while the same device pairing exists.
5. **Dispositions** (🔴 Confirmed issue / 🟢 False alarm / 🔧 Fixed in
   model) — quick tags that DON'T change status; the punch list shows both
   your tag and the honest status.
6. **🔍 Investigate** — copies a complete technical brief (ids, both
   coordinates, distance, spec) for a Claude session connected to the live
   Revit model, which interrogates the actual model for you.
7. **Comment box** — anything you type is also read by the teach engine: a
   convention ("HD3 means H3") becomes a permanent rule.

## 7. 🧠 Teach AI — make it smarter forever

Plain-English rules: *"HD3 means H3"*, *"TD-1 is a holdown"*, *"N-EXT-SH-68
walls are SW-4"*. Each becomes a saved, visible, deletable rule applied on
the next ① Extract — **on every future project too** (rules are global).
Limit by design: teaching changes what gets *recognized*; it can never
manufacture a MATCH — the distance math stays untouched.

## 8. Reading a project like Dogwood (real example)

- 43 physical PDF hold-down devices vs 62 modeled; 16 MATCH immediately.
- 20 LOCATION_MISMATCH — but the AI shows they share one systematic ~2.3 ft
  NW shift → one drafting-offset judgment, bulk-accept with audit trail.
- 25 shear-wall runs in the drawings vs **0 walls in the export** → real
  finding: the export view had Walls hidden. Fix: make Walls visible in the
  Revit 3D view, re-export (2 min), re-run ②.
- 35 REVIT_ONLY hold-downs → modeled devices whose callouts weren't found
  (secondary sheets / detector recall) — spot-check a few.
- NOT_IN_SCHEDULE marks → teach the mapping once, gone forever.

## 9. Exports (Pipeline step 9)

- **Punch list CSV** — every element: status, sheet, distance, disposition,
  comments. The deliverable for the site team.
- **Review overlay PNG/SVG** — the marked-up plan image.
- **element_list.json** — full machine-readable results.

## 10. What the software will never do

- Never declare MATCH without verified registration + distance gate.
- Never silently change a status — only YOUR accept does, and it leaves an
  audit block preserving the original verdict and distance forever.
- Never hide a failure: unreadable schedules, unregistrable sheets and
  missing categories are labeled as exactly that.
