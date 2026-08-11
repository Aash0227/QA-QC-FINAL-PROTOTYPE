# Hardcoded Project Data — Complete Audit Report
**Date:** 2026-08-06  
**Scope:** 32 backend modules + frontend  
**Total hardcoded instances found:** 63

---

## Executive Summary

The codebase contains **63 instances of hardcoded project-specific data** that prevent it from working generically across different construction projects. The largest offenders are:

1. **s201_detector.py** (17 instances) — Frozen Madera-specific detector
2. **revit_convert.py** (4 instances) — Hardcoded Madera baseline counts
3. **normalization.py** (3 instances) — Madera-specific mark vocabulary
4. **pdf_intelligence.py** (2 instances) — Madera expected counts
5. **revit_v3_adapter.py** (6 instances) — Simpson-only family regexes

**Impact:** System only works correctly for Madera project. All other projects get wrong QA warnings, missed elements, or crashes.

---

## 🔴 CRITICAL — Will Break Other Projects (4 instances)

### 1. revit_convert.py:268 — Hardcoded Madera PDF Baseline
```python
pdf_baseline = {"H1": 10, "H2": 21, "H3": 6, "H4": 17}
```
**Impact:** Every non-Madera project gets bogus QA warnings like "H1: Revit=5 vs PDF baseline=10"  
**Fix:** Replace with `from .compare import _project_pdf_baseline` (pattern already exists in control_points.py:21-36)

### 2. revit_convert.py:270,321 — Hardcoded Mark Names
```python
for mark in ("H1", "H2", "H3", "H4"):  # line 270
"by_mark": {m: body_by_mark.get(m, 0) for m in ("H1", "H2", "H3", "H4")}  # line 321
```
**Impact:** Any project with different marks (HD1-HD8, HTT1-HTT3) is invisible  
**Fix:** Derive marks dynamically from `body_by_mark.keys()` or project PDF baseline

### 3. config.py:107,109 — Hardcoded "madera" Migration Target
```python
def _migrate_legacy_layout() -> None:
    """One-time: move flat artifacts/* into artifacts/projects/madera/."""
    legacy_marker = ARTIFACT_BASE / "element_list.json"
    if not legacy_marker.exists() or (PROJECTS_DIR / "madera").exists():
        return
    target = PROJECTS_DIR / "madera"
```
**Impact:** Fresh install on different project creates "madera" folder  
**Fix:** Use active project slug from ACTIVE_PROJECT_FILE

### 4. control_points.py:413 — Test Assertion with Madera Total
```python
assert diag["pdf_baseline"]["total"] == 54
```
**Impact:** Test assumes Madera's baseline is loaded  
**Fix:** Make test data self-consistent with fake baseline in fixture

---

## 🟠 HIGH — Major Functionality Issues (19 instances)

### PDF Intelligence Modules

#### 5. pdf_intelligence.py:49,65-66 — Hardcoded Expected Baseline
```python
baseline = {"H1": 10, "H2": 21, "H3": 6, "H4": 17}
"matches_expected_baseline": summary.get("by_type") == baseline and summary.get("total") == 54,
```
**Impact:** QA gate only passes for Madera  
**Fix:** Remove or make optional/config-driven

#### 6. pdf_intelligence.py:36-37,45,54 — Hardcoded Sheet Number
```python
"sheet_number": "S-201",
sheet_number="S-201",
```
**Impact:** Always assumes foundation plan is "S-201"  
**Fix:** Discover dynamically (generic_page_intelligence.py already does this)

#### 7. normalization.py:6-11 — Hardcoded Mark-to-Product Mapping
```python
CORE_TOKEN_TO_MARK = {"HDU6": "H1", "HDU11": "H2", "HD10S": "H3", "HD15B": "H4"}
```
**Impact:** Only Madera's Revit family types recognized  
**Fix:** Load from project config or learn from Revit memory

#### 8. normalization.py:61 — Hardcoded Mark Pattern
```python
re.fullmatch(r"H[1-4]", cleaned)
```
**Impact:** Only recognizes H1-H4 marks  
**Fix:** Make pattern configurable or learn from data

