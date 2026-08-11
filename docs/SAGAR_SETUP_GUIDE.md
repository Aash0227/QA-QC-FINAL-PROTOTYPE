# Livio QA-QC Intelligence — Setup Guide for Sagar Karpe

**Version:** 2026-07-31 bundle · **From:** Ashwin · **Est. time:** ~2 hours

This is a complete, self-contained setup guide. You can follow it manually, or
paste this entire document into **Claude Desktop** or **Hermes Desktop** and
say: *"Walk me through this setup step by step. Run the commands for me where
you can, and verify each checkpoint before moving on."* The AI assistant should
execute these steps exactly — it should not modify any application code.

---

## 0 · What you should have received from Ashwin

| Item | What it is |
|---|---|
| `qaqc-sagar-bundle-2026-07-31.zip` (≈83 MB) | The application + a sample project (Madera) |
| **OpenRouter API key** | Sent separately (chat/secure channel) — never stored in this document |
| **Nonica account login** | For the Nonica PRO seat purchased for your machine |
| `revit_mcp_plugin` folder + `.addin` file | The open-source Revit connector add-in, copied from Ashwin's machine |
| `LivioQAQC.extension` folder | The pyRevit "Export QAQC" button, copied from Ashwin's machine |

If any item is missing, stop and ask Ashwin before continuing.

---

## 1 · Prerequisites (install in this order)

### 1.1 Python 3.11 — exact major version required
1. Download **Python 3.11.x** (64-bit) from python.org (not 3.12/3.13 — untested).
2. In the installer, **tick "Add python.exe to PATH"**.
3. Verify in a new PowerShell window:
   ```powershell
   python --version   # must print Python 3.11.x
   ```

### 1.2 Revit + your project models
Revit must be installed with the models you review (e.g. Country Side, Dogwood).
Note your Revit **year version** — you need it in 1.4.

### 1.3 Nonica Tab (PRO)
1. Install Nonica Tab from nonica.io per their instructions.
2. Open Revit → NonicaTab ribbon → log in with the account Ashwin gave you.
3. Confirm the **"A.I. Connector"** button exists on the ribbon. Leave it OFF for now.

### 1.4 Open-source revitMCP add-in
1. Copy the `revit_mcp_plugin` folder **and** the `mcp-servers-for-revit.addin`
   file into:
   ```
   %APPDATA%\Autodesk\Revit\Addins\<YOUR REVIT YEAR>\
   ```
2. Restart Revit → a **revitMCP** ribbon tab appears, with an **Open Server** button.

