# Deployment — QA-QC webapp (production-plan §10)

Runs on the **same Windows machine as Revit** — the Nonica MCP bridge spawns
`RevitMCPConnection.exe` locally, so co-location is required, not optional.

## Process model

- **One worker.** `uvicorn --workers 1`. The artifact store and the Revit
  bridge lock are single-process by design; a second worker would race the
  benchmark-workflow state file and double-drive the MCP exe.
- The backend also serves the frontend (`StaticFiles`), so there is one
  process to run, not two.

## Run it

```powershell
./run_backend.ps1            # dev  — auto-reload; honors $env:BIND_HOST (default 127.0.0.1)
./run_backend.ps1 -Prod      # ship — one worker, no reload; -Port 8077 by default
```

### Auto-start — a Startup-folder shortcut, **not** a Windows service

**Do not run this app as a service (NSSM or `sc create`).** A Windows service
runs in **session 0**, which has no access to the interactive desktop — and the
Nonica/revitMCP bridge drives the **Revit UI in the logged-on user's session**.
Under a service, every Revit-live feature (Show-in-Revit, selection sync, ID
lookup, live 3D) breaks, and it breaks *silently* — the HTTP API still answers.
This is a hard constraint, not a preference.

- **Pick this:** `Win+R` → `shell:startup` → new shortcut to
  ```
  powershell.exe -ExecutionPolicy Bypass -File "C:\QA-QC-FINAL-PROTOTYPE\run_backend.ps1" -Prod
  ```
  Set **Run: Minimized**. It launches inside the interactive logon session by
  construction — no admin rights, no service account, nothing to debug.
- **Upgrade path — Task Scheduler:** a task "At log on of \<user\>", Action =
  `run_backend.ps1 -Prod`, **"Run only when user is logged on"** (same session-0
  reason). Equivalent to the shortcut, plus restart-on-failure. Move to it only
  when auto-restart-on-crash actually matters.

## Environment variables

| Var | Default | Purpose |
|-----|---------|---------|
| `BIND_HOST` | `127.0.0.1` | Bind address. `0.0.0.0` exposes on the LAN — only with an auth token set. |
| `QAQC_AUTH_TOKEN` | *(unset → auth off)* | When set, every `/api/*` route (except `/api/health`) needs `Authorization: Bearer <token>` (or `?token=` for SSE/images). Set this whenever `BIND_HOST` is not localhost. |
| `NONICA_MCP_EXE` | `C:\NONICAPRO\...\RevitMCPConnection.exe` | Path to the Nonica MCP connector the bridge spawns. |
| `OPENROUTER_API_KEY` | *(unset)* | Enables the agentic chatbot (`/api/chat`). App runs without it; chat is the only feature that needs it. |
| `OPENROUTER_REASONING_MODEL` | `deepseek/deepseek-v4-pro` | Chat model. |
| `QAQC_EVIDENCE_CAP_MB` | `512` | Per-project evidence-crop cache cap; oldest crops GC'd at startup. |
| `QAQC_LOG_FILE` | `logs/app.log` | Rotating structured log (5 MB × 5 backups; tune via `QAQC_LOG_MAX_BYTES`, `QAQC_LOG_BACKUPS`). |

## Security posture

- Localhost-only by default. Do not set `BIND_HOST=0.0.0.0` without
  `QAQC_AUTH_TOKEN`.
- Secrets come from the environment / `.env` (gitignored) — never commit keys.

## Tests / gates

```powershell
cd backend;  python -m pytest -q          # unit + router + bridge (fake MCP)
cd frontend; npx playwright test          # browser smoke (asserts MATCH=107)
```

Live-Revit tests are marked `revit_live` and auto-skip unless the connector
answers `status`.