#### 9. normalization.py:132-141 — Hardcoded Suffix List
```python
("WITHANCHOR", "WITHBOLT1", "WITHBOLT2", "WASHER", "NUT", "PLATE", "SCREW")
```
**Impact:** Madera-specific family naming  
**Fix:** Make configurable or derive from data

#### 10. pdf_convert.py:13 — Duplicate MARK_TO_CORE_TOKEN
```python
MARK_TO_CORE_TOKEN = {"H1": "HDU6", "H2": "HDU11", "H3": "HD10S", "H4": "HD15B"}
```
**Impact:** Same Madera mapping duplicated  
**Fix:** Single source of truth — load from config

#### 11. pdf_convert.py:32-38 — Hardcoded LLM Prompt
```python
system_prompt = (
    "...confirm the mapping between PDF plan marks (H1-H4) and "
    "canonical core tokens (HDU6, HDU11, HD10S, HD15B). Reply ONLY with JSON "
    '{"mapping":{"H1":"..","H2":"..","H3":"..","H4":".."},...}.'
)
```
**Impact:** LLM prompt assumes H1-H4 marks  
**Fix:** Generate prompt dynamically from learned vocabulary

### Revit Integration Modules

#### 12. revit_v3_adapter.py:30-31 — Simpson-Only Family Regex
```python
HOLDOWN_FAMILY_RE = re.compile(r"(HTT|HD[UB]?)\s*_?(\d+)([A-Z]?)", re.IGNORECASE)
```
**Impact:** Only Simpson HD/HDU/HDB/HTT families recognized. MiTek, USP invisible  
**Fix:** Make configurable via env var `QAQC_HOLDOWN_FAMILY_RE`

#### 13. revit_v3_adapter.py:32 — Anchor Bolt Family Regex
```python
BOLT_FAMILY_RE = re.compile(r"ANCHOR[_\s-]*BOLT", re.IGNORECASE)
```
**Impact:** "J-Bolt", "Anchor_Rod" missed  
**Fix:** Make configurable or broaden pattern

#### 14. revit_v3_adapter.py:78 — Schedule Mark Regex
```python
_SCHED_MARK_RE = re.compile(r"^(?:H|HD|HDU|HTT|TD)-?\d{1,2}$", re.IGNORECASE)
```
**Impact:** Only Madera/Dogwood-style marks recognized  
**Fix:** Make configurable via env var or project config

#### 15. revit_v3_adapter.py:243-248 — Hold-Down Categories
```python
HOLDOWN_CATEGORIES = (
    "Structural Connections",
    "Structural Foundation",
    "Generic Models",
    "Structural Framing",
)
```
**Impact:** Other categories not searched  
**Fix:** Make configurable via env var or project config

#### 16. revit_bridge.py:40 — Default Benchmark Family
```python
DEFAULT_BENCHMARK_FAMILY = "mwfBenchmark"
```
**Impact:** Default is project-specific (already has env override)  
**Fix:** Consider removing default or requiring explicit configuration

#### 17. element_registry.py:31 — Hardcoded Sheet Number
```python
compare_sheet="S-201"
```
**Impact:** Madera's holdown plan sheet number  
**Fix:** Discover dynamically or make configurable

#### 18. wall_match.py:24-25,31-34 — Madera-Tuned Thresholds
```python
SW_MATCH_MAX_PT = 60.0
SW_LOCATION_MISMATCH_MAX_PT = 120.0
LEADER_MIN_LEN = 14.0
LEADER_MAX_LEN = 80.0
LEADER_SLOPE_MIN = 0.3
LEADER_SLOPE_MAX = 3.5
```
**Impact:** Thresholds "tuned on Madera S-202 ground truth"  
**Fix:** Make configurable via env vars

#### 19. compare.py:23-24 — Scale-Dependent Thresholds
```python
MATCH_MAX_PT = 16.0
LOCATION_MISMATCH_MAX_PT = 40.0
```
**Impact:** Assumes specific drawing scale  
**Fix:** Scale by registration or make configurable

#### 20. registration.py:347 — Expected Scale
```python
expected_scale_pt_per_ft: float = 18.0
```
**Impact:** Assumes 1/8"=1'-0" scale  
**Fix:** Make configurable or derive from registration

