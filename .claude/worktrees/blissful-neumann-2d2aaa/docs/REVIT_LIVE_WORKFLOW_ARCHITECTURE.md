# Revit Live Workflow Architecture

> ⚠️ **CORRECTION (2026-07-27):** Appendix A and §4.x cite MCP tools that do
> not exist in the Nonica connector (`operate_element`, `send_code_to_revit`).
> Use `set_user_selection_in_revit` / `set_isolated_elements_in_view` /
> `set_additional_property_for_all_elements` instead; there is NO zoom tool.
> Phase-1 equivalents shipped 2026-07-27 inside `routers/revit.py` (not the
> new-router layout this doc proposes): POST /api/revit/highlight,
> GET /api/revit/selection, GET /api/revit/lookup/{element_id}.

**Version:** 1.0  
**Date:** 2026-07-27  
**Status:** Design Phase — Phase 1 shipped 2026-07-27 (see correction note)

---

## 1. Executive Summary

This document describes the complete solution architecture for transitioning the QA-QC prototype from a **JSON-export-based workflow** to a **live Revit-integrated workflow**. The new system eliminates the need for manual JSON exports, enables real-time bidirectional communication between the webapp and Revit, and adds AI-powered element explanations.

**Key Capabilities:**
- PDF-only upload workflow (no manual Revit JSON export required)
- Live Revit model queries via Nonica API
- Real-time coordinate comparison (PDF ↔ Revit)
- "Show in Revit" highlighting from web UI
- AI-generated explanations per element
- Bidirectional status sync (confirm/false alarm from Revit → webapp)

---

## 2. Current System State

### Existing Workflow
```
1. Upload PDF
2. Extract PDF data (holdowns, shear walls, dimensions)
3. Upload Revit JSON export (manual step)
4. AI-convert JSON to internal format
5. Run coordinate registration/calibration
6. Compare PDF vs Revit elements
7. Display results in web UI (3D viewer + table + PDF overlay)
```

### Current Limitations
- **Manual JSON export**: User must export Revit model to JSON, then upload
- **Stale data**: JSON export is a snapshot; doesn't reflect Revit model changes
- **No live interaction**: Cannot highlight elements in actual Revit from webapp
- **No status sync**: User cannot confirm/false-alarms directly in Revit
- **No AI explanations**: Mismatches shown but not explained

### Existing Components to Preserve
- **PDF extraction pipeline** (pdf_convert.py, pdf_intelligence.py, s201_detector.py)
- **Coordinate registration system** (registration.py, ransac_holdown.py)
- **Device matching logic** (device_match.py)
- **3D visualization** (WebGL viewer, currently without IFC)
- **Review system** (review.py, review_comments.json)
- **Backend API structure** (FastAPI, routers structure)

---

## 3. New Architecture Overview

