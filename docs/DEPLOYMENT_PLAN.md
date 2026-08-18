# QBC — Deployment Plan for Livio

**Status:** plan only. Nothing here has been implemented.
**Derived from:** the actual repository, not a reference architecture. Every
constraint below was verified in code; file references let you re-check each.

---

## 1. What the architecture actually is

| Component | Reality in this repo | Deployment consequence |
|---|---|---|
| Backend | Single FastAPI app, `uvicorn app.main:app`, **one worker** (`docs/DEPLOY.md:8`) | Cannot be horizontally scaled as-is |
| Frontend | Static Vite build, mounted by the backend itself (`main.py:151`) | No separate web server needed |
| Database | **None.** Every artifact is JSON on disk under `artifacts/projects/<slug>/` (`config.py:19-22`) | Backups are file backups; no DB to operate |
| Auth | One shared bearer token, `QAQC_AUTH_TOKEN` (`main.py:41`). Empty = **no auth at all** | Not per-user; see section 5 |
| Project isolation | `X-Project` header or `?project=`, bound per request into a ContextVar (`routers/common.py:34-48`) | Isolation is per-request, not per-user |
| Revit connectivity | Backend **spawns `RevitMCPConnection.exe` locally** (`revit_bridge.py:34-36, 715`) | **The defining constraint** |
| LLM | OpenRouter over HTTPS, `OPENROUTER_API_KEY` | Needs egress; advisory-only, never gates a verdict |

### The constraint that decides everything

`revit_bridge.py` launches Nonica's `RevitMCPConnection.exe` as a **local child
process over stdio**. It does not speak to Revit over the network. Therefore:

> **The backend can only talk to Revit on the machine where Revit is running.**

A conventional "put the server in the cloud" deployment **cannot reach Revit**.
Any plan that ignores this yields a system that works up to the model-comparison
step and then fails on every project.

---

## 2. Recommended architecture: central server + local Revit agent

Two deployable units, split exactly along the constraint above.

```
QA engineer workstation                     Livio server (Windows VM)
+---------------------------+              +-----------------------------+
|  Browser  ----------------+--- HTTPS ----+->  QBC backend (FastAPI)    |
|                           |              |    + built frontend         |
|  Revit + Nonica           |              |    + artifacts/ on disk     |
|    ^                      |              |           |                 |
|  QBC Revit Agent  <-------+-- outbound --+-----------+                 |
|  (small local service)    |   WebSocket  |                             |
+---------------------------+              +-----------------------------+
                                                    | HTTPS
                                                    v  OpenRouter (advisory)
```

**Why this split:** PDF extraction, registration, matching and the review UI are
pure computation over files, so they belong on a shared server. Only the Revit
conversation is machine-bound, so only that moves to the workstation.

**Honest cost:** the Revit Agent **does not exist yet**, and it is not a trivial
wrapper. `revit_bridge.py` assumes it can spawn a process and own its stdio.
Making that remote means defining a request/response protocol, handling the
agent going offline mid-run, and deciding what a pipeline does when Revit is
unavailable. **Estimate: several days, not hours.**

### Interim option (recommended for the CEO demo and first pilot)

**Single-workstation deployment.** Install backend + frontend on one Windows
machine that already runs Revit and Nonica. One QA engineer uses it locally;
others can reach it over the LAN for everything except live-Revit actions.

This needs **no new code** and is the honest answer to "what can ship this week".
It does not scale past roughly one concurrent Revit user — a real limit, not a
temporary one.

---

## 3. Employee workflow (target state)

1. Open `https://qbc.livio.internal` (served by the backend itself).
2. Authenticate — see section 5, the weakest part today.
3. Create or select a project (`POST /api/projects`; `X-Project` thereafter).
4. Upload the structural PDF set (`POST /api/upload`; 50 MB cap, magic-byte checked).
5. Connect Revit: open the model; the local agent registers with the server.
6. Run the pipeline; watch live SSE progress with per-stage plain-English narration.
7. Read results as **LOCATION_MATCH / LOCATION_MISMATCH / NEEDS_REVIEW**.
8. Open an element for its evidence: distance, registration quality, which
   evidence channel decided it, candidates ruled out.
9. Ask the QBC QA/QC Agent "why is this a mismatch?" — answered from recorded
   evidence via `explain_element`, never from speculation.