#### 21. scene3d.py:21 — Assumed Wall Height
```python
ASSUMED_WALL_HEIGHT_FT = 10.0
```
**Impact:** Walls render at 10 ft even if real height differs  
**Fix:** Make configurable via env var `QAQC_ASSUMED_WALL_HEIGHT_FT`

#### 22. revit_bridge.py:34-37 — Nonica MCP Path
```python
NONICA_EXE = os.environ.get(
    "NONICA_MCP_EXE",
    r"C:\NONICAPRO\OtherFiles\System\Core\net8.0-windows\RevitMCPConnection.exe",
)
```
**Impact:** Default path is Madera-specific (already has env override)  
**Fix:** Already configurable, consider removing default

#### 23. revit_bridge.py:419 — Revit MCP Address
```python
REVIT_MCP_ADDR = os.environ.get("REVIT_MCP_ADDR", "127.0.0.1:8080")
```
**Impact:** Default is localhost (already has env override)  
**Fix:** Already configurable

---

## 🟡 MEDIUM — Moderate Impact (27 instances)

### s201_detector.py — Frozen Madera-Specific Detector (17 instances)

#### 24. Line 21 — PLAN_BBOX
```python
PLAN_BBOX: BBox = (40, 60, 2250, 1660)
```
**Impact:** Exact bounding box of Madera's plan area  
**Fix:** Accept as parameter (already partially done)

#### 25. Lines 22-27 — S201_TABLE_BBOXES
```python
S201_TABLE_BBOXES: tuple[BBox, ...] = (
    (1760, 725, 2250, 1045),
    (1785, 1435, 2250, 1590),
    (1875, 1035, 2250, 1425),
    (1460, 1225, 1790, 1650),
)
```
**Impact:** Four exact table bounding boxes on Madera's S-201  
**Fix:** Use generic `schedule_tables.discover_tables()`

#### 26. Lines 28-33 — HOLDOWN_ROW_BANDS
```python
HOLDOWN_ROW_BANDS = (
    ("H1", 1504, 1524),
    ("H2", 1524, 1544),
    ("H3", 1544, 1565),
    ("H4", 1564, 1586),
)
```
**Impact:** Exact y-coordinate bands for Madera's schedule rows  
**Fix:** Discover dynamically from table structure

#### 27. Lines 34-37 — HOLDOWN_RE
```python
HOLDOWN_RE = re.compile(
    r"^(?:(?:\((?P<count_paren>\d+)\)|(?P<count_plain>\d+))\s*)?(?P<label>H[1-4])$",
    re.IGNORECASE,
)
```
**Impact:** Only matches H1-H4 marks  
**Fix:** Already partially addressed via `_holdown_re_for(mark_pattern)`

#### 28. Lines 52-57 — MARK_TO_CORE_TOKEN
```python
MARK_TO_CORE_TOKEN = {
    "H1": "HDU6",
    "H2": "HDU11",
    "H3": "HD10S",
    "H4": "HD15B",
}
```
**Impact:** Madera-specific mark→product mapping  
**Fix:** Load from project config or learn from Revit memory

#### 29. Lines 59-84 — DEFAULT_HOLDOWN_SCHEDULE
```python
DEFAULT_HOLDOWN_SCHEDULE = {
    "H1": {
        "holdown_type": "S/HDU6",
        "stud_fasteners": "(12) #14",
        "anchor_bolt": '5/8" (SABR)',
        "min_embedment_depth_in_concrete": '24"',
    },
    "H2": { ... },
    "H3": { ... },
    "H4": { ... },
}
```
**Impact:** Complete Madera holdown schedule used as fallback  
**Fix:** Extract from PDF schedule tables or error for non-Madera

#### 30. Lines 350-353 — Column x-ranges
```python
holdown_type = _text_in_col(row_words, 1888, 1952)
fasteners = _text_in_col(row_words, 1954, 2024)
anchor_bolt = _text_in_col(row_words, 2030, 2110)
embedment = _text_in_col(row_words, 2160, 2195)
```
**Impact:** Exact x-coordinate column boundaries for Madera's table  
**Fix:** Derive from discovered table columns

