# QBC — UI Design Direction

**Scope:** `frontend/` as it exists today (read, not assumed). Every proposal below maps to
code or an API route that already exists. Anything needing new backend work is tagged
**`[BACKEND]`** and isolated so it can be cut without breaking the rest.

**Product one-liner for the UI to serve:** *for every structural element called out on a PDF,
say whether the Revit model agrees — and be able to prove it.*

---

## 1. Inventory of existing UI surfaces

### 1.1 Two pages, two runtimes

| Page | Runtime | Entry |
|---|---|---|
| `frontend/index.html` — the dashboard | Vanilla shell + 13 React islands | `src/app.js`, `src/react/dashboard-main.tsx` |
| `frontend/pipeline.html` — the run view | Pure React (Tailwind v4) | `src/react/main.tsx` → `App.tsx` → `PipelineIsland` |

The dashboard's React islands are mounted by `dashboard-main.tsx` into pre-existing DOM ids and
deliberately **do not** import `src/react/index.css`. So the dashboard is styled by
`tokens.css` + `components.css` + `app.css`, and the pipeline page is styled by Tailwind
`@theme` in `index.css`. **Two token systems, two accents.** This is the single biggest source
of "it doesn't feel like one product" and it is fixed in §2.

### 1.2 Surface-by-surface

| # | Surface | DOM id / file | React or vanilla | Notes |
|---|---|---|---|---|
| 1 | App shell / 4-zone header | `index.html` `<header>`, `app.css` | **vanilla** | 5 verbs + `⚙` `<details>` popover |
| 2 | Kinetic background (dashboard) | `src/kinetic-grid.js` | vanilla canvas | `#kinetic-bg`, `z-index:0`, `opacity:.5` |
| 3 | Kinetic background (pipeline) | `components/PipelineIsland/KineticGrid.tsx` | React canvas | same math, own copy |
| 4 | Header stats string | `#hdr-stats`, `app.js:loadAll()` | vanilla | `"N elements · N verified · N flagged"` |
| 5 | Element list (cat → mark → row) | `#list-rows` | **React** `element-review/ElementList.tsx` | search/filter wiring still vanilla (`panels/list.js`) |
| 6 | Search + status/sheet filters | `#search`, `#status-filter`, `#sheet-filter` | vanilla | mutates `store.filters` |
| 7 | PDF pane + SVG overlay | `#sheet-panel`, `src/panels/pdf.js` | **vanilla** | pan/zoom, isolation, measure, layer toggles, benchmark markers |
| 8 | 3D model pane | `#model-panel`, `src/panels/viewer3d.js` | **vanilla** | three.js, tooltip, legend, live refresh |
| 9 | Results table | `#results-tbody` | **React** `element-review/ResultsTable.tsx` | sort headers + open/close still vanilla (`panels/table.js`) |
| 10 | Scope-warning banner | `#scope-banner` | **React** `element-review/ScopeBanner.tsx` | |
| 11 | Inspector drawer | `#insp-body` | **React** `inspector/Inspector.tsx` | embeds a DOM island from `panels/revit_live.js` |
| 12 | Count consistency table | `#cc-table` | **React** `inspector/CountConsistency.tsx` | |
| 13 | Needs-review workspace | `#rev-body` | **React** `inspector/ReviewWorkspace.tsx` | queue, evidence crop, AI analysis, disposition, comments |
| 14 | Runs comparison drawer | `#runs-body` | **React** `inspector/RunsComparison.tsx` | |
| 15 | Revit ID lookup drawer | `#rl-body`, `panels/revit_live.js` | **vanilla** | |
| 16 | Chat / Ask drawer | `#chat-log` | **React** `chat/Chat.tsx` | count cards, status breakdown, tables, `ui_actions` |
| 17 | Drawer open/close manager | `panels/inspector.js` | **vanilla** | owns all 5 drawers + focus management |
| 18 | Benchmark Autopilot wizard | `#bm-rail/#bm-cards/#bm-log/#wizard-banner-root` | **React** `benchmark-wizard/Wizard.tsx` | full-screen `#bmwizard`, open/close vanilla |
| 19 | Project Manager overlay | `#dashboard-react-root` | **React** `project-manager/ProjectManager.tsx` + `VerdictRing.tsx` | |
| 20 | Pipeline island (page 2) | `PipelineIsland/index.tsx`, `PipelineTimeline.tsx`, `StepRow.tsx`, `AiText.tsx` | **React** | shadcn-ish `ui/{badge,button,card,separator,status}` |
| 21 | Pipeline modal shell (dashboard) | `#pipe-modal` | vanilla, **dead** | `#btn-pipe` now navigates to `/pipeline.html`; markup is a leftover |
| 22 | Toasts | `#toast-box`, `util.js:toast()` | vanilla + GSAP | |

**Shared state seam:** `src/store.js` singleton + `subscribe/emit` pub-sub, plus `window`
CustomEvents (`open-project-manager`, `chat-init`, `open-review-drawer`, `runs-init`,
`wizard-open/close`). Any new UI must go through these two, never cross-imports.

### 1.3 The gap that defines this redesign

```
$ grep -rn "product" frontend/src --include=*.ts --include=*.tsx --include=*.js
# → nothing but comments
```

`element_registry.py:268` stamps `el["product"] = matching_engine.product_result(el)` on every
row and `element_registry.py:275` emits `product_counts`. **The frontend consumes none of it.**
Every list row, table cell, pill, dot bar, verdict ring and chat pill still renders one of the
ten *internal* statuses from `util.js:COL`. The UI is showing engine vocabulary to a QA
engineer. Fixing that is P0 and is nearly free — the data is already on the wire.

---

## 2. Design system — exact values

### 2.1 Background layers (the dark foundation)

The kinetic grid must stay visible, so the ground has to be genuinely dark and *slightly cyan*,
not warm grey. Current `body` gradient uses `#161a20` (warm) which fights a cyan accent.

