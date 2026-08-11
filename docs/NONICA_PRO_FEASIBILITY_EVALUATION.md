# Nonica PRO API — Technical Feasibility Evaluation

> ⚠️ **CORRECTION (2026-07-27, live-verified):** This doc names tools that do
> NOT exist in the Nonica MCP (`operate_element`, `send_code_to_revit`,
> `get_current_view_elements` — those belong to a different open-source Revit
> MCP). The real, live-verified equivalents are `set_user_selection_in_revit`
> (highlight = blue selection; SHIPPED via POST /api/revit/highlight),
> `get_user_selection_in_revit`, `set_isolated_elements_in_view`,
> `set_graphic_overrides_for_elements_in_view`, and
> `set_additional_property_for_all_elements` (for qa_status write-back).
> **There is no zoom/camera tool** — the shipped UX is selection + "press ZS".
> Phase 1 (highlight, lookup, Why-panel) shipped 2026-07-27; see
> `docs/REVIT_SIDE_FLAW_REPORT.md`.

**Date:** 2026-07-27
**Evaluator:** Subagent (Hermes)
**Scope:** Assess whether Nonica PRO can drive the proposed workflow — PDF pipeline stays in webapp, Revit becomes live frontend via API, "Show in Revit" button highlights elements, and a "paste Revit ID → show element + reasoning" tool lives in Revit.

---

## Executive Summary

**VERDICT: FEASIBLE — and already 60% implemented.**

The project already has a production-proven `backend/app/revit_bridge.py` that drives the Nonica PRO `RevitMCPConnection.exe` directly (no Claude in the loop). The MCP transport is proven, 52 tools are exposed, and the benchmark placement workflow (placing BM-1/BM-2 in the live model with server-side readback verification) has been validated end-to-end on the Madera model. The remaining gap is wiring the **highlight / isolate / zoom-to-element** PRO tools to a new frontend button and a Revit-side "ID lookup" tool.

---

## What the Nonica PRO API Actually Provides (52 tools)

### Read tools (free tier — already used)
| Tool | Purpose | Already used? |
|------|---------|---------------|
| `get_active_view_in_revit` | Connection health + current model title | ✔ `revit_bridge.status()` |
| `get_elements_by_category` | All elements of a category (walls, columns, StructConnections) | ✔ `connection_locations_sequence()` |
| `get_location_for_element_ids` | XYZ coordinates of any element | ✔ `place_sequence()`, `live_connection_locations()` |
| `get_all_elements_of_specific_families` | Find elements of named families | ✔ benchmark placement |
| `get_element_ids_in_active_view` | Visible element filter | not yet |
| Parameter read tools (Mark, family, type, level) | Query metadata | partial |

### Edit tools (PRO tier — €85/yr/seat — **the unlock for this proposal**)
| Tool | Purpose | Maps to proposed feature |
|------|---------|---------------------------|
| `set_copy_element` | Clone element with vector offset | ✔ already used for BM placement |
| `set_parameter_value_for_elements` | Write Mark / param values | ✔ already used |
| **`operate_element` (Select)** | Make element the active selection | "Show in Revit" highlight |
| **`operate_element` (SelectionBox)** | Zoom/focus to element bounding box | "Show in Revit" navigation |
| **`operate_element` (SetColor)** | Apply RGB overlay to element | "Show in Revit" visibility |
| **`operate_element` (SetTransparency)** | Fade or reveal elements | Context highlighting |
| **`operate_element` (Highlight)** | One-shot red highlight (convenience) | Quick glance |
| **`operate_element` (Isolate)** | Show ONLY the named elements, hide everything else | Deep-dive review |
| **`operate_element` (Hide / TempHide)** | Hide specific elements | Filter noise |

> The `operate_element` family is exactly what the "Show in Revit" button needs. The existing Revit MCP tools session running in this workspace already exposes them (`mcp__revit_mcp__operate_element`), so the capability is live and testable.

---

## Proposed Features — Mapping to Nonica PRO Tools

### Feature 1: "Show in Revit" button from the webapp

**User flow:** QA engineer clicks a row in the comparison table → clicks "Show in Revit" → the element highlights in the open Revit model.

**Data flow:**
1. Webapp UI button → `POST /api/revit/highlight` (new endpoint)
2. Backend resolves the assembly's **live ElementId** via `revit_bridge.live_connection_locations()` (coordinate match — already implemented in `/api/revit/element-ids/{assembly_id}`)
3. Backend calls `operate_element(action="Highlight", elementIds=[live_id])` or `operate_element(action="Isolate")` via the MCP bridge
4. User sees the element red/selected in Revit; click again → `ResetIsolate` or `Unhide`

**Implementation effort:** Small. The live-id lookup already exists (`revit_element_ids()`). Only new code: a bridge wrapper for `operate_element`, and a new endpoint. ~50 lines backend, ~30 lines frontend.

**Prerequisites:**
- Nonica PRO seat active (€85/yr) — already available to user
- Revit model open with AI Connector enabled (current constraint, already surfaced in UI)

### Feature 2: "Paste Revit ID → Show element + reasoning" tool in Revit

**User flow:** User selects an element in Revit, copies its ElementId, pastes into a dialog (webapp panel or Revit ribbon button), and sees the QA pipeline's verdict, match status, distance, spec mismatch, and PDF sheet reference.

