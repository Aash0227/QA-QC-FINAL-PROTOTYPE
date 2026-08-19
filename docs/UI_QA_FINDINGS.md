# QBC Frontend — Adversarial UI/UX Audit

**Date:** 2026-08-19
**Scope:** `frontend/` — `/` (dashboard) and `/pipeline.html` (React pipeline island)
**Method:** code read + live Chromium (Playwright) against vite `:5173` proxying the running backend `:8077`, project `dogwood-lane` (259 elements, `product_counts` = 33/98/10/118).
**Baseline commit at audit start:** `0faf543`. Two fixes landed mid-audit (`0c05e6b`, `621d905`) — noted inline.

Every finding below is either **CONFIRMED** (reproduced in the browser and measured) or **SUSPECTED** (read from code, not reproduced). Three claims I initially formed were disproved on verification and are recorded in *Checked and Clean* so nobody re-reports them.

---

## CRITICAL

### C-1. The verdict filter can be left active with no on-screen way to clear it
**CONFIRMED**

- `index.html:119` — `<div id="scope-banner">` (the `VerdictBar` mount) lives **inside** `#table-panel`.
- `index.html:120` / `app.css:18` — `#table-panel` starts `hidden` and is toggled by `▤ All results`.
- `panels/table.js:32` — `#btn-table-close` re-hides the whole panel.
- `ScopeBanner.tsx:30-41` — the only writer of `store.verdictFilter`.
- `elements.ts:14-17` — `visibleElements()` applies `verdictFilter` to **both** the left list and the results table.

Reproduction:
1. Load `/`. Click `▤ All results`. Click the `10 Needs review` legend chip.
2. Left element list collapses from 4 categories to one (`Shear walls 10`). Correct so far.
3. Click `✕` on the results panel.
4. The left list is **still filtered** — 3 of 4 categories are gone — and the `VerdictBar` is now in a `display:none` subtree. `Escape` does not clear it (`app.js:137-143` clears selection only). The status/sheet/search controls in `#list-panel` all show "All …", so the UI actively asserts no filter is applied.

Measured: after close, `#table-panel` class `pane glass hidden`, `.verdict-bar` `isVisible() === false`, `#list-rows` text `"▶Shear walls 10?10"`, `#hdr-stats` still reads `141 in scope · 33 verified · 98 mismatch · 10 to review`.

**Consequence:** a QA engineer sees an element list missing three quarters of the project, with no filter indicator and no control to restore it. The only recovery is re-opening a panel they just closed, or reloading the page. On a punch-list review this reads as "the pipeline lost my hold-downs".

**Fix:** either (a) hoist the `VerdictBar` out of `#table-panel` into a permanently visible position, or (b) clear `store.verdictFilter` in `#btn-table-close`'s handler, or (c) render a dismissible "Filtered to: Needs review ✕" chip in `#list-panel` whenever `verdictFilter` is non-null. (c) is the smallest and also fixes C-2's symptom.

---

## HIGH

### H-1. The "Verdict" column header is a dead sort control that pretends to work
**CONFIRMED**

- `index.html:126` — `<th data-k="verdict">Verdict</th>`
- `panels/table.js:20-30` — sets `store.tableSort.key = "verdict"` and stamps `class="sorted"` + `data-dir="▲/▼"`.
- `ResultsTable.tsx:22-34` — comparator reads `a["verdict"]`; **no `verdict` key exists on the row** (`types.ts:5-26`; live API confirms the verdict lives at `product.verdict`).

Every value is `undefined` → `av == null && bv == null` → comparator returns `0` for every pair → `Array.sort` is stable → the table silently reverts to raw API order while the header displays a sort arrow.

Measured: clicking the header twice produced **byte-identical** row order (`asc === desc`), and the resulting verdict column was ungrouped (`Mismatch, Mismatch, …` interleaved with others further down). By contrast `th[data-k="mark"]` sorts correctly (`EXW-1, EXW-1, …`), proving the mechanism works and only this column is broken.

**Consequence:** the single most useful sort in a QA table — "show me all the mismatches together" — is the one that does nothing, and the ▲ indicator tells the user it worked. Highest-value dead control on the page.

**Fix:** in `ResultsTable.tsx`, special-case `key === "verdict"` to compare `rowVerdict(a)` vs `rowVerdict(b)`, ideally against a severity order (`LOCATION_MISMATCH, NEEDS_REVIEW, LOCATION_MATCH, NOT_APPLICABLE`) rather than alphabetically.

### H-2. Two different numbers labelled "needs review" are on screen at the same time
**CONFIRMED**

