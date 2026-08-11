# QA Team Runbook — QA-QC Automated System

**Architecture (why it works this way):** the backend serves the frontend itself via
StaticFiles, so there is **one** app to run and no separate web host. There is deliberately
**no Vercel/cloud frontend** — the backend must run on the *same machine as Revit* to reach
the localhost Revit MCP connectors, and a hosted frontend would break that loopback.
The backend is distributed as a **tagged release on the private GitHub repo**; QA laptops
clone it once and pull updates with a script.

## Daily start

1. Sign in to Windows — the backend starts automatically (startup shortcut created by the
   installer). If it isn't running: double-click the **QAQC-Backend** shortcut, or run
   `.\run_backend.ps1 -Prod` from the repo folder.
2. Open your Revit model.
3. Enable **both** connectors:
   - Nonica **A.I. Connector** → ON
   - **revitMCP** → *Open Server*
4. Browse to **http://127.0.0.1:8077**

## Updating to a new release

Run `scripts\update_qaqc.ps1` (right-click → *Run with PowerShell*). It does `git pull` +
dependency refresh. Restart the backend afterwards (close its console window, re-run
`run_backend.ps1 -Prod`, or sign out/in).

## Troubleshooting

| Symptom | Fix |
|---|---|
| Connector offline / live features dead | In Revit: enable Nonica **A.I. Connector**, and click **Open Server** in revitMCP |
| HTTP 401 from the API | Check `QAQC_AUTH_TOKEN` in `.env` matches what the client sends |
| Stale results | Re-export from Revit — the export is the source of truth |
| Something else | Logs at `logs\app.log` |

## Honest limitations

- **BX to zoom**: live bounding-box interaction is zoom/highlight only.
- **The export is the source of truth for all math** — numbers come from the Revit export,
  not from live queries.
- **Live = interaction only.** The Revit connection drives selection/zoom; it does not
  recompute results.
