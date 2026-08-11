# Pipeline Plan — "upload PDF → live Revit → compare"

**Date:** 2026-07-31 · **Author:** research pass (no code written) · **Audience:** founder + the agents shipping today's UI
**Question asked:** what does it actually take to drop "upload Revit JSON" from the primary flow and let the backend read the OPEN model live?

**Answer in one line:** the *interaction* half is already live and proven; the *math* half has **four unproven links** (per-element family, per-element mark, wall centreline, grids) and one newly-discovered blocker (a hardcoded product whitelist inside Livio's own Revit add-in). Ship **Design A2 — zero-upload auto-ingest** today; do the live fetch as its own validated sprint.

---

## 0. Probe status — READ THIS FIRST

**No live probe was possible.** At the time of this pass:

```
tasklist          → Revit.exe NOT running (only 5 orphaned RevitMCPConnection.exe)
127.0.0.1:8080    → WinError 10061, connection refused (revit-mcp socket down)
revit_bridge.status() → {"connected": false,
                         "reason": "Revit AI Connector (NonicaTab PRO) is closed or disabled.",
                         "model_title": null}
```

Everything below marked **PROVEN** comes from a prior live session recorded in
`AGENT_HANDOFF.md` / `docs/REVIT_SIDE_FLAW_REPORT.md`. Everything marked **UNVERIFIED**
is inferred from code, .NET metadata, or add-in logs and **must be probed before anyone
writes live-fetch code**. §6 lists the exact 10-minute probe script.

### 0.1 `get_holdown_assemblies` / `get_wall_assemblies` — what they really are

These are **not** upstream `mcp-servers-for-revit` tools. They are **Livio's own custom
Revit commands**, registered in
`%APPDATA%\Autodesk\Revit\Addins\2023\revit_mcp_plugin\Commands\commandRegistry.json`
(lines 349-377), developer field `"Livio"`, description
*"Read-only Livio physical hold-down assembly extraction"* / *"…physical wall assembly extraction"*.

They are implemented in `Livio.RevitMCP.WallCommands.V2.dll` (and mirrored into
`RevitMCPCommandSet.dll`), types `GetHoldownAssembliesCommand`, `GetWallAssembliesCommand`,
result types `HoldownAssemblyResult` / `CanonicalHoldownAssembly` / `HoldownMember` and
`WallAssemblyResult` / `CanonicalWallAssembly` / `WallOpening` / `WallElevationCohort`.

**They re-implement, in C#, the exact clustering the Python pipeline does.** String
literals recovered from the DLL:

| Literal in the DLL | What it tells us |
|---|---|
| `"Anchor bolts and offset components are evidence members, not separate hold-downs."` | same body/bolt/offset rule as `revit_v3_adapter._is_body` |
| `"Two-sided families emit two physical locations."` | handles `HTT4 both side` — better than the Python side |
| `"Only validated HDU family/type names are classified."` | **whitelist-gated — see the blocker below** |
| `"The command is read-only and never modifies the active Revit document."` | safe to call |
| `"Extracted {0} physical hold-downs from … relevant framing members."` | doc/level scoped, not view-scoped → would fix R-07 |
| `"LGS studs, tracks, and nogging are grouped by Revit assembly, group, panel, bundle, or BIMSF container metadata first."` | wall side groups real LGS panels, not just native Revit walls |
| ids `revit-wall-{0}`, `revit-wall-group-`, `revit-wall-track-{0:0000}`, `assembly:{0}` | **content-derived ids — would fix R-17** (positional `rev_asm_NNN`) |
| params read: `Mark`, `Type Mark`, `Comments`, `ASSEMBLY_CODE`, `Assembly Version`, `Family`, `Type`, `Level`, `Reference Level` | mark/level available |
| result props: `Confidence`, `ClassificationMethod`, `AuditFlags`, `Assumptions`, `Diagnostics`, `RawMemberCount`, `DeduplicatedMemberCount`, `UnmappedMembers`, `RuntimeMs` | honest-reporting surface already designed in |
| `ClassificationMethod` values: `validated_family_type`, `panel_or_assembly_metadata`, `native_revit_wall`, `lgs_framing_assembly`, `member_profile_inferred_from_track`, `stud_spacing_unavailable`, `track_not_identified`, `profile_unmapped` | |
| **every** geometry prop ends `Mm`: `PhysicalLocationsMm`, `BboxMm`, `StartMm`, `EndMm`, `LengthMm`, `PhysicalWidthMm`, `MinElevationMm`/`MaxElevationMm`, `MaximumStudSpacingMm` | **units are MILLIMETRES.** The whole pipeline is in FEET. `/304.8` at the boundary, and every distance gate (2 ft / 6 ft / 4 ft / 12 ft) must stay in feet. |
| params accepted: `levelName`, `elevationToleranceMm`, `proximityToleranceMm`, `includeDetailedTypes`, `familyNameFilter` | |

#### BLOCKER — the whitelist does not cover 2 of our 3 projects

The only product codes present in **all four** candidate DLLs
(`Livio.RevitMCP.WallCommands.V2.dll`, `Livio.RevitMCP.WallCommands.dll`,
`RevitMCPCommandSet.dll`, `RevitMCPCommandSet.Livio.1.0.1.dll`) are:

```
HDU  HDU6  HDU10S  HDU11  HDU15B  HD10S  HD15B  S/HDU6  S/HDU11  S/HD10S  S/HD15B
```

Against the real families in our three stored exports:

| Project | Real hold-down families (count) | Covered by the DLL whitelist? |
|---|---|---|
| **Madera** | `SHDU11-With Bolt` (24), `SHDU6-With Bolt` (22), `SHD15B-WITH BOLT` (13), `SHD10S-with bolt` (10) + bolts/offsets | ✅ yes — all four |
| **Country Side** | `SHDU15S-WITH BOLT` (20), `SHDU9-with bolt` (12), `SHDU6-With Bolt` (10) + bolts/offsets | ❌ **HD15S and HD9 absent** |
| **Dogwood** | `HTT4` (44), `HTT4 both side` (14), `Anchor_Bolt_HTT5` (46), `A_THD37500H…` (2) | ❌ **no HTT / THD at all** |

The whitelist is Madera-tuned. Calling `get_holdown_assemblies` on Country Side or Dogwood
would return a **silently short list** — the exact failure mode (`PDF_ONLY` everywhere under
a green badge) that R-09/R-10 already burned us on. Python's `HOLDOWN_FAMILY_RE`
(`(HTT|HD[UB]?)\s*_?(\d+)([A-Z]?)`) covers all three projects.

→ **Do not adopt `get_holdown_assemblies` as the math source until the C# whitelist is
replaced with the same regex (or made configurable).** That is a Revit-add-in change, not a
backend change, and it is outside this repo.

#### The add-in log line that looks fatal but isn't

`…\revit_mcp_plugin\Logs\mcp_2026*.log` shows, on **every** Revit start:

```
Failed to create command instance [get_holdown_assemblies]: RevitMCPCommandSet.dll
Failed to create command instance [get_wall_assemblies]: Livio.RevitMCP.WallCommands.V2.dll
```

**This is noise, not a fault.** The same log emits the identical line for
`get_selected_elements` at `2026-07-28 11:59:46`, and `get_selected_elements` was
live-proven working that same day (ship-day Country Side acceptance,
`GET /api/revit/selected-element`). All 26 commands log it; the socket then reports
`Socket service initialized on port 8080` and serves them fine. The plugin resolves
commands lazily at call time. Still worth one probe to be sure (§6).

#### The escape hatch nobody has used

`send_code_to_revit` — *"Execute dynamic C# code in Revit with access to the Document and
Revit API"* — is registered and enabled, and Roslyn (`Microsoft.CodeAnalysis.CSharp.dll`) is
shipped next to it. That is a **complete** answer to every gap in the table below: the
backend could post the exporter's collector as C# and get the full v3 payload back,
doc-wide, with no pyRevit and no whitelist. It is also arbitrary code execution into the
user's Revit session and a WRITE-capable channel. Treat it as a Design-B option to be
decided deliberately, never as a default.

---

## 1. Field-by-field gap table

Consumers: `backend/app/revit_v3_adapter.py` (`adapt_raw`, `_holdown_records`,
`build_ai_revit`, `normalize_point_mark`), `backend/app/scene3d.py`,
`backend/app/routers/pipeline.py:415` (post/column point matching),
`backend/app/control_points.py` (grid registration).

Legend — **P** = proven live, **U** = plausible but unverified, **✗** = no tool exists.

### 1.1 Per-element fields (`elements[]`, the hold-down + point math)

| Field | Consumed by | Nonica | revit-mcp / Livio | Verdict |
|---|---|---|---|---|
| `id` (UniqueId) | `revit_ref`, `member_element_ids`, live ID lookup | ✗ **no UniqueId tool at all** (flaw report Part 3: "coordinate matching is the only path") | `get_selected_elements` returns `UniqueId` **P**; Livio results carry `UniqueId` **U** | **Identity scheme changes.** Live fetch would key on integer ElementId. Better for Show-in-Revit, but breaks continuity with stored `review_comments.json` targets. Migration item. |
| `category` | `HOLDOWN_CATEGORIES` filter, scene3d | **P** — you query *by* category (`get_elements_by_category`, live-proven on 28k) | `get_current_view_elements(modelCategoryList)` **U** | ✅ solved |
| `family` | `holdown_variant_key()` — **the whole classification** | ✗ no id→family tool. Only the inverse: `get_all_used_families_of_category` → `get_all_elements_of_specific_families` **U** (the family→ids direction is **P**, used by `place_sequence`) | `get_selected_elements` → `Properties.Family` **P**; `ai_element_filter` **U** (caps at ~50 elements); `get_holdown_assemblies` **U + whitelisted** | ⚠️ **Unproven link #1.** Two-step inverse mapping is the realistic path (~10-20 families × 1 call for OST_StructConnections). |
| `mark` | `normalize_point_mark` → P-/C- point matching; hold-down mark | `get_parameters_values_for_element_ids` with `MARK_PARAM_ID = -1001203` **U** (we *write* through that id **P**, so reading is very likely) | `Properties.Mark` **P** (selection only); Livio reads `Mark`/`Type Mark` **U** | ⚠️ **Unproven link #2.** |
| `location.point` [x,y,z] **ft** | clustering, every distance gate, device match | **P** — `get_location_for_element_ids`, parser `_parse_id_locations`, feet | selection payload has **no point** (documented in `_from_revit_mcp`); Livio gives `PhysicalLocationsMm` **U, millimetres** | ✅ solved by Nonica |
| `elevation_ft` | z, `scene3d` datum `z0`, R-03 level gate | **P** (z of the location triple) | Livio `MinElevationMm`/`MaxElevationMm` **U** | ✅ solved |
| `bbox` | assembly bbox, framing instancing | **P** at scale — `get_boundingboxes_for_element_ids`, accepts subset ids, chunked at 300 | Livio `BboxMm` **U** | ✅ solved |
| `level` | R-03 level gate (dormant) | `get_parameters_values_for_element_ids` **U** | `Properties.Level` **P**; Livio `LevelName`/`AssociatedLevel` **U** | 🟡 low stakes — **already `null` for every Structural Connection in all 3 stored exports**, so live can only match or improve |
| `type_name` | record field | `get_element_types_for_elementids` **U** | `Name` **P** | 🟡 low stakes — **`""` for every connection in all 3 exports**; not load-bearing |
| `params{}` | `raw_parameters` passthrough | `get_parameters_from_elementid` / `get_all_additional_properties_from_elementid` **U**, per-element | Livio `Parameters` **U** | 🟡 nothing in the math reads it (only Dogwood populates it) |

### 1.2 Walls (`walls[]`)

| Field | Consumed by | Nonica | revit-mcp / Livio | Verdict |
|---|---|---|---|---|
| `centerline` [[x,y],[x,y]] | `wall_match.py` segment distance, scene3d | `get_location_for_element_ids` emits `LocationPoint` for points — whether it emits `LocationCurve` endpoints for a wall is **UNVERIFIED**. `get_boundary_lines` **U**. Fallback = bbox → axis-aligned only (loses skewed walls) | `get_wall_assemblies` → `StartMm`/`EndMm`/`LengthMm` + `FitAxisAlignedCenterline` **U** — the best-shaped source that exists | ⚠️ **Unproven link #3.** |
| `thickness` ft | wall verdicts | `get_material_layers_from_types` (type-level sum) **U** | Livio `Thickness` / `PhysicalWidthMm` **U** | ⚠️ unproven |
| `type_name` | SW token → shear-wall verdicts | `get_element_types_for_elementids` **U** | Livio `WallType`/`ScheduledType`/`ShearWall` **U** | ⚠️ unproven. Note Country Side exports `""` for all 18 walls anyway |
| `height_ft`, `is_structural`, `mark`, `level` | 3D + verdicts | parameters **U** | Livio `IsStructural`/`IsLoadBearing`/`Mark`/`LevelName` **U** | ⚠️ unproven |
| — bonus — | not consumed today | — | Livio adds `Openings`, `StudCount`, `MaximumStudSpacingMm`, `NoggingCount`, `StudThicknessMil`, `SteelGradeKsi`, `ElevationCohorts` | future upside |

### 1.3 Project-level

| Field | Consumed by | Nonica | revit-mcp / Livio | Verdict |
|---|---|---|---|---|
| `benchmarks[]` {mark, family, point_ft, level} | 2-point calibration — **the trust anchor** | **P, fully** — `get_all_elements_of_specific_families(mwfBenchmark)` + `get_location_for_element_ids` + Mark. This is literally what `place_sequence()` already does | — | ✅ **already 100 % live-capable today** |
| `grids[]` {label, line} | `control_points.py` grid-intersection registration | `get_elements_by_category(OST_Grids = -2000220)` **U** + curve read **U** + label read **U** | no `get_grids` tool exists (`create_grid` only) | ⚠️ **Unproven link #4 — the weakest.** Three unverified hops. |
| `levels[]` {name, elevation_ft} | level bands | `get_elements_by_category(OST_Levels = -2000240)` **U** + elevation param **U** | Livio emits `LevelName`/`LevelElevation`/`ElevationCohorts` as a by-product of `get_wall_assemblies` **U** | 🟡 probably fine |
| `export_view`, `export_scope` | provenance, R-07 scope warning | **P** — `get_active_view_in_revit` (`model_title` proven) | `get_current_view_info` **U** | ✅ — and going doc-wide via `get_elements_by_category` **fixes R-07 for free** |
| `source_model` / model binding | *(nothing today — that is the bug)* | **P** — `model_title` from `get_active_view_in_revit` | — | ✅ see §5.2 |
| `exported_at` | R-14 staleness — **dropped by `adapt_raw` today** | live fetch makes it `now()` | — | ✅ free win |
| `skipped_count` | R-06 | live fetch makes skips explicit | Livio `UnmappedMembers`/`AuditFlags` | ✅ free win |

### 1.4 Scale — how big is "live fetch" really?

Only ~4 categories carry the math. The 28k framing is **3D only, and already live**
(bbox massing, capped at 3000/category with an honest truncation note).

| | Madera | Country Side | Dogwood |
|---|---|---|---|
| total `v3_elements` | 7,356 | **29,606** | 14,775 |
| Structural Framing (3D only, already live) | 6,166 | 28,378 | 13,573 |
| **Structural Connections (the math)** | **1,150** | **1,194** | **1,169** |
| Structural Columns (C- point marks) | 19 | 28 | 2 |
| Structural Foundation | 21 | 1 | 31 |
| walls / grids / levels | 127 / 6 / 6 | 18 / 22 / 7 | 0 / 7 / 6 |
| elements with a non-empty mark | 264 | 209 | 415 |
| hold-down-family elements after regex | 162 | 118 | 108 |

**~1,250 elements per project carry the entire verdict math.** That is 4-8 Nonica round
trips at the proven 300-id chunk size — not a 30k problem. Live fetch is a *correctness*
problem, not a *performance* problem.

---

## 2. Design A — ship TODAY

### A1 (rejected): build the export equivalent live on "Connect"

Requires all four unproven links (family, mark, wall centreline, grids) to work *and* be
validated against the 106-MATCH baseline, on a day when **Revit is not even open to probe
them**. Plus the Livio hold-down tool would silently under-report 2 of our 3 demo projects.
Shipping this today means shipping an unvalidated math source. **No.**

### ✅ A2 (RECOMMENDED): zero-upload auto-ingest — the file becomes plumbing, not UX

> The founder's ask is *"no upload step"*, not *"no file"*. A2 delivers the ask with **zero
> math risk**: the pyRevit **Export QAQC** button already writes the JSON; the backend just
> stops making a human carry it.

**Operator flow becomes:** open the model in Revit → press **Export QAQC** → the webapp
notices within ~3 s and ingests it. Upload PDF stays. Upload Revit JSON disappears.

**Why this is the right rung:** the math source byte-for-byte unchanged → the 106-MATCH
Madera baseline, all 279 pytest and the 3-project acceptance stay valid by construction.
It also closes R-14 (staleness invisible) and the model-binding hole (§5.2) as side effects,
which A1 does not.

#### New / changed endpoints (contract for the other agents)

```
GET  /api/revit/export-status
→ {
    "found": true,
    "path": "C:\\Users\\…\\Downloads\\raw_revit_export.json",
    "watch_dirs": ["…\\Downloads", "…\\artifacts\\incoming"],
    "mtime": "2026-07-31T09:12:44Z",
    "age_s": 41,                       // → R-14 "Revit export: N min old" banner
    "source_file": "1311 COUNTRY SIDE CT_MAIN HOUSE_LGS MODEL_V02_07072026.rvt",
    "schema_version": "3.1",
    "element_count": 29606,
    "ingested": false,                 // already the active project's raw_revit?
    "live_model_title": "1311 COUNTRY SIDE CT…",   // from revit_bridge.status()
    "binding": "match" | "mismatch" | "unknown",   // §5.2
    "reason": null
  }
```
`found:false` and `binding:"unknown"` are normal states, never errors. Never 500 — this
endpoint is polled.

```
POST /api/revit/ingest        body: {"path": "<optional, else newest found>"}
→ same JSON as POST /api/upload's manifest
```
Internally identical to the `revit_json` branch of `POST /api/upload`
(`routers/projects.py:88-106`): `json.loads` → `revit_v3_adapter.is_v3` → `adapt_raw` →
`save_artifact("raw_revit", …)` → `_maybe_auto_advance_export(raw)` → manifest write. Reuse
that code path; do not fork it. Rejects `binding:"mismatch"` with **409** unless
`{"force": true}` — a wrong-model ingest is the single most expensive silent failure we have.

```
GET /api/revit/status          (existing — additive fields only)
→ { …, "expected_model": "<manifest.revit_model_title>", "model_match": true|false|null }
```

#### Config / manifest

* `QAQC_EXPORT_WATCH_DIRS` — `os.pathsep`-joined. Default: `%USERPROFILE%\Downloads`
  + `<ARTIFACT_BASE>/incoming`. Glob `*revit*export*.json` + `raw_revit_export.json`,
  newest `mtime` wins.
* New manifest field **`revit_model_title`** — the live Revit `model_title` this project is
  bound to. Written on the first successful ingest from `revit_bridge.status().model_title`;
  compared thereafter against both the live title and the export's `source_file` stem.

#### UI contract

| Today | After A2 |
|---|---|
| `<label class="file">Revit JSON <input id="up-revit" …>` (`frontend/src/app.js:211`) | **removed from the primary card** |
| `#btn-upload` appends `revit_json` (`app.js:264`) | appends `pdf` only |
| — | new **Connect to Revit** card: model title from `/api/revit/status`, export freshness from `/api/revit/export-status`, one button **Refresh from Revit** → toast *"Press Export QAQC in Revit"* → poll `/api/revit/export-status` every 2 s for ≤60 s → auto `POST /api/revit/ingest` on a newer `mtime` |
| — | **red** banner on `binding:"mismatch"`: *"This project is bound to «X» but Revit has «Y» open."* Ingest blocked until the operator confirms. |
| — | **amber** chip on `age_s > 86400`: *"Revit export is N days old"* (closes R-14) |

`POST /api/upload` keeps accepting `revit_json` unchanged — support and debug still need it.
It is simply no longer on the operator's path.

**Estimated effort: ~4 h** (1 new module for the watcher, 2 endpoints, 1 manifest field,
1 UI card, 3 tests). No frozen module touched. No verdict math touched.

---

## 3. Design B — full live fetch (next sprint)

### B0 · Probe & unblock — 0.5 day, **hard prerequisite**
Run §6 with all three models open in turn. Outcome is a yes/no on each of the four unproven
links. **If wall centreline or grids come back "no tool"**, B stops at hold-downs + points
and walls/grids keep coming from the export — a hybrid, and that is an acceptable landing
spot. Also decide the `send_code_to_revit` question here.

### B0.5 · C# whitelist fix — outside this repo, **blocks Livio-tool adoption**
Replace the `HDU6/HDU10S/HDU11/HDU15B/HD10S/HD15B` whitelist in
`GetHoldownAssembliesCommand` with the Python regex `(HTT|HD[UB]?)\s*_?(\d+)([A-Z]?)`, or
expose it as a `familyNameFilter` regex parameter. Until then `get_holdown_assemblies` is
Madera-only. **If this does not happen, build B on raw Nonica calls, not on the Livio tool.**

### B1 · `live_export.py` — hold-downs + point marks — 1.5 days
`get_elements_by_category([-2009030, -2001330, -2009000?, …])` → ids → chunked
`get_location_for_element_ids` + `get_boundingboxes_for_element_ids` →
`get_all_used_families_of_category` + `get_all_elements_of_specific_families` to invert
family→ids → batched `get_parameters_values_for_element_ids` for Mark/Level.
Emits a **schema-v3-shaped dict** — so `adapt_raw` / `build_ai_revit` / `scene3d` are
literally unchanged. That is the whole trick: swap the *producer*, never the *consumer*.
Stamp `export_scope: "live_document"`, `exported_at: now`, `skipped_ids: [...]`.

### B2 · walls / grids / levels — 1-2 days, **gated on B0**
Blocked → keep them from the export and say so in `assumptions[]`.

### B3 · Validation protocol — 0.5 day, **non-negotiable**
1. For each of Madera / Country Side / Dogwood, with the model open, build the live export
   and write it beside the stored `artifacts/projects/<p>/raw_revit_export.json`.
2. **Field-by-field diff**, not a summary: per element matched by `(round(x,2), round(y,2))`,
   assert `family`, `mark`, `category`, `elevation_ft` equal; report counts
   `only_live` / `only_export` / `differs`. Any `differs` is a stop.
3. Run the full pipeline on the live payload and assert **`by_status` is identical** —
   Madera `MATCH == 106`, hold-down devices `44 M / 16 LM / 4 PO / 1 MM / 11 RO`;
   Country Side `21`; Dogwood `16 M / 20 LM / 16 PO / 35 RO`.
4. Only then flip the default. Keep `QAQC_REVIT_SOURCE=export|live` for one release so a
   regression is one env var away from being attributed.

### B4 · Cutover — 0.5 day
Default `live`, export path retained as fallback, `intelligence_source`-style stamp on every
artifact saying which producer ran.

**Total ≈ 4-5 working days** after B0 comes back clean, and it does **not** start until
Design A2 has shipped and the founder has seen the zero-upload flow.

### Free wins that arrive with B
R-06 (skipped count), R-07 (doc-wide → `SCOPE_SUSPECT` instead of false `PDF_ONLY`),
R-11 (no fixed filename), R-14 (`exported_at` is always now), R-17 (content ids, if the
Livio tool is adopted), and the pyRevit exporter add-in stops being a deploy dependency.

---

## 4. What we are NOT doing
* Not adopting `get_holdown_assemblies` for math until its whitelist is fixed — it is
  Madera-only today and fails **silently**.
* Not calling `send_code_to_revit` without an explicit decision — arbitrary C# into the
  user's Revit session is a security posture change, not an implementation detail.
* Not touching `compare.py`, `registration.py` math, `device_match.py` thresholds, or any
  frozen module. Design A2 changes the *transport* of the same bytes.

---

## 5. Risks

### 5.1 Model not open / connector off / server not started
Three separate off states, three different fixes, and the operator cannot tell them apart:

| State | Detect via | Message |
|---|---|---|
| Revit closed | `status().connected == false`, `bridge unavailable:` | "Open the model in Revit." |
| Nonica A.I. Connector closed/disabled | `_looks_disconnected` markers | "Open NonicaTab PRO → A.I. Connector and keep the window open." |
| revit-mcp socket down (**needs a manual "Open Server" click on the revitMCP ribbon**) | `ConnectionRefusedError` on 127.0.0.1:8080 | "In Revit: revitMCP → Open Server." |
| Revit UI blocked by a modal | `_looks_blocked` (R-35) | "Press Esc in Revit, then retry." |

**Design A2 is immune to all four** — it needs the connector only for the *nice-to-have*
model-title binding, and degrades to `binding:"unknown"` with the export still ingesting.
Design B is hard-blocked by all four, which is the strongest argument for A2 today.

### 5.2 Wrong model open — the expensive one
Today **nothing** binds a project workspace to a Revit model. Country Side's PDF against
Madera's open model produces a full, green, confidently wrong report. Live fetch makes this
worse (today at least the export's `source_file` records the truth; live fetch has no
paper trail at all).

**Proposed manifest field:**
```json
"revit_model_title": "1311 COUNTRY SIDE CT_MAIN HOUSE_LGS MODEL_V02_07072026"
```
Written on first successful ingest, from `revit_bridge.status().model_title`, cross-checked
against `Path(raw["source_file"]).stem`. Compared on every ingest, every live scene, every
highlight. Mismatch → **409 + red banner**, never a silent proceed. Case- and
extension-insensitive compare; `null` on either side → `binding:"unknown"` (amber, allowed).

### 5.3 Nonica response truncation at scale
Already met and handled: large lists compress to a subset line
(`ElementIdsOfCategory[28]{SubsetId,IdsCount,SampleElementId}: -9000002,28380,2248112`) —
R-34, `_subset_ids` / `_parse_category_blocks`. Bounded by `SCENE_MAX_PER_CATEGORY = 3000`
and `SCENE_BBOX_CHUNK = 300`. **For B, the 3000 cap must NOT apply to the math categories** —
a capped hold-down list is a silently short verdict table. Cap the 3D scene; never cap the
math. Assert `len(parsed) == reported_count` per category and raise if short (`truncated{}`
already carries the evidence).

### 5.4 Performance — 28k framing
Non-issue for the math (§1.4: ~1,250 elements, 4-8 round trips). Real cost is the 3D scene,
already capped + 60 s cached. `_run()` spawns a **fresh `RevitMCPConnection.exe` per
operation** (`asyncio.run(_with_session(...))`, 20 s init timeout) — 6 sequential ops ≈ 6
process spawns. For B, hold one session per build (`scene_geometry_sequence` already proves
the multi-call-in-one-session pattern). Note the 5 orphaned `RevitMCPConnection.exe`
processes observed during this pass — spawn hygiene is already leaking; worth a look
regardless of B.

### 5.5 Units
Nonica = **feet** (proven). Livio commands = **millimetres** (every prop suffixed `Mm`).
`ai_element_filter` bounding boxes = **millimetres** per its own docstring. All pipeline
gates are feet. One conversion point at the adapter boundary, `/304.8`, and a self-check
asserting a known Madera hold-down lands within 0.01 ft of its stored export coordinate.

### 5.6 Identity migration
Live fetch yields integer ElementIds; the export yields UniqueIds. `review_comments.json`
keys on `category:mark:target_id` and `target_id` is the positional `rev_asm_NNN` (R-17), so
stored human decisions survive a UniqueId→ElementId switch **only** as long as assembly
ordering is stable — which R-17 says it is not. Adopting content-derived ids (Livio's
`assembly:{0}` style, or `mark + rounded xy`) in the same sprint kills both birds; doing it
in a later sprint means two migrations.

---

## 6. The 10-minute probe (run this the moment Revit is open)

Prereqs: model open · Nonica A.I. Connector window open+enabled · revitMCP ribbon → **Open
Server** clicked. Everything below is **read-only**.

```python
# scratch probe — NOT production code
import sys, json; sys.path.insert(0, "C:/QA-QC-FINAL-PROTOTYPE-bkp/backend")
from app import revit_bridge as rb

print(rb.status())                                   # expect connected + model_title

# --- A. the two Livio tools (THE headline question) -------------------------
for tool in ("get_holdown_assemblies", "get_wall_assemblies"):
    try:
        print(tool, json.dumps(rb._revit_mcp_call(tool, {}, timeout=120))[:4000])
    except Exception as e:
        print(tool, "FAILED", e)
# Check: does the hold-down count match the project's stored export?
#   Madera 162 raw / 72 assemblies · Country Side 118 · Dogwood 108
# A short list on Country Side or Dogwood CONFIRMS the whitelist blocker (§0.1).
# Record: units (Mm?), id kind (UniqueId or int?), Assumptions/AuditFlags text.

# --- B. the four unproven Nonica links --------------------------------------
import asyncio
async def seq(call):
    out = {}
    out["families"] = (await call("get_all_used_families_of_category",
                                  {"list_categoryids": [-2009030]}))[:1500]
    ids = rb._element_ids(await call("get_elements_by_category",
                                     {"list_categoryids": [-2009030]}))[:5]
    out["mark"]  = (await call("get_parameters_values_for_element_ids",
                    {"list_elementIds": ids, "list_idParameters": [-1001203]}))[:1500]
    out["types"] = (await call("get_element_types_for_elementids",
                    {"list_elementIds": ids}))[:1500]
    out["grids"] = (await call("get_elements_by_category",
                    {"list_categoryids": [-2000220]}))[:1500]   # OST_Grids
    out["levels"]= (await call("get_elements_by_category",
                    {"list_categoryids": [-2000240]}))[:1500]   # OST_Levels
    wall_ids = rb._element_ids(await call("get_elements_by_category",
                    {"list_categoryids": [-2000011]}))[:3]
    out["wall_loc"] = (await call("get_location_for_element_ids",
                    {"list_elementIds": wall_ids}))[:1500]      # LocationCurve?
    out["units"] = (await call("get_all_project_units", {}))[:600]
    return out
print(json.dumps(rb._run(seq), indent=1)[:8000])
```

**Decision rules.** `wall_loc` shows two coordinate triples → link #3 solved.
`grids` returns ids **and** a curve+label read works → link #4 solved.
`mark` returns the Mark strings → link #2 solved. `families` inverts cleanly → link #1
solved. Four yeses → B1+B2 are a straight build. Any no → that field stays on the export
and gets named in `assumptions[]`.

**Paste the raw payloads into this document (§0.1 and §1) when you have them.** The table
above is honest about what is guessed; it must not stay guessed once Revit is open.

---

## 7. Recommendation

1. **Today:** ship **A2**. The founder gets exactly the flow he asked for — PDF in, Revit
   connected, compare runs, no JSON in sight — for ~4 h of work and **zero** risk to the
   106-MATCH baseline.
2. **First thing with Revit open:** run §6. It is 10 minutes and it converts this document's
   four ⚠️ rows into facts.
3. **Then, and only then:** B0.5 (the C# whitelist) and B1-B4, gated on the §B3 validation
   protocol.

The one hard item is still hard. It is now *specifically* hard — four named links, one named
blocker, and a probe that resolves all five in ten minutes.
