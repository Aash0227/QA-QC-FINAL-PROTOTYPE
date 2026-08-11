# QA-QC Employee Setup Guide

No technical knowledge needed. Follow the steps in order.

---

## Part 1 — One-time setup (about 10 minutes, do it once)

1. Open File Explorer and go to the QA-QC folder: **`C:\QA-QC-FINAL-PROTOTYPE-bkp`**
2. Open the **`scripts`** folder.
3. **Double-click `QAQC_Setup.bat`.**
4. Wait. The black window shows progress. It installs Python (if missing), all
   backend components, sets the system to start automatically at login, and
   checks the Revit add-ins.
5. At the end it prints a **SETUP SUMMARY**:
   - Green = done automatically.
   - Yellow = a one-time manual step is needed — read the numbered list it
     prints and see **Part 2** below.
6. Press any key to close the window.

That's the whole setup. You never need to run it again (re-running is safe if
you're unsure — it won't break or duplicate anything).

---

## Part 2 — The 3 manual things (one-time each)

### 2.1 Install NonicaTab PRO *(licensed software — cannot be auto-installed)*

1. Get the NonicaTab PRO installer and license from the engineering team.
2. Double-click the installer and click **Next / Install** through the wizard.
3. Done when `C:\NONICAPRO` exists on your computer. The setup script checks
   this for you — re-run `QAQC_Setup.bat` afterwards and it will show green.

### 2.2 Approve the Revit add-ins (first Revit launch only)

1. Open Revit after setup.
2. Revit will pop up a security window for each new add-in (revitMCP, pyRevit
   tools) asking *"Do you want to load this add-in?"*
3. Click **Always Load** on each one.
4. It will never ask again.

### 2.3 Add the API key

1. Get the `OPENROUTER_API_KEY` value from the engineering team.
2. Open File Explorer, go to `C:\QA-QC-FINAL-PROTOTYPE-bkp`, find the file
   named **`.env`**.
3. Right-click it → **Open with** → **Notepad**.
4. Find the line `OPENROUTER_API_KEY=` and paste the key right after the `=`
   (no spaces, no quotes).
5. **File → Save**, close Notepad. Sign out of Windows and back in (so the
   backend restarts with the key).

---

## Part 3 — Daily workflow (every working day)

1. **Sign in** to Windows. The QA-QC backend starts by itself, minimized —
   you don't have to click anything.
2. **Open your Revit model.**
3. **Turn the 2 switches ON** (in the Revit add-in tabs):
   - **Nonica A.I. Connector** → switch ON
   - **revitMCP** → click **Open Server**
4. Open your browser and go to: **http://127.0.0.1:8077**

The backend and Revit must run on the same computer — the connection is
localhost-only by design.

---

## Part 4 — Troubleshooting

| Problem | Fix |
|---|---|
| Browser says "can't reach" 127.0.0.1:8077 | The backend isn't running. Sign out of Windows and back in (auto-start kicks in), or double-click `run_backend.ps1` → **Run with PowerShell**. Wait 10 seconds, refresh the browser. |
| Setup window said Python failed | Install Python 3.11 by hand from python.org (Downloads → 3.11.9 → "Windows installer (64-bit)"). Tick **"Add python to PATH"** during install. Re-run `QAQC_Setup.bat`. |
| Buttons in the app do nothing / "Revit not connected" | One of the 2 switches is OFF. In Revit: Nonica A.I. Connector ON, revitMCP → **Open Server**. Then refresh the browser page. |
| Revit keeps asking to load add-ins every launch | You clicked "Load" instead of **"Always Load"**. Next launch, click **Always Load**. |
| AI features fail / "API key" error | The key in `.env` is missing or wrong. Redo step **2.3** above (or ask engineering for a fresh key). |

Still stuck? Send the file `logs\setup.log` (in the QA-QC folder) plus a photo
of any error window to the engineering team.