- `index.html:37` — `⚠ Needs review (<span id="rev-count">0</span>)`, filled from `/api/review/queue` (`ReviewWorkspace.tsx:47-56`, `q.total - q.reviewed`).
- `VerdictBadge.tsx:84` — legend chip renders `product_counts.NEEDS_REVIEW`.

Live: header badge = **25**, verdict bar = **10 Needs review**. Both visible in one viewport (see the 700px capture). The review queue mixes `LOCATION_MISMATCH` + `NEEDS_REVIEW` and is capped somewhere; the verdict bar counts only the product verdict.

**Consequence:** the whole point of the verdict vocabulary is that the screen and the API cannot disagree (`VerdictBadge.tsx:1-6`). Two contradictory "needs review" counts, six inches apart, destroys exactly that trust. A reviewer cannot tell which one is the workload.

**Fix:** rename the header button to the thing it actually opens ("⚠ Review queue (25)"), or drive it from `product_counts.NEEDS_REVIEW` so both surfaces agree.

### H-3. `store.verdictFilter` is never reset by a data reload
**CONFIRMED (code) / SUSPECTED (browser — not reproduced end-to-end, re-match is slow)**

- `store.js:14` declares it; `app.js:47-104` `loadAll()` reassigns `elements`, `sheets`, `cc`, `scopeWarnings`, `productCounts` — and **not** `verdictFilter` (nor `filters`, `openCats`, `selected`).
- `app.js:107-126` — `① Extract elements` and `② Match to model` both call `loadAll()` **without** a page reload.

So a filter chosen against run N survives into run N+1's data. If the new run has zero elements at that verdict, both surfaces show `No elements match.` immediately after a "successful" re-match, with the toast saying `Element list: N elements, M MATCH.`

**Not a bug:** project switching is clean — `ProjectManager.tsx:430,494` does `location.reload()`, which resets everything.

**Fix:** `store.verdictFilter = null` at the top of `loadAll()`. One line.

### H-4. The same element is coloured by two different palettes in the same table row
**CONFIRMED**

Two independent colour maps are rendered side by side:

| Concept | `COL` (`util.js:26-29`) | `VERDICT_COL` (`util.js:60-65`) |
|---|---|---|
| `LOCATION_MISMATCH` | `#f59e0b` amber | `#FF5A36` red |
| `NEEDS_REVIEW` | `#a78bfa` violet | `#FBBF24` amber |
| `MATCH` / `LOCATION_MATCH` | `#22c55e` | `#34D399` |

`ResultsTable.tsx:62` renders the `VERDICT_COL` badge; `ResultsTable.tsx:66-70` renders the `COL` pill in the adjacent cell. Result: a `LOCATION_MISMATCH` row shows a **red** badge next to an **amber** pill — and amber is the verdict palette's colour for *Needs review*. A third hardcoded `#a78bfa` at `ResultsTable.tsx:76` (the `status_detail` pill) collides with `COL.NEEDS_REVIEW`.

Verified in the 700px capture: a `NEEDS REVIEW` row renders an amber `? Needs review` badge beside a violet `NEEDS REVIEW` pill — the identical words in two colours, touching.

**Consequence:** colour is the fastest channel in a triage table, and it is now actively misleading. Amber means "mismatch" in one column and "needs review" in the next.

**Fix:** derive the Detail pill's colour from the row's *verdict*, not its status, and reserve `COL` for the PDF/3D overlays where the engine statuses genuinely matter.

### H-5. Opening the results panel makes the page overflow horizontally
**CONFIRMED**

- `app.css:21` — `#results-table th,#results-table td{…white-space:nowrap}` on a Reason column carrying strings up to **198 characters** (longest in live data: the SW-2 vocabulary-gap message).
- `app.css:17-19` — `#table-panel{display:flex;flex-direction:column}` / `#table-wrap{overflow:auto;min-height:0}` — `min-height:0` is set but **`min-width:0` is not**, so the flex child refuses to shrink below its nowrap content width.

Measured at viewport 1600×1000, clean load: `#table-panel` right edge = **1920px**, width **1908px** — 308px past the viewport, producing document-level horizontal scroll. The Reason column and part of Device sit off-screen with no visual cue.

**Fix:** `#table-wrap{min-width:0}` plus `white-space:normal` (or a `max-width` + `text-overflow:ellipsis` + `title`) on the reason cell only.

### H-6. No responsive layout below ~1100px; the app overflows and clips
**CONFIRMED**

