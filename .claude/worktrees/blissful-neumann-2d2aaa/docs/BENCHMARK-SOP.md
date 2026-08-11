# Benchmark SOP — 2-point registration (BM-1 / BM-2)

One-time setup per project: stamp two crosshairs on the plan PDF in Bluebeam
and place two matching benchmark family instances in the Revit model at the
**same grid intersections**. From then on, drawing-to-model alignment is
exact and deterministic — no more re-picking points every session.

## Rules that make or break it

1. **Two DIAGONAL grid intersections.** Pick intersections far apart across
   the sheet diagonal (e.g. grid A/1 and H/6). The solver rejects benchmarks
   closer than 200 pt on paper / 10 ft in the model.
2. **Same physical spot on both sides.** BM-1 on the PDF and BM-1 in Revit
   must be the SAME grid intersection. Swapping them (or reusing a mark)
   is caught and blocked, but costs you a round-trip.
3. **Stamp each mark exactly once,** on the plan sheet you QA against
   (e.g. S-201). Duplicates anywhere in the PDF are a hard error.

## Part 1 — Bluebeam Revu (the PDF side)

1. Get the stamp files: `tools/stamps/BM-1.pdf` and `BM-2.pdf`
   (regenerate anytime with `python tools/make_benchmark_stamp.py`).
2. Import once: **Markup > Stamp > Import Stamp…** and select both PDFs.
   They now appear under Markup > Stamp permanently.
3. Open the plan sheet, **zoom to at least 400%** on the first grid
   intersection.
4. Place the BM-1 stamp so the crosshair center sits exactly on the
   intersection of the two grid lines. Do not resize asymmetrically —
   the crosshair center is the measured point.
5. In the Properties panel of the placed stamp, confirm **Subject = BM-1**
   (Bluebeam fills it from the stamp title; fix it if edited).
6. Repeat with BM-2 on the second (diagonal) intersection.
7. Save the PDF. Do **not** flatten if avoidable — stamps stay as
   annotations, which is the most reliable path. (If a flattened copy is
   all you have, the backend falls back to recognizing the drawn crosshair
   plus its BM-x label — keep the label next to the symbol.)

## Part 2 — Revit (the model side)

1. Place a benchmark family instance at the same two grid intersections,
   at plan level. Any point-based family works — detection is by name:
   family name contains **"Benchmark"** OR the **Mark** parameter is
   `BM-1` / `BM-2`.
2. Set **Mark = BM-1** on the first, **Mark = BM-2** on the second
   (must correspond to the PDF stamps' intersections).
3. Snap to the grid intersection exactly (type `SI` for snap intersection).
4. Re-export with the Livio QA-QC exporter (v3.1+). The export dialog now
   shows a `Benchmarks: 2` count — if it says 0, the family/marks were not
   recognized. The markers export document-wide, so hiding them in the
   curated view is fine.

## Part 3 — Run it (dashboard or API)

1. Upload the stamped PDF and the fresh Revit JSON as usual.
2. Pipeline modal > **Benchmark calibration (2-point)** > Extract stamps,
   then Calibrate. (API: `POST /api/pdf/benchmarks` then
   `POST /api/registration/benchmarks`.)
3. Expect: quality `medium` or `high`, derived scale within 0.5% of the
   title-block scale. Then run compare/match as always.

## When it refuses to calibrate

| Message | Cause | Fix |
|---|---|---|
| `Mark(s) not found: BM-…` | stamp missing, wrong Subject, or FreeText comment instead of a stamp | re-stamp via Markup > Stamp with Subject BM-x |
| `found on multiple pages` / duplicate | mark stamped more than once | delete the extras |
| `Benchmarks too close` | intersections not diagonal | move one stamp+family to a far corner |
| `BENCHMARK_SCALE_MISMATCH` | stamped the wrong sheet, or sheet scale differs from expected | verify sheet + its title-block scale |
| `BENCHMARK_CHIRALITY_CONFLICT` | PDF/model mirrored relative to assumption | check BM-1/BM-2 aren't swapped between sides |
| `Revit export has no benchmarks` | family not named "Benchmark" and Mark not BM-x, or old exporter | fix Mark, re-export with v3.1+ |