| Token | Value | Use |
|---|---|---|
| `--bg-void` | `#07090C` | Outermost page ground, behind the canvas |
| `--ink` | `#0B0D10` | **Keep.** Canonical app background; referenced app-wide |
| `--bg-halo` | `#0E1519` | Replaces `#161a20` in the `body` radial gradient — cyan-leaning, not warm |
| `--panel-solid` | `#12161B` | Opaque panels: sticky table `<th>`, `⚙` popover, tooltips |
| `--panel2` | `#171C22` | Second opaque step: skeleton base, nested cards |
| `--line` | `#232A32` | **Structural** border (table rules, dividers) |
| `--line-soft` | `rgba(255,255,255,.07)` | **Glass** border — never a solid hex on a glass edge |
| `--line-strong` | `#2E3742` | Focus rings on non-accent elements, table header underline |

`body` becomes:
```css
background:
  radial-gradient(1200px 800px at 72% -12%, var(--bg-halo) 0%, var(--ink) 55%),
  var(--bg-void);
```

### 2.2 Glass fills

| Token | Value |
|---|---|
| `--glass-1` | `rgba(13,17,22,.55)` — chrome (header, pane bars, tab strips) |
| `--glass-2` | `rgba(11,14,18,.72)` — content panels (list, table, drawers) |
| `--glass-3` | `rgba(8,10,13,.86)` — modal/overlay (Project Manager, wizard, dialogs) |
| `--glass-hi` | `rgba(255,255,255,.05)` — 1px inset top highlight |
| `--scrim` | `rgba(4,7,11,.72)` — full-screen dimmer behind `--glass-3` |

**The rule:** if a surface carries running body text, it is `--glass-2` or heavier. `--glass-1`
is for chrome only. This is what lets the grid stay alive in the header, the 12px gutters and
the pane bars, while the list and table stay razor-legible.

### 2.3 Cyan accent ramp

Today there are **three** competing accents: `--signal:#5EEAD4` (teal, dashboard),
`--color-primary:#06adf5` (Livio blue, pipeline page), and the grid's active line
`rgb(74,158,255)` = `#4A9EFF`. Collapse to one electric-cyan ramp that sits between them —
it reads as a natural evolution of both, so nothing looks "recoloured".

| Token | Value | Contrast on `--ink` `#0B0D10` | Use |
|---|---|---|---|
| `--cy-100` | `#CFFAFE` | 17.9 : 1 | Text on a filled cyan button |
| `--cy-300` | `#67E8F9` | 14.6 : 1 | Hover/active text, focused labels |
| `--cy-400` | `#3DDCF0` | 12.2 : 1 | Icon strokes, active tab text |
| `--cy-500` | `#22D3EE` | **10.8 : 1** | **The accent.** Borders, links, active states, focus ring |
| `--cy-600` | `#06B6D4` | 8.0 : 1 | Filled primary button background |
| `--cy-700` | `#0891B2` | 5.0 : 1 | Pressed state, muted accent rules |
| `--cy-glow` | `rgba(34,211,238,.14)` | — | Selected-row wash, chip fill |
| `--cy-ring` | `rgba(34,211,238,.38)` | — | Focus ring, 2px |
| `--cy-ink` | `#02171C` | — | Text **on** `--cy-600` fill (14.9 : 1 against it) |

Aliases so nothing breaks: `--signal: var(--cy-500)`, `--accent: var(--cy-500)`,
`--bw-signal: var(--cy-500)`, and on the Tailwind side `--color-primary: #22D3EE;
--color-primary-foreground: #02171C; --color-ring: #22D3EE`.

**Retune both kinetic grids to match** — a one-line change each:
- `src/kinetic-grid.js:22` → `const ACTIVE = { r: 34, g: 211, b: 238, a: 0.80 };`
- same constant in `PipelineIsland/KineticGrid.tsx`
- the radial dot glow `rgba(74,158,255,…)` → `rgba(34,211,238,…)`
- ripple stroke `rgba(100,180,255,…)` → `rgba(103,232,249,…)`
- `#kinetic-bg { opacity: .42 }` (down from `.5` — the cyan reads hotter than the blue did)

### 2.4 The four product verdict colours

These are the only four colours a QA engineer needs to learn. Every one clears 4.5:1 on `--ink`
as text, and every one is light enough to take `--ink` as a glyph on top of it as a filled dot.

| Verdict | Token | Hex | Contrast on `--ink` | Fill (12% tint) | Glyph | Label shown |
|---|---|---|---|---|---|---|
| `LOCATION_MATCH` | `--v-match` | `#34D399` | 10.4 : 1 | `rgba(52,211,153,.12)` | `✓` | **Match** |
| `LOCATION_MISMATCH` | `--v-mismatch` | `#FF5A36` | 6.3 : 1 | `rgba(255,90,54,.13)` | `✕` | **Mismatch** |
| `NEEDS_REVIEW` | `--v-review` | `#FBBF24` | 11.6 : 1 | `rgba(251,191,36,.12)` | `?` | **Needs review** |
| `NOT_APPLICABLE` | `--v-na` | `#8A93A0` | 6.3 : 1 | `rgba(138,147,160,.10)` | `–` | **Not applicable** |

Notes:
- `--v-mismatch` **is** the existing `--markup: #FF5A36`. Keeping it means the "correction /
  destructive" colour and the "mismatch" colour are the same idea — deliberate, one red family.
- `--v-review` is the existing `--warn: #fbbf24`. Also deliberate: amber has always meant "your
  judgement required" in this app (scope banner, unverified rows).
- Cyan is **never** a verdict colour. Cyan = interactive/selected/system. A cyan thing is
  something you can click; a verdict colour is something the engine decided. Keeping these
  disjoint is what stops the UI reading as decorative.
- The glyph is mandatory (`ElementList.tsx` already does this via `util.js:GLYPH`) — verdict is
  never colour-only, and a greyscale print of a punch list still reads.

**The ten internal statuses stay** in `util.js:COL` — they are still shown, but demoted to
secondary text inside the evidence panel and as a small monospace suffix on a table row. They
never drive a colour on a primary surface again.

### 2.5 Everything else

| Token | Value |
|---|---|
| `--txt` / `--paper` | `#ECE9E1` (keep) — 16.1 : 1 on `--ink` |
| `--txt-2` | `#B9C0C8` — secondary body, 9.4 : 1 |
| `--dim` | `#98A0AA` — labels/meta, 6.8 : 1 (raise from `#9AA0A6`; same feel, safer) |
| `--dur-fast` / `--dur` / `--dur-exit` | `.12s` / `.20s` / `.14s` (tightened from `.14/.24/.16`) |
| `--ease` | `cubic-bezier(.22,1,.36,1)` (keep) |