- `app.css:71` — `#main{grid-template-columns:360px 1fr}` with no breakpoint.
- `app.css:106` — `#dual{grid-template-columns:1fr 1fr}` with no breakpoint.
- The **only** width breakpoints in the entire stylesheet are `app.css:53` (header padding at 1280px) and `app.css:462` (which touches `#pm-grid`/`.pm-head` in the Project Manager overlay only).

Measured `document.scrollWidth` at viewport widths 1100 / 900 / 700 / 375 → **1100 / 907 / 907 / 907**. Below ~907px the page overflows; at 375px the user sees a 907px-wide layout in a 375px window. The 700px capture shows the 3D pane and the results table both clipped, and the 360px sidebar still eating half the screen.

The verdict bar legend itself is fine (`flex-wrap:wrap`, `app.css:502`; measured height stayed 29px at every width) — the failure is entirely in the outer grid.

**Fix:** a single `@media(max-width:1100px)` collapsing `#main` to one column and `#dual` to stacked panes.

### H-7. The review drawer — where the reviewer actually adjudicates — still speaks raw engine statuses
**CONFIRMED**

- `ReviewWorkspace.tsx:69` — `<span style={{color: e.status === "LOCATION_MISMATCH" ? "var(--warn)" : "#94a3b8"}}>{e.status}</span>`
- `ReviewWorkspace.tsx:246` — `{e.mark} · {e.status}`

Live drawer text: `HD2 holdown · S-05 · LOCATION_MISMATCH · 20.6pt off`, repeated. Zero `.verdict-badge` elements in `#rev-body`. This is also the only place in the app that conveys a distinction (mismatch vs. everything else) by **colour alone** — `var(--warn)` vs `#94a3b8` with no glyph and no label difference, directly contradicting the stated design rule at `VerdictBadge.tsx:8-10`.

> **Fixed mid-audit for two of three surfaces.** `0c05e6b` moved the left list to verdict dots/pills (`ElementList.tsx:130-144`) and `621d905` put a `VerdictBadge` in the inspector (`Inspector.tsx:158`). `ReviewWorkspace.tsx` is the remaining holdout and still shows raw `LOCATION_MISMATCH` / `NEEDS_REVIEW` tokens.

---

## MEDIUM

### M-1. The verdict bar's coloured track looks clickable and is not
**CONFIRMED** — `VerdictBadge.tsx:63-70`

The segmented track is the dominant visual affordance; only the small legend chips below it are interactive. Measured on `.verdict-bar__seg`: `cursor: auto`, no `onclick`, `tabIndex: -1`. Users will click the bar first. Either wire the segments to the same `onSelect` or explicitly de-emphasise them.

### M-2. The element list cannot be expanded with a keyboard
**CONFIRMED** — `ElementList.tsx:90-98` (`.cat-hdr`), `:106` (`.mark-hdr`)

Both are `<div onClick>` with no `role`, no `tabIndex`, no key handler. Measured: `tabIndex === -1`, `role === null`. Rows are `role="option"` and J/K stepping works (`panels/list.js:63-74`), but J/K only walks rows that are **already rendered** — and on load only one category is open with all marks collapsed, so a keyboard-only user has **zero** reachable rows and no way to open a group. Make them `<button>` or add `role="button" tabIndex={0}` + Enter/Space.

### M-3. `#list-rows` is an ARIA `listbox` containing non-option children
**CONFIRMED** — `index.html:68`

Measured children order: `cat-hdr (role=none)`, `mark-hdr (role=none)`, `row (role=option)`. A `listbox` may only contain `option`/`group`. Screen readers will either drop the headers or mis-announce the count. Use `role="tree"` with `treeitem`/`group`, or drop the listbox role and rely on the headings.

### M-4. Two 404s fire on every dashboard load for a drawer nobody opened
**CONFIRMED** — `RunsComparison.tsx:56`

`GET /api/runs/compare` → `404 {"detail":"No run baseline saved…"}`, fired **twice** per load (StrictMode double-mount) even though `#runs` is closed. Gate the fetch on drawer visibility. The drawer's own empty state, once opened, is genuinely good copy — see *Checked and Clean*.

### M-5. The verdict bar presents explicitly-suspect data as a hard number
**CONFIRMED** — `ScopeBanner.tsx:43-47`

The `VerdictBar` renders **above** the export-scope warning. Live: the bar says `98 Mismatch`, and the banner immediately below says *"No shear_wall elements in the Revit export. These PDF_ONLY verdicts may be wrong."* — covering 35 of those 98. The headline number is 35/98 = 36% built on data the app itself flags as untrustworthy, and `#hdr-stats` (`app.js:65-68`) repeats `98 mismatch` at the top of the screen with no caveat at all.