10. Export the punch list (`GET /api/export/punch-list.csv`).

---

## 4. Infrastructure

**Server:** Windows Server or Windows 11 VM, 8 vCPU / 16 GB RAM / 250 GB SSD.
Windows rather than Linux because the Revit tooling is Windows-only, and one OS
avoids a second build target if the agent is ever co-located.

- Python 3.11+, `pip install -r backend/requirements.txt`
- `npm ci && npm run build` in `frontend/` (backend serves `frontend/dist`)
- Run under NSSM or a Windows Service wrapper so it survives reboot
- **`--workers 1` is mandatory**, not a tuning choice (`docs/DEPLOY.md:8`): the
  artifact store and the Revit bridge both assume a single process. A second
  worker would race on artifact writes.
- Reverse proxy (IIS or Caddy) terminating TLS in front of uvicorn

**Storage:** `artifacts/` is the entire state of the system. Give it a dedicated
volume. Per-project subdirectories make per-project restore a directory copy.

---

## 5. Security, and its current honest state

**What exists:** one shared bearer token for all `/api/*` (`main.py:41`).

**What that means:** **no user accounts, no per-user permissions, no audit trail
of who did what.** Everyone shares one secret. If it leaks, every project is
exposed, and rotating it logs everyone out at once.

**Acceptable for a pilot on a trusted internal network. Not acceptable for wider
rollout.** Staged path:

1. **Now:** set `QAQC_AUTH_TOKEN` — it defaults to *empty*, which disables auth
   entirely, so verify it is set before any network exposure. Bind to the
   internal network; TLS at the proxy.
2. **Next:** put the app behind the company IdP (Entra ID / Okta) at the reverse
   proxy. Real identity, no application changes.
3. **Later:** per-user sessions and per-project ACLs in the app, once project
   ownership actually matters.

`OPENROUTER_API_KEY` is server-side only and already never reaches the browser.
Uploads are size- and magic-byte-checked. The LLM is advisory throughout and
never gates a MATCH verdict, so an LLM outage degrades explanations, not
correctness.

---

## 6. Logging, backup, monitoring

- **Logging:** already file-based and rotating (`QAQC_LOG_FILE`,
  `QAQC_LOG_MAX_BYTES`, `QAQC_LOG_BACKUPS`).
- **Backups:** nightly snapshot of `artifacts/` — that is the whole system state.
  Test a restore before relying on it.
- **Monitoring:** poll `/api/health`; alert on process down, disk above 80%, and
  repeated pipeline stage failures. The per-stage summaries in
  `phase_summaries.json` make failures legible without reading logs.

---

## 7. Deployment steps

1. Provision the Windows VM; install Python 3.11 and Node 20.
2. Clone the repo; `pip install -r backend/requirements.txt`.
3. `cd frontend && npm ci && npm run build`.
4. Create `.env`: `QAQC_AUTH_TOKEN` (**required**), `OPENROUTER_API_KEY`, log settings.
5. Install as a Windows Service via NSSM:
   `uvicorn app.main:app --host 127.0.0.1 --port 8077 --workers 1`.
6. Configure the reverse proxy with TLS; expose only to the internal network.
7. Point `artifacts/` at the dedicated volume; schedule the nightly backup.
8. Smoke test: create a project, upload a PDF, run the pipeline, confirm verdicts
   render and the punch-list export downloads.
9. **Revit:** until the agent exists, use the single-workstation deployment for
   any workflow needing live Revit.

---

## 8. Rollback

The app is stateless relative to `artifacts/`, so rollback is a code rollback:
stop the service, `git checkout <previous tag>`, rebuild the frontend, restart.
Artifacts are forward-compatible — the element list is backfilled with product
verdicts at read time, so an older artifact still renders on a newer build. Keep
the previous build directory until the new one is confirmed.

---

## 9. Open questions before rollout

1. **Revit Agent** — the only real engineering work. Scope and schedule it, or
   accept single-workstation deployment as the product for now.
2. **Identity** — the shared token is a pilot-grade answer. Decide when IdP happens.
3. **Concurrency** — one worker means one pipeline at a time. Two engineers
   running pipelines simultaneously will queue. Fine at current team size;
   measure before it isn't.