**Motion budget:** one transform-or-opacity transition per interaction, max 200ms. **Zero**
infinite animations except: the kinetic grid, the pipeline "running" spinner, the SSE
`live` connection dot, and the skeleton shimmer. Everything else in §7 gets deleted.

---

## 3. Typography and spacing

### 3.1 Type scale

Families stay: `IBM Plex Sans` (body), `IBM Plex Mono` (all numbers/ids/status tokens),
`Big Shoulders Display` (uppercase headings only). Already self-hosted via `src/fonts.js`.

| Role | Size / line-height | Family / weight | Where |
|---|---|---|---|
| `display` | **28 / 1.12**, `.02em`, uppercase | Big Shoulders 800 | Wizard `h1`, Project Manager title, empty-state hero |
| `title` | **19 / 1.20**, `.03em`, uppercase | Big Shoulders 700 | Drawer headers (`.drawer-hd`), overlay headers |
| `section` | **15 / 1.35** | Plex Sans 600 | Card titles, pipeline stage title, `h2` in evidence panel |
| `body` | **13.5 / 1.55** | Plex Sans 400 | **Base.** Keep — it is the right density for this dashboard |
| `body-strong` | **13.5 / 1.55** | Plex Sans 600 | Marks, element names, active row label |
| `meta` | **12 / 1.45** | Plex Sans 400, `--dim` | Row subtitles, reasons, timestamps |
| `micro` | **11 / 1.35**, `.08em`, uppercase | Plex **Mono** 600 | Column headers, pane titles, pill labels, kickers |
| `num` | **13 / 1.2**, `tabular-nums` | Plex Mono 500 | Distances, counts, ids, coordinates |
| `num-hero` | **34 / 1.0**, `tabular-nums` | Plex Mono 600 | Verdict-bar tile numbers |

**Hard floor: 11px.** Today's sub-floor offenders to fix — `#three-note` (10px),
`.pill` (10px), `.pm-slug`/`.pm-status`/`.pm-fact` (10.5px), `#results-table th` (10.5px),
`.msg .saved` (10.5px), `.mem-chip .k` (10px), `.steplog` (11px, ok). All → 11px micro.

**Weights: two only — 400 and 600.** Delete every `font-weight:700` and `800` outside Big
Shoulders headings. Current offenders: `.status-pill{font-weight:700}`, `.cat-hdr{700}`,
`.resolve-btn{800}`, `.resolved-chip{700}`, `.chat-card-num{700}`.

**Numbers are always mono + `tabular-nums`.** Already true in `#results-table td.num` and
`.cnt`; extend to distances in `ElementList`, `ReviewWorkspace`, `RunsComparison`, verdict tiles.

### 3.2 Spacing scale

`4 · 8 · 12 · 16 · 24 · 32 · 48` — as `--s1 … --s7`. Nothing else. Today's file has 5, 6, 7, 9,
10, 11, 13, 14, 18, 26, 40 scattered through `app.css`; snap them.

| Context | Value |
|---|---|
| Shell gutter / grid gap (`#app`, `#main`, `#dual`) | **12** (keep — the grid needs to breathe through here) |
| Panel inner padding | **16** |
| Overlay inner padding | **24** |
| Row vertical padding (list, table) | **8** (dense-comfortable at 13.5px body) |
| Row horizontal padding | **12** |
| List indent per level (cat → mark → row) | **0 / 16 / 32** (today: 10 / 26 / 40) |
| Icon-to-label gap | **8** |
| Chip/pill internal | **3 / 10** |
| Section stack gap | **16**; group gap **24** |

**Radii:** `--r-sm 8` (chips, mini buttons) · `--r-md 12` (buttons, inputs, rows) ·
`--r-lg 16` (panels, drawers, cards) · `--r-xl 20` (overlays) · `--r-full 999px` (pills, dots).
Today `9, 10, 11, 14` all appear — snap them.

**Hit targets:** every clickable ≥ 32px tall; `.mini` buttons go from `4/9` padding to
`6/10` with `min-height:30px`.

---

## 4. Glass panel spec

The constraint: the kinetic grid must remain *perceptible* behind the UI, but body text must
never sit on a moving substrate. The resolution is **tiered opacity by content type** plus a
1px inner highlight that gives the glass an edge without a glow.

```css
/* Tier 1 — chrome. Grid clearly visible through it. Labels only, no paragraphs. */
.glass-1 {
  background: var(--glass-1);                 /* rgba(13,17,22,.55) */
  backdrop-filter: blur(20px) saturate(118%);
  -webkit-backdrop-filter: blur(20px) saturate(118%);
  border: 1px solid var(--line-soft);         /* rgba(255,255,255,.07) */
  border-radius: var(--r-lg);                 /* 16px */
  box-shadow:
    inset 0 1px 0 var(--glass-hi),            /* rgba(255,255,255,.05) top edge */
    0 6px 20px rgba(0,0,0,.40);
}

/* Tier 2 — content. The default `.glass`. Grid reads as a slow shimmer, text is crisp. */
.glass, .glass-2 {
  background: var(--glass-2);                 /* rgba(11,14,18,.72) */
  backdrop-filter: blur(26px) saturate(112%);
  -webkit-backdrop-filter: blur(26px) saturate(112%);
  border: 1px solid var(--line-soft);
  border-radius: var(--r-lg);
  box-shadow:
    inset 0 1px 0 var(--glass-hi),
    0 16px 44px rgba(0,0,0,.52);
}

/* Tier 3 — overlays. Grid is a hint at the edges only. */
.glass-3 {
  background: var(--glass-3);                 /* rgba(8,10,13,.86) */
  backdrop-filter: blur(32px) saturate(108%);
  -webkit-backdrop-filter: blur(32px) saturate(108%);
  border: 1px solid var(--line-soft);
  border-radius: var(--r-xl);                 /* 20px */
  box-shadow: 0 32px 80px rgba(0,0,0,.62);
}
```

**Assignments in the current code:**

