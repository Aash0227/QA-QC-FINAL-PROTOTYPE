# UI/UX v2 Plan — drawer bugs, Runs learn-loop, Livio branding, 3D fidelity

*User + manager asks, 2026-07-15. Repo snapshot taken first
(`C:\QA-QC-FINAL-PROTOTYPE-bkp-OLD`). All items in `frontend/index.html`
unless stated; `index_v3_backup.html` stays the pre-redesign fallback.*

## B1 — Drawer overlap bug (severity: high, minutes to fix)

**Symptom (user screenshot):** Human review, Teach AI and Runs panels
visible stacked on the right without their buttons being clicked.
**Fix:** `.drawer` default state must be fully hidden —
`visibility:hidden` + off-screen `transform` until `.open` is applied;
audit z-index stacking and recent additions (runs drawer, AI cards).
**Acceptance (Playwright):** fresh page load shows NO drawer; each drawer
appears only via its own button; ✕ hides it completely; opening one closes
the others.

## B2 — ⚖ Runs: baseline → memory rules → rerun loop

**Goal:** make the run comparison actionable, not just a table.
**Flow:** reviewer works the queue (accept/reject with reasoning) → clicks
**Save as baseline** → backend ALSO distills that run's human decisions
(resolutions + comment threads in `review_comments.json`) into GLOBAL
teach-memory entries (`teach.add_entry`, kind `review_resolution`) and
reports how many rules were saved → UI then offers **🔁 Re-run with learned
rules** → runs ① Extract + ② Match → Runs drawer reopens showing
baseline-vs-new deltas (MATCH movement highlighted).
**Honesty:** rules affect recognition only; stored human accepts re-apply
via the existing `apply_stored_resolutions`; no rule ever mints a MATCH.
**Touch points:** `POST /api/runs/baseline` (extend), Runs drawer JS.

## B3 — Livio-brand redesign (use `ui-ux-pro-max` skill)

**Reference:** https://hub.golivio.com — same wordmark treatment but
**LIVIO QA QC**. Deliverables: design tokens (palette, type scale, spacing
scale) applied across the app; toolbar grouped into [project] [pipeline
actions] [drawers]; aligned three-pane grid with consistent gutters; button
hierarchy (primary/secondary/mini) consistent; no functional changes, no
framework rewrite. Fallback kept; backup re-synced after.
**Acceptance:** visual pass vs hub reference; all existing Playwright flows
still pass; user sign-off on a screenshot.

## B4 — 3D fidelity pass (time-boxed, honest)

**Goal:** the 3D pane should read like the Revit model (user provided
Madera + Country Side screenshots as reference).
**Levers (data-driven only):** use per-element bbox from the v3 export for
true member sizes (framing, columns, walls); real wall heights; foundations
as slabs; grid labels both ends. Where the export lacks geometry, use the
Nonica MCP (`get_boundingboxes_for_element_ids`) to spot-VERIFY dimensions
live — geometry is never invented.
**Acceptance:** side-by-side screenshot vs the user's Revit screenshots;
element counts in scene == export counts; no regression in click-to-select.

## Order

B1 → (Part A benchmark plan, see BENCHMARK-REGISTRATION-PLAN.md) → B2 → B3 → B4.
Gate after each: pytest green, Madera MATCH ≥106, Country Side ≥21,
Dogwood ≥16, Playwright smoke.