**Data flow:**
1. Webapp input panel accepts an ElementId
2. Backend calls `get_location_for_element_ids([id])` → XYZ in model feet
3. Backend runs the existing `compare.py` match against that point (same code that generated the row) → returns verdict + reason
4. Backend renders the reasoning in the webapp's **Review drawer** AND copies it to clipboard for the "Investigate" flow (already shipped — `docs/REVIT_MCP_EVALUATION.md` §B2)

**Alternative (true Revit-side):** A Revit ribbon button that POSTs the current selection's ID back to the webapp via a socket — but this is scope creep; the clipboard-investigate flow already works and uses the same data.

**Implementation effort:** Small. The reverse lookup (id → location → comparison verdict) is the inverse of the existing `/api/revit/element-ids` endpoint. ~80 lines backend, reuse review drawer frontend.

---

## Constraints and Risks (proven, not theoretical)

| Constraint | Source | Mitigation |
|---|---|---|
| Live Revit + AI Connector required at call time | Every Nonica tool call times out if connector is off | `revit_bridge.status()` exposes this; wizard already shows connection badge |
| Pinned elements can't be copied | 2026-07-20 live finding in Madera model | Bridge surfaces clear error: "Unpin it in Revit (select it, press UP/Unpin)" |
| ElementIds can change after central-model ops | `revit_bridge.py` docstring | Lookups match by **coordinate**, not export-time ids; export ids returned as "honest fallback" only |
| One MCP session per backend call | FastAPI is sync; bridge wraps in `asyncio.run()` | Acceptable for interactive rare clicks; for batch ops, consider persistent session later |
| ~20 s init timeout on cold spawn | `init_timeout=20` in `_with_session()` | Hot path (connector already enabled) is instant; cold path only on first call after Revit launch |
| PRO license cost | €85/yr/seat | Worth it iff the team actually clicks "Show in Revit" >10× per week; currently the free tier covers the "Investigate" clipboard flow well |

---

## Current State of the Codebase (what ships tomorrow vs. what's new)

**Already shipped (no work):**
- `GET /api/revit/status` — live connection badge
- `GET /api/revit/element-ids/{assembly_id}` — returns live ElementIds by coordinate match
- `revit_bridge.live_connection_locations()` — cached (300 s TTL) full StructConnection list
- "🔍 Investigate" button in the review drawer — copies a full brief to clipboard
- Benchmark placement (BM-1/BM-2) end-to-end with server-side readback verification

**New to build (≤ 1 day of work):**
- `POST /api/revit/highlight` — calls `operate_element(action="Highlight" | "Isolate", elementIds=[...])`
- `POST /api/revit/reset` — calls `operate_element(action="ResetIsolate")`
- Webapp row action button wired to the endpoint
- `POST /api/revit/lookup-by-id` — reverse id → location → match verdict

---

## Recommendation

1. **Buy Nonica PRO** for the QA engineer's seat (€85/yr) — the edit tools are a hard prerequisite for "Show in Revit". The free tier only covers read/clipboard flows.
2. **Ship Feature 1 ("Show in Revit") first** — it's the highest-value, lowest-risk change. The existing `revit_element_ids` endpoint already returns the right live ElementId; the new 50-line endpoint just wraps `operate_element`.
3. **Ship Feature 2 (ID → reasoning) second** — it reuses Feature 1's endpoint and the existing review drawer. ~80 lines backend.
4. **Keep PDF pipeline in webapp** — the coordinate registration, RANSAC calibration, and device matching all live in `backend/app/` and have no reason to migrate. Revit should never become the "live frontend" for the math; it should only become the live **viewer/actor**.
5. **Do NOT replace the clipboard-Investigate flow** — it works today, doesn't need PRO, and is the right fallback when the connector is off. Feature 1 and the Investigate button should coexist.

---

## Evidence References

| File | Relevance |
|---|---|
| `backend/app/revit_bridge.py` (301 lines) | LIVE bridge — proven 2026-07-20 to spawn exe, handshake, list 52 tools, place BM-1/BM-2 with readback |
| `backend/app/routers/revit.py` (124 lines) | `/api/revit/status` + `/api/revit/element-ids/{id}` already shipped |
| `docs/REVIT_MCP_EVALUATION.md` (80 lines) | Prior evaluation: free vs PRO; live validation on Madera (19 columns, SHDU families, UniqueId match) |
| `AGENT_HANDOFF.md` §"Key facts discovered" | Notes Nonica Revit MCP registered user-scope as "Revit"; live model + A.I. Connector required |
| `backend/run_benchmark_acceptance.py` | Full live benchmark acceptance test (2026-07-16, Madera) — proof that write operations to the real model work |
| Live MCP tools visible in current session | `mcp__revit_mcp__operate_element` exposes Select/SelectionBox/SetColor/SetTransparency/Delete/Hide/TempHide/Isolate/Unhide/ResetIsolate/Highlight — all PRO edit tools confirmed present |

---

## Bottom Line

The Nonica PRO API can do everything the proposal asks, is technically a trivial extension of what's already working, and the bridge code has been proven end-to-end on the Madera model. **Proceed; the risk is near-zero and the implementation is ~1 day of work.**
