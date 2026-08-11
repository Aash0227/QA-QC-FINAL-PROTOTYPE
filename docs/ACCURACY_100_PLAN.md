# Road to 100% — the foundation flaw, proven, and the fix plan

## The user's hypothesis, tested

> "The Revit model is made FROM the PDF — elements existing 'only in Revit'
> or 'only in PDF' is not logically possible."

**Verdict: correct.** Probe (`scripts/holdown_dedup_probe.py`, Madera
holdowns, 2026-07-14) — every PDF callout inverse-projected to model space
with its sheet's verified transform, clustered across sheets:

| Fact | Number |
|---|---|
| PDF callout rows (what the pipeline counts today) | 122 |
| **Physical hold-down devices those rows depict** | **62** |
| Rows that are RE-APPEARANCES of a device already MATCHED on another sheet | 34 (27 shown as PDF_ONLY, 7 as LOCATION_MISMATCH) |
| PDF devices with NO Revit device within 6 ft | **0** |
| PDF devices with a Revit device ≤ 2 ft, same mark | 45 / 62 |
| Revit assemblies | 72 |

So: **there are no real PDF_ONLY holdowns.** Today's 51 PDF_ONLY holdown
rows are an accounting artifact. Root causes, in order of damage:

1. **Wrong unit of account.** The pipeline scores *sheet appearances*
   (S-201 + S-202 + S-205 each get a row for the same physical anchor).
   One device matched on S-201 but 18 pt off on S-205 produces
   1 MATCH + 1 PDF_ONLY for one physical object. 122 rows ≠ 62 devices.
2. **Gates in PDF points, paid per sheet.** Per-sheet registration carries
   6–8 pt rms residual; the 16 pt MATCH gate spends most of its budget on
   registration error, not on real model-vs-drawing offset.
3. **Chirality/coordinate traps.** PDF y is flipped vs model y; any
   consumer that re-fits transforms without testing reflection gets
   garbage silently (the probe itself hit this first try).
4. Real but small: a few devices drawn with one mark where the model has a
   neighboring variant (e.g. H4 drawn, H3 modeled) — these are genuine
   findings and must stay flagged, as MARK_MISMATCH not PDF_ONLY.
5. Revit 72 vs PDF 62: ~10 devices appear on sheets/levels where the
   detector found no callout — candidates for detector recall work, and
   the only honest REVIT_ONLY.

## The fix: physical-element matching (holdowns first, then walls)

**P1 — Physical device registry (PDF side).**
Inverse-project every sheet callout to model feet (chirality-aware, reuse
the verified per-sheet calibrations — no new registration math), cluster
same-mark points within tolerance. Output: one physical device per
cluster; its sheet appearances become *evidence*, not rows.

**P2 — Global one-to-one assignment (model space, feet).**
Match 62 PDF devices ↔ 72 Revit assemblies by nearest-neighbor one-to-one
assignment, same-mark first, then a mark-blind pass. Gates in FEET
(MATCH ≤ 2 ft; LOCATION_MISMATCH 2–6 ft with the offset reported in ft;
beyond 6 ft = unmatched), decoupled from any single sheet's registration
quality. No fake matches: pairing still requires the verified transforms
that produced the model-space points, and every gate is explicit.

**P3 — Honest statuses at device level.**
MATCH / LOCATION_MISMATCH (real ft offset) / **MARK_MISMATCH** (device
present, different schedule mark — new status) / REVIT_ONLY (no callout on
any sheet) / PDF_ONLY (no device within 6 ft — currently zero).
Per-sheet rows remain visible as appearances under each device.

**P4 — UI.** Element list groups by physical device; Evidence Inspector
shows all sheet appearances + the model-space pairing. Run-comparison
(⚖ Runs) gains the device-level table.

**P5 — Walls (same disease, same cure).** SW callouts per sheet →
inverse-project segment anchors → cluster per wall run → assign against
wall centerlines in model space. The 42 REVIT_ONLY walls are doc-wide
SW walls vs sheet-scoped callouts — device-level accounting collapses
them the same way.

Expected holdown outcome from today's probe: ~40+ device MATCH, ~8–14
LOCATION_MISMATCH with honest ft offsets to review, a handful of
MARK_MISMATCH findings, ~10 REVIT_ONLY for detector recall — and zero
phantom PDF_ONLY. That is the honest ceiling; closing the last gap is
detector recall + reviewing the real offsets, not more matching tricks.

Frozen modules stay frozen: compare.py/registration.py/s201_detector.py
untouched — this is a new accounting layer ABOVE their per-sheet outputs.
