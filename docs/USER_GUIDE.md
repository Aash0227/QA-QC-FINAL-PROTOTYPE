# QA-QC Automated System — User Guide & Walkthrough

**Audience:** Anyone at Livio who needs to run or understand the tool — QA-QC engineers and non-technical staff alike.
**What this covers:** What the tool does, how to start it, how every feature works, and how to run the full pipeline step by step.

---

## Part 1 — What this tool is (30-second version)

You give it two files:

1. A **Revit export** (a `.json` file the Revit add-on produces from the 3D model).
2. A **PDF drawing set** (the structural sheets, e.g. S-201, S-202).

It reads both, lines them up, and tells you — for every hold-down, shear wall, post and column — whether the drawing and the model **agree (green)** or **disagree (red)**. You review the reds, and export a punch-list for the site team.

That's it. Everything below is detail.

---

## Part 2 — Starting the application

### Prerequisites (one-time)
- Python 3.11 installed.
- The project folder at `C:\QA-QC-FINAL-PROTOTYPE-bkp`.
- (Optional) An `OPENROUTER_API_KEY` in the `.env` file — only needed for the smartest version of the "Teach the AI" feature. Everything else works without it.

### Start the server
Open **PowerShell**, then:

```powershell
cd C:\QA-QC-FINAL-PROTOTYPE-bkp
.\run_backend.ps1
```

Leave that window open — it is the running server. You'll see `Uvicorn running on http://127.0.0.1:8077`.

### Open the dashboard
In your browser go to:

```
http://127.0.0.1:8077
```

> **Note on the interface:** the project ships with two front-ends. The **full interactive dashboard** (grouped element list, 3D model, Teach-AI) is the main product. If the page you see is the basic panel view instead, activate the dashboard once with the command below, then refresh the browser (Ctrl+Shift+R).

```powershell
Copy-Item frontend\index_v2_backup.html frontend\index.html -Force
```

---

## Part 3 — The dashboard at a glance

The screen has three zones:

| Zone | What it shows |
|---|---|
| **Left panel** | The searchable, grouped list of every element (collapsible with the menu button). |
| **Centre** | The real PDF drawing (left) and the 3D Revit model (right), side by side. |
| **Top bar** | Pipeline, Teach AI, Extract and Match buttons, plus live counts. |

Two slide-in drawers appear from the right when needed: the **Evidence Inspector** (element details) and the **Teach AI** chat.

---

## Part 4 — Running the full pipeline (step by step)

Click **Pipeline** in the top bar. This opens a full-screen, scrollable explainer with one card per stage. You can run each stage with its own button, or click **Run full pipeline** to do them all in order.

Here is what each stage does and produces:

### Stage 0 — Upload project
Provide the client's PDF and Revit JSON. If you skip this, the built-in **Madera sample project** is used, so you can try the whole tool with no files of your own.
*Produces:* the project manifest.

### Stage 1 — AI Revit Convert
Reads the raw Revit export and groups the loose parts (a hold-down body plus its anchor bolt) into single, real assemblies, learning the family naming as it goes.
*Produces:* `AIConvert_revit.json` (the canonical assemblies).

### Stage 2 — PDF Page Intelligence
Finds the foundation-plan page and detects every hold-down callout (H1–H4), following the leader lines to each one's true location on the drawing.
*Produces:* `pdf_page_intelligence.json` plus evidence image crops.

### Stage 3 — AI PDF Convert
Restructures the PDF detections into the same shape as the Revit data so the two can be compared directly.
*Produces:* `AIConvert_pdf.json`.

### Stage 4 — RANSAC Calibration
Automatically works out how model coordinates (feet) map onto the paper drawing (points), by finding the alignment that lines up the most hold-downs. This is the mathematical heart of the tool.
*Produces:* `registration_calibration.json` (the verified transform).

### Stage 5 — AI Compare
Pairs each Revit hold-down with a PDF hold-down, one-to-one. Within tolerance = **MATCH**. Nothing is faked; anything unpaired is flagged honestly.
*Produces:* `ai_compare_report.json` (the verdicts).

### Stage 6 — Extract ALL Elements
Scans **every** sheet, reads **every** schedule table (posts, shear walls, columns, walls), learns which marks exist, and finds them all on the plans. Applies any rules you have taught the AI.
*Produces:* `element_intelligence.json` (the full inventory).

