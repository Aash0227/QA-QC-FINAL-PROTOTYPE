# Hardcoded Project-Specific Data Report
## Revit Integration + Infrastructure Modules

**Scope:** 15 files in `C:\QA-QC-FINAL-PROTOTYPE-bkp\backend\app\`
**Date:** 2026-08-06

---

## 🔴 CRITICAL — Project-Specific Hardcoded Data

### 1. `revit_convert.py` — Line 268: Hardcoded Madera PDF Baseline Counts

```python
pdf_baseline = {"H1": 10, "H2": 21, "H3": 6, "H4": 17}
```

**What it hardcodes:** The exact expected hold-down counts for the Madera project's S-201 sheet. Every other project will be scored against Madera's numbers.

**Impact:** ANY non-Madera project gets bogus QA warnings like "H1: Revit body assemblies=5 vs PDF baseline=10".

**Fix:** Replace with `from .compare import _project_pdf_baseline` (same pattern already used in `control_points.py:21-36`). If no project baseline exists, skip the per-mark comparison entirely.

---

### 2. `revit_convert.py` — Lines 270, 321: Hardcoded Mark Names

```python
for mark in ("H1", "H2", "H3", "H4"):    # line 270
...
"by_mark": {m: body_by_mark.get(m, 0) for m in ("H1", "H2", "H3", "H4")},  # line 321
```

**What it hardcodes:** The Madera project's mark vocabulary. Any project with different marks (e.g., HD1-HD8, HTT1-HTT3) is invisible.

**Fix:** Derive marks dynamically from `body_by_mark.keys()` or from the project's PDF baseline when available.

---

### 3. `config.py` — Lines 107, 109: Hardcoded "madera" Project Name

```python
def _migrate_legacy_layout() -> None:
    """One-time: move flat artifacts/* into artifacts/projects/madera/."""
    legacy_marker = ARTIFACT_BASE / "element_list.json"
    if not legacy_marker.exists() or (PROJECTS_DIR / "madera").exists():
        return
    target = PROJECTS_DIR / "madera"
