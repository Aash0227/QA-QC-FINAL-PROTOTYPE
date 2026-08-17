# Future UI References — Fit Audit (Phase 0)

Audit of the two supplied components against the current codebase. **No integration done.**

---

## 1. KineticGrid (`Background-UI.txt`)

**What it is:** a fixed full-screen canvas animation — warped grid of dots/segments that follows the cursor and fires ripples on click. Pure canvas + rAF loop. React + TS + Tailwind + `cn()` from `@/lib/utils`.

**Dependencies:** React, Tailwind (bg-[#161618], text-white/70 classes), `cn` util (shadcn idiom). No external animation libs — hand-rolled lerp physics. `"use client"` = Next.js App Router convention (not needed in Vite, harmless).

**Compatibility with current app:**
- Current frontend is vanilla JS + Vite — the component is TSX. It ports in only after the React shell exists (or as a React island).
- It renders `fixed inset-0 z-0 pointer-events-none` canvas + `z-10` content wrapper. Canvas is `pointer-events-none`, so it cannot block the UI. ✅
- **Performance:** rAF redraw every frame, full window canvas, grid = ceil(W/55)×ceil(H/55) nodes ≈ 35×20 = 700 nodes + ~1400 segments per frame at 1080p. With lerp colors + per-node radial gradients on hover — fine on a discrete GPU, but it runs **always**, even when idle (mouse at -9999 still draws all segments at base color). On Sagar's laptop (RTX 3050-class) alongside the three.js scene this is wasted GPU. Mitigation when integrated: pause rAF when `document.hidden` or when tab is in background (IntersectionObserver), and consider `globalColor="monochrome"` to kill the glow gradients.
- **Best integration point:** app-level background layer behind the shell (z-0), NOT inside the pipeline modal (z-80 overlays). The QA dashboard is content-dense; a full kinetic background competes with the PDF drawing + 3D scene. Recommendation: use it on the landing/empty states + modal backdrop only, or run at reduced opacity.

## 2. AgentPlanning timeline (`PIPELINE-UI.txt`)

**What it is:** an expandable vertical timeline of agent steps with `pending / active / success / error` statuses, per-step icons, durations, and rich expandable content panels. The second snippet (`Component` with a count +1/-1 button) is a template placeholder — ignore it.

**Dependencies:** React, lucide-react icons, Tailwind (`animate-in fade-in slide-in-from-top-4` = tailwindcss-animate class set), `cn()`. Grid-rows 0fr→1fr accordion animation is pure Tailwind — no JS animation lib needed.

**State model → real pipeline mapping (this is the valuable part):**

| AgentPlanning | QA/QC pipeline reality |
|---|---|
| `steps: PlanStep[]` prop | `POST /api/pipeline/run` response `stages[]` — already returns `{key, title, status: done|skipped|failed, duration_s, reason}` |
| `status: 'success'` | `done` (or `done, skipped:true` → map to success with muted style) |
| `status: 'active'` | the stage currently executing — requires **per-stage progress events**, which the SSE stream already emits (`progress.py` start/done per step) |
| `status: 'error'` | `failed` + `reason` (already in the response — the reason string is the expandable content panel) |
| `status: 'pending'` | `skipped` ("waiting on: …") |
| `duration` | `duration_s` already returned per done stage |
| expandable content | `reason` (skip), AI status text (`/api/pipeline/ai-status`), or artifact summary |

**Key gap:** the current `/api/pipeline/run` is ONE blocking POST that returns only at the end — AgentPlanning needs a stream of stage transitions to show an *active* step live. Two options when integrating: (a) frontend polls `pipeline/status` while the run POST is in flight and derives stage states from artifact appearance; (b) move `pipeline/run` to background execution (BackgroundTasks + run state file) and drive the timeline from SSE `pipeline/events`. (b) is the correct production shape — it also fixes the single-worker blocking problem (§G).

**Demo-data removal:** `DEFAULT_STEPS` is hardcoded demo content — delete it; pass `steps` from the real run response. Icons map from stage key (Search→extract, FileText→revit_convert, etc.).

---

## grid.golivio.com ZIP

Not present in this message — the prompt says to treat it as branding reference. **Needs verification:** locate the downloaded ZIP before Phase 1. Once available, extract: logo assets, palette hexes, typography, spacing scale → port into `tokens.css`/Tailwind config.