### Stage 7 — Teach the AI (optional)
If the drawing uses non-standard labels, teach the system here (see Part 6). Optional but powerful.
*Produces:* `ai_teach_memory.json` (persistent rules).

### Stage 8 — Match everything
Aligns each sheet independently, matches shear walls to Revit wall centrelines, joins in the hold-down verdicts, and builds the single unified element list you review.
*Produces:* `element_list.json` and the 3D scene.

### Stage 9 — Review & Export
Green = verified in the model, red = discrepancy. Export the punch-list CSV for the site team, or the annotated drawing overlays.
*Produces:* `punch_list.csv` and review overlay images.

> **Shortcut:** after the first full run, the top-bar buttons **Extract** and **Match** re-run the multi-element half of the pipeline in one click each — that's the day-to-day loop.

---

## Part 5 — Reviewing the results

### The element list (left panel)
Elements are grouped by type — Hold-downs, Shear walls, Posts, Steel columns, Wall types — each a collapsible dropdown showing a count and a row of coloured status dots. Open a type, then open a specific mark (e.g. `SW-1`) to see each individual instance.

Use the **search box** and the **status / sheet filters** at the top to narrow the list.

### The colour code

| Colour | Status | Meaning |
|---|---|---|
| Green | MATCH | Verified: drawing and model agree, within tolerance. |
| Amber | LOCATION MISMATCH | Same element found, but slightly out of tolerance — worth a look. |
| Blue | PDF ONLY | On the drawing, no partner found in the model. |
| Red | REVIT ONLY | In the model, no partner found on the drawing. |
| Grey | NO REVIT DATA | On the drawing; the model has no data for this element type yet. |
| Pink | NOT IN SCHEDULE | On the plan but missing from every schedule table. |

### Clicking an element
Click any row (or any box on the drawing, or any shape in the 3D model) and three things happen together:

1. The **PDF drawing flies to that element** and highlights **only** it (everything else dims).
2. A **glowing information ball** flies to the same element in the **3D model**. Click the ball to open the full **Evidence Inspector** (ID, category, sheet, coordinates, distance, spec, and the reason for the verdict). The ball keeps the 3D view clear until you actually want the details.
3. The list scrolls to and selects the row.

Press **Esc** to clear the selection.

### The 3D model (right pane)
A 3D reconstruction: walls (shear walls solid, others faint), hold-downs as spheres at their real elevations, doors and windows, and grid lines with labels. Drag to orbit, hover for a tooltip, click to select, double-click to isolate one element. Buttons let you jump to a **Top view**, show **shear walls only**, or **Reset** the camera.
*Note: wall height is shown as an assumed 10 ft — it is not in the export and is clearly labelled as assumed.*

It renders the frozen export snapshot first (instant), then — if Revit is open with the connectors on (see below) — fetches the live model's geometry in the background and swaps it in. A badge in the corner always says which one you're looking at: **SNAPSHOT · export** or **LIVE · [model name]**, plus a **⟳ live** button to force a fresh read.

### QA tools
- **Measure**: click two points on the drawing to get the distance in points and feet.
- **Layers**: toggle which status types are shown on the drawing.
- **Count consistency panel** (in the inspector): for each mark, how many appear on the plan versus whether the schedule lists it — a quick sanity check.

### Revit-live features (optional — need Revit open)

These need Revit open with two connectors running: NonicaTab PRO's **A.I. Connector** switched on, and the open-source **revitMCP** add-in's **Open Server** button clicked. If either is off, the buttons below simply grey out — that is expected, not a bug.

- **🎯 Show in Revit**: on a hold-down's detail panel, selects that element in the live Revit model. There is no zoom API, so afterward **press BX in Revit** (Selection Box — crops and jumps to the selection). Don't click the drawing area first; that clears the selection.
- **🔎 Revit ID drawer**: paste an ElementId, or click **"Use current Revit selection"** to pull whatever is currently selected in Revit with one click. Either way it shows which assembly the element belongs to, its paired PDF device, and a plain-English explanation of the verdict.
- **Scope-warning banner**: if a whole element category has PDF callouts but no matches in the Revit model, an amber banner says so above the table — usually the export view had that category hidden, not that the model is actually missing everything.
- **🤖 phase summaries**: after each pipeline stage, the Live log shows a short plain-English line about what that stage actually did — not raw counts or JSON.