| Selector | Tier |
|---|---|
| `header`, `.pane-bar`, `#tabs`, `#layer-bar`, `#three-legend .chip` | `glass-1` |
| `#list-panel`, `#table-panel`, `.drawer`, `.pane` body, `.chat-card`, `.pm-card` | `glass-2` |
| `#bmwizard`, `#dashboard-react-root` overlay, `#pipe-modal` (if kept) | `glass-3` + `--scrim` backdrop |

**Rules that keep this from turning into soup:**

1. **Never nest glass in glass.** A card inside a `glass-2` panel uses a *solid* fill
   (`--panel-solid` / `--panel2`), not another blur. Stacked `backdrop-filter` is both the
   #1 perf cost and the #1 legibility killer. Current offender: `.pane-bar` (blur 10) sits
   inside `.pane.glass` (blur 16), and `#viewport`/`#three-wrap` add a *third* blur layer
   inside that. Collapse: the `.pane` keeps the glass, `#viewport` and `#three-wrap` become
   opaque `background: var(--bg-void)` — a drawing and a 3D scene should never have a
   translucent backing anyway, it reduces drawing contrast for zero gain.
2. **Max 3 stacked blur layers on screen at once**, and never on a scrolling container.
3. `backdrop-filter` creates a stacking context — the existing `header:has(#adv-menu[open])
   { z-index:70 }` hack exists precisely because of this. Keep the z-ladder documented:
   `0 canvas · 1 main · 50 header · 60 drawers · 70 header-with-popover · 80 modals · 90 popover · 100 toasts`.
4. **Contrast floor is measured against the lightest possible substrate.** The grid's brightest
   pixel is `--cy-500` at 80% alpha. Through `--glass-2` at .72 the effective panel background
   worst case is ≈ `#151A20`; `--paper` on that is 13.9 : 1 and `--dim` is 5.9 : 1. Both pass.
   Through `--glass-1` at .55 the worst case is ≈ `#1B242B`, where `--dim` drops to ~4.9 : 1 —
   still passing, but this is exactly why body text is banned from tier 1.
5. **Reduced motion:** `prefers-reduced-motion` already kills CSS animation globally in
   `tokens.css` and `kinetic-grid.js` stops the RAF loop. Add: when reduced, raise all glass
   alphas by `.10` (the grid is frozen, so translucency buys nothing).

---

## 5. Layout and navigation

### 5.1 The workflow, as five states

`PROJECT → UPLOAD/CONNECT → RUN → RESULTS → EVIDENCE → ASK`

Today this is spread across two pages, one full-screen overlay, one full-screen wizard and five
right-side drawers, with no visible sense of *where you are*. The fix is not more chrome — it is
**one persistent context strip and three views**.

### 5.2 Header — one line, three zones

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ [Livio]  Madera Ridge ▾   │  ● Model connected · Run 3f2a · 4m ago  │  [Ask] │
└──────────────────────────────────────────────────────────────────────────────┘
```

- **Left:** logo, then the project name as a dropdown (opens `ProjectManager`). One control,
  not two — `#btn-projects` and `#proj-name` merge.
- **Centre:** a *state strip*, not a stats string. Revit connection dot
  (`/api/revit/status`, already polled by `panels/revit_live.js`), run id + age
  (`/api/pipeline/status`), and a `Re-run` action that navigates to `/pipeline.html`.
  This replaces `#hdr-stats` entirely — the numbers move to the verdict bar (§5.3).
- **Right:** `Ask` (chat drawer) and a single overflow `⋯` for the advanced verbs.

The `⚙` popover contents get triaged: `Registration wizard`, `Compare with last run`,
`Find element in Revit` stay in the overflow. `① Extract elements` / `② Match to model`
**move to the pipeline page** (they are pipeline stages, and the pipeline page already runs
them with progress and AI narration — the header buttons are a worse duplicate that fires a
long POST with only a toast).

### 5.3 The RESULTS view — the heart

Three horizontal bands. Everything else on screen is subordinate to these.

```
┌─ VERDICT BAR ────────────────────────────────────────────────────────────────┐
│  ✓ 128 MATCH  │  ✕ 14 MISMATCH  │  ? 6 NEEDS REVIEW  │  – 41 N/A            │
│  ▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔  proportional bar, one row              │
└──────────────────────────────────────────────────────────────────────────────┘
┌─ ELEMENTS (360) ─┬─ EVIDENCE ─────────────────────────────────────────────────┐
│ ✕ Mismatch  14   │  ┌ DRAWING (58%) ────────┐ ┌ MODEL (42%) ───────────────┐ │
│   ▸ Hold-downs 9 │  │                        │ │                            │ │
│     HD3      ×4  │  │   PDF page + overlay   │ │   three.js scene           │ │
│     HD5      ×5  │  │                        │ │                            │ │
│   ▸ Shear walls 5│  └────────────────────────┘ └────────────────────────────┘ │
│ ? Needs review  6│                                                             │
│ ✓ Match       128│  ┌ WHY THIS VERDICT ─────────────────────────────────────┐ │
│ – N/A          41│  │  evidence block — §6.3                                │ │
└──────────────────┴──┴───────────────────────────────────────────────────────┴─┘
```

**Information hierarchy, top to bottom — this is the argument the screen makes:**

1. **How many, of what verdict** (verdict bar) — the CEO-demo number and the daily triage
   number are the same number. Source: `product_counts` from `GET /api/elements`, already
   emitted, currently unused. Each tile is a **filter toggle** writing a new
   `store.filters.product` key; `elements.ts:visibleElements()` gets one extra clause.
   Frontend-only.
2. **Which elements** (left rail) — regrouped **verdict → category → mark → instance**, replacing
   today's category → mark → instance. This is the single highest-value structural change:
   a reviewer opens the app and the first thing under their cursor is *the 14 things that are
   wrong*, not "Hold-downs (183)". `NOT_APPLICABLE` renders collapsed and dimmed by default —
   present for honesty, never in the way. `ElementList.tsx` change only.
3. **The proof** (evidence workspace) — drawing and model side by side, drawing wider because
   that is the document the engineer is being asked to trust. Both panes already sync to
   `store.select()`.
4. **The reasoning** (evidence block, always visible under the panes — *not* a drawer).
   The current Inspector is a right-side drawer that overlaps the 3D pane, and
   `panels/inspector.js` even toasts *"Inspector stays closed unless already open (it covers
   the 3D pane)"* — a design apologising for itself. Move it inline below the panes at
   ~180px, expandable to 50%. The drawer slot is then freed for `Ask` and `Review` only.

