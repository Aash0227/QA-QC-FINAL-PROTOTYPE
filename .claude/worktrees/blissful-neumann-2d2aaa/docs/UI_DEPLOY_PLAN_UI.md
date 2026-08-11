# UI Declutter Plan — the "Sagar view"

*Research + plan only. No code written. Target: one non-technical QA-QC reviewer
(Sagar) at Livio, shipping today. Constraint: vanilla ES modules, no build step,
GSAP 3.12.5 already loaded globally (index.html:10). No React, no Framer Motion,
no new dependencies.*

**Scope discipline:** this is a targeted declutter, not a redesign. The token
system (`src/tokens.css`), the glass panel treatment, the 3-pane grid, and the
status color legend all stay exactly as they are. What changes is **what is
visible by default** and **what the labels say**.

---

## 0. The one-line diagnosis

The app is not ugly — it is *addressed to a developer*. The header exposes nine
top-level verbs, three of which are pipeline internals (`Extract`, `Match`,
`Autopilot`); the pipeline modal narrates artifact filenames
(`AIConvert_revit.json`, `element_intelligence.json`); the 3D pane prints
truncation telemetry (`capped: walls 5000/28000`); the review drawer has a
button that copies a prompt for a Claude session. Sagar needs four verbs:
**open the project → see what's flagged → judge it → export the punch list.**

Everything else is either advanced or dev clutter.

---

## 1. Current-state inventory

Verdicts: **KEEP** (core review) · **RELABEL** (plain words, same place) ·
**DEMOTE** (still reachable, moved behind ⚙ Advanced / a disclosure) ·
**REMOVE** (deleted from the UI).

### 1a. Header (`frontend/index.html:26–55`)