#### 31. Line 347 — x-range filter
```python
row_words = [w for w in words if y0 <= _center(_bbox(w))[1] <= y1 and 1780 <= _center(_bbox(w))[0] <= 2235]
```
**Impact:** x-range 1780-2235 for Madera's schedule region  
**Fix:** Use discovered table bbox x-extent

#### 32. Lines 364-365 — H4 OCR fixup
```python
if rows.get("H4", {}).get("stud_fasteners") == '(4) 3 4" DIA':
    rows["H4"]["stud_fasteners"] = '(4) 3/4" DIA'
```
**Impact:** Specific OCR error correction for Madera's H4  
**Fix:** Generic OCR cleanup pattern

#### 33. Lines 737-740 — Page-size heuristic
```python
def _table_bboxes(page: fitz.Page) -> list[BBox]:
    if page.rect.width > 2000 and page.rect.height > 1500:
        return list(S201_TABLE_BBOXES)
    return []
```
**Impact:** Assumes Madera's page size means Madera layout  
**Fix:** Use `schedule_tables.discover_tables()`

#### 34. Lines 527-559 — Vector/geometry thresholds
```python
(4 <= width <= 22 and 4 <= height <= 22)
if not 10 <= length <= 220:
if dx < 8 or dy < 8:
if not 0.25 <= slope <= 4:
if fill and max(fill) < 0.25 and rect:
```
**Impact:** Madera-specific leader line/marker size assumptions  
**Fix:** Reasonable heuristics but could be parameterized

#### 35. Lines 648-677 — Distance/proximity thresholds
```python
if min(distance_a, distance_b) >= 55 and distance_segment >= 14:
if _distance(far, label_center) < 25:
if all(_distance(point, existing) > 22 for existing in out):
if 25 < _distance(marker.center, label_center) < 85:
horizontally_paired = abs(a[1] - b[1]) < 12 and 20 <= abs(a[0] - b[0]) <= 45
```
**Impact:** Madera-specific leader proximity and marker pair distances  
**Fix:** Reasonable heuristics but could be parameterized

#### 36. Lines 498-500 — Count-prefix proximity
```python
if abs(ocy - wcy) < 8 and 0 <= gap < (55 if not text.startswith("(") else 65):
```
**Impact:** Y-alignment tolerance and gap thresholds for count prefixes  
**Fix:** Reasonable heuristic, could scale by page dimensions

#### 37. Lines 504-517 — Detail-reference filter
```python
if not re.match(r"^S-\d{3}$", text, re.IGNORECASE):
if abs(scx - ncx) < 55 and 0 < scy - ncy < 45:
```
**Impact:** Only filters "S-NNN" sheet references  
**Fix:** Use detected sheet number pattern

#### 38. Line 718 — Instance expansion spacing
```python
spacing = 18.0
```
**Impact:** Fixed 18pt spacing for synthetic instance expansion  
**Fix:** Derive from label font size or nearby mark spacing

#### 39. Lines 727-732 — Crop padding and DPI
```python
bbox = (
    max(0, min(x, lx0) - 90),
    max(0, min(y, ly0) - 90),
    min(float(page.rect.width), max(x, lx1) + 90),
    min(float(page.rect.height), max(y, ly1) + 90),
)
pix = page.get_pixmap(matrix=fitz.Matrix(180 / 72, 180 / 72), ...)
```
**Impact:** 90pt crop padding and 180 DPI render  
**Fix:** Minor — could be config-driven

#### 40. Lines 127-129 — S-201 page location logic
```python
if not re.search(r"S-?201", text, re.IGNORECASE):
marks = len(re.findall(r"\bH[1-4]\b", text))
```
**Impact:** Only looks for "S-201" and "H[1-4]" marks  
**Fix:** Use learned sheet numbering and mark vocabulary

### Other Modules

#### 41. revit_convert.py:24 — Member Attach Distance
```python
MEMBER_ATTACH_MAX_FT = 3.0
```
**Fix:** Make configurable via env var `QAQC_MEMBER_ATTACH_MAX_FT`