**Two secondary views**, switched by a segmented control in the verdict bar's right end:

| View | What it is | Existing code |
|---|---|---|
| **Evidence** (default) | the layout above | `#dual` + panels |
| **Table** | full-height results table, not the current 38vh bottom drawer | `#table-panel`, `ResultsTable.tsx` — change `max-height:38vh` to fill `#main` |
| **Review** | the needs-review queue as a full workspace, not a 480px drawer | `ReviewWorkspace.tsx` re-mounted into `#main` |

Same data, three densities. `Table` is what a QA engineer exports from; `Review` is what they
work through; `Evidence` is what they show someone.

### 5.4 The PIPELINE page

Structurally good already (`PipelineIsland`): centred card, vertical timeline, per-stage AI
narration, live SSE dot. Three changes:
- Adopt the unified tokens (§2) so it stops being Livio-blue while the dashboard is cyan.
- Widen `max-w-2xl` → `max-w-3xl`; at 7 stages the current column is a narrow strip in a wide dark void.
- On `status === "completed"`, render a **verdict bar preview** (same component as §5.3, fed by
  `GET /api/elements`) plus a primary `View results →` button. Right now a completed run
  dead-ends at a green checklist; the moment of payoff is on the wrong page.

### 5.5 Navigation contract

Three destinations, never more: **Results** (`/`), **Pipeline** (`/pipeline.html`),
**Projects** (overlay). Drawers reduce from five to two: `Ask` and `Review`.
`Runs comparison` and `Revit lookup` become sections inside the inline evidence block
(§6.3) — they are both "more detail about what I'm looking at", which is what that region is.

---

## 6. Component specs

### 6.1 Verdict badge — `<VerdictBadge verdict size />`

New file: `src/react/components/ui/VerdictBadge.tsx`. The one component that renders a verdict
anywhere. Nothing else is allowed to colour a verdict.

```
sm   [✓]                      18px round, glyph only, in list rows / dot bars
md   [✓ Match]                24px pill, glyph + label, table rows / inspector header
lg   [✓ Match      128]       tile with num-hero, verdict bar only
```

| Property | Value |
|---|---|
| Shape | `border-radius: var(--r-full)`; `sm` is a 18px circle |
| Fill | verdict colour at 12% (`--v-*-fill`) |
| Border | `1px solid` verdict colour at 34% |
| Text | verdict colour at 100%, `micro` (11/600/mono/uppercase/.08em) |
| Glyph | `✓ ✕ ? –` from the table in §2.4, always present, `aria-hidden` |
| Padding | `3px 10px` (`md`), `0` (`sm`) |
| `aria-label` | `"Location match"` / `"Location mismatch"` / `"Needs review"` / `"Not applicable"` |
| Interactive variant | only in the verdict bar; adds `cursor:pointer`, `:hover` border→100%, `[aria-pressed=true]` gets `box-shadow: 0 0 0 1px <verdict>` |
| Animation | none. Not on mount, not on change |

The `lg` tile additionally carries: `num-hero` count, `micro` label, and a 2px proportional
bar at its bottom edge in the verdict colour at 60%. Four tiles in one flex row, equal width.

**Source of truth:** `e.product.verdict`. Never derived in the frontend — `matching_engine.py`
docstring is explicit that this seam exists so no frontend file re-implements the mapping.

### 6.2 Results table row