| # | Control | file:line | Verdict | New label / location |
|---|---------|-----------|---------|----------------------|
| 1 | `#btn-left` ☰ list toggle | index.html:29 | KEEP | title → "Show/hide the element list" |
| 2 | `.brand` wordmark | index.html:30 | KEEP | unchanged |
| 3 | `.brand small` "multi-element · generalized · no fake matches" | index.html:30 | REMOVE | engineering boast, not a subtitle for a reviewer |
| 4 | `#proj-switch` project select | index.html:31–32 | KEEP | move inline styles into a `.hzone select` CSS rule (5 declarations sitting in HTML) |
| 5 | `Stats` hzlabel | index.html:35 | REMOVE | the badge speaks for itself once reworded |
| 6 | `#hdr-stats` badge | index.html:36, written app.js:47–49 | RELABEL | `342 elements · 106 verified · 12 need review` (see §1f for the test that asserts on this string) |
| 7 | `#btn-pipe` "▶ Pipeline" | index.html:39 | RELABEL | **"▶ Run the check"** — primary-adjacent, stays top level |
| 8 | `#btn-extract` "① Extract" | index.html:40, wired app.js:85 | DEMOTE | into ⚙ Advanced. Already runnable as pipeline step 6 (app.js:128) |
| 9 | `#btn-match` "② Match" | index.html:41, wired app.js:86 | DEMOTE | into ⚙ Advanced. Already pipeline step 8 (app.js:134) |
| 10 | `Pipeline` / `Views` / `AI` hzlabels | index.html:38,44,52 | REMOVE | three zone labels for six buttons is scaffolding; also fails contrast (see §3) |
| 11 | `#btn-table` "▤ Table" | index.html:45 | RELABEL | **"▤ All results"** |
| 12 | `#btn-autopilot` "◎ Autopilot" | index.html:46, wired wizard.js:312 | **DEMOTE (founder ask #1)** | out of the header entirely. Entry points become: the auto-benchmark banner's **"Review / Edit"** (wizard.js:290 already does `$("#btn-autopilot").click()`) + ⚙ Advanced |
| 13 | `#btn-runs` "⚖ Runs" | index.html:47, wired inspector.js:33 | DEMOTE | ⚙ Advanced → **"Compare with the last run"** |
| 14 | `#btn-review` "⚠ Review" + `#rev-count` | index.html:48, wired inspector.js:34 | **KEEP + PROMOTE** | becomes the header's `.primary` button: **"⚠ Needs review (12)"**. This is Sagar's job. |
| 15 | `#btn-revit-lookup` "🔎 Revit ID" | index.html:49, wired inspector.js:35 | DEMOTE | ⚙ Advanced → **"Find an element in Revit"** |
| 16 | `#btn-chat` "💬 Chat" | index.html:53, wired inspector.js:32 | KEEP + RELABEL | **"💬 Ask"**. *Verdict on the founder's question mark:* keep it top-level. It is the only control that answers a question in the reviewer's own words ("how many holdowns?") and it is where teaching happens. Removing it removes the app's friendliest surface. |
| 17 | *(new)* `#adv-menu` ⚙ Advanced | — | ADD | native `<details>` popover holding #8, #9, #12, #13, #15 |

### 1b. Drawing (PDF) pane (`index.html:72–89`)

| Control | file:line | Verdict | New label |
|---|---|---|---|
| `.title` "DRAWING · PDF" | index.html:74 | RELABEL | "DRAWING" |
| `#tabs` sheet tabs | index.html:75, pdf.js:14 | KEEP | — |
| `#btn-measure` 📏 | index.html:77, pdf.js:127 | KEEP | title → "Measure between two points" |
| `#btn-fit` ⛶ | index.html:78 | KEEP | title → "Fit the sheet to the pane" |
| `#btn-layers` "Layers" | index.html:79 | RELABEL | **"Show / hide"** |
| `#btn-sheet-max` ⤢ | index.html:80 | KEEP | — |
| `#layer-bar` chips + `#opacity` | index.html:82–85, pdf.js:173 | KEEP | already collapsed by default |

### 1c. 3D pane (`index.html:91–107`)

| Control | file:line | Verdict | New label |
|---|---|---|---|
| `.title` "REVIT MODEL · 3D" | index.html:93 | RELABEL | "3D MODEL" |
| `#three-live-badge` SNAPSHOT/LIVE | index.html:94, viewer3d.js:339–344 | **KEEP** | trust signal — never hide. Copy → `LIVE · Madera.rvt` / `SNAPSHOT · last export` |
| `#btn-3d-live` "⟳ live" | index.html:96, viewer3d.js:420 | RELABEL | **"⟳ Refresh from Revit"** |
| `#btn-sw-only` "SW only" | index.html:97, viewer3d.js:426 | RELABEL | **"Shear walls only"** (jargon acronym) |
| `#btn-top` "Top view" | index.html:98 | KEEP | — |
| `#btn-3d-reset` "Reset" | index.html:99 | RELABEL | "Reset view" |
| `#btn-model-max` ⤢ | index.html:100 | KEEP | — |
| `#three-note` idle copy | index.html:105 | RELABEL | "Waiting for the model… · drag to orbit · click to select" |
| `#three-note` live telemetry — `capped: walls 5000/28000`, `N connections matched to this project's registry` | viewer3d.js:347–359 | **DEMOTE** | move the `capped:` line and `status_joined` count into the element's `title=` tooltip. **Keep visible:** "bounding-box massing — not exact geometry" (honesty claim) and the `wall height ASSUMED …` warning (viewer3d.js:358) |
| `#three-legend` status chips | index.html:104, viewer3d.js:331 | KEEP | — |

### 1d. Results table (`index.html:111–132`)

| Control | file:line | Verdict | New label |
|---|---|---|---|
| `.title` "RESULTS TABLE" | index.html:113 | KEEP | — |
| `#scope-banner` export-scope warning | index.html:117, table.js:11–27 | **KEEP** | honesty guard-rail (R-07). Untouched. |
| `th[data-k="device_id"]` "Device" column | index.html:126, table.js:55 | DEMOTE | internal ids (`dev_h2_3`) — hide behind a "Show technical columns" checkbox in the pane bar (P2) |
| `status_detail` second pill | table.js:51–53 | KEEP | it explains *why* a REVIT_ONLY happened |
| other columns | index.html:121–127 | KEEP | — |

### 1e. Drawers

| Control | file:line | Verdict | New label / location |
|---|---|---|---|
| `#inspector` header "Evidence Inspector" | index.html:155 | RELABEL | **"Element details"** |
| `#chat` header "💬 QA-QC Copilot" | index.html:165 | RELABEL | **"💬 Ask about this project"** |
| `#chat` badge "asks the data · acts on the UI" | index.html:165 | REMOVE | describes the implementation, not the feature |
| `#chat-input` placeholder | index.html:171 | KEEP | good — it teaches by example |
| `#runs` drawer | index.html:177–185 | KEEP (demoted entry) | header → "Compare with the last run" |
| `#runs-save-baseline` | index.html:180 | KEEP | title → "Freeze today's results as the reference for future runs" |
| `#review` drawer | index.html:188–222 | **KEEP — this is the product** | header → "⚠ Needs review" |
| `[data-disp]` disposition buttons | index.html:208–210 | KEEP | — |
| `#rev-investigate` "🔍 Investigate" | index.html:211, inspector.js:235–259 | **REMOVE** | copies a 20-line prompt for "a Claude session with the Revit MCP connected"; the `title` cites `docs/REVIT_MCP_EVALUATION.md`. Pure developer affordance. |
| `#rev-comment` thread | index.html:213–219 | KEEP | the teach loop |
| `#revitlookup` drawer | index.html:225–238 | KEEP (demoted entry) | header → "Find an element in Revit" |
| `#rl-selection` "⇱ Use current Revit selection" | index.html:233 | KEEP | genuinely useful to a reviewer sitting in Revit |

### 1f. Pipeline modal (`index.html:241–252` + `app.js:106–271`)

| Control | file:line | Verdict | New label / location |
|---|---|---|---|
| `h2` "How the QA-QC pipeline works" | index.html:244 | RELABEL | **"Run the check"** |
| badge "plain-English · anyone can run it" | index.html:246 | REMOVE | self-congratulation |
| `#btn-run-all` "▶ Run full pipeline" | index.html:247 | RELABEL | **"▶ Run everything"** (stays `.primary`) |
| **Upload card** `#up-pdf` / `#up-revit` / `#btn-upload` | app.js:209–212 | **REWORK (founder ask #2)** | see §2 |
| Step titles "1 · AI Revit Convert", "3 · AI PDF Convert", "4 · RANSAC Calibration" | app.js:110,116,119 | RELABEL | "1 · Read the Revit model", "3 · Line up the drawing data", "4 · Auto-align drawing to model" |
| `s.produces` artifact filenames (10×) | app.js:112,115,118,121,124,127,130,133,136,139 + rendered app.js:206 | DEMOTE | wrap the `→ produces` line in the advanced disclosure |
| `[data-runstep]` "Run this step" (7×) | app.js:208 | DEMOTE | advanced disclosure |
| `.steplog` live event log | app.js:224, css app.css:164 | DEMOTE | advanced disclosure — but `.resultstrip` (app.js:225) **stays visible**: that's the plain-English outcome |
| 4b benchmark buttons "1 · Extract PDF stamps" / "2 · Calibrate from benchmarks" | app.js:216–217 | DEMOTE | advanced disclosure (auto-benchmark handles this now) |
| step 7 "Chat / Teach (optional)" + `data-open-teach` | app.js:131, 213 | KEEP | — |
| exports: "⬇ Punch list CSV" | app.js:220 | **KEEP — promote** | this is the deliverable; make it `.primary` |
| exports: "⬇ element_list.json" | app.js:221 | **REMOVE** | raw pipeline artifact |
| exports: "⬇ Review PNG" | app.js:222 | KEEP | RELABEL "⬇ Marked-up drawing (PNG)" |

### 1g. Benchmark Autopilot wizard (`index.html:136–151` + `wizard.js`)

Whole surface: **DEMOTE, do not delete.** The DOM node `#bmwizard` and every id
inside it stay exactly where they are — only the header entry point disappears.

| Control | file:line | Verdict | Note |
|---|---|---|---|
| `#bm-banner` auto-benchmark approval banner | wizard.js:270–291 | **KEEP — this becomes the only default-visible benchmark surface** | copy tweak only; see §1h |
| `#bmb-approve` "✓ Approve" | wizard.js:286 | KEEP | — |
| `#bmb-review` "Review / Edit" | wizard.js:287 | **KEEP — this is the wizard's new front door** | RELABEL "Review the points" |
| `.bw-kicker` "Benchmark Autopilot · 2-point registration" | index.html:141 | KEEP | it is an advanced screen now; jargon is appropriate |
| `h1` "Zero-Click Registration" | index.html:142 | KEEP | — |
| `#bm-log` live log | index.html:147 | KEEP | advanced screen |

### 1h. Banner copy

Current (wizard.js:283–285): *"Auto-proposed 2 benchmark registration points at
**A-3** & **F-12** (max diagonal). Approve to continue."*

Proposed: *"The system picked two reference points on this sheet — **A-3** and
**F-12** — to line the drawing up with the Revit model. Approve to continue."*

⚠ `frontend/tests/smoke.spec.js:85` asserts the banner contains
`"Approve to continue"` — the proposed copy preserves that exact phrase, so the
test stays green. **Do not drop those three words.**

---

## 2. The upload card, PDF-only (founder ask #2)

Today, `app.js:209–212` renders two file inputs side by side, giving equal
billing to "PDF" and "Revit JSON". A live-fetch pipeline is being planned by
another agent; the UI side is:

```
┌─ 📁 Open a project ─────────────────────────────────────────┐
│                                                             │
│   Drawing set                                               │
│   [ Choose PDF… ]  Madera_Structural.pdf   [ Upload ]       │
│                                                             │
│   Revit model                                               │
│   ● Connected · Madera.rvt              [ Check again ]     │
│   ○ Not connected — open Revit and turn on the              │
│     Nonica A.I. Connector               [ Check again ]     │
│                                                             │
│   ▸ Advanced: upload a Revit export JSON instead            │
│     └ [ Choose JSON… ]                                      │
└─────────────────────────────────────────────────────────────┘
```

Implementation notes (no code here, just the seams):

- The two file inputs collapse to one visible input (`#up-pdf`). `#up-revit`
  **stays in the DOM**, moved inside a native `<details>` — so `app.js:261`
  (`$("#up-revit").files[0]`) and the `FormData` contract at app.js:264 are
  unchanged, and the backend `/api/upload` needs no edit.
- The connection pill reuses the already-cached status helper in
  `revit_live.js:20–27` (`connStatus()`, 15 s cache). Export it and render the
  same three states the wizard pill already renders
  (`wizard.js:240–257`, class `.bw-revit-status` with `.on` / `.off`) — same
  visual language in both places, zero new CSS.
- Offline copy is already written once, in `revit_live.js:12`
  (`OFFLINE_HINT`). Reuse the constant; do not write a second sentence.
- Rate limiting matters: `/api/revit/status` spawns the Nonica exe. The wizard
  already debounces it to 12 s (`wizard.js:259`). The upload card must go
  through the same cached helper, never a raw `api("/api/revit/status")`.

---

## 3. Target layout — the "Sagar view"

```
╔═══════════════════════════════════════════════════════════════════════════╗
║ ☰  LIVIO QA-QC INTELLIGENCE   [Madera ▾]  │  342 elements · 106 verified   ║
║                                           │  · 12 need review              ║
║                            [▶ Run the check] [▤ All results]              ║
║                            [⚠ NEEDS REVIEW (12)] [💬 Ask]  [⚙]            ║
╚═══════════════════════════════════════════════════════════════════════════╝
  ┌ (banner, only when a benchmark is pending) ───────────────────────────┐
  │ The system picked two reference points… [✓ Approve] [Review the points]│
  └───────────────────────────────────────────────────────────────────────┘
┌──────────────┬──────────────────────────┬─────────────────────────────────┐
│ ELEMENTS     │ DRAWING                  │ 3D MODEL     [LIVE · Madera.rvt] │
│ [search    ] │ S-201 S-202 …  📏 ⛶      │  ⟳ Refresh from Revit           │
│ [status][sht]│  Show/hide  ⤢            │  Shear walls only · Top · Reset │
│              │                          │                                 │
│ ▾ Hold-downs │      (pan/zoom sheet)    │       (orbit 3D scene)          │
│   ▾ H2  (14) │                          │                                 │
│     ● S-201  │                          │                                 │
│     ● S-201  │                          │  ● MATCH ● MISMATCH ● …         │
│ ▸ Shear walls│                          │  bounding-box massing           │
└──────────────┴──────────────────────────┴─────────────────────────────────┘
┌ ALL RESULTS (toggled) ────────────────────────────────────────────── ✕ ────┐
│ ⚠ Export scope: …                                                          │
│ Mark │ Category │ Sheet │ Status │ Distance (ft) │ Reason                   │
└────────────────────────────────────────────────────────────────────────────┘

⚙ Advanced  (native <details> popover, anchored right)
   ├ ① Extract elements          (#btn-extract)
   ├ ② Match to model            (#btn-match)
   ├ ◎ Registration wizard       (#btn-autopilot)
   ├ ⚖ Compare with the last run (#btn-runs)
   └ 🔎 Find an element in Revit (#btn-revit-lookup)
```

**Header goes from 9 visible verbs to 5** (Run the check · All results · Needs
review · Ask · ⚙). One primary CTA per screen — `Needs review` — per the
`primary-action` rule. The 3-pane body, drawers, and pipeline modal keep their
current geometry; only labels and default-visibility change.

**Drawers** are unchanged structurally: same right-slot, same
one-at-a-time manager (`inspector.js:16–27`), same `.drawer.open` transform.

---

## 4. Design tokens — what changes (almost nothing)

The existing system in `frontend/src/tokens.css` is already coherent and is
**not** being restyled. For the record, what exists today:

| Token | Value | Role |
|---|---|---|
| `--ink` | `#0B0D10` | app background |
| `--panel-solid` / `--panel2` | `#14171C` / `#191D24` | opaque surfaces |
| `--panel` | `rgba(20,23,28,.82)` | the glass treatment |
| `--line` | `#262B33` | borders, dividers |
| `--paper` / `--txt` | `#ECE9E1` | primary text |
| `--dim` | `#9AA0A6` | secondary text |
| `--signal` / `--accent` | `#5EEAD4` | accent, focus, primary buttons |
| `--markup` | `#FF5A36` | corrections / destructive |
| `--match` / `--revitonly` | `#22c55e` / `#ef4444` | status semantics |
| `--bw-*` (8) | aliases → the above | wizard-scope names (BUG-12 dedup) |
| `--font-body` / `--font-display` / `--font-mono` | IBM Plex Sans / Big Shoulders / IBM Plex Mono | type |

### Additions — 4 variables, one media query. That is the whole spec.

```
--warn: #fbbf24;          /* already hardcoded 5×: inspector.js:178, table.js:18,
                             app.css (scope banner), wizard bw-unverified */
--dur-fast: .14s;         /* press / hover feedback */
--dur:      .24s;         /* enter: drawers, banners, cards */
--dur-exit: .16s;         /* exit ≈ 65% of enter (motion-ui: exit-faster-than-enter) */
--ease:     cubic-bezier(.22,1,.36,1);   /* the value app.css:109 already uses */
```

Nothing else moves. Specifically **do not** introduce a spacing scale or a new
type scale — the current 8/10/12/14 px rhythm is consistent enough and touching
it would blow the time box.

### Two contrast defects found (fix, don't redesign)

1. `.hzlabel` — `app.css:35–36` sets `color:var(--dim); opacity:.65` at 8.5 px.
   Effective foreground ≈ `#6A6E73` on `#0B0D10` ≈ **3.1:1** — below the 4.5:1
   floor for text this size. Resolved for free: those labels are being removed
   (§1a #5, #10). Any survivor must drop the `opacity:.65`.
2. No `prefers-reduced-motion` handling exists anywhere in the codebase —
   `app.css` runs 12 keyframe animations including three infinite loops
   (`pulseG` app.css:121, `bwLock` app.css:253, `pulse` app.css:96). One global
   block in `tokens.css` fixes it:
   `@media (prefers-reduced-motion: reduce){ *,*::before,*::after{ animation-duration:.01ms!important; animation-iteration-count:1!important; transition-duration:.01ms!important } }`
   GSAP tweens are separately gated with one `gsap.globalTimeline.timeScale()`
   guard, or by checking `matchMedia("(prefers-reduced-motion: reduce)").matches`
   before the decorative tweens (`viewer3d.js:248` wall rise,
   `viewer3d.js:268–271` info-ball). Camera flights are *functional* motion and
   should be made instant rather than removed.

---

## 5. Motion plan — 6 micro-interactions, no new dependency

Mechanism is CSS transition wherever the property is `transform`/`opacity`;
GSAP only where a tween already exists or an element needs a one-shot on a
value change. **Motion One / `motion` ESM is not needed and should not be
added** — GSAP is loaded on every page already (index.html:10).

| # | Interaction | Mechanism | Timing | Status |
|---|---|---|---|---|
| M1 | **Drawer slide-in** (`.drawer` → `.drawer.open`) | CSS transition, already at `app.css:107–110` | retune enter `.35s → var(--dur)` (.24s); add a shorter exit by splitting the rule so the closed state uses `var(--dur-exit)`. Ease unchanged (`--ease`). | **exists — tune only** |
| M2 | **Approval banner enter** (`#bm-banner`, wizard.js:276–282) | CSS — the node already gets `class="glass"`, which fires `panelIn` (`components.css:20–21`) | retune `panelIn` `.5s → var(--dur)`, keep `translateY(6px)→0` + fade, `ease-out` | **exists — tune only** |
| M3 | **Toast in / out** | GSAP, already at `util.js:13–14` | leave alone; optionally trim the 4600 ms hold to 4000 ms (motion-ui: 3–5 s auto-dismiss) | **exists — leave** |
| M4 | **Review-count bump** — `#rev-count` when the number changes (inspector.js:169, 311) | GSAP one-shot: `gsap.fromTo(el,{scale:1.35},{scale:1,duration:.35,ease:"back.out(2)"})` | .35s, `back.out(2)` | **new, 1 line** |
| M5 | **3D source badge swap** SNAPSHOT → LIVE (viewer3d.js:339–344) | GSAP crossfade on the badge when the text actually changes | `.28s`, `power2.out`, `y:-4→0` + fade | **new, 3 lines** |
| M6 | **Row select feedback** (`.row.selected`, app.css:68) | CSS — extend the existing `transition:background .12s` (app.css:66) to include `border-color` and add `transform:scale(.995)` on `:active` | `var(--dur-fast)` | **new, 2 declarations** |
| M7 | **⚙ Advanced disclosure** | Native `<details>` — no animation. Rung 4 of the ladder: the platform already does this, and an animated height is the classic layout-thrash bug. | — | **none** |

Rules honored: transform/opacity only (never width/height/top/left); enter
`.24s` / exit `.16s`; one global `prefers-reduced-motion` kill-switch (§4);
no animation blocks input; the pipeline `pulseIc` (app.css:171) and PDF
`pulse-ring` (app.css:95) stay — both communicate live state.

**Explicitly rejected:** staggered list entrance for `#list-rows` (hundreds of
rows, would feel slow and adds a re-render cost on every filter keystroke);
shared-element transitions between panes (the GSAP `flyToPoint` camera move at
pdf.js:96 already provides spatial continuity).

---

## 6. Phased task list

### P1 — must ship today (~2–4 h)

| # | Task | Files | Risk |
|---|---|---|---|
| P1-1 | **Header restructure.** Move `#btn-extract`, `#btn-match`, `#btn-autopilot`, `#btn-runs`, `#btn-revit-lookup` into a `<details id="adv-menu">` popover. Promote `#btn-review` to `.primary`. Delete the three `.hzlabel` spans and `.brand small`. | `index.html:26–55`, `app.css:30–44` | **HIGH — see §7.1.** Every id must remain in the DOM. |
| P1-2 | **⚙ menu CSS.** ~12 lines: `#adv-menu{position:relative}`, `summary` styled as a `.mini` button, `#adv-menu[open] .adv-list{…}` absolutely positioned panel, `z-index` above the header. Click-outside-to-close via one `document` listener. | `app.css` | low |
| P1-3 | **Upload card rework** (§2): PDF input + Revit status pill + `<details>` advanced JSON input. Export `connStatus` from `revit_live.js`. | `app.js:209–212, 258–270`, `revit_live.js:20–27` | medium — must not add a second `/api/revit/status` caller |
| P1-4 | **Plain-English relabels.** Header buttons, pane titles, drawer headers, `STEPS[].title`, `#three-note`, `#hdr-stats` string. | `index.html`, `app.js:47–49, 106–140`, `viewer3d.js:350–359` | **medium — breaks 2 test assertions, see §7.2** |
| P1-5 | **Remove dev affordances.** `#rev-investigate` (+ its 25-line handler), the `element_list.json` export button, `.brand small`, the chat "asks the data · acts on the UI" badge, the pipeline "plain-English · anyone can run it" badge. | `index.html:211,165,246,30`, `inspector.js:235–259`, `app.js:221` | low |
| P1-6 | **Advanced disclosure inside the pipeline modal.** Wrap `produces`, `[data-runstep]`, `.steplog`, and the 4b benchmark buttons in one `<details>` per step card. `.resultstrip` stays outside it. | `app.js:196–227` | low — pure template change |
| P1-7 | **Tokens + reduced motion.** 4 vars + the one media query; replace the 5 hardcoded `#fbbf24` with `var(--warn)`. | `tokens.css`, `app.css`, `table.js:18`, `inspector.js:178` | low |
| P1-8 | **Update the Playwright suite** for the new selectors/strings. | `frontend/tests/smoke.spec.js` | see §7 |

### P2 — nice to have

| # | Task | Files |
|---|---|---|
| P2-1 | Motion M4 (review-count bump) + M5 (3D badge crossfade) + M1/M2 retunes | `inspector.js`, `viewer3d.js`, `app.css`, `components.css` |
| P2-2 | Table "Show technical columns" toggle — hides `Device` (and, if wanted, `Reason`) by default | `index.html:126`, `table.js:43–57` |
| P2-3 | `#three-note` telemetry → `title=` tooltip; keep only the honesty sentence visible | `viewer3d.js:347–359` |
| P2-4 | First-run empty state: replace the bare `"no data yet — open ▶ Pipeline"` (app.js:52) with a centered card + a big Upload button | `app.js:50–54`, `app.css` |
| P2-5 | Move the 5 inline style declarations on `#proj-switch` into CSS | `index.html:31–32`, `app.css` |
| P2-6 | Keyboard: `Esc` already deselects (app.js:97–103) — extend it to close the ⚙ menu and the open drawer | `app.js:97` |
| P2-7 | `.hzlabel` opacity fix if any survive | `app.css:35` |

---

## 7. Risk register

### 7.1 The load-order trap (the single biggest way to break this)

`util.js:4` is `export const $ = s => document.querySelector(s)` — it returns
`null` for a missing node, and every panel wires handlers at **module import
time**, unguarded:

- `app.js:85` `$("#btn-extract").onclick = …`
- `app.js:86` `$("#btn-match").onclick = …`
- `inspector.js:32–35` `$("#btn-chat"|"#btn-runs"|"#btn-review"|"#btn-revit-lookup").onclick = …`
- `table.js:73–74`, `pdf.js:184–201`, `viewer3d.js:424–430`, `wizard.js:312–320`

Deleting any of these ids from `index.html` throws
`Cannot set property 'onclick' of null` **at import**, which kills the entire
module graph — the app renders a blank page, not a degraded one. Also
`chat.js:87` looks up `#btn-autopilot` by string to satisfy the bot's
`open_panel` action, and `wizard.js:290` clicks it from the banner.

**Rule for the implementer: every id in §1 marked DEMOTE keeps its element in
the DOM. Demotion is achieved by moving the node inside `<details id="adv-menu">`,
never by deleting it.** Only the four REMOVE items lose their nodes, and each
of those needs its handler deleted in the same commit (`#rev-investigate` →
`inspector.js:235`).

### 7.2 Playwright — every assertion that will break

`frontend/tests/smoke.spec.js` (config: `frontend/playwright.config.js`):

| Line | Assertion | Impact of P1 | Fix |
|---|---|---|---|
| 17 | `#hdr-stats` contains `"MATCH"` — in `gotoLoaded()`, so **every test depends on it** | **BREAKS** if the stats string drops the word MATCH | change the wait to `"verified"` (one line, fixes all 7 tests) |
| 28 | `#hdr-stats` contains `"106 MATCH"` | **BREAKS** | → `"106 verified"` |
| 52 | `#btn-table` click | safe — stays visible | — |
| 76 | `#btn-autopilot` click | **BREAKS** — Playwright refuses to click a node inside a closed `<details>` (not visible) | prepend `await page.locator("#adv-menu > summary").click();` |
| 85 | `#bm-banner` contains `"Approve to continue"` | safe **if** the §1h copy keeps that phrase | preserve the phrase |
| 118 | `#btn-chat` click | safe — stays top-level | — |
| 140 | `#btn-autopilot` click | **BREAKS** (same as :76) | same fix |
| 145 | `#chat [data-close="chat"]` | safe | — |
| 192 | `#btn-revit-lookup` click | **BREAKS** (same cause) | same fix |
| 59 | `th[data-k="mark"]` | safe; P2-2 only hides `device_id` | — |
| 46 | `#insp-body .status-pill` | safe — inspector internals untouched | — |

Net: **5 line edits in one file.** Do them in the same commit as P1-1/P1-4, then
run `npx playwright test` from `frontend/` before shipping.

### 7.3 Other risks

- **Backend contract:** none of this touches an endpoint. `/api/upload` still
  receives the same `FormData` keys (`pdf`, `revit_json`) — the JSON input is
  hidden, not removed (§2).
- **The MATCH=106 gate:** unchanged. No pipeline logic is touched, so the
  standing Madera/Country Side/Dogwood baselines cannot move. If they do, the
  cause is elsewhere.
- **`/api/revit/status` cost:** it spawns the Nonica exe. The new upload pill is
  a third caller after `wizard.js:258` and `revit_live.js:21`. Route it through
  the existing 15 s-cached `connStatus()`; a raw call on every pipeline-modal
  render would spawn the exe on every open.
- **Chat `open_panel` action:** `chat.js:86–89` maps `"autopilot" → #btn-autopilot`
  and `.click()`s it. Inside a closed `<details>`, a programmatic `.click()`
  still fires the handler (unlike Playwright), so this keeps working — but the
  wizard will open with the ⚙ menu still collapsed behind it, which is fine.
- **Reduced-motion + GSAP:** the global CSS media query does **not** stop GSAP
  tweens. The three infinite GSAP loops (`viewer3d.js:270` ball bob,
  `viewer3d.js:271` ring spin, `viewer3d.js:404` emissive pulse) need the
  explicit `matchMedia` guard, or they keep running for a user who asked for
  stillness.

---

## 8. What was deliberately not done

- No new dependency (Motion One rejected — GSAP covers all six interactions).
- No spacing/type scale rework — the existing rhythm is fine and the time box is
  today.
- No component-library extraction — `components.css` is 35 lines and cohesive.
- No responsive/mobile pass — this is a desktop tool next to Revit on a
  workstation. `app.css:41` already handles the ≤1280 px header squeeze.
- No touch-target audit — desktop mouse-only tool. (The `.mini` buttons at
  ~24 px tall would fail a mobile audit; flagged, not fixed.)
- The Chat drawer survives. It is the only place a non-technical reviewer can
  ask a question in their own words, and it is where teaching happens.