#### 42. revit_convert.py:21 — Member Keywords
```python
MEMBER_KEYWORDS = ("anchor", "offset", "screw", "plate", "nut", "washer", "stud")
```
**Fix:** Make configurable via env var `QAQC_MEMBER_KEYWORDS`

#### 43. revit_v3_adapter.py:33 — Cluster Tolerance
```python
CLUSTER_TOL_FT = 2.0
```
**Fix:** Make configurable via env var `QAQC_CLUSTER_TOL_FT`

#### 44. benchmark_workflow.py:49-50 — Vector Detection Radii
```python
VECTOR_R_MIN, VECTOR_R_MAX = 6.0, 30.0
VECTOR_TEXT_NEAR_PT = 60.0
```
**Fix:** Make configurable via env vars

#### 45. benchmark_workflow.py:548 — Stamp Tolerance
```python
STAMP_TOLERANCE_PT = 3.0
```
**Fix:** Make configurable via env var

#### 46. benchmark_workflow.py:354-355 — Grid Bubble Detection
```python
band_fraction: float = 0.14,
tol_pt: float = 8.0,
```
**Fix:** Make configurable via env vars

#### 47. revit_bridge.py:39 — Readback Tolerance
```python
READBACK_TOLERANCE_FT = 0.05
```
**Fix:** Make configurable via env var

#### 48. revit_bridge.py:524 — Max Elements Per Category
```python
SCENE_MAX_PER_CATEGORY = 3000
```
**Fix:** Make configurable via env var

#### 49. revit_bridge.py:525 — Bounding Box Chunk Size
```python
SCENE_BBOX_CHUNK = 300
```
**Fix:** Make configurable via env var

#### 50. openrouter.py:96 — HTTP Referer
```python
"HTTP-Referer": "https://localhost/qa-qc-final-prototype",
```
**Fix:** Make configurable via env var

---

## 🟢 LOW — Minor/Already Configurable (13 instances)

### Cache TTLs / Buffer Sizes (Not Project-Specific)

51. revit_bridge.py:244 — `_CONN_CACHE_TTL_S = 300.0`
52. revit_bridge.py:527 — `_SCENE_CACHE_TTL_S = 60.0`
53. revit_bridge.py:739 — `_STATUS_CACHE_TTL_S = 30.0`
54. revit_bridge.py:745 — `_STATUS_CACHE_OFFLINE_TTL_S = 300.0`
55. progress.py:24 — `_MAX_EVENTS = 500`
56. phase_summary.py:36 — `SYSTEMATIC_SAMPLE_CAP = 30`
57. maintenance.py:17-20 — `EVIDENCE_CAP_MB`, `LOG_MAX_BYTES`, `LOG_BACKUPS` (already env-overridable)
58. openrouter.py:46-48,104,131 — `max_tokens`, `temperature`, `timeout`, `max_attempts`
59. export_watch.py:26 — `PATTERNS = ("revit_export*.json", "raw_revit_export*.json")`

### Truly Generic Modules (No Hardcoded Data)

60. schedule_tables.py — CATEGORY_HEADERS and CATEGORY_MARK_RE are built-in defaults but extensible
61. leader_anchor.py — Geometric thresholds assume standard scale (reasonable)
62. generic_page_intelligence.py — **TRULY GENERIC** (derives everything dynamically)
63. element_detector.py — DETAIL_REF_RE slightly biased but broad enough

---

## Summary by Module

| Module | Hardcoded Instances | Severity |
|--------|-------------------|----------|
| **s201_detector.py** | 17 | 🔴 CRITICAL (frozen Madera detector) |
| **revit_convert.py** | 4 | 🔴 CRITICAL |
| **normalization.py** | 3 | 🟠 HIGH |
| **pdf_intelligence.py** | 2 | 🟠 HIGH |
| **revit_v3_adapter.py** | 6 | 🟠 HIGH |
| **pdf_convert.py** | 2 | 🟠 HIGH |
| **compare.py** | 2 | 🟠 HIGH |
| **registration.py** | 1 | 🟠 HIGH |
| **wall_match.py** | 2 | 🟠 HIGH |
| **element_registry.py** | 1 | 🟠 HIGH |
| **scene3d.py** | 1 | 🟠 HIGH |
| **revit_bridge.py** | 8 | 🟡 MEDIUM |
| **benchmark_workflow.py** | 3 | 🟡 MEDIUM |
| **config.py** | 1 | 🔴 CRITICAL |
| **control_points.py** | 1 | 🔴 CRITICAL |
| **openrouter.py** | 1 | 🟡 MEDIUM |
| **Other** | 8 | 🟢 LOW |