Columns, in this order (today's order is `mark, category, sheet, status, distance_ft,
device_id, reason` — status is buried 4th and it is the *internal* status):

| # | Column | Width | Format |
|---|---|---|---|
| 1 | **Verdict** | 130px | `VerdictBadge md`. Sortable, sorts by verdict severity not alphabet |
| 2 | **Mark** | 90px | `body-strong`, mono |
| 3 | **Category** | 120px | `meta`, from `CAT_LABEL` — "Hold-downs" not `holdown` |
| 4 | **Sheet** | 90px | `num` mono |
| 5 | **Δ ft** | 80px, right | `num` mono, 2dp, `—` when null. Cell text goes `--v-mismatch` when the row is a mismatch **and** distance is the reason |
| 6 | **Why** | flex, min 280px | `evidence.reason`, one line, `text-overflow:ellipsis`, full text in `title` |
| 7 | **Evidence** | 180px | up to 2 chips: `resolved_by` (cyan outline chip, e.g. `via orientation`) and `evidence_conflict` (amber outline chip). Both already in `product.evidence` |
| 8 | **Revit** | 120px | `evidence.revit_ref.id`, mono, truncated, click-to-copy |

Row spec:

| State | Style |
|---|---|
| Base | `padding: 8px 12px`; `border-bottom: 1px solid var(--line)`; `td` colour `--txt-2` (up from `--dim` — today's table body is uniformly dim, which flattens it) |
| Hover | `background: rgba(255,255,255,.03)`; 120ms; **no transform** |
| Selected | `background: var(--cy-glow)`; `box-shadow: inset 3px 0 0 var(--cy-500)` (left accent bar, not a full border) |
| Verdict tint | `box-shadow: inset 2px 0 0 <verdict>` at rest for `MISMATCH`/`NEEDS_REVIEW` only — a 2px left rail so a scan down the table reads as a stripe pattern |
| Internal status | shown as a `micro` mono suffix under the Why text, `--dim`, e.g. `PDF_ONLY` — honesty without hierarchy |
| Header | sticky, `--panel-solid`, `micro`, `border-bottom: 1px solid var(--line-strong)` |
| Empty | `.empty-state` with the active filter named: *"No LOCATION_MISMATCH elements on A2.1."* |

Zebra striping: **no.** At 13.5px with a 1px rule and a verdict rail, striping is noise.

### 6.3 Evidence panel (inline, replaces the Inspector drawer)

The panel answers exactly one question — *why this verdict* — in four stacked blocks. Sources
are all in `product.evidence` (`internal_status, reason, distance_ft, confidence, revit_ref,
sheet, mark, category, resolved_by, evidence_conflict`) plus existing endpoints.

```
┌───────────────────────────────────────────────────────────────────────────┐
│  HD3        [✕ Mismatch]                       Sheet A2.1 · Hold-down     │  ← header
├───────────────────────────────────────────────────────────────────────────┤
│  The drawing places HD3 2.31 ft from the nearest modelled hold-down.       │  ← verdict sentence
│  Gate is 0.75 ft. Resolved by orientation. Confidence 0.82.                │
├──────────────────────┬────────────────────────────────────────────────────┤
│  DISTANCE   2.31 ft  │  REVIT REF   holdown_assembly · rev_asm_014  [copy] │  ← evidence grid
│  CONFIDENCE    0.82  │  INTERNAL    LOCATION_MISMATCH                      │
│  RESOLVED BY  orient │  CONFLICT    —                                      │
├───────────────────────────────────────────────────────────────────────────┤
│  [ Show in Revit ]  [ Nearest candidates (3) ▾ ]  [ Count consistency ▾ ]  │  ← actions
│  [ Compare with last run ▾ ]                                              │
└───────────────────────────────────────────────────────────────────────────┘
```

| Block | Spec | Existing source |
|---|---|---|
| Header | mark `section` + `VerdictBadge md` + `meta` breadcrumb `sheet · category` | `Inspector.tsx` `<h3>` |
| Verdict sentence | `body`, 2 lines max, plain English, numbers in mono. Composed from `reason` + `distance_ft` + `resolved_by` + `confidence` | `evidence.*` |
| Evidence grid | 2 columns, `micro` labels / `num`-or-`body` values, 8px row gap. Replaces the current 118px-label `.kv` list which is 11 rows tall | `Inspector.tsx` `.kv` |
| Actions | ghost buttons, 30px. `Show in Revit` reuses `panels/revit_live.js:showInRevitBtn` verbatim. Collapsibles for nearest candidates, count consistency, run comparison | `Inspector.tsx`, `CountConsistency`, `RunsComparison` |
| Empty | `micro` + hint icon, `--dim`, 24px pad: *"Select an element to see the evidence."* | current placeholder span |

The `LiveRevitId` "⟳ fetch live ID" flow (`GET /api/revit/element-ids/{id}`) keeps its four
states but restyles: idle = ghost button, loading = `Spinner` from `ui/status.tsx`,
success = mono id + copy, connector-off = `--dim` micro. No colour beyond `--v-*` and `--dim`.

**Review mode** (`NEEDS_REVIEW` / `LOCATION_MISMATCH` rows) adds a fifth block from
`ReviewWorkspace.tsx`: evidence crop (`/api/review/{id}/evidence.png`), AI analysis
(`/api/review/{id}/analysis`), and the disposition row. Disposition buttons become three equal
ghost buttons with a verdict-coloured left rail — **not** the current gradient-filled,
`scale(1.04)`-on-hover, infinitely-pulsing green/red pair.

### 6.4 Pipeline stage timeline

`PipelineTimeline.tsx` + `StepRow.tsx` are structurally right. Restyle only:

| Element | Now | Spec |
|---|---|---|
| Node | 24px ring, `ring-4 ring-card`, tailwind blue/emerald/rose | 22px ring; `pending` = `--line-strong` outline + `--dim` dot; `active` = `--cy-500` outline + `Spinner` in `--cy-400`; `success` = `--v-match` at 18% fill + `✓`; `error` = `--v-mismatch` at 18% + `!`; `skipped` = `--line` outline, 45% opacity |
| Connector | `w-px bg-border/60` | 1px `--line`; the segment **above the active node** fills `--cy-500` at 55% — a progress spine, the only place a gradient is allowed |
| Title | `text-sm` mixed weights | `section` (15/600) for active, `body` (13.5/400) `--txt-2` otherwise |
| Duration | `text-xs font-mono tabular-nums` | keep — `num` micro, `--dim`, right-aligned |
| Expanded body | `text-xs text-foreground/70` | `meta`; AI text in a `--panel2` card with a 2px `--cy-700` left rail |
| Technical details | mono block | keep, `--panel-solid`, `micro`. **Make the artifact filename a real link** to `/api/artifacts/{filename}` — `GET /api/artifacts/{filename}` exists (`routers/system.py:63`) and `STAGE_ARTIFACT` already carries the filename. Delete the "available when backend supports…" placeholder line, it is false |
| Enter animation | `animate-in fade-in slide-in-from-top-4 duration-500` | 200ms fade + 4px rise, staggered 40ms. 500ms with a 16px slide on seven rows is the most "demo-ware" moment in the app |

Stage titles come from `stage_graph.py` and are already human ("Reading drawings", "Aligning
coordinates", "Building the review queue") — do not touch them.

### 6.5 AI chat surface

`Chat.tsx` already renders three structured block types (`count_card`, `status_breakdown`,
`table`) plus `ui_actions` that drive selection/filtering/panel-opening. That is a genuinely
good agent surface; it just looks like a toy.

| Element | Spec |
|---|---|
| Container | Drawer at 420px, `glass-2`. Log is a flex column, gap 16 |
| User message | right-aligned, max 80%, `--panel2` fill, `1px solid var(--line)`, `--r-md`, 8/12 padding. **Kill the indigo `rgba(99,102,241,.18)`** — indigo is a fourth accent nobody declared |
| Agent message | left-aligned, max 88%, **no bubble** — plain `body` text on the drawer, with a 2px `--cy-700` left rail and 12px left padding. Removing the bubble is what makes it read as a colleague rather than a chatbot |
| Typing | three 5px `--dim` dots, existing `@keyframes ty`, keep |
| `count_card` | `--panel2`, `--r-lg`, 16px pad; `num-hero` in `--cy-300`; `micro` label; category breakdown as `meta` |
| `status_breakdown` | **rebuild on verdicts** — `VerdictBadge md` with counts, in the fixed order match / mismatch / needs review / N/A. Today it maps raw internal statuses through `COL`, which is where engine vocabulary leaks into the user's face most visibly |
| `table` block | same row spec as §6.2 at `meta` size; clickable rows already call `select(id)`; add a `--cy-glow` hover |
| Input row | full-width input, `--r-md`, `--panel-solid`, focus ring `2px var(--cy-ring)`; send is an icon button (`SendHorizontal` from lucide), not a filled "Send" |
| Suggested prompts | first-open only, 3 ghost chips using questions the backend actually answers — `"how many hold-downs?"`, `"show me the mismatches"`, `"why is HD3 flagged?"` |

---

## 7. Remove or simplify — opinionated

Ordered by how much clutter each removal buys.

### 7.1 Delete outright

1. **Every emoji in chrome.** `📁 ⚡ ▤ ⚠ 💬 ⚙ ⤢ 📏 ⛶ 🔎 ◎ ⚖ ☰ ✕ 🔴 🟢 🔧 🧠 🎉 ℹ 🤖 💬 ⇱ ①②`.
   Twenty-plus emoji across `index.html`, `ReviewWorkspace.tsx`, `Inspector.tsx`, `Chat.tsx`,
   `inspector.js`. They render differently per OS, they carry no semantic weight, and they are
   single-handedly what makes this read as a hobby project. `lucide-react` is **already a
   dependency** (used throughout `PipelineIsland`) — use it on both sides. This is the highest
   impact-per-hour change in the entire document.
2. **`@keyframes pulseG`** (`app.css`) — an infinitely pulsing green glow on the accept button.
3. **`.resolve-btn:hover { transform: scale(1.04) }`** and the gradient fills on
   `.resolve-accept` / `.resolve-reject`.
4. **`button:hover { transform: translateY(-1px) }`** (`components.css`) — global. Every button
   in the app bounces. Replace with a border-colour transition.
5. **`.brand` gradient-clipped text** (`app.css:52-55`) — dead CSS. The element's only child is
   `<img class="brand-logo">`; `background-clip:text` on it does nothing.
6. **`#pipe-modal` + `#pipe-inner` + `.pipe-head` + `.steplog`** — the vanilla pipeline modal.
   `#btn-pipe` navigates to `/pipeline.html`; this markup and ~30 lines of CSS are orphaned.
7. **`#three-note`** — *"Waiting for the model… · drag to orbit · click to select"*, 10px,
   permanent, low contrast. Show orbit hints once, on first hover, or not at all.
8. **The two disabled buttons in `PipelineIsland/index.tsx`** — `Stop` and `Report`, both
   `disabled title="not yet implemented"`. Dead buttons in a CEO demo are worse than absent
   ones. `Stop` → delete (no endpoint exists). `Report` → **wire it**, don't delete:
   `GET /api/export/punch-list.csv` exists (`routers/elements.py:463`).
9. **The `Force` button** in the pipeline header → move into an overflow. A destructive-ish
   re-run should not sit next to the primary action at equal weight.
10. **`Debug: raw SSE events`** — gate behind `?debug=1`. It is currently always visible under
    the timeline.
11. **The `"artifact viewer: available when backend supports GET /api/artifacts/{key}"`** line
    in `StepRow.tsx` — the endpoint exists. Replace with the link (§6.4).

### 7.2 Merge / demote

12. **Two token systems → one.** `src/react/index.css`'s `@theme` block redefines the entire
    palette in Livio blue/green. Make it *alias* `tokens.css` (`--color-primary: var(--cy-500)`
    etc.) and import `tokens.css` from both entry points. Today the dashboard and the pipeline
    are visibly different products.
13. **`#hdr-stats`** → the verdict bar. The string *"N elements · N verified · N flagged"* is
    doing the verdict bar's job with a third vocabulary ("verified"/"flagged" appears nowhere
    else in the codebase), and `app.js:loadAll()` even carries a comment apologising for the
    two different numbers under similar labels.