### 3.1 High-Level Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        WEB UI (Frontend)                         │
│  - PDF upload                                                     │
│  - Results table (match/mismatch)                                │
│  - 3D visualization (existing)                                   │
│  - PDF overlay (existing)                                        │
│  - NEW: "Show in Revit" button                                   │
│  - NEW: AI explanation panel                                     │
│  - NEW: Real-time status indicators (synced from Revit)          │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP / WebSocket
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   BACKEND API (FastAPI)                          │
│                                                                  │
│  EXISTING ROUTERS:                                               │
│  - /api/projects/* (project management)                         │
│  - /api/pipeline/* (PDF extraction pipeline)                    │
│  - /api/elements/* (comparison, matching)                       │
│  - /api/registration/* (coordinate calibration)                 │
│  - /api/review/* (human review system)                          │
│                                                                  │
│  NEW ROUTERS:                                                    │
│  - /api/revit-live/* (live Revit queries via Nonica MCP)        │
│  - /api/revit-actions/* (highlight, select, confirm)            │
│  - /api/ai-explain/* (AI explanation generation)                │
│  - /ws/revit-sync (WebSocket for real-time updates)             │
│                                                                  │
│  NEW SERVICES:                                                   │
│  - revit_live_bridge.py (Nonica MCP client)                     │
│  - revit_action_proxy.py (bidirectional action handler)         │
│  - ai_explanation_engine.py (LLM-based explanations)            │
│  - coordinate_sync.py (live coord mapping)                      │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           │ Nonica Revit MCP
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   REVIT (Live Model)                             │
│                                                                  │
│  - Nonica MCP Server (user-scope "Revit")                       │
│  - A.I. Connector enabled in Revit                              │
│  - Element queries: get elements by category, type, location    │
│  - Element actions: select, highlight, isolate                  │
│  - Status sync: read/write element parameters (e.g., "QA_Status")│
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Data Flow

#### Workflow Step 1: PDF Upload & Extraction
```
User uploads PDF
    ↓
POST /api/pipeline/upload-pdf
    ↓
PDF extraction pipeline (existing)
    ↓
Extract: holdowns, shear walls, dimensions, benchmarks
    ↓
Store: artifacts/projects/{project}/pdf_extracted.json
    ↓
Return: PDF element count, page count, sheet numbers
```

#### Workflow Step 2: Live Revit Query (NEW)
```
POST /api/revit-live/fetch-elements
    ↓
Backend calls Nonica MCP: mcp__revit_mcp__get_current_view_elements
    ↓
Filter: structural elements (Structural Columns, Structural Framing, Walls)
    ↓
Extract: ElementId, Family, Type, Location (X,Y,Z), Level, Parameters
    ↓
Transform: Revit internal units (feet) → project coordinate system
    ↓
Store: artifacts/projects/{project}/revit_live_cache.json
    ↓
Return: Revit element count, bounding box, level summary
```

#### Workflow Step 3: Coordinate Registration (EXISTING)
```
POST /api/registration/compute-calibration
    ↓
Use existing registration.py logic
    ↓
Input: PDF benchmarks (if available) OR holdown RANSAC
    ↓
Compute: similarity transform (PDF points ↔ Revit feet)
    ↓
Validate: RMS residual, max residual, match_allowed flag
    ↓
Store: artifacts/projects/{project}/registration_calibration.json
    ↓
Return: calibration quality, match_allowed status
```

#### Workflow Step 4: Comparison (EXISTING + ENHANCED)
```
POST /api/compare/run
    ↓
Load: PDF elements, Revit live cache, registration transform
    ↓
Compare: PDF holdowns vs Revit columns (existing device_match.py)
    ↓
Enhance: Add AI explanation for each mismatch
    ↓
Classify: MATCH, LOCATION_MISMATCH, MARK_MISMATCH, PDF_ONLY, REVIT_ONLY
    ↓
Store: artifacts/projects/{project}/compare_report.json
    ↓
Return: element list with statuses, distances, explanations
```

#### Workflow Step 5: Show in Revit (NEW)
```
User clicks "Show in Revit" button on element row
    ↓
POST /api/revit-actions/highlight
    ↓
Backend looks up Revit ElementId for this element
    ↓
Backend calls Nonica MCP: mcp__revit_mcp__operate_element
    ↓
Action: Select + highlight (red color)
    ↓
Return: success/failure
```

#### Workflow Step 6: Confirm/False Alarm (NEW)
```
User right-clicks element in Revit → "Confirm as MATCH" / "Mark as FALSE ALARM"
    ↓
Revit plugin (future) OR user clicks in webapp → "Confirm" button
    ↓
POST /api/revit-actions/update-status
    ↓
Backend updates compare_report.json
    ↓
If Revit plugin available: write status to Revit element parameter
    ↓
Return: updated status
```

---

## 4. Component Design

### 4.1 Revit Live Bridge Service

**File:** `backend/app/revit_live_bridge.py`

**Purpose:** Abstracts Nonica Revit MCP calls into a clean API for the backend.

**Key Functions:**

```python
async def fetch_revit_elements(
    categories: List[str],
    include_hidden: bool = False,
    level_filter: Optional[str] = None
) -> List[Dict]:
    """
    Fetch elements from live Revit model via Nonica MCP.
    
    Steps:
    1. Call mcp__revit_mcp__get_current_view_elements with filters
    2. Extract: ElementId, Family, Type, Location, Level, Parameters
    3. Transform coordinates to project system (if needed)
    4. Return structured list
    
    Returns:
        [
            {
                "element_id": "1234567",
                "family": "HSS Column",
                "type": "HSS6x6x3/8",
                "location": {"x": 10.5, "y": 20.3, "z": 0.0},  # feet
                "level": "Level 1",
                "parameters": {"mark": "H1", "qa_status": "PENDING"}
            },
            ...
        ]
    """

async def highlight_element(element_id: str) -> bool:
    """
    Highlight an element in Revit by ElementId.
    
    Steps:
    1. Call mcp__revit_mcp__operate_element with action="Select"
    2. Call mcp__revit_mcp__operate_element with action="SetColor" (red)
    
    Returns: True if successful, False otherwise
    """

async def update_element_status(element_id: str, status: str) -> bool:
    """
    Update element QA status in Revit (if plugin available).
    
    Steps:
    1. Call mcp__revit_mcp__send_code_to_revit with C# snippet
    2. C# code sets parameter "QA_Status" to value
    3. Returns True if successful
    
    Note: Requires custom Revit plugin with "QA_Status" shared parameter
    """

async def get_revit_model_info() -> Dict:
    """
    Get current Revit model metadata.
    
    Returns:
        {
            "model_name": "Madera_Structural.rvt",
            "file_path": "C:\\Projects\\Madera_Structural.rvt",
            "view_name": "S-201",
            "element_count": 1523,
            "levels": ["Level 1", "Level 2"],
            "last_modified": "2026-07-27T10:30:00Z"
        }
    """
```

**Integration:** Calls Nonica MCP tools via subprocess (similar to how chat_agent.py calls OpenRouter).

---

### 4.2 Revit Action Proxy Service

**File:** `backend/app/revit_action_proxy.py`

**Purpose:** Handles bidirectional actions between webapp and Revit. Maintains action queue and syncs status.

**Key Functions:**

```python
async def show_in_revit(element_id: str) -> Dict:
    """
    Highlight element in Revit and return action result.
    
    Steps:
    1. Look up element in revit_live_cache.json
    2. Call revit_live_bridge.highlight_element()
    3. Log action in action_log.json
    4. Return result
    
    Returns:
        {
            "success": True,
            "element_id": "1234567",
            "family": "HSS Column",
            "type": "HSS6x6x3/8",
            "action": "HIGHLIGHTED"
        }
    """

async def update_qa_status(element_id: str, status: str, reason: str) -> Dict:
    """
    Update element QA status (from webapp or Revit).
    
    Steps:
    1. Update compare_report.json for this element
    2. If Revit plugin available: call revit_live_bridge.update_element_status()
    3. Broadcast WebSocket update to connected clients
    4. Log action
    
    Returns:
        {
            "success": True,
            "element_id": "1234567",
            "new_status": "CONFIRMED_MATCH",
            "synced_to_revit": True
        }
    """

async def sync_revit_statuses() -> Dict:
    """
    Poll Revit for element QA_Status parameters and sync to webapp.
    
    Steps:
    1. Call revit_live_bridge.fetch_revit_elements() with QA_Status parameter
    2. For each element with QA_Status != "PENDING":
        - Update compare_report.json
        - Broadcast WebSocket update
    3. Return sync summary
    
    Returns:
        {
            "elements_synced": 5,
            "statuses": {
                "CONFIRMED_MATCH": 3,
                "FALSE_ALARM": 2
            }
        }
    """
```

**WebSocket Integration:** Emits real-time updates to frontend when statuses change in Revit.

---

### 4.3 AI Explanation Engine

**File:** `backend/app/ai_explanation_engine.py`

**Purpose:** Generates human-readable explanations for each element mismatch using LLM.

**Key Functions:**

```python
async def generate_explanation(element: Dict, context: Dict) -> str:
    """
    Generate AI explanation for a single element mismatch.
    
    Input:
        element: {
            "id": "H1-01",
            "status": "LOCATION_MISMATCH",
            "pdf_location": {"x": 10.2, "y": 20.1},
            "revit_location": {"x": 10.5, "y": 20.4},
            "distance_ft": 2.1,
            "revit_type": "HSS6x6x3/8",
            "revit_mark": "H1"
        }
        context: {
            "project_name": "Madera",
            "sheet": "S-201",
            "other_mismatches_count": 15,
            "common_offset_direction": "northeast"
        }
    
    Output:
        "This hold-down (H1-01) is located 2.1 ft from the Revit model, 
         offset to the northeast. This is a common pattern in this project 
         (15 similar mismatches), suggesting a systematic coordinate shift 
         rather than a modeling error. Possible causes:
         1. PDF drawing scale not calibrated
         2. Revit model coordinate origin differs from PDF
         3. Design change not yet reflected in PDF"
    
    Implementation:
        1. Build prompt with element details + project context
        2. Call OpenRouter API (existing openrouter.py)
        3. Return explanation text
    """

async def batch_generate_explanations(elements: List[Dict]) -> List[Dict]:
    """
    Generate explanations for multiple elements in parallel.
    
    Optimization: Group by status + common patterns to reduce LLM calls.
    
    Returns:
        [
            {
                "element_id": "H1-01",
                "explanation": "..."
            },
            ...
        ]
    """

def _build_prompt(element: Dict, context: Dict) -> str:
    """
    Internal: Build LLM prompt for explanation generation.
    
    Prompt structure:
        - Role: "You are a structural engineer reviewing QA/QC discrepancies"
        - Context: Project name, sheet, common patterns
        - Element details: Location, distance, type, mark
        - Question: "Explain this mismatch in 2-3 sentences"
    """
```

**Integration:** Uses existing `chat_agent.py` and `openrouter.py` infrastructure.

---

### 4.4 Coordinate Sync Service

**File:** `backend/app/coordinate_sync.py`

**Purpose:** Maintains coordinate mapping between PDF and live Revit model. Handles updates when Revit model changes.

**Key Functions:**

```python
def sync_coordinates(pdf_elements: List[Dict], revit_elements: List[Dict]) -> Dict:
    """
    Update coordinate registration when Revit model is re-fetched.
    
    Steps:
    1. Check if existing registration_calibration.json is valid
    2. If valid: apply same transform to new Revit elements
    3. If invalid: trigger re-calibration (benchmark or RANSAC)
    4. Return sync status
    
    Returns:
        {
            "status": "synced" | "recalibrated" | "needs_recalibration",
            "registration_quality": {
                "confidence": "high",
                "match_allowed": True
            }
        }
    """

def validate_registration(registration: Dict, revit_elements: List[Dict]) -> Dict:
    """
    Validate existing registration against new Revit data.
    
    Checks:
        - Bounding box overlap (PDF vs Revit)
        - Sample element locations (transform PDF → Revit, check distance)
        - Benchmark positions (if available)
    
    Returns:
        {
            "valid": True,
            "drift_pt": 0.5,
            "warning": None
        }
    """
```

---

## 5. Backend API Design

### 5.1 New API Endpoints

#### Revit Live Router (`/api/revit-live`)

```python
# GET /api/revit-live/model-info
# Returns: current Revit model metadata
Response: {
    "model_name": "Madera_Structural.rvt",
    "view_name": "S-201",
    "element_count": 1523,
    "last_modified": "2026-07-27T10:30:00Z"
}

# POST /api/revit-live/fetch-elements
# Fetches elements from live Revit model
Request: {
    "categories": ["Structural Columns", "Structural Framing", "Walls"],
    "level_filter": "Level 1",
    "include_hidden": false
}
Response: {
    "success": true,
    "elements_fetched": 120,
    "cache_updated": true,
    "summary": {
        "columns": 45,
        "beams": 70,
        "walls": 5
    }
}

# GET /api/revit-live/status
# Returns: connection status to Revit
Response: {
    "connected": true,
    "model_loaded": true,
    "last_sync": "2026-07-27T14:22:00Z"
}
```

#### Revit Actions Router (`/api/revit-actions`)

```python
# POST /api/revit-actions/highlight
# Highlights element in Revit
Request: {
    "element_id": "1234567"
}
Response: {
    "success": true,
    "action": "HIGHLIGHTED",
    "element": {
        "family": "HSS Column",
        "type": "HSS6x6x3/8",
        "mark": "H1"
    }
}

# POST /api/revit-actions/update-status
# Updates element QA status
Request: {
    "element_id": "1234567",
    "status": "CONFIRMED_MATCH",
    "reason": "Verified by engineer"
}
Response: {
    "success": true,
    "status_updated": true,
    "synced_to_revit": true
}

# POST /api/revit-actions/sync-from-revit
# Polls Revit for status updates
Response: {
    "elements_synced": 5,
    "statuses": {
        "CONFIRMED_MATCH": 3,
        "FALSE_ALARM": 2
    }
}
```

#### AI Explain Router (`/api/ai-explain`)

```python
# POST /api/ai-explain/generate
# Generates AI explanation for element
Request: {
    "element_id": "H1-01",
    "include_context": true
}
Response: {
    "explanation": "This hold-down (H1-01) is located 2.1 ft from the Revit model...",
    "confidence": "high",
    "generated_at": "2026-07-27T14:25:00Z"
}

# POST /api/ai-explain/batch
# Generates explanations for multiple elements
Request: {
    "element_ids": ["H1-01", "H2-15", "H3-07"],
    "include_context": true
}
Response: {
    "explanations": [
        {"element_id": "H1-01", "explanation": "..."},
        {"element_id": "H2-15", "explanation": "..."},
        {"element_id": "H3-07", "explanation": "..."}
    ],
    "total_tokens": 1500
}
```

#### WebSocket Endpoint

```python
# WebSocket /ws/revit-sync
# Real-time updates from Revit
Messages (server → client):
    {
        "type": "status_update",
        "element_id": "1234567",
        "new_status": "CONFIRMED_MATCH",
        "source": "revit_plugin"
    }
    {
        "type": "element_selected",
        "element_id": "1234567",
        "action": "highlighted"
    }
```

### 5.2 Enhanced Existing Endpoints

```python
# POST /api/compare/run (enhanced)
# Now includes AI explanations by default
Request: {
    "generate_explanations": true,  # NEW
    "explanation_batch_size": 10     # NEW
}
Response: {
    "elements": [
        {
            "id": "H1-01",
            "status": "LOCATION_MISMATCH",
            "distance_ft": 2.1,
            "explanation": "...",  # NEW
            "revit_element_id": "1234567"  # NEW
        }
    ]
}

# GET /api/elements/list (enhanced)
# Now includes revit_element_id for "Show in Revit" button
Response: {
    "elements": [
        {
            "id": "H1-01",
            "status": "MATCH",
            "revit_element_id": "1234567",  # NEW
            "can_show_in_revit": true        # NEW
        }
    ]
}
```

---

## 6. Frontend Changes

### 6.1 New UI Components

#### Element Row (Enhanced)
```html
<!-- In results table -->
<tr>
    <td>H1-01</td>
    <td>LOCATION_MISMATCH</td>
    <td>2.1 ft</td>
    <td>
        <button class="btn-primary" onclick="showInRevit('1234567')">
            Show in Revit
        </button>
        <button class="btn-info" onclick="showExplanation('H1-01')">
            Explain
        </button>
    </td>
    <td>
        <button onclick="confirmMatch('1234567')">✓ Confirm</button>
        <button onclick="markFalseAlarm('1234567')">✗ False Alarm</button>
    </td>
</tr>
```

#### AI Explanation Panel (NEW)
```html
<div id="explanation-panel" class="panel collapsed">
    <h3>AI Explanation</h3>
    <div id="explanation-content">
        <p>Loading...</p>
    </div>
    <button onclick="regenerateExplanation()">Regenerate</button>
</div>
```

#### Revit Status Indicator (NEW)
```html
<!-- In header or status bar -->
<div id="revit-status">
    <span class="status-dot connected"></span>
    <span>Revit: Connected</span>
    <span>Last sync: 2 min ago</span>
    <button onclick="syncFromRevit()">Sync Now</button>
</div>
```

### 6.2 JavaScript Functions

```javascript
// Show element in Revit
async function showInRevit(elementId) {
    const response = await fetch('/api/revit-actions/highlight', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({element_id: elementId})
    });
    const result = await response.json();
    if (result.success) {
        showToast('Element highlighted in Revit');
    } else {
        showToast('Failed to highlight element', 'error');
    }
}

// Show AI explanation
async function showExplanation(elementId) {
    const panel = document.getElementById('explanation-panel');
    panel.classList.remove('collapsed');
    
    const response = await fetch('/api/ai-explain/generate', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({element_id: elementId, include_context: true})
    });
    const result = await response.json();
    
    document.getElementById('explanation-content').innerHTML = 
        `<p>${result.explanation}</p>`;
}

// Confirm match
async function confirmMatch(elementId) {
    const response = await fetch('/api/revit-actions/update-status', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            element_id: elementId,
            status: 'CONFIRMED_MATCH',
            reason: 'Verified by engineer'
        })
    });
    const result = await response.json();
    if (result.success) {
        updateRowStatus(elementId, 'CONFIRMED_MATCH');
        showToast('Status updated');
    }
}

// WebSocket connection
const ws = new WebSocket('ws://localhost:8077/ws/revit-sync');
ws.onmessage = function(event) {
    const data = JSON.parse(event.data);
    if (data.type === 'status_update') {
        updateRowStatus(data.element_id, data.new_status);
        showToast(`Status updated from Revit: ${data.new_status}`);
    }
};
```

---

## 7. Data Model Changes

### 7.1 Enhanced compare_report.json

**Before:**
```json
{
  "elements": [
    {
      "id": "H1-01",
      "status": "LOCATION_MISMATCH",
      "distance_ft": 2.1,
      "pdf_location": {"x": 10.2, "y": 20.1},
      "revit_location": {"x": 10.5, "y": 20.4}
    }
  ]
}
```

**After:**
```json
{
  "elements": [
    {
      "id": "H1-01",
      "status": "LOCATION_MISMATCH",
      "distance_ft": 2.1,
      "pdf_location": {"x": 10.2, "y": 20.1},
      "revit_location": {"x": 10.5, "y": 20.4},
      "revit_element_id": "1234567",  // NEW
      "revit_family": "HSS Column",    // NEW
      "revit_type": "HSS6x6x3/8",      // NEW
      "explanation": "This hold-down...",  // NEW
      "explanation_generated_at": "2026-07-27T14:25:00Z",  // NEW
      "qa_status": "PENDING",  // NEW: PENDING | CONFIRMED_MATCH | FALSE_ALARM
      "qa_status_updated_at": "2026-07-27T14:25:00Z",  // NEW
      "qa_status_source": "webapp"  // NEW: webapp | revit_plugin
    }
  ]
}
```

### 7.2 New Data Files

#### revit_live_cache.json
```json
{
  "fetched_at": "2026-07-27T14:20:00Z",
  "model_name": "Madera_Structural.rvt",
  "view_name": "S-201",
  "elements": [
    {
      "element_id": "1234567",
      "family": "HSS Column",
      "type": "HSS6x6x3/8",
      "location": {"x": 10.5, "y": 20.4, "z": 0.0},
      "level": "Level 1",
      "parameters": {
        "mark": "H1",
        "qa_status": "PENDING"
      }
    }
  ]
}
```

#### action_log.json
```json
[
  {
    "timestamp": "2026-07-27T14:22:00Z",
    "action": "HIGHLIGHT",
    "element_id": "1234567",
    "source": "webapp",
    "user": "engineer@example.com"
  },
  {
    "timestamp": "2026-07-27T14:25:00Z",
    "action": "STATUS_UPDATE",
    "element_id": "1234567",
    "new_status": "CONFIRMED_MATCH",
    "source": "webapp",
    "user": "engineer@example.com"
  }
]
```

---

## 8. Error Handling & Resilience

### 8.1 Revit Connection Failures

**Scenario:** Nonica MCP not available or Revit model not loaded.

**Handling:**
```python
if not revit_live_bridge.is_connected():
    return {
        "success": False,
        "error": "REVIT_NOT_CONNECTED",
        "message": "Revit model not available. Please ensure:"
                   "1. Revit is running with A.I. Connector enabled"
                   "2. Nonica MCP server is running"
                   "3. Model is loaded",
        "fallback": "Use JSON export workflow"
    }
```

**User Experience:**
- Web UI shows warning banner: "Revit not connected"
- "Show in Revit" button disabled
- Fallback option: "Upload Revit JSON" (existing workflow)

### 8.2 Element Not Found in Revit

**Scenario:** User clicks "Show in Revit" but element not in live model.

**Handling:**
```python
if element_id not in revit_cache:
    return {
        "success": False,
        "error": "ELEMENT_NOT_FOUND",
        "message": "Element not found in current Revit view"
    }
```

**User Experience:**
- Toast: "Element not found in Revit. Try refreshing Revit data."
- Suggest: "Re-fetch Revit elements" button

### 8.3 AI Explanation Generation Failures

**Scenario:** OpenRouter API unavailable or rate-limited.

**Handling:**
```python
try:
    explanation = await openrouter.generate(prompt)
except Exception as e:
    return {
        "explanation": "Explanation unavailable. Please try again later.",
        "error": "AI_SERVICE_UNAVAILABLE",
        "fallback": "Use manual review"
    }
```

**User Experience:**
- Explanation panel shows: "AI explanation unavailable. Try again later."
- No blocking: other features still work

---

## 9. Security Considerations

### 9.1 Nonica MCP Authentication

**Current:** Nonica MCP uses local socket (no auth needed on localhost).

**Enhancement:** If deployed remotely:
- Add API key authentication for `/api/revit-live/*` endpoints
- Use environment variable: `REVIT_MCP_API_KEY`
- Validate token in middleware

### 9.2 Element Modification Permissions

**Current:** Any user can update element status.

**Enhancement:** Add role-based permissions:
```python
if user.role not in ["engineer", "admin"]:
    return {
        "success": False,
        "error": "PERMISSION_DENIED",
        "message": "Only engineers can update QA status"
    }
```

### 9.3 Audit Trail

**Implementation:** All actions logged to `action_log.json`:
- Who performed action (user email)
- When (timestamp)
- What (action type + element ID)
- Source (webapp or revit_plugin)

---

## 10. Performance Considerations

### 10.1 Revit Fetch Optimization

**Problem:** Fetching all elements from Revit can be slow (1000s of elements).

**Solution:**
- **Caching:** Cache fetched elements in `revit_live_cache.json`
- **Incremental fetch:** Only fetch elements in current view
- **Background refresh:** Auto-refresh every 5 minutes in background
- **Manual refresh:** User can trigger refresh when needed

### 10.2 AI Explanation Batching

**Problem:** Generating explanations for 100+ elements is slow and expensive.

**Solution:**
- **Batch API:** `/api/ai-explain/batch` processes elements in parallel
- **Caching:** Store explanations in `compare_report.json`, regenerate only if element changes
- **Lazy loading:** Generate explanations on-demand (when user clicks "Explain")
- **Grouping:** Group similar mismatches → single explanation for pattern

### 10.3 WebSocket Scaling

**Problem:** Multiple users connecting to WebSocket.

**Solution:**
- Use connection pooling (FastAPI WebSocket manager)
- Broadcast only to interested clients (filter by project)
- Reconnect logic in frontend (auto-reconnect on disconnect)

---

## 11. Migration Strategy

### 11.1 Phase 1: Foundation (Week 1-2)

**Goals:**
- Implement `revit_live_bridge.py` (Nonica MCP client)
- Add new API endpoints: `/api/revit-live/*`, `/api/revit-actions/*`
- Update `compare_report.json` schema
- Add "Show in Revit" button to frontend

**Deliverables:**
- Working "Show in Revit" highlighting
- Live Revit fetch (manual trigger)
- Backend tests for new endpoints

### 11.2 Phase 2: AI Explanations (Week 3)

**Goals:**
- Implement `ai_explanation_engine.py`
- Add `/api/ai-explain/*` endpoints
- Add explanation panel to frontend
- Integrate with comparison pipeline

**Deliverables:**
- AI explanations for all mismatches
- Batch generation support
- Caching to avoid re-generation

### 11.3 Phase 3: Bidirectional Sync (Week 4)

**Goals:**
- Implement WebSocket for real-time updates
- Add "Confirm/False Alarm" buttons to frontend
- Add Revit status sync polling
- Implement `revit_action_proxy.py`

**Deliverables:**
- Real-time status sync (Revit ↔ webapp)
- Action logging
- WebSocket connection manager

### 11.4 Phase 4: Polish & Testing (Week 5)

**Goals:**
- Error handling for all failure modes
- Performance optimization (caching, batching)
- User testing with Madera + Country Side projects
- Documentation updates

**Deliverables:**
- Production-ready code
- User guide for new workflow
- Troubleshooting guide

---

## 12. Testing Strategy

### 12.1 Unit Tests

**Coverage:**
- `revit_live_bridge.py`: Mock Nonica MCP calls
- `revit_action_proxy.py`: Mock Revit actions
- `ai_explanation_engine.py`: Mock OpenRouter API
- New API endpoints: pytest for all new routes

**Example:**
```python
# test_revit_live_bridge.py
def test_fetch_elements():
    # Mock Nonica MCP response
    mocker.patch('app.revit_live_bridge.call_nonica_mcp', return_value={...})
    
    result = revit_live_bridge.fetch_revit_elements(categories=["Structural Columns"])
    
    assert len(result) > 0
    assert result[0]["element_id"] == "1234567"
    assert result[0]["family"] == "HSS Column"
```

### 12.2 Integration Tests

**Coverage:**
- End-to-end: PDF upload → Revit fetch → Compare → Highlight
- WebSocket: Status update → frontend receives update
- AI explanation: Element mismatch → explanation generated

### 12.3 User Acceptance Testing

**Scenarios:**
- Upload Madera PDF, fetch Revit, run comparison
- Click "Show in Revit" → element highlights in Revit
- Click "Explain" → AI explanation appears
- Click "Confirm" → status updates in webapp + Revit
- Update status in Revit → webapp receives WebSocket update

---

## 13. Deployment Considerations

### 13.1 Local Deployment (Current)

**Requirements:**
- Python 3.11+
- Node.js 18+ (for frontend if separated)
- Revit 2024+ with A.I. Connector
- Nonica MCP server running locally

**Steps:**
1. Start backend: `python -m uvicorn app.main:app --host 127.0.0.1 --port 8077`
2. Ensure Revit is running with model loaded
3. Ensure Nonica MCP server is running
4. Open frontend in browser

### 13.2 Remote Deployment (Future)

**Requirements:**
- Server with Python 3.11+
- Reverse proxy (nginx)
- SSL certificate
- Revit on user machine (local)
- Nonica MCP over network (requires VPN or SSH tunnel)

**Architecture:**
```
[User Browser] ↔ [Frontend Server] ↔ [Backend Server]
                                         ↓
                                    [Revit on User Machine]
                                         ↓
                                    [Nonica MCP Server]
```

**Challenges:**
- Nonica MCP is local-only → requires SSH tunnel or custom plugin
- Latency for Revit actions → optimize with caching
- Security → API keys, CORS, rate limiting

---

## 14. Future Enhancements

### 14.1 Revit Plugin for Native Integration

**Idea:** Custom Revit plugin (C#) for tighter integration.

**Capabilities:**
- Native "Confirm/False Alarm" buttons in Revit
- Direct parameter updates (no Nonica MCP middleman)
- Real-time bidirectional sync
- Custom UI panel in Revit showing webapp data

**Implementation:**
- Revit API: `IExternalApplication`
- UI: WPF dockable panel
- Communication: HTTP client → backend API

### 14.2 Multi-Model Support

**Idea:** Compare single PDF against multiple Revit models (e.g., structural + architectural).

**Implementation:**
- `revit_live_bridge.py` supports multiple connections
- Element registry tracks which model each element comes from
- UI shows model selector

### 14.3 Automated PDF Calibration

**Idea:** Automatically extract scale/coordinate info from PDF title block.

**Implementation:**
- Use AI vision model to detect title block
- Extract scale (e.g., "1/4" = 1'-0"")
- Compute coordinate transform automatically
- No manual benchmark placement needed

### 14.4 Clash Detection

**Idea:** Detect clashes between PDF elements and Revit model.

**Implementation:**
- Compare PDF dimensions to Revit geometry
- Flag conflicts (e.g., beam too short, column misaligned)
- Generate clash report

---

## 15. Risks & Mitigations

### 15.1 Risk: Nonica MCP Instability

**Risk:** Nonica MCP server crashes or becomes unresponsive.

**Mitigation:**
- Health check endpoint: `/api/revit-live/status`
- Auto-reconnect logic in `revit_live_bridge.py`
- Fallback to JSON export workflow
- Alert user via UI banner

### 15.2 Risk: Slow Revit Queries

**Risk:** Fetching large models (>5000 elements) takes too long.

**Mitigation:**
- View-based filtering: only fetch elements in current view
- Background fetching: async task with progress indicator
- Caching: reuse cached data if model unchanged
- Incremental updates: only fetch changed elements

### 15.3 Risk: AI Explanation Quality

**Risk:** AI generates inaccurate or misleading explanations.

**Mitigation:**
- Confidence score in response
- User feedback: "Helpful" / "Not helpful" buttons
- Manual override: engineer can edit explanation
- Disclaimer: "AI-generated, verify independently"

### 15.4 Risk: Coordinate Drift

**Risk:** Revit model changes cause coordinate registration to become invalid.

**Mitigation:**
- Validation function: check registration against new Revit data
- Auto-recalibrate if drift > threshold
- Warn user if recalibration needed
- Preserve manual calibration (never overwrite)

---

## 16. Success Metrics

### 16.1 Functional Metrics

- **Workflow Time:** Reduce total QA/QC workflow time by 50% (no manual JSON export)
- **Element Coverage:** 100% of PDF elements matched to Revit (no missing Revit data)
- **Interaction Speed:** "Show in Revit" action completes in <2 seconds
- **Status Sync:** Real-time sync latency <5 seconds

### 16.2 User Experience Metrics

- **User Satisfaction:** 80%+ of users report "easier to use" in survey
- **Error Rate:** <5% of actions fail (highlight, confirm, sync)
- **AI Explanation Quality:** 70%+ of explanations rated "helpful" by users

### 16.3 Performance Metrics

- **Revit Fetch:** <30 seconds for 1000 elements
- **Comparison:** <10 seconds for 500 elements (with AI explanations)
- **WebSocket:** <1 second message delivery latency

---

## 17. Conclusion

This architecture provides a complete solution for transitioning from a JSON-export-based workflow to a live Revit-integrated workflow. The key innovations are:

1. **Live Revit queries** eliminate manual JSON exports
2. **"Show in Revit"** enables direct interaction with the model
3. **AI explanations** provide context for mismatches
4. **Bidirectional sync** keeps webapp and Revit in sync
5. **WebSocket real-time updates** provide immediate feedback

The architecture is modular, allowing phased implementation and easy testing at each stage. Error handling ensures graceful degradation when Revit is unavailable. Performance optimizations (caching, batching, background tasks) ensure the system scales to large projects.

**Next Steps:**
1. Review and approve this architecture document
2. Begin Phase 1 implementation (Revit Live Bridge + API endpoints)
3. Test with Madera project
4. Iterate based on user feedback

---

## Appendix A: Nonica MCP Tool Reference

### Available Tools (from Hermes Agent)

```python
# Fetch elements from current view
mcp__revit_mcp__get_current_view_elements(categories, includeHidden, limit)
# Returns: list of elements with properties

# Operate on elements (select, highlight, delete, etc.)
mcp__revit_mcp__operate_element(elementIds, action, colorValue, transparencyValue)
# Actions: Select, SetColor, Hide, Isolate, Delete, etc.

# Send C# code to Revit
mcp__revit_mcp__send_code_to_revit(code, parameters)
# Executes C# code in Revit context

# Get selected elements
mcp__revit_mcp__get_selected_elements(limit)
# Returns: currently selected elements in Revit

# Get current view info
mcp__revit_mcp__get_current_view_info()
# Returns: view type, name, scale, etc.
```

### Custom C# Code Example

```csharp
// Set element parameter
var element = doc.GetElement(new ElementId(1234567));
var param = element.LookupParameter("QA_Status");
if (param != null)
{
    param.Set("CONFIRMED_MATCH");
}
```

---

## Appendix B: Data Flow Diagrams

### B.1 PDF Upload → Comparison

```
[User] → [Upload PDF] → [Backend]
  → [Extract PDF] → [Store PDF elements]
  → [Fetch Revit] → [Store Revit elements]
  → [Register coordinates] → [Store calibration]
  → [Compare] → [Store compare_report.json]
  → [Generate explanations] → [Store in compare_report.json]
  → [Return to frontend]
```

### B.2 Show in Revit

```
[User clicks "Show in Revit"] → [Frontend]
  → [POST /api/revit-actions/highlight]
  → [Backend looks up element_id]
  → [revit_live_bridge.highlight_element()]
  → [Nonica MCP: operate_element(Select + SetColor)]
  → [Revit highlights element]
  → [Return success to frontend]
  → [Show toast]
```

### B.3 Status Sync (Revit → Webapp)

```
[User confirms in Revit (via plugin)] → [Revit updates parameter]
  → [Backend polls Revit: sync_from_revit()]
  → [Reads QA_Status parameters]
  → [Updates compare_report.json]
  → [WebSocket message to frontend]
  → [Frontend updates row status]
  → [Show toast]
```

---

## Appendix C: File Structure

```
backend/
├── app/
│   ├── revit_live_bridge.py          # NEW: Nonica MCP client
│   ├── revit_action_proxy.py         # NEW: Bidirectional action handler
│   ├── ai_explanation_engine.py      # NEW: LLM explanation generator
│   ├── coordinate_sync.py            # NEW: Live coord mapping
│   ├── routers/
│   │   ├── revit_live.py             # NEW: /api/revit-live/* endpoints
│   │   ├── revit_actions.py          # NEW: /api/revit-actions/* endpoints
│   │   ├── ai_explain.py             # NEW: /api/ai-explain/* endpoints
│   │   ├── websocket.py              # NEW: WebSocket endpoint
│   │   ├── elements.py               # MODIFIED: Add revit_element_id
│   │   └── compare.py                # MODIFIED: Add explanations
│   └── main.py                       # MODIFIED: Register new routers
└── artifacts/
    └── projects/
        └── {project}/
            ├── revit_live_cache.json  # NEW: Cached Revit elements
            ├── action_log.json        # NEW: Action audit trail
            └── compare_report.json    # MODIFIED: Add explanations + status

frontend/
├── index.html                         # MODIFIED: Add new buttons + panels
└── src/
    ├── revit_actions.js               # NEW: Revit interaction logic
    ├── ai_explanation.js              # NEW: Explanation panel logic
    └── websocket_client.js            # NEW: WebSocket connection manager
```

---

## Appendix D: API Request/Response Examples

### D.1 Fetch Revit Elements

**Request:**
```http
POST /api/revit-live/fetch-elements
Content-Type: application/json

{
  "categories": ["Structural Columns", "Structural Framing"],
  "level_filter": "Level 1",
  "include_hidden": false
}
```

**Response:**
```json
{
  "success": true,
  "elements_fetched": 120,
  "cache_updated": true,
  "summary": {
    "columns": 45,
    "beams": 75
  },
  "model_info": {
    "model_name": "Madera_Structural.rvt",
    "view_name": "S-201",
    "fetched_at": "2026-07-27T14:20:00Z"
  }
}
```

### D.2 Highlight Element

**Request:**
```http
POST /api/revit-actions/highlight
Content-Type: application/json

{
  "element_id": "1234567"
}
```

**Response:**
```json
{
  "success": true,
  "action": "HIGHLIGHTED",
  "element": {
    "element_id": "1234567",
    "family": "HSS Column",
    "type": "HSS6x6x3/8",
    "mark": "H1",
    "level": "Level 1"
  },
  "highlight_color": [255, 0, 0]
}
```

### D.3 Generate AI Explanation

**Request:**
```http
POST /api/ai-explain/generate
Content-Type: application/json

{
  "element_id": "H1-01",
  "include_context": true
}
```

**Response:**
```json
{
  "explanation": "This hold-down (H1-01) is located 2.1 ft from the Revit model, offset to the northeast. This is a common pattern in this project (15 similar mismatches), suggesting a systematic coordinate shift rather than a modeling error. Possible causes:\n1. PDF drawing scale not calibrated\n2. Revit model coordinate origin differs from PDF\n3. Design change not yet reflected in PDF",
  "confidence": "high",
  "generated_at": "2026-07-27T14:25:00Z",
  "model": "openrouter/qwen3-235b"
}
```

### D.4 Update QA Status

**Request:**
```http
POST /api/revit-actions/update-status
Content-Type: application/json

{
  "element_id": "1234567",
  "status": "CONFIRMED_MATCH",
  "reason": "Verified by engineer - location within tolerance"
}
```

**Response:**
```json
{
  "success": true,
  "status_updated": true,
  "synced_to_revit": true,
  "element": {
    "element_id": "1234567",
    "old_status": "PENDING",
    "new_status": "CONFIRMED_MATCH",
    "updated_at": "2026-07-27T14:30:00Z"
  }
}
```

---

## Appendix E: WebSocket Message Examples

### E.1 Status Update from Revit

```json
{
  "type": "status_update",
  "element_id": "1234567",
  "new_status": "CONFIRMED_MATCH",
  "source": "revit_plugin",
  "timestamp": "2026-07-27T14:30:00Z",
  "user": "engineer@example.com"
}
```

### E.2 Element Selected in Revit

```json
{
  "type": "element_selected",
  "element_id": "1234567",
  "action": "highlighted",
  "timestamp": "2026-07-27T14:22:00Z"
}
```

### E.3 Connection Status

```json
{
  "type": "connection_status",
  "status": "connected",
  "model_name": "Madera_Structural.rvt",
  "timestamp": "2026-07-27T14:20:00Z"
}
```

---

**END OF ARCHITECTURE DOCUMENT**