Either render the warning above the bar, or split the suspect count out of the Mismatch segment.

### M-6. The exported punch list has no verdict column
**CONFIRMED** — `GET /api/export/punch-list.csv` header row:
`sheet,category,mark,status,distance_ft,…,reason,reviewer_disposition,reviewer_comments`

`VerdictBadge.tsx:8-10` justifies the glyph design so the verdict "survives a monochrome print of a punch list" — but the punch list contains only the raw `status` (`PDF_ONLY`, `NOT_IN_SCHEDULE`, …). The reviewer's on-screen vocabulary does not survive the one artefact that leaves the app. Add a `verdict` column.

### M-7. Elements in an unknown category are silently dropped from the list
**SUSPECTED** — `ElementList.tsx:73` (`CAT_LIST.filter(cat => byCat[cat])`) against the fixed `CATS` at `util.js:94`

The results table iterates rows directly, the left list iterates the hardcoded category whitelist. Today the API returns only known categories (`holdown/post/shear_wall/steel_column`), so this does not currently reproduce — but the day the backend adds one, those elements vanish from the list, remain in the table, and stay counted in the verdict bar. A `category` not in `CATS` should still render, under an "Other" group.

### M-8. React logs a DOM-nesting error on every dashboard load
**CONFIRMED** — `dashboard-main.tsx:43` (`mount("results-tbody", <ResultsTable />)`)

`In HTML, <tr> cannot be a child of <table>. This will cause a hydration error.` React's validator does not see the real `<tbody>` root. Harmless today, but it is a permanent red console error that will mask a real one.

---

## LOW

### L-1. Accent-colour drift after the unification
**CONFIRMED.** `:root` is clean (`--signal` = `--accent` = `#22D3EE`, `tokens.css:27,34`), but leftovers remain:
- `#5eead4` (old teal) hardcoded — `panels/pdf.js:141,147,148,149` (measure tool), `panels/viewer3d.js:252,258,296` (3D selection highlight), `app.css:408` (`.pm-status-active` border)
- `--color-ring:#06adf5` (old Livio blue) — `react/index.css:32`; the pipeline page's focus ring is a different blue from its own `--color-primary: #22D3EE` two lines up
- `glow: "74,158,255"` — `PipelineIsland/KineticGrid.tsx:96`

So the selected element in the 3D viewer glows teal while everything else that means "selected" is cyan.

### L-2. Three stacked backdrop-filter layers
**CONFIRMED.** 31 elements with a non-`none` `backdrop-filter` on one page, nested:
- `#table-panel` blur(16) → `.pane-bar` blur(10)
- `#sheet-panel` blur(14) → `.pane-bar` blur(10) → `#layer-bar` blur(10)
- `#list-panel` blur(14) → `.cat-hdr` blur(14) ← `app.css:471` blurs every category header, which sits on an already-blurred panel and reads as mud

Each nested layer forces another compositor pass for no visual gain (blurring an already-blurred surface). Drop `.cat-hdr` and `.pane-bar` from the glass selector list.

### L-3. Dead CSS selectors for ids that no longer exist
**CONFIRMED** — `app.css:468-471` targets `#pdf-panel` (it is `#sheet-panel`), `#list-wrap`, `#chat-drawer` (it is `#chat`), `#pipe-modal` (removed with the vanilla pipeline modal), `#setting-panel`. Harmless, but it makes the glass layer look like it covers surfaces it does not.

### L-4. Left-list rows are visually indistinguishable
**CONFIRMED.** Under `H1 (12)` the rows render as four identical `S-05 · pdf only  [Mismatch]` lines (`ElementList.tsx:133-144`). `distance_pdf_points` is the only differentiator and it is null for `PDF_ONLY`. Selecting the third one is guesswork. Consider surfacing the callout index or PDF coordinate.

### L-5. 259 rows render unpaginated
**CONFIRMED** — `ResultsTable.tsx:48`. `#table-panel{max-height:38vh}` plus a sticky `th` (`app.css:22`) makes it survivable, but there is no virtualisation and no row count shown anywhere in the table chrome.

---

## Checked and Clean — do not re-report

These were suspected and **disproved** by measurement:

1. **The search filter works.** An earlier probe suggested it did not; re-tested with real keystrokes, `zzzzzzz` → `No elements match.` in both surfaces, `SW-2` → 25 rows. The `#search` → `store.filters.search` → `visibleElements()` path is correct.
2. **Verdict filter toggle-off works.** Second click on the same chip clears it (`VerdictBadge.tsx:82`, `onSelect(isSel ? null : v)`); measured 98 → 259 rows. `aria-pressed` is correct.
3. **The verdict filter does filter both surfaces.** One shared `visibleElements()` (`elements.ts`) backs the list and the table; measured 10 rows / 1 category simultaneously.
4. **Focus is not suppressed.** No global `outline:none`. `.verdict-bar__item` matches `:focus-visible` with the browser default outline; reachable in 13 Tab presses from the search box. (A custom high-contrast ring would still be an improvement on the dark ground, but nothing is broken.)
5. **Verdict is never conveyed by colour alone in the badge.** Every `VerdictBadge` carries a glyph (`✓ ✕ ? –`) and a text label; the legend chips carry the count and the label. (The exception is `ReviewWorkspace` — H-7.)
6. **Contrast passes comfortably.** Measured against the `#0B0D10` ground: legend chips 16.0:1, table headers 16.0:1, reason text 7.4:1, list meta 7.4:1, `#hdr-stats` 7.4:1. All well over 4.5:1.
7. **Project switching resets state correctly** — `ProjectManager.tsx:430,494` full `location.reload()`.
8. **The runs-comparison empty state is good.** *"No baseline saved for this project yet. Run the pipeline, then press 'Save as baseline' — the next run will compare against it."* — says what happened and what to do next.
9. **Empty states exist and are wired** — `ElementList.tsx:76` and `ResultsTable.tsx:36-44` both render `No elements match.`; `ReviewWorkspace.tsx` renders a real "nothing to review" state. (They are terse and offer no clear-filter action — that is C-1, not a missing state.)
10. **The API is not mis-encoded.** An apparent mojibake in the `reason` field was my own `json.load` locale-decode artefact; the wire bytes are correct UTF-8 (`e2 80 94`).
11. **The `Report` button is real.** `PipelineIsland/index.tsx:64-67` → `GET /api/export/punch-list.csv` → `200 text/csv`, `content-disposition: attachment`. Downloads without navigating away.

### `/pipeline.html` is genuinely clean

Enumerated every `<button>`/`<a>`: `◂ Dash`, `Grid`, `Run`, `Force`, `Report`, `Technical details` ×7, `Debug: raw SSE events (0)`. **Zero disabled controls, zero dead handlers.** Removing the placeholder `Stop` was the right call. `document.scrollWidth === 375` at a 375px viewport — the one responsive surface in the product. No console errors, no failed requests. The live/polling indicator carries both a colour and the words "live"/"polling".

The one thing worth adding later: `Run` and `Force` have no pending/disabled state while a run is in flight, so a double-click can fire two runs, and `Force` (a destructive re-run) has no confirmation. Neither reproduced as a failure here — flagging as **SUSPECTED**, low.

---

## Priority order

| # | Finding | Severity |
|---|---|---|
| 1 | C-1 Verdict filter trap — silently filtered list, no visible escape | CRITICAL |
| 2 | H-1 "Verdict" column header sorts nothing but shows a sort arrow | HIGH |
| 3 | H-2 Header says "Needs review (25)", verdict bar says "10 Needs review" | HIGH |
| 4 | H-4 Two colour palettes for the same verdict, side by side in one row | HIGH |
| 5 | H-3 `verdictFilter` survives a re-match onto new data | HIGH |
| 6 | H-6 No responsive layout — 907px minimum, clips below that | HIGH |
| 7 | H-5 Results panel overflows the viewport horizontally (1908px @ 1600px) | HIGH |
| 8 | H-7 Review drawer still speaks raw engine statuses, colour-only | HIGH |
| 9 | M-2 Element list unreachable by keyboard | MEDIUM |
| 10 | M-5 Verdict bar states 98 mismatch above a banner saying 35 may be wrong | MEDIUM |
| 11 | M-1 Verdict bar track looks clickable, is not | MEDIUM |
| 12 | M-6 Punch-list CSV has no verdict column | MEDIUM |
| 13 | M-4 Two 404s per load from a closed drawer | MEDIUM |
| 14 | M-3 Invalid ARIA listbox structure | MEDIUM |
| 15 | M-8 React DOM-nesting error every load | MEDIUM |
| 16 | M-7 Unknown categories silently dropped from the list | MEDIUM (latent) |
| 17 | L-1…L-5 Accent drift, stacked blurs, dead CSS, ambiguous rows, no pagination | LOW |

**Cheapest high-value fixes:** H-3 is one line in `app.js`. C-1 is a `verdictFilter = null` in `#btn-table-close` plus a chip. H-1 is a three-line special case in the `ResultsTable` comparator. Those three remove the CRITICAL and two HIGHs for well under 30 lines.