### 1.5 pyRevit + the Export QAQC button
1. Install pyRevit (latest release from github.com/pyrevitlabs/pyRevit).
2. Copy the `LivioQAQC.extension` folder into `%APPDATA%\pyRevit\Extensions\`.
3. Restart Revit → the **Export QAQC** button appears in the pyRevit/Livio tab.

**Checkpoint 1:** `python --version` = 3.11.x · Revit shows NonicaTab, revitMCP,
and the Export QAQC button.

---

## 2 · Install the application

### 2.1 Extract
1. Copy the ZIP to your machine and extract it to:
   ```
   C:\qaqc\
   ```
   You should now have `C:\qaqc\backend\`, `C:\qaqc\frontend\`,
   `C:\qaqc\run_backend.ps1`, `C:\qaqc\BUNDLE_README.txt`, etc.

### 2.2 Install Python dependencies
```powershell
cd C:\qaqc\backend
python -m pip install -r requirements.txt
```

### 2.3 Configure the environment
1. Copy the template:
   ```powershell
   Copy-Item C:\qaqc\.env.example C:\qaqc\.env
   ```
2. Open `C:\qaqc\.env` in Notepad and set:
   ```
   OPENROUTER_API_KEY=<the key Ashwin sent you>
   ```
   Nothing else needs changing. Never share or commit this file.

### 2.4 First start
```powershell
cd C:\qaqc
.\run_backend.ps1 -Prod
```
Then open **http://127.0.0.1:8077** in your browser and bookmark it.

**Checkpoint 2:** the page loads showing the header
"… elements · … verified · … flagged" with the sample **madera** project in the
project dropdown. Quick API check (new PowerShell window):
```powershell
Invoke-RestMethod http://127.0.0.1:8077/api/health
```
Expect a JSON reply with `"api_key_present": true`.

### 2.5 Start on login (do NOT install as a Windows service)
A Windows service cannot talk to Revit's UI, so use a Startup shortcut instead:
1. Press `Win+R` → `shell:startup` → Enter.
2. Right-click → New → Shortcut → target:
   ```
   powershell.exe -ExecutionPolicy Bypass -File C:\qaqc\run_backend.ps1 -Prod
   ```
3. Name it "QA-QC Backend". It now starts automatically when you log in.

---

## 3 · Connect Revit (do this each work session)

1. Open your project model in Revit.
2. NonicaTab ribbon → **A.I. Connector → ON** (keep its window open, don't close it).
3. revitMCP ribbon → **Open Server** → then **close that dialog window**.
   ⚠ Any open dialog in Revit blocks all connector traffic — keep Revit free of
   pop-ups while using the webapp.
4. In Revit, click **Export QAQC** (pyRevit tab). Within ~3 seconds the webapp's
   upload card pill should flip to **"Model synced · just now · <your model>"**.

**Checkpoint 3:** in the webapp, the Revit pill is green/synced, and the 3D pane
badge switches from "SNAPSHOT" to **"LIVE · <your model name>"** shortly after load.

---

## 4 · Full working test (7 steps, ~15 min)

Run this once with Ashwin on a call, using a real project:

1. **Upload the permit PDF** (webapp → ▶ Run the check → "Open a project" step).
   The PDF is the only file you upload — the Revit side comes from Export QAQC.
2. A banner appears: *"Auto-proposed 2 benchmark registration points… Approve to
   continue."* → click **Approve** (or "Review the points" if they look wrong).
3. Click **▶ Run the check** and let the pipeline finish. Watch for the 🤖
   summary lines after each phase.
4. Click **⚠ Needs review** → open any LOCATION MISMATCH → read
   **"Why this verdict?"** — it states the offset in feet vs the 2 ft gate, the
   compass direction, and a suggested next step.
5. Click **🎯 Show in Revit** → switch to Revit **without clicking in the
   drawing area** → type **BX** → Revit jumps to the element (blue selection).
6. Reverse direction: click any element in Revit → webapp ⚙ → **Find an element
   in Revit** → **Use current Revit selection** → the element's verdict and
   explanation appear.
7. Judge one item: **False alarm** (turns it into a verified match, with audit
   trail) or **Confirmed issue**. Re-run the check — your decision must survive.

**Checkpoint 4:** all 7 steps behave as described → the deployment is good.

---

## 5 · Daily use in one paragraph

Open Revit with your model → A.I. Connector ON → Open Server (close the dialog)
→ Export QAQC → open the bookmark → upload the PDF (first time per project) →
▶ Run the check → work through **⚠ Needs review**, using "Why this verdict?",
**Show in Revit** (+ BX), and the False alarm / Confirmed issue buttons. The
user manual is `C:\qaqc\docs\LIVIO_TEAM_GUIDE.md`.

---

## 6 · Troubleshooting

| Symptom | Fix |
|---|---|
| Revit buttons greyed out, "Connector is closed or disabled" | Turn ON NonicaTab's A.I. Connector; keep its window open |
| Everything reads "nothing selected" / tools stall | A dialog is open in Revit — press Esc / close all pop-ups (keep the A.I. Connector window open) |
| Pill says "Connected — click Export QAQC in Revit" | The model hasn't been exported yet this session — click Export QAQC |
| Pill warns the export is days old | Re-run Export QAQC — you're looking at stale data |
| "…isn't a Revit Element ID" in the lookup | ElementIds are plain numbers; easier: select in Revit and click "Use current Revit selection" |
| Page won't load | Backend not running — run `C:\qaqc\run_backend.ps1 -Prod`, or restart your machine (Startup shortcut relaunches it) |
| Port 8077 already in use | An old copy is running: `Get-NetTCPConnection -LocalPort 8077 -State Listen \| % { Stop-Process -Id $_.OwningProcess -Force }` then start again |
| Anything else | Send Ashwin the last lines of `C:\qaqc\logs\app.log` |

---

## 7 · Notes for the AI assistant (Claude/Hermes Desktop)

If Sagar pasted this guide into you: execute sections 1–4 in order, running the
PowerShell commands on his behalf where you have shell access, and stop at each
**Checkpoint** to verify before continuing. Ask Sagar to perform the Revit-side
clicks (ribbon buttons, BX) and the credential entry himself — never handle the
API key value directly, never modify files under `C:\qaqc\backend\` or
`C:\qaqc\frontend\`, and never delete anything. If a checkpoint fails, show the
exact error output and the matching troubleshooting row instead of improvising
fixes.