14. **Model pane header: 5 buttons + a chip → 2 buttons + the chip.** `Top view` and
    `Reset view` collapse into `Reset view`; `Shear walls only` moves into the layers popover
    next to the other visibility toggles (it *is* a visibility toggle);
    `⟳ Refresh from Revit` stays; `⤢` stays.
15. **Drawing pane header: 4 buttons → 2 + overflow.** `Fit` and `Expand` stay; `Measure` and
    `Show/hide layers` go into a `⋯`.
16. **Five drawers → two.** `Ask` and `Review` keep the right slot. `Inspector` goes inline
    (§5.3), `Runs comparison` and `Revit lookup` become collapsibles inside it. This also
    deletes most of the `openDrawer()` juggling in `panels/inspector.js`.
17. **`⚙` popover `① Extract elements` / `② Match to model`** → move to the pipeline page.
    They fire multi-minute POSTs (`/api/elements/extract`, `/api/elements/match`) whose only
    feedback is a toast, while the pipeline page runs the same work with a live timeline.
18. **`VerdictRing`** on project cards: 9 internal-status segments → 4 verdict segments.
    Nine colours in a 56px donut is a pie chart of noise. **`[BACKEND]`** — needs
    `product_counts` on `/api/projects` (§8).
19. **`.dot` bars in `ElementList`** — same change, 10 statuses → 4 verdicts.
20. **Sub-11px type** — the eleven offenders listed in §3.1.
21. **`font-weight: 700/800`** outside Big Shoulders headings — five offenders in §3.1.

### 7.3 Keep, explicitly

The kinetic grid (retuned to cyan), the pipeline timeline structure, the chat block types, the
element-list tri-level grouping (regrouped, not removed), the PDF overlay isolation mode, the
glyph-per-verdict accessibility pattern, `prefers-reduced-motion` handling, focus management in
`openDrawer()`, and the "never fake coordinates" toasts in `panels/inspector.js`. Those are all
good, considered work.

---

## 8. Prioritized implementation list

Cheapest × highest-impact first. P0 is a one-day path to a demo that looks like a different
product. Nothing in P0 or P1 touches the backend.

### P0 — do these first (≈ 1 day, no backend)