---

## Priority Fix Order

### Phase 1: Critical (This Week)
1. **revit_convert.py:268** — Replace hardcoded pdf_baseline with project-aware lookup
2. **revit_convert.py:270,321** — Derive mark names dynamically
3. **config.py:107,109** — Use active project slug instead of "madera"
4. **pdf_intelligence.py:49,65-66** — Remove hardcoded baseline check or make optional
5. **pdf_intelligence.py:36-37,45,54** — Discover sheet number dynamically

### Phase 2: High (Next Sprint)
6. **normalization.py:6-11,61,132-141** — Make mark vocabulary configurable/learnable
7. **revit_v3_adapter.py:30-31,32,78,243-248** — Make family regexes configurable via env vars
8. **pdf_convert.py:13,32-38** — Single source of truth for MARK_TO_CORE_TOKEN
9. **compare.py:23-24** — Scale thresholds by registration or make configurable
10. **registration.py:347** — Make expected_scale configurable
11. **wall_match.py:24-25,31-34** — Make thresholds configurable via env vars
12. **element_registry.py:31** — Discover compare_sheet dynamically
13. **scene3d.py:21** — Make ASSUMED_WALL_HEIGHT_FT configurable

### Phase 3: Medium (Backlog)
14. **s201_detector.py** — Keep frozen for Madera, document as Madera-specific. All new projects use generic path.
15. **revit_bridge.py** — Make remaining thresholds configurable via env vars
16. **benchmark_workflow.py** — Make detection parameters configurable

### Phase 4: Low (Nice-to-Have)
17. Cache TTLs, buffer sizes — Make configurable if needed for tuning

---

## Already Configurable (No Action Needed)

✅ `NONICA_MCP_EXE` (env var)  
✅ `REVIT_MCP_ADDR` (env var)  
✅ `QAQC_BENCHMARK_FAMILY` (env var)  
✅ `QAQC_EXPORT_WATCH_DIR` (env var)  
✅ `QAQC_EVIDENCE_CAP_MB` (env var)  
✅ `QAQC_LOG_FILE`, `QAQC_LOG_MAX_BYTES`, `QAQC_LOG_BACKUPS` (env vars)  
✅ `OPENROUTER_API_KEY`, `OPENROUTER_REASONING_MODEL`, `OPENROUTER_BASE_URL` (env vars)  
✅ `QAQC_AUTH_TOKEN` (env var)

---

## Key Architectural Insight

**The generic path is correctly implemented.** `generic_page_intelligence.py` derives everything dynamically:
- Sheet number from `choose_foundation_sheet()` (most holdown marks)
- Mark pattern from learned vocabulary
- plan_bbox from page dimensions
- table_bboxes from discovered tables

**The problem:** The frozen `s201_detector.py` is still called by the generic path with additive parameters, but it contains 17 hardcoded Madera values that can't be overridden.

**Solution:** Either:
1. Keep s201_detector.py frozen for Madera, ensure all new projects use generic path
2. Refactor s201_detector.py to accept all hardcoded values as parameters
3. Replace s201_detector.py with a fully generic detector

**Recommendation:** Option 1 (keep frozen, document clearly, use generic path for new projects)

---

## Verification

To verify the system works generically after fixes:
1. Create a new project with different mark vocabulary (e.g., HD1-HD8)
2. Upload PDF + Revit JSON
3. Run full pipeline
4. Verify no Madera-specific warnings appear
5. Verify all elements detected correctly

---

**Report generated:** 2026-08-06  
**Next action:** Phase 1 fixes (critical hardcoded data removal)