### Honestly limited, on purpose
- Revit's connector has no zoom call — "Show in Revit" selects, you press BX.
- The live 3D view caps very large categories and says so rather than truncating silently.
- Element IDs can change after central-model operations, so live lookups match by coordinate (nearest live element to the export point), and the response says which method it used.
- The export snapshot — not the live model — is what the verdicts and distances are computed from. Re-export and re-run the pipeline to update the actual comparison; the live connectors are for looking and clicking, not for changing the math.

---

## Part 6 — Teaching the AI (the key feature for non-standard PDFs)

Every client labels drawings differently. Rather than re-programming the tool for each one, you **teach it in plain English.**

1. Click **Teach AI** in the top bar. The assistant opens and immediately tells you **what it could not recognise** in this drawing set (e.g. a mark on the plan that isn't in any schedule, or a table titled something it doesn't know).
2. Explain the convention in the chat box, for example:
   - `HD3 means H3`
   - `TD-1 is a holdown`
   - `the STUD SCHEDULE is the post table`
3. The assistant replies in real time — *"Got it, HD3 is an alias for H3"* — and shows a **saved to memory** confirmation. The rule now appears in the memory list (with a delete button).
4. Click **Re-run Extract to apply**. The system re-scans with your rule active. Elements matched because of a taught rule carry a **brain marker** in the list and inspector.

The rules persist per project in `ai_teach_memory.json`. This works with the AI model connected (smartest) or with a built-in deterministic parser if there's no API key (it will tell you honestly if it could only save your note without changing extraction).

**Important:** teaching only affects *how elements are recognised*. It can never manufacture a MATCH — a green result still requires verified alignment and passing the distance tolerance. You cannot "talk" the tool into a false pass.

---

## Part 7 — Running it without the dashboard (API / power users)

Every stage is also an HTTP endpoint, so the pipeline can be scripted. Example (curl) against the sample project:

```
curl -X POST "http://127.0.0.1:8077/api/revit/ai-convert?use_sample=true"
curl -X POST "http://127.0.0.1:8077/api/pdf/page-intelligence?use_sample=true"
curl -X POST "http://127.0.0.1:8077/api/pdf/ai-convert"
curl -X POST "http://127.0.0.1:8077/api/registration/auto-holdown"
curl -X POST "http://127.0.0.1:8077/api/compare/ai"
curl -X POST "http://127.0.0.1:8077/api/elements/extract"
curl -X POST "http://127.0.0.1:8077/api/elements/match"
```

Then read results from `http://127.0.0.1:8077/api/elements` or download `http://127.0.0.1:8077/api/export/punch-list.csv`.

Uploading your own project instead of the sample is a single `POST /api/upload` with the PDF and Revit JSON attached; after that, every step uses your files automatically.

---

## Part 8 — Where the outputs live

Everything the tool produces is written as plain files in the `artifacts/` folder, so there is a full audit trail:

| File | What it is |
|---|---|
| `element_list.json` | The master list of every element and its status. |
| `ai_compare_report.json` | The hold-down verdicts with distances and reasons. |
| `punch_list.csv` | Every non-matching element, for the site team. |
| `ai_teach_memory.json` | The rules you have taught the system. |
| `s201_review_overlay.png` / `.svg` | The drawing with discrepancies boxed in colour. |

---

## Part 9 — Troubleshooting

| Symptom | Fix |
|---|---|
| Browser says it can't connect | The server window was closed. Re-run `.\run_backend.ps1`. |
| Page looks like a plain panel list, not the dashboard | Activate the dashboard (see the note in Part 2), then hard-refresh. |
| "No data yet — open Pipeline" | Run the pipeline once (Stage 0–9, or the sample buttons). |
| A whole sheet shows every element as "needs review" | That sheet couldn't be aligned to the model (too few shared hold-downs). This is honest behaviour, not an error. |
| Teach AI only saves "notes" | Phrase it as a rule, e.g. "X means Y" or "X is a holdown". |

---

## Part 10 — One-paragraph summary to remember

**Start the server, open the dashboard, click Run full pipeline, review the green/red element list, teach the AI any odd labels, and export the punch-list.** Green means the drawing and model agree and it's provable; red means a real discrepancy for a human to resolve. The tool never fakes a match — that is exactly why you can trust it.