```

**What it hardcodes:** The migration target is always "madera". For a fresh install on a different project, this creates a "madera" folder.

**Impact:** Low (one-time migration), but pollutes the workspace with a Madera-named folder for non-Madera projects.

**Fix:** Use the active project slug from `ACTIVE_PROJECT_FILE`, or detect the legacy project name from the existing data.

---

### 4. `control_points.py` — Line 413: Test Assertion with Madera Total

```python
assert diag["pdf_baseline"]["total"] == 54
```

**What it hardcodes:** Test expects Madera's total of 54 hold-downs. The test data is synthetic but the assertion assumes Madera's baseline is loaded.

**Fix:** Make the test data self-consistent — set up a fake baseline in the test fixture and assert against that.

---

## 🟠 HIGH — Hardcoded Family Names / Regex Patterns

### 5. `revit_v3_adapter.py` — Lines 30-31: Simpson Hold-Down Family Regex

```python
HOLDOWN_FAMILY_RE = re.compile(r"(HTT|HD[UB]?)\s*_?(\d+)([A-Z]?)", re.IGNORECASE)
```

**What it hardcodes:** Only Simpson HD/HDU/HDB/HTT product families are recognized. Other manufacturers (MiTek, USP, etc.) are invisible.

**Fix:** Make configurable via env var `QAQC_HOLDOWN_FAMILY_RE` or a project config file. Fall back to the current regex.

---

### 6. `revit_v3_adapter.py` — Line 32: Anchor Bolt Family Regex

```python
BOLT_FAMILY_RE = re.compile(r"ANCHOR[_\s-]*BOLT", re.IGNORECASE)
```

**What it hardcodes:** Only families with "ANCHOR BOLT" in the name are classified as bolts. "J-Bolt", "Anchor_Rod", etc. are missed.

**Fix:** Make configurable or broaden to include common variants.

---

### 7. `revit_v3_adapter.py` — Line 78: Schedule Mark Regex

```python
_SCHED_MARK_RE = re.compile(r"^(?:H|HD|HDU|HTT|TD)-?\d{1,2}$", re.IGNORECASE)
```

**What it hardcodes:** Only Madera/Dogwood-style marks (H1, HD3, HDU6, HTT4, TD2) are recognized as schedule marks.

**Fix:** Make configurable via env var or project config.

---

### 8. `revit_v3_adapter.py` — Lines 36-37: Mark Normalization Regexes

```python
_MARK_SIMPLE_RE = re.compile(r"^([A-Z]+)-?0*(\d+)", re.IGNORECASE)
_MARK_TYPENUM_RE = re.compile(r"^([A-Z]+)(\d+)", re.IGNORECASE)
```

**What it hardcodes:** Mark normalization assumes letter-prefix + number pattern (P-01 → P-1, C2-01-02 → C-2).

**Impact:** Moderate — works for most structural marks but may fail on non-standard naming.

**Fix:** Low priority; these are general-purpose patterns.

---

### 9. `revit_bridge.py` — Line 40: Default Benchmark Family

```python
DEFAULT_BENCHMARK_FAMILY = "mwfBenchmark"
```

**What it hardcodes:** The family name used for benchmark marker placement. Already has env override (`QAQC_BENCHMARK_FAMILY`), but the default is project-specific.

**Fix:** Already configurable. Consider changing the default to something more generic or requiring explicit configuration.

---

### 10. `revit_v3_adapter.py` — Lines 243-248: Hold-Down Categories

```python
HOLDOWN_CATEGORIES = (
    "Structural Connections",
    "Structural Foundation",
    "Generic Models",
    "Structural Framing",
)
```

**What it hardcodes:** The Revit categories searched for hold-down elements. Other categories (e.g., "Structural Columns") are not searched.

**Fix:** Make configurable via env var or project config.

---

## 🟡 MEDIUM — Hardcoded File Paths / Network Addresses

### 11. `revit_bridge.py` — Lines 34-37: Nonica MCP Executable Path

```python
NONICA_EXE = os.environ.get(
    "NONICA_MCP_EXE",
    r"C:\NONICAPRO\OtherFiles\System\Core\net8.0-windows\RevitMCPConnection.exe",
)
```

**What it hardcodes:** The default installation path for Nonica PRO. Already has env override.

**Fix:** Already configurable via `NONICA_MCP_EXE`. Consider removing the default and requiring explicit configuration.

---

### 12. `revit_bridge.py` — Line 419: Revit MCP Socket Address

```python
REVIT_MCP_ADDR = os.environ.get("REVIT_MCP_ADDR", "127.0.0.1:8080")
```

**What it hardcodes:** Default host:port for the open-source revit-mcp add-in. Already has env override.

**Fix:** Already configurable.

---

### 13. `openrouter.py` — Line 96: HTTP Referer Header

```python
"HTTP-Referer": "https://localhost/qa-qc-final-prototype",
```

**What it hardcodes:** The referer sent to OpenRouter. Not project-specific but reveals the prototype name.

**Fix:** Make configurable via env var `QAQC_OPENROUTER_REFERER` or use a generic value.

---

## 🟡 MEDIUM — Hardcoded Thresholds / Magic Numbers

### 14. `scene3d.py` — Line 21: Assumed Wall Height

```python
ASSUMED_WALL_HEIGHT_FT = 10.0
```

**What it hardcodes:** Default wall height when the export doesn't carry real height data. Used for 3D rendering.

**Impact:** Walls render at 10 ft even if the real height is 8 ft or 12 ft. Already flagged as `height_assumed=true` in the output.

**Fix:** Make configurable via env var `QAQC_ASSUMED_WALL_HEIGHT_FT` or project config.

---

### 15. `revit_bridge.py` — Line 38: Mark Parameter ID

```python
MARK_PARAM_ID = -1001203        # built-in Revit "Mark" parameter
```

**What it hardcodes:** The Revit built-in parameter ID for "Mark". This is a Revit API constant, not project-specific.

**Fix:** No fix needed — this is a Revit standard.

---

### 16. `revit_bridge.py` — Line 39: Readback Tolerance

```python
READBACK_TOLERANCE_FT = 0.05    # placed marker must land within this of intent
```

**What it hardcodes:** 0.05 ft (0.6 inch) tolerance for benchmark placement verification.

**Fix:** Make configurable via env var `QAQC_READBACK_TOLERANCE_FT`.

---

### 17. `revit_bridge.py` — Line 242: Structural Connections Category ID

```python
STRUCT_CONNECTIONS_CAT = -2009030   # OST_StructConnections (holdown hardware)
```

**What it hardcodes:** Revit BuiltInCategory ID for Structural Connections. This is a Revit API constant.

**Fix:** No fix needed — Revit standard.

---

### 18. `revit_bridge.py` — Lines 517-523: Scene Categories

```python
SCENE_CATEGORIES = (
    ("walls", -2000011, "OST_Walls"),
    ("framing", -2001320, "OST_StructuralFraming"),
    ("columns", -2001330, "OST_StructuralColumns"),
    ("connections", -2009030, "OST_StructConnections"),
)
```

**What it hardcodes:** Which Revit categories are rendered in the live 3D massing view.

**Fix:** Make configurable via project config or env var.

---

### 19. `revit_bridge.py` — Line 524: Max Elements Per Category

```python
SCENE_MAX_PER_CATEGORY = 3000
```

**What it hardcodes:** Cap on elements rendered per category to prevent UI stalls.

**Fix:** Make configurable via env var `QAQC_SCENE_MAX_PER_CATEGORY`.

---

### 20. `revit_bridge.py` — Line 525: Bounding Box Chunk Size

```python
SCENE_BBOX_CHUNK = 300
```

**What it hardcodes:** Number of element IDs per `get_boundingboxes_for_element_ids` call.

**Fix:** Make configurable via env var `QAQC_SCENE_BBOX_CHUNK`.

---

### 21. `revit_v3_adapter.py` — Line 33: Cluster Tolerance

```python
CLUSTER_TOL_FT = 2.0
```

**What it hardcodes:** 2 ft proximity threshold for clustering hold-down assembly members.

**Fix:** Make configurable via env var `QAQC_CLUSTER_TOL_FT`.

---

### 22. `revit_convert.py` — Line 24: Member Attach Distance

```python
MEMBER_ATTACH_MAX_FT = 3.0
```

**What it hardcodes:** Max distance for attaching evidence members (anchor bolts, offsets) to a body.

**Fix:** Make configurable via env var `QAQC_MEMBER_ATTACH_MAX_FT`.

---

### 23. `revit_convert.py` — Line 21: Member Keywords

```python
MEMBER_KEYWORDS = ("anchor", "offset", "screw", "plate", "nut", "washer", "stud")
```

**What it hardcodes:** Keywords that identify a family as an "evidence member" rather than a body.

**Fix:** Make configurable via env var `QAQC_MEMBER_KEYWORDS` (comma-separated).

---

### 24. `benchmark_workflow.py` — Lines 49-50: Vector Detection Radii

```python
VECTOR_R_MIN, VECTOR_R_MAX = 6.0, 30.0
VECTOR_TEXT_NEAR_PT = 60.0
```

**What it hardcodes:** Crosshair symbol detection parameters (circle radius 6-30 pt, text within 60 pt).

**Fix:** Make configurable via env vars `QAQC_VECTOR_R_MIN`, `QAQC_VECTOR_R_MAX`, `QAQC_VECTOR_TEXT_NEAR_PT`.

---

### 25. `benchmark_workflow.py` — Line 548: Stamp Tolerance

```python
STAMP_TOLERANCE_PT = 3.0
```

**What it hardcodes:** 3 pt tolerance for verifying benchmark stamp placement.

**Fix:** Make configurable via env var `QAQC_STAMP_TOLERANCE_PT`.

---

### 26. `benchmark_workflow.py` — Lines 354-355: Grid Bubble Detection

```python
band_fraction: float = 0.14,
tol_pt: float = 8.0,
```

**What it hardcodes:** Grid bubble detection parameters (14% of page dimension for edge band, 8 pt clustering tolerance).

**Fix:** Make configurable via env vars or function parameters.

---

## 🟢 LOW — Cache TTLs / Buffer Sizes (Not Project-Specific)

### 27. `revit_bridge.py` — Lines 244, 527, 739, 745: Cache TTLs

```python
_CONN_CACHE_TTL_S = 300.0       # line 244
_SCENE_CACHE_TTL_S = 60.0       # line 527
_STATUS_CACHE_TTL_S = 30.0      # line 739
_STATUS_CACHE_OFFLINE_TTL_S = 300.0  # line 745
```

**What they hardcode:** Cache time-to-live values. Not project-specific, but could be tuned per deployment.

**Fix:** Make configurable via env vars if needed.

---

### 28. `progress.py` — Line 24: Event Ring Buffer Size

```python
_MAX_EVENTS = 500
```

**What it hardcodes:** Max events kept in memory for the SSE progress stream.

**Fix:** Make configurable via env var `QAQC_MAX_EVENTS`.

---

### 29. `phase_summary.py` — Line 36: Systematic Sample Cap

```python
SYSTEMATIC_SAMPLE_CAP = 30
```

**What it hardcodes:** Max mismatches sampled for systematic-shift detection.

**Fix:** Make configurable via env var `QAQC_SYSTEMATIC_SAMPLE_CAP`.

---

### 30. `maintenance.py` — Lines 17-20: Log/Evidence Caps

```python
EVIDENCE_CAP_MB = float(os.environ.get("QAQC_EVIDENCE_CAP_MB", "512"))
LOG_MAX_BYTES = int(os.environ.get("QAQC_LOG_MAX_BYTES", str(5 * 1024 * 1024)))
LOG_BACKUPS = int(os.environ.get("QAQC_LOG_BACKUPS", "5"))
```

**What they hardcode:** Default evidence crop cap (512 MB), log rotation (5 MB × 5 backups). Already env-overridable.

**Fix:** Already configurable.

---

### 31. `openrouter.py` — Lines 46-48, 104, 131: LLM Call Defaults

```python
max_tokens: int = 4000,
temperature: float = 0.1,
timeout: float = 90.0,
...
max_attempts = 3
delay = 2 ** attempt  # 1s, 2s, 4s
```

**What they hardcode:** Default LLM call parameters and retry logic.

**Fix:** Make configurable via env vars or function parameters.

---

### 32. `export_watch.py` — Line 26: Export Filename Patterns

```python
PATTERNS = ("revit_export*.json", "raw_revit_export*.json")
```

**What it hardcodes:** The filename patterns the auto-ingest watcher looks for.

**Fix:** Make configurable via env var `QAQC_EXPORT_PATTERNS` (os.pathsep-joined).

---

## 📊 Summary

| Severity | Count | Description |
|----------|-------|-------------|
| 🔴 CRITICAL | 4 | Hardcoded Madera baseline counts and mark names |
| 🟠 HIGH | 6 | Hardcoded family regexes and category lists |
| 🟡 MEDIUM | 13 | Hardcoded paths, thresholds, magic numbers |
| 🟢 LOW | 10 | Cache TTLs, buffer sizes (already env-overridable) |

**Total hardcoded instances found: 33**

---

## 🎯 Priority Fixes

1. **`revit_convert.py:268`** — Replace hardcoded `pdf_baseline` with project-aware lookup (same pattern as `control_points.py:21-36`)
2. **`revit_convert.py:270,321`** — Derive mark names dynamically from data, not from hardcoded tuple
3. **`config.py:107,109`** — Use active project slug instead of hardcoded "madera" in migration
4. **`revit_v3_adapter.py:30-31,78`** — Make family/mark regexes configurable via env vars
5. **`scene3d.py:21`** — Make `ASSUMED_WALL_HEIGHT_FT` configurable
6. **`revit_bridge.py:40`** — Consider removing the "mwfBenchmark" default or documenting it more clearly

---

## ✅ Already Configurable (No Action Needed)

- `NONICA_MCP_EXE` (env var)
- `REVIT_MCP_ADDR` (env var)
- `QAQC_BENCHMARK_FAMILY` (env var)
- `QAQC_EXPORT_WATCH_DIR` (env var)
- `QAQC_EVIDENCE_CAP_MB` (env var)
- `QAQC_LOG_FILE`, `QAQC_LOG_MAX_BYTES`, `QAQC_LOG_BACKUPS` (env vars)
- `OPENROUTER_API_KEY`, `OPENROUTER_REASONING_MODEL`, `OPENROUTER_BASE_URL` (env vars)
- `QAQC_AUTH_TOKEN` (env var)

---

## 📝 Notes

- **`revit_ids.py`** — No hardcoded project-specific data. The UniqueId decoding algorithm is a Revit standard.
- **`benchmarks.py`** — Just a re-export shim, no hardcoded data.
- **`main.py`** — `STEP_BY_PATH` is structural (endpoint mapping), not project-specific.
- **`control_points.py:21-36`** — Already uses project-aware baseline lookup via `compare._project_pdf_baseline()`. This is the pattern to follow for `revit_convert.py`.
