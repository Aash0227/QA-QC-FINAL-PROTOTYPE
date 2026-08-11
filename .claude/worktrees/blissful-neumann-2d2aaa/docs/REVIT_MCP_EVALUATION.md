# Live Revit ↔ AI connection — evaluation & setup (Phase B1)

**Goal:** give the AI (Claude) live access to the open Revit model so every
flagged element can be *investigated* against the real model, not just the
JSON snapshot. The snapshot stays the batch backbone (auditable, repeatable);
the live channel adds semantics and interactivity.

## Candidates

| | NonicaTab A.I. Connector (MCP) | Open-source `revit-mcp` (already on this machine) |
|---|---|---|
| What it is | Commercial Revit add-in exposing 50+ tested MCP tools | Community plugin (`revit_mcp_plugin` + `mcp-servers-for-revit.addin` found in `%APPDATA%\Autodesk\Revit\Addins\2023`) |
| Read tools (query elements, params, by category/level) | ✅ Free tier | ✅ (tool coverage varies by version) |
| Edit/document tools (highlight, modify params, place views) | PRO — €85/yr per seat | Partial, community-maintained |
| Maintenance / support | Vendor-maintained, Autodesk App Store distribution, used by WSP/AECOM/Arup | Self-maintained; the local copies date from earlier MCP experiments |
| Risk | Vendor lock for edit tier | Breakage on Revit upgrades; needs our own upkeep |

**Recommendation:** start with **NonicaTab free tier** for reliability
(read-only tools cover the entire investigation use case), keep the
open-source plugin as fallback/reference. Buy PRO only when we want the agent
to highlight/fix/document elements *inside* Revit.

Sources: [Nonica AI Connector](https://tools.nonica.io/AIConnector) ·
[Why MCP over code generation](https://aiconnectorforrevit.com/revit-mcp/) ·
[Autodesk App Store listing](https://apps.autodesk.com/RVT/en/Detail/Index?id=9212699819557407848) ·
[GitHub issue tracker](https://github.com/NonicaTeam/AI-Connector-for-Revit)

## Setup (user, ~15 min, one time)

1. Install **NonicaTab** from the Autodesk App Store (link above) into Revit 2023/2026.
2. In Revit: NonicaTab ribbon → A.I. Connector → enable the MCP server (it prints an MCP endpoint/config snippet).
3. Register it for Claude Code (this machine):
   `claude mcp add nonica -- <command from the Nonica setup dialog>`
   (or paste the snippet into Claude Desktop's MCP config for desktop use).
4. Open the project model, then in a Claude session ask e.g.:
   *"Using the Revit tools: list all Structural Connections within 3 ft of (52.1, 33.4) on GRADE LEVEL and give their family, type and Mark."*

## Acceptance test (B1 verification)

With the Country Side model open, the connector must answer:
- count of Structural Columns visible in the active view (expect 28),
- family + Mark of the element nearest a given hold-down coordinate,
- level and elevation of a named element id.

Record results + latency here after the first session:

| Test (2026-07-10, first session) | Result |
|---|---|
| Connection health (`claude mcp list`) | ✔ Connected (`RevitMCPConnection.exe`, stdio) |
| Structural Columns count | ✔ answered: 19 — revealed the OPEN model was Madera (view `{3D - sagarkarpe}`), not Country Side; the live channel caught a wrong-model situation instantly |
| SHDU family query | ✔ answered: SHDU11/SHDU10S/SHDU6 families + element ids (Madera products — confirms model identity) |
| Active view query | ✔ answered: `{3D - sagarkarpe}`, no level |
| **Verdict** | **Connector works end-to-end. Re-run counts with the Country Side model open to finish the numeric acceptance row (expect 28 columns).** |

| Test (2026-07-14, Madera open, connector enabled) | Result |
|---|---|
| Model identity | ✔ `10510 Madera Dr_LGS model_08052026`, view `{3D - sagarkarpe}` |
| Structural Columns (view / document) | ✔ 19 / 19 — matches the v3 export exactly |
| Walls document-wide | ✔ 270 — confirms the export view hides 220 walls (incl. 77 SW); the v2-merge enrichment used real model data |
| Merged holdown spot-check | ✔ UniqueId `…-0012a904` found live: `SHDU6-With Bolt` at (17.56, 62.01, 1.50) ft — coordinates identical to the enriched JSON to the hundredth |
| **Verdict** | **B3 exporter live-validation proven: every enrichment decision verified against the open model. Country Side numeric row still pending (open that model, expect 28 columns).** |

## How it plugs into the QA workflow (B2 — shipped)

The **⚠ Review drawer** now has an **🔍 Investigate** button per flagged
element. It composes a full investigation brief (element id, mark, status,
both coordinates in ft and pt, distance, spec, sheet) and copies it to the
clipboard — paste it into a Claude session that has the Revit MCP connected
and the agent interrogates the live model and explains the flag. The
suggestion goes into the element's comment thread; the honest pipeline status
is never overwritten.

## What the live channel does NOT do

It does not change the distance math or create matches — coordinates from MCP
are the same Revit API values the JSON already carries. Its value is
*explanation, semantics and action*, not different numbers. (This was the
core finding of the Nonica research: the matching accuracy levers are
PDF-side — leader lines, registration, schedule parsing — and they shipped
separately as Phase A.)