| # | Task | Files | Why it's cheap |
|---|---|---|---|
| 1 | **Unify tokens + cyan ramp** | `tokens.css`, `react/index.css` | Add ~14 vars, realias `--signal`/`--accent`/`--color-primary`. Every existing rule inherits |
| 2 | **Retune both kinetic grids to cyan** | `kinetic-grid.js:22`, `KineticGrid.tsx` | 3 constants each |
| 3 | **Motion diet** | `components.css`, `app.css` | Delete `pulseG`, `:hover{translateY}`, `scale(1.04)`, gradient resolve buttons. Pure deletion |
| 4 | **Emoji → lucide** | `index.html`, `ReviewWorkspace.tsx`, `Inspector.tsx`, `Chat.tsx` | `lucide-react` already installed. Biggest perceived-quality jump per hour |
| 5 | **`VerdictBadge` component** | new `ui/VerdictBadge.tsx` | ~40 lines. Unblocks 6, 7, 8 |
| 6 | **Verdict bar from `product_counts`** | new component + `app.js:loadAll()` | Data already on the wire, unused. This is *the* demo moment |
| 7 | **Verdict in list rows + table rows** | `ElementList.tsx`, `ResultsTable.tsx` | Read `e.product.verdict`, swap the pill for `VerdictBadge` |
| 8 | **Verdict-first grouping in the left rail** | `ElementList.tsx` | One extra grouping level; the component already groups twice |
| 9 | **Glass tiers** | `components.css`, `app.css` | Three classes; reassign ~10 selectors. Kill nested blur on `#viewport`/`#three-wrap` |
| 10 | **Type floor + weight diet** | `app.css`, `components.css` | Mechanical find/replace on 11 sizes and 5 weights |
| 11 | **Delete dead UI** | `index.html`, `app.css`, `PipelineIsland/index.tsx`, `StepRow.tsx` | §7.1 items 5–11. Pure deletion; ~90 lines gone |
| 12 | **Wire `Report` → punch-list CSV; artifact filename → link** | `PipelineIsland/index.tsx`, `StepRow.tsx` | Both endpoints exist. Turns two lies into two features |

### P1 — the layout (≈ 1–2 days, no backend)

| # | Task | Files |
|---|---|---|
| 13 | Header rebuild: 3 zones, project dropdown, state strip, overflow | `index.html`, `app.js`, `app.css` |
| 14 | Inspector drawer → inline evidence panel under the panes | `index.html`, `app.css`, `Inspector.tsx`, `panels/inspector.js` |
| 15 | Evidence panel restructure per §6.3 (verdict sentence + 2-col evidence grid) | `Inspector.tsx` |
| 16 | Results table: full-height view, new column order, verdict rail | `app.css`, `ResultsTable.tsx`, `panels/table.js` |
| 17 | View switcher: Evidence / Table / Review | `index.html`, `app.js` |
| 18 | Verdict-tile click → `store.filters.product` filter | `store.js`, `elements.ts`, verdict bar |
| 19 | Pane header decluttering (§7.2 items 14–15) | `index.html`, `pdf.js`, `viewer3d.js` |
| 20 | Drawer consolidation 5 → 2 | `panels/inspector.js`, `index.html` |

### P2 — polish (≈ 1 day, no backend)

| # | Task | Files |
|---|---|---|
| 21 | Pipeline timeline restyle + progress spine + `max-w-3xl` | `StepRow.tsx`, `PipelineTimeline.tsx` |
| 22 | Verdict-bar preview + `View results →` on pipeline completion | `PipelineIsland/index.tsx` |
| 23 | Chat surface restyle: rail not bubble, verdict-based `status_breakdown`, suggested prompts | `Chat.tsx` |
| 24 | Review disposition buttons restyle (ghost + verdict rail) | `ReviewWorkspace.tsx` |
| 25 | Empty/error/loading states across all panels using the one `.skeleton` + `.empty-state` pattern | `components.css`, all features |
| 26 | Focus rings: `2px var(--cy-ring)` on every interactive element | `components.css` |

### P3 — **`[BACKEND]`** — flagged, cut if time is short

| # | Task | Change | Blocks |
|---|---|---|---|
| B1 | `product_counts` on project cards | `routers/projects.py` — include `product_counts` in the project summary payload alongside `counts` | §7.2 item 18 (4-segment `VerdictRing`). Until then, the ring keeps 9 internal segments — visually inconsistent with the rest but not wrong |
| B2 | Review queue on product vocabulary | `review.py:28` `REVIEW_STATUSES = ("LOCATION_MISMATCH","NEEDS_REVIEW")` is *internal* statuses. Product `NEEDS_REVIEW` is a strictly different set (it excludes `PDF_ONLY`/`REVIT_ONLY`, which are product mismatches). Splitting into a **Findings** queue (product mismatch) and a **Review** queue (product needs-review) needs `build_queue()` to read `product_verdict()` | A clean "Needs review (N)" header count. Workaround: compute both counts client-side from `product_counts` and leave `/api/review/queue` as the detail source |
| B3 | `product` column in the punch list | `routers/elements.py:463` — add `product_verdict` as column 4; its skip set (`MATCH, SPEC_ONLY, NOT_EVALUATED`) also doesn't align with `NOT_APPLICABLE` | Export matching what's on screen. ~5 lines |
| B4 | Stop a running pipeline | No endpoint exists | The `Stop` button. **Recommendation: don't build it for the demo — delete the button** |
| B5 | Per-verdict server-side filtering on `/api/elements` | Not needed at current volumes (a few hundred rows) — client-side filter in `elements.ts` is correct | Nothing. Listed only so nobody builds it |

---

## Appendix — verification of every claim about existing functionality

| Claim | Evidence |
|---|---|
| Backend emits `product` per element | `element_registry.py:268` |
| Backend emits `product_counts` | `element_registry.py:275` → `matching_engine.py:914` |
| Four verdicts + evidence fields | `matching_engine.py:835-838`, `900-910` |
| Frontend uses none of it | `grep -rn "product" frontend/src` → comments only |
| `lucide-react` available | imported in `PipelineIsland/{index,StepRow,PipelineTimeline}.tsx`, `ui/status.tsx` |
| Punch-list CSV exists | `routers/elements.py:463` |
| Artifact download exists | `routers/system.py:63` |
| No stop-run endpoint | absent from the full route list in `routers/*.py` |
| Review queue uses internal statuses | `review.py:28` |
| Pipeline modal is orphaned | `app.js` `#btn-pipe` → `window.location.href = "/pipeline.html"` |
| Two token systems | `tokens.css` `--signal:#5EEAD4` vs `react/index.css` `--color-primary:#06adf5`; `dashboard-main.tsx` header comment states the non-import is deliberate |
| Nested blur layers | `.glass`(16) → `.pane-bar`(10) → `#viewport`/`#three-wrap`(10) |
| Grid must stay visible | `kinetic-grid.js` header comment: *"panels show through as a subtle live layer"* |
