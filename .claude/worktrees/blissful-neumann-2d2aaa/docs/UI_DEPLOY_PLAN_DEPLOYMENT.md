# Deployment Plan — QA-QC webapp → Sagar Karpe (Livio), ship day

**Status:** PLAN ONLY. Nothing in this document has been implemented. No code
was changed to produce it.
**Scope:** one user (Sagar Karpe, QA-QC reviewer), one machine, one Revit.
**Author context:** Ashwin = founder / operator. "Agent-doable in advance" =
can be done in-repo before anyone touches Sagar's machine.

---

## 0 · The architecture decision (read this first)

### 0.1 The hard constraint

Three subsystems must be on the **same Windows machine and the same
interactive logon session** as Revit:

| Subsystem | Evidence | Why co-located |
|---|---|---|
| Nonica bridge | `backend/app/revit_bridge.py:32` — `NONICA_EXE` defaults to `C:\NONICAPRO\OtherFiles\System\Core\net8.0-windows\RevitMCPConnection.exe`; `:682` `StdioServerParameters(command=NONICA_EXE)` | The backend **spawns the exe as a child process**. It cannot spawn it on another machine. |
| revit-mcp add-in | `backend/app/revit_bridge.py:415` — `REVIT_MCP_ADDR = "127.0.0.1:8080"`; `:424` `socket.create_connection(...)` | Raw TCP to loopback. The add-in binds inside Revit's process. |
| Revit UI session | `docs/DEPLOY.md:31-33` — "Run only when user is logged on" | Both connectors need the interactive desktop; neither works from session 0. |

`docs/DEPLOY.md:3-4` already states this: *"Runs on the same Windows machine as
Revit … co-location is required, not optional."*

### 0.2 Option 1 — everything on Sagar's workstation (localhost-only)

Backend binds `127.0.0.1:8077`, Revit + both connectors on the same box.

**Works:** every feature. Show in Revit, `Use current Revit selection`, live
hybrid 3D, benchmark marker placement, the ID drawer, the whole pipeline.

**Requires on Sagar's machine:** Python 3.11, the repo, `.env` with the
OpenRouter key, Revit + the client model, the revit-mcp add-in, the pyRevit
exporter extension, and — **flagged, see §0.4** — a Nonica PRO seat.

**Cost:** one €85/yr Nonica seat (if the PRO-gated features are in scope on
day one), plus ~90 min of provisioning.

### 0.3 Option 2 — backend on Ashwin's machine, Sagar over LAN

`BIND_HOST=0.0.0.0` + `QAQC_AUTH_TOKEN`, Sagar opens
`http://<ashwin-ip>:8077` in his browser.

**Spell out the constraint honestly:** the backend's Revit-live calls resolve
to **the Revit running on Ashwin's machine**. So:

- "🎯 Show in Revit" highlights an element in **Ashwin's** Revit window. Sagar
  sees nothing happen on his screen.
- "Use current Revit selection" reads **Ashwin's** current selection, not
  Sagar's.
- The LIVE 3D badge shows **Ashwin's** open model. If Ashwin has a different
  model open — or none — the badge and geometry are about the wrong document.
- Benchmark marker placement (`POST /api/benchmark-workflow/place-markers`)
  **creates geometry in Ashwin's live model**.
- If Sagar has the same model open on his machine at the same time, this is
  actively dangerous: two people, one authoritative Revit, and the UI gives no
  signal about whose it is.

Option 2 is only sane in two narrow shapes:

1. **Co-review / screen-share:** Ashwin drives Revit, Sagar drives the webapp,
   both look at Ashwin's Revit on a shared screen. Works well for a demo.
2. **Export-snapshot-only review:** Ashwin's Revit is closed / connectors off.
   Sagar reviews the uploaded export + PDF. The Revit-live buttons grey out
   honestly with a reason (this behavior already ships — README "Revit-live
   buttons grey out honestly when Revit is offline"). This loses roughly the
   whole §5 chapter of the team guide but the verdict math is unaffected:
   `README.md` — *"The Revit add-in is not read directly for the comparison
   math."*

### 0.4 ⚠️ LICENSING DECISION — needs an answer before D2

Nonica PRO is **€85/yr per seat** and is currently licensed on **Ashwin's**
machine (`docs/NONICA_PRO_FEASIBILITY_EVALUATION.md:41,73,101,124`).

The split matters, because it is not all-or-nothing:

| Nonica tier | Tools | Features on Sagar's machine |
|---|---|---|
| **Free** (read) | `get_active_view_in_revit`, `get_elements_by_category`, `get_location_for_element_ids`, `get_all_elements_of_specific_families` | Connector status badge, live 3D pane, live element-id lookup by coordinate, Revit ID drawer read path |
| **PRO** (edit, €85/yr/seat) | `set_user_selection_in_revit`, `set_copy_elements`, `set_parameter_value_for_elements` | 🎯 **Show in Revit**, benchmark **marker placement** in the live model |

**Three ways to resolve it — pick one, today:**

- **(A) Buy a second seat, €85/yr.** Full feature parity for Sagar. Recommended
  if Show-in-Revit is part of what he was promised.
- **(B) Ship without PRO on Sagar's machine.** Free-tier reads work; Show-in-
  Revit and marker placement fail. The app already greys these out honestly, so
  it degrades visibly rather than silently — but Sagar must be told in D5 that
  those two buttons are off, and why, or the honest grey-out reads as a bug.
- **(C) Move Ashwin's seat to Sagar's machine.** Zero cost, but Ashwin loses
  live Revit dev/debug capability. Not recommended while the product is still
  being iterated on.

The open-source revit-mcp add-in is **free and unlicensed** — the ID-drawer
"Use current Revit selection" path goes through it (`revit_bridge.py:457-459`),
so that specific feature survives option (B).

### 0.5 Recommendation

> **PRIMARY: Option 1** — install everything on Sagar's workstation,
> localhost-only, `BIND_HOST` left at its `127.0.0.1` default, no auth token
> needed. It is the only configuration where the product's headline features
> (Show in Revit, live 3D, selection sync) are actually true for the person
> using them. Resolve §0.4 as **(A) buy the second seat** if Show-in-Revit is
> in scope; otherwise **(B)** and say so out loud in training.
>
> **FALLBACK: Option 2 in the "co-review" shape** — if Sagar's machine cannot
> take Python + the two add-ins today (IT lockdown, no admin rights, Revit
> version mismatch), run the backend on Ashwin's machine with
> `BIND_HOST=0.0.0.0` **and** `QAQC_AUTH_TOKEN` set, and do the first review
> session as a shared-screen walkthrough with Ashwin driving Revit. Treat this
> as a stopgap measured in days, not the deployment.

---

## PHASE D1 — Pre-flight hardening (in-repo, today, before anything is copied)

Owner: **agent-doable in advance** unless marked. Total ≈ 2 h.
These are **plan items only** — none are implemented.

### D1.1 🔴 CRITICAL — rotate the GitHub PAT embedded in `.git/config`

**Owner: Ashwin (only he can rotate it). 10 min. Do this first.**

`git remote -v` returns a URL of the form
`https://Aash0227:ghp_<REDACTED>@github.com/Aash0227/QA-QC-FINAL-PROTOTYPE.git`.
A live GitHub personal access token is stored in cleartext in
`.git/config`. **Any copy of this folder — zip, robocopy, USB — hands Sagar
(and anyone with access to his machine) Ashwin's GitHub credentials.**

Plan:
1. Revoke the token at github.com → Settings → Developer settings → PATs.
2. Issue a new fine-grained token scoped to this one repo, read-only if Sagar
   only ever pulls.
3. `git remote set-url origin https://github.com/Aash0227/QA-QC-FINAL-PROTOTYPE.git`
   and let **Git Credential Manager** hold the secret, so it never lands in a
   file that gets copied.
4. Verify: `git remote -v` shows no `@` before the host.

*Not a code change — a credential-hygiene gate on D3.*

### D1.2 Fail closed when `BIND_HOST` is not localhost and no token is set

**Owner: agent. ~15 lines in `backend/app/main.py`. 20 min.**

Today: `main.py:38` `AUTH_TOKEN = os.environ.get("QAQC_AUTH_TOKEN", "").strip()`
— empty by default, so `main.py:98` no-ops and every route is open. `BIND_HOST`
is read **only by `run_backend.ps1:9`**; the app itself has no idea what
address it is bound to. So `BIND_HOST=0.0.0.0` with no token is a silent
full-open LAN exposure, and the audit already calls it out
(`docs/CODEBASE_AUDIT_REPORT.md:253`).

Plan: in `create_app()`, read `BIND_HOST`; if it is not in
`{"", "127.0.0.1", "localhost", "::1"}` **and** `AUTH_TOKEN` is empty, raise on
startup with a message naming `QAQC_AUTH_TOKEN`. Fail-closed, not a warning —
a warning scrolls past in a console nobody is watching.

Verify: `$env:BIND_HOST="0.0.0.0"; ./run_backend.ps1` refuses to start;
setting `QAQC_AUTH_TOKEN` lets it start; unset `BIND_HOST` still starts clean.

*ponytail: one guard in `create_app`, not a config-validation layer.*

### D1.3 Stop writing the bearer token to `logs/app.log`

**Owner: agent. ~8 lines in `backend/app/maintenance.py`. 20 min.**

Root cause (`docs/CODEBASE_AUDIT_REPORT.md:251,298`): `main.py:101-104` accepts
`?token=` as a full credential — necessary, because EventSource/`<img>`/
`window.open` cannot set headers (`frontend/src/api.js:17-20` `tokenized()`) —
and `maintenance.py:67-68` attaches the rotating file handler to
`uvicorn.access`, whose format string includes the full request line. Every SSE
connect and every evidence crop therefore writes the token to disk in cleartext,
where it survives log rotation.

Plan: add a `logging.Filter` on the handler in `setup_logging()` that rewrites
`token=<anything>` to `token=REDACTED` in the formatted record. Attach it to the
handler, **not** to `uvicorn.access` — one filter then covers every logger that
ever formats a URL, present and future. Do **not** detach the access logger:
that trades a leak for the loss of the whole request audit trail.

Verify: start with `QAQC_AUTH_TOKEN=testtoken`, hit
`/api/health?token=testtoken`, `grep testtoken logs/app.log` → no match; the
request line is still present with `token=REDACTED`.

*ponytail: a redacting filter on one handler beats per-call-site scrubbing.
Skipped: structured JSON logging — add when someone actually ships these logs
somewhere.*

### D1.4 `requirements.txt` — already pinned, verified complete. No action.

`backend/requirements.txt` pins exact `==` versions for all five direct deps
(`fastapi==0.136.1`, `uvicorn==0.47.0`, `PyMuPDF==1.27.2.3`,
`python-multipart==0.0.20`, `Pillow==12.2.0`, `mcp==1.27.2`).

Cross-checked against every third-party import in `backend/app/**`: only `PIL`,
`fitz`, `fastapi` and `mcp` appear — HTTP calls go through stdlib `urllib`
(`openrouter.py`), so there is no unpinned `requests`/`httpx` hiding.
**Nothing to fix.**

*Skipped: a hash-pinned lockfile (`pip-compile`). Add when the install target
count exceeds one machine.*

### D1.5 Ship-mode launcher — drop `--reload`

**Owner: agent. ~6 lines in `run_backend.ps1`. 15 min.**

`run_backend.ps1:13,15` runs `uvicorn --reload`. That is a dev flag: it forks a
reloader supervisor plus a worker, which contradicts `docs/DEPLOY.md:8-10`
("One worker … a second worker would race the benchmark-workflow state file and
double-drive the MCP exe"), and it restarts the server on any file touch —
mid-pipeline, on a machine where the user is not expecting it.

Plan: add a `-Prod` switch (or read `$env:QAQC_PROD`) that runs
`--workers 1` with no `--reload`. Keep the reload path as the default for
Ashwin's dev loop. Sagar's shortcut passes `-Prod`.

Verify: `./run_backend.ps1 -Prod`; `Get-Process python` shows one process, not
two; editing a `.py` file does not restart it.

### D1.6 `/api/health` detail is unauthenticated

**Owner: agent. ~5 lines in `backend/app/routers/system.py`. 15 min.**

`main.py:99` exempts `/api/health` from auth by design (probes). But
`system.py:29,39-42` returns the absolute `artifact_dir` and the sample-input
filesystem paths to any unauthenticated caller
(`docs/CODEBASE_AUDIT_REPORT.md:537`). Harmless on localhost; a free filesystem
map on a LAN deployment.

Plan: when `AUTH_TOKEN` is set **and** the request is unauthenticated, return
the short `{"status":"ok","version":...}` form; return the full dict otherwise.

Note the related audit item is **already fixed**: `config.py:196-200` no longer
emits `api_key_preview` (the comment reads *"No key preview: this dict is
served unauthenticated on /api/health"*), and `main.py:105` already uses
`hmac.compare_digest`. `docs/CODEBASE_AUDIT_REPORT.md:252,271` are stale on
those two lines.

### D1.7 Documentation corrections DEPLOY.md/team guide already owe

**Owner: agent. 20 min. Doc-only.**

| Doc | Line | Wrong | Right |
|---|---|---|---|
| `docs/LIVIO_TEAM_GUIDE.md:255` | "Server logs: `backend/logs/`" | Actual path is `<repo root>/logs/app.log` (`maintenance.py:17` — `config.PROJECT_ROOT / "logs"`) | Fix the path |
| `docs/DEPLOY.md:24` | "**nssm** (recommended)" | NSSM runs as a Windows **service in session 0**, which cannot reach the interactive Revit UI — the exact thing `DEPLOY.md:31-33` says is required. NSSM is the wrong tool for this app. | Demote NSSM; promote logon-session launch (see D3.4) |
| `docs/LIVIO_TEAM_GUIDE.md:16` | Start command has no `BIND_HOST`/prod note | Add the `-Prod` shortcut from D1.5 | |

### D1.8 Tag before you ship

**Owner: Ashwin. 2 min.** `git tag deploy-sagar-2026-07-31 && git push --tags`
(after D1.1 fixes the remote URL). This is the rollback anchor for D6.

### D1.9 Green gate

**Owner: agent. 15 min (run time).**
`cd backend; python -m pytest -q` (expect the 279-green baseline from
`AGENT_HANDOFF.md:120`) and `cd frontend; npx playwright test`
(7 specs; the smoke asserts the Madera MATCH baseline). Both must pass **after**
D1.2/D1.3/D1.5/D1.6 land. Nothing ships on a red suite.

---

## PHASE D2 — Provision the target machine

Owner: **Ashwin** (needs physical/remote access + admin on Sagar's box).
Time: ≈ 90 min. Agent cannot do any of this in advance.

### D2.1 Installer checklist

| # | Item | Exact version / path | Notes |
|---|---|---|---|
| 1 | **Python 3.11** (64-bit) | Install to `C:\Users\<sagar>\AppData\Local\Programs\Python\Python311\` | `run_backend.ps1:2` — *"MUST run under Python 3.11"*; `run_backend.ps1:11` probes that exact path first, then falls back to `py -3.11`. Do **not** install 3.12/3.14. Tick "py launcher" during install. |
| 2 | **Autodesk Revit** | Same major version as the add-in target — **2023** (`revit_bridge.py:411` — `%APPDATA%\Autodesk\Revit\Addins\2023\`) | If Sagar is on 2024/2025, the revit-mcp add-in folder must be re-targeted; confirm before ship day. |
| 3 | **The client model** | `.rvt`, opened before any live feature is used | Must be the *same* model the uploaded export came from. |
| 4 | **NonicaTab PRO** | Installs `C:\NONICAPRO\OtherFiles\System\Core\net8.0-windows\RevitMCPConnection.exe` | **⚠️ See §0.4 — license seat decision.** Verify the exe path after install; if it differs, set `NONICA_MCP_EXE` in `.env` rather than editing code (`revit_bridge.py:33`). |
| 5 | **revit-mcp add-in** (open-source `mcp-servers-for-revit`) | Copy the `revit_mcp_plugin` folder + its `.addin` manifest into `%APPDATA%\Autodesk\Revit\Addins\2023\` | Free. Source folder is on Ashwin's machine at that same path — copy it verbatim. Listens on TCP `127.0.0.1:8080` once "Open Server" is clicked. |
| 6 | **pyRevit + the Livio QA-QC exporter extension** | pyRevit (current stable) + the "Livio QA-QC → Export" extension | ⚠️ **The exporter lives outside this repo** (`docs/REVIT_SIDE_FLAW_REPORT.md:7` — *"need the pyRevit exporter, outside this repo"*; `docs/PRODUCTION_ROADMAP.md:45` — *"installed per machine by hand"*). Ashwin must locate the extension folder and copy it. Emits schema v3.1+ (`docs/LIVIO_TEAM_GUIDE.md:32`). |
| 7 | **Chrome or Edge** | Any current | The frontend ships as native ES modules, no build step (`frontend/package.json` description). |
| 8 | Firewall | Nothing to open for Option 1 | Loopback only. If the fallback (Option 2) is used, TCP 8077 inbound on Ashwin's machine — **and only with `QAQC_AUTH_TOKEN` set**. |

### D2.2 Verification for D2

Run each, in order, on Sagar's machine:

```powershell
py -3.11 --version                  # → Python 3.11.x
Test-Path "C:\NONICAPRO\OtherFiles\System\Core\net8.0-windows\RevitMCPConnection.exe"
Test-Path "$env:APPDATA\Autodesk\Revit\Addins\2023\revit_mcp_plugin"
```

Then, with the model open in Revit: Nonica ribbon shows **A.I. Connector**;
revitMCP ribbon shows **Open Server**; pyRevit ribbon shows **Livio QA-QC →
Export**. Three ribbons present = D2 done.

**⚠️ Known gotcha to pre-brief (R-35, `AGENT_HANDOFF.md:140-141`):** a modal
dialog left open in Revit — including revitMCP's own "Open Server" dialog —
**blocks every MCP tool call**. The backend now reports this as an honest error
with an unblock hint rather than "nothing selected". Tell Sagar: dismiss Revit
dialogs before clicking anything Revit-live.

---

## PHASE D3 — Install the app

Owner: **Ashwin**, with agent-prepared seed bundle. Time: ≈ 45 min.

### D3.1 Code transfer — `git clone`, not a folder copy

**Decision: git clone.** Reasons, from the actual repo state:

- Only **196 files are tracked**; `size-pack` is trivial. The clone is seconds.
- A folder copy carries `.git/config` — **the PAT from D1.1**. Even after
  rotation, don't build the habit.
- A folder copy also carries `artifacts/` (**577 MB**),
  `artifacts_madera_snapshot/` (23 MB), `artifacts_old_contaminated/` (23 MB),
  `node_modules/`, ~40 loose debug `.png` files at the repo root, and
  `server-out.log` / `server-err.log`. All of it noise; most of it already
  `.gitignore`d precisely because it is runtime state.
- `git pull` is the D6 update path. Starting from a clone makes that free.

```powershell
cd C:\
git clone https://github.com/Aash0227/QA-QC-FINAL-PROTOTYPE.git QA-QC-FINAL-PROTOTYPE
# credential prompt → Git Credential Manager stores the new fine-grained PAT (D1.1)
cd C:\QA-QC-FINAL-PROTOTYPE\backend
py -3.11 -m pip install -r requirements.txt
```

### D3.2 Seed data — what actually ships, and why

**`.gitignore:22` ignores `artifacts/projects/`.** The Madera sample therefore
**does not travel via git**, and the README's "ships with a bundled Madera
sample project" is false for a fresh clone. This must be handled deliberately.

What *does* travel via git: `artifacts/memory/global.json` — the single tracked
artifact (cross-project teach memory, `config.py:148-151`). Good; Sagar inherits
the learned exclude/vocabulary rules.

**Decision — ship exactly one seed workspace, Madera, stripped:**

| Workspace | Size | Ship? | Why |
|---|---|---|---|
| `madera` | 252 MB | ✅ **yes, stripped** | It is the reference baseline — the Playwright smoke asserts the Madera MATCH count (`docs/DEPLOY.md:57`), and `LIVIO_TEAM_GUIDE.md:238` quotes it as the acceptance reference (354 elements · 107 MATCH). Sagar needs a known-good project to compare against when something looks wrong. |
| `country-side-ct` | 263 MB | ❌ no | Second live-verified project; nice for Ashwin, dead weight for Sagar. |
| `dogwood-lane` | 37 MB | ❌ no | Historical. |
| `madera_prev_v2_run` | 25 MB | ❌ no | Superseded v2 export (`docs/PRODUCTION_ROADMAP.md:18`). |

**Strip before zipping:** inside `artifacts/projects/madera/`, drop `evidence/`
and `pages/` — both are regenerable caches (the evidence GC deletes them
routinely, `maintenance.py:22-24` — *"Evidence crops are regenerable from the
source PDFs"*). Keep the `.json` artifacts, `punch_list.csv`, `run_baseline.json`
and `uploads/`. Expect the bundle to land well under 100 MB.

Also **do not ship** `artifacts/_*.json` (loose debug dumps at
`artifacts/_activate.json`, `_bm_calib.json`, `_match_err.json`, …) or
`artifacts/active_project.json` — the last one is Ashwin's UI preference and
would point Sagar at a project he does not have. `config.active_project()`
(`config.py:55-63`) falls back to `"madera"` when the file is absent, which is
exactly the right landing state.

Transfer: one zip over Teams/USB, unpacked to
`C:\QA-QC-FINAL-PROTOTYPE\artifacts\projects\madera\`.

### D3.3 `.env`

**Owner: Ashwin. `.env` is gitignored (`.gitignore:2`) — it will not be in the
clone.** Copy `.env.example` → `.env` and fill:

```ini
OPENROUTER_API_KEY=<key>
OPENROUTER_REASONING_MODEL=deepseek/deepseek-v4-pro
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
# add only if D2.1 item 4 installed Nonica somewhere non-default:
# NONICA_MCP_EXE=C:\...\RevitMCPConnection.exe
```

Do **not** set `BIND_HOST` or `QAQC_AUTH_TOKEN` for Option 1 — the defaults
(`127.0.0.1`, auth off) are correct for a localhost-only install, and D1.2 makes
the unsafe combination impossible.

Note: the app runs **without** the OpenRouter key; chat is the only feature that
needs it (`docs/DEPLOY.md:42`). If the key is a per-seat billing concern, ship
without it and the chat panel degrades honestly.

Verify: `GET /api/health` → `openrouter.api_key_present: true`.

### D3.4 Auto-start — **Startup-folder shortcut**, not NSSM, not Task Scheduler

Evaluated, in order of laziness:

| Option | Verdict |
|---|---|
| **Startup-folder shortcut** ✅ **pick this** | `Win+R` → `shell:startup` → shortcut to `powershell.exe -ExecutionPolicy Bypass -File "C:\QA-QC-FINAL-PROTOTYPE\run_backend.ps1" -Prod`. Runs in the interactive logon session **by construction** — which is exactly what the Nonica bridge needs. No admin rights, no service account, no XML, nothing to debug at 9am on ship day. |
| Task Scheduler "At log on" | Works (and `DEPLOY.md:31-33` describes it correctly), but adds a task definition to maintain for zero benefit over the shortcut at n=1 user. **Upgrade to this only when auto-restart-on-crash actually matters.** |
| **NSSM** ❌ | `DEPLOY.md:24` recommends it — **that recommendation is wrong for this app.** A Windows service runs in session 0 and cannot reach the interactive Revit UI, breaking every live feature. See D1.7. |

Set the shortcut's "Run" to **Minimized** so a console window is not in Sagar's
face all day, but leave it visible in the taskbar so he can tell at a glance
whether the server is up.

*ponytail: fewest moving parts that satisfies the session-0 constraint. Skipped:
service wrapper, health-check watchdog, log shipping — add when there is a
second user.*

### D3.5 Browser shortcut

Desktop `.url` shortcut named **"Livio QA-QC"** → `http://127.0.0.1:8077`.
Optional and worth the 60 seconds: Edge/Chrome → open the app → ⋮ → *Install as
app*, which gives a windowed PWA-style launcher with its own taskbar icon and no
address bar. Makes it feel like software rather than a localhost URL.

### D3.6 Verification for D3

```powershell
cd C:\QA-QC-FINAL-PROTOTYPE\backend; py -3.11 -m pytest -q   # green
```
Then reboot the machine, log in as Sagar, wait ~15 s, double-click the desktop
shortcut → the app loads, the header shows **madera**, and STATS is populated.
If the pytest suite is green and a cold reboot lands on a working UI, D3 is done.

---

## PHASE D4 — Acceptance smoke on the target machine

Owner: **Ashwin, with Sagar watching** (it doubles as the first half of
training). Time: ≈ 25 min. Shape borrowed from the Country Side acceptance
(`AGENT_HANDOFF.md:143-146`) and the team guide's 10-minute test
(`docs/LIVIO_TEAM_GUIDE.md:221-239`).

**Pre-step:** open the real client model in Revit, turn on **both** connectors —
Nonica **A.I. Connector → On**, revitMCP ribbon → **Open Server** — and dismiss
any modal dialog (R-35).

| # | Step | Expected | Fails if |
|---|---|---|---|
| 1 | Load `http://127.0.0.1:8077` | No console errors; header shows active project; STATS populated | Backend not started → check the Startup shortcut |
| 2 | Connector badges | **Both** show connected | A connector is off, or a Revit dialog is blocking (R-35) |
| 3 | Upload the client PDF + the v3 export JSON to a **new** project | Workspace created and activated; project switcher lists it | pyRevit export is pre-v3.1 |
| 4 | Auto-benchmark banner | BM-1/BM-2 proposed from the PDF's own grid intersections, with evidence crops; approve | "Only 0 labeled grid intersections" → fall back to manual grid picking (guide §6) |
| 5 | Run the full pipeline | Every stage 200; 🤖 phase summaries appear in the log after each phase; counts identical on a second run | Determinism break — do not ship |
| 6 | Match results | Verdict counts populate; MATCH only where registration is verified | MATCH with no verified registration = a real bug, stop |
| 7 | 🎯 **Show in Revit** on one hold-down row | The element becomes the live selection in Revit; UI reports a sub-foot coordinate delta (Country Side hit 0.003 ft) | **⚠️ Requires Nonica PRO (§0.4).** Greyed out under option (B) — that is expected, not a failure |
| 8 | Press **BX** in Revit right after step 7 | Revit zooms to the selection box | Revit's API has no zoom call — this manual step is by design (`README.md`, commit `2e32dca`) |
| 9 | Revit ID drawer → **Use current Revit selection** | Full plain-English verdict for whatever is selected in Revit | Needs the revit-mcp socket (free tier) — check "Open Server" |
| 10 | 3D pane | **SNAPSHOT** badge renders instantly, then swaps to **LIVE** with the ⟳ button available | Live swap needs Nonica free-tier reads |
| 11 | Switch project A→B→A | Counts change per project and restore exactly | Workspace contamination — stop |
| 12 | Review: comment → accept/reject on one mismatch | AI verdict appears; buttons enable only after a comment; resolution persists across a re-run | |
| 13 | Export the punch list CSV | Downloads with `distance_ft` populated | |
| 14 | `GET /api/health` | `registration.calibration_source` unchanged (benchmark stays benchmark) | |

**Ship gate: 1-6 and 11-14 must pass. 7 and 10 are conditional on §0.4.**

---

## PHASE D5 — Training + handover

Owner: **Ashwin**. Time: 30 min live + the card.
`docs/LIVIO_TEAM_GUIDE.md` (256 lines, already written) is the reference
document — do **not** rewrite it. This phase is the live walkthrough and a
one-pager for the desk.

### D5.1 · 30-minute walkthrough agenda

| Min | Topic | Anchor | Point to land |
|---|---|---|---|
| 0-3 | **What it is and what it is not.** | Guide intro | It compares a permit PDF to a Revit export. It never emits MATCH on name agreement alone — MATCH needs verified coordinate registration plus a distance gate. It is an assistant, not an authority. |
| 3-6 | **Starting it.** | §1, D3.4/D3.5 | It auto-starts at logon. Desktop icon. If the page won't load, the console window is your check — see the D6 failure table. |
| 6-12 | **A new client project, end to end.** | §2-3 | Three inputs (PDF, v3 export JSON, optional IFC from the *same* model). Every project is its own workspace; they never contaminate. Run the pipeline; watch the 🤖 phase summaries. |
| 12-17 | **Reading the three panes.** | §4 | Click a row → PDF flies and rings, 3D highlights. Open "Why this verdict?" on a mismatch: offset in feet against the 2 ft gate, compass direction, and the systematic-drawing-offset note when several nearby mismatches shift the same way. |
| 17-21 | **The honesty features — the trust conversation.** | §4, README | The scope-warning banner (PDF callouts but zero Revit targets = check whether the export view hid the category, *before* concluding the model is wrong). Per-sheet registration quality. The classification chain. Greyed-out buttons are honest, not broken. |
| 21-26 | **Revit-live.** | §5 | Both connectors on. Show in Revit → **then press BX yourself** (Revit has no zoom API). "Use current Revit selection". LIVE vs SNAPSHOT badge. **If §0.4 resolved as (B): say plainly that Show-in-Revit is licence-gated and off.** |
| 26-29 | **Review workflow + chat.** | §7-8 | Comment → accept (false alarm → becomes MATCH with an audit trail) or reject (stays a discrepancy). Resolutions persist across re-runs. Chat answers about the current project; teach it exclude rules for marks the client says are fake. |
| 29-30 | **Where to get help.** | §11, D6 | The troubleshooting list, `Bugs.md` with repro + expected/actual, and Ashwin. |

Leave 5 minutes at the end for Sagar to drive the tool himself on his own
project while Ashwin watches. Watching him fumble once is worth more than the
other 30 minutes.

### D5.2 · One-page quick-reference card — content outline

Single side of A4, taped next to the monitor. Contents, in this order:

1. **Start / stop** — auto-starts at logon; desktop **Livio QA-QC** icon;
   `http://127.0.0.1:8077`; to restart, close the PowerShell window and
   re-run the Startup shortcut.
2. **Before any Revit-live click** — a 3-item checkbox strip:
   ☐ model open ☐ Nonica **A.I. Connector → On** ☐ revitMCP → **Open Server**
   ☐ no Revit dialog open.
3. **New project in 3 steps** — upload PDF + v3 export JSON → approve the
   BM-1/BM-2 banner → Run pipeline.
4. **Verdict legend** — MATCH / LOCATION_MISMATCH / MARK_MISMATCH / PDF_ONLY /
   REVIT_ONLY / NEEDS_REVIEW / NO_REVIT_DATA, one plain line each.
5. **The two keystrokes that aren't buttons** — **BX** in Revit after Show in
   Revit (selection box); the ⟳ live button on the 3D pane.
6. **Four symptoms → four fixes** (the D6.4 table, verbatim).
7. **Trust rules** — greyed out = honest, not broken. A scope warning means
   check the export view before blaming the model. No MATCH without verified
   registration.
8. **Escalation** — file it in `Bugs.md` with repro + expected/actual, then
   ping Ashwin. Logs are at `C:\QA-QC-FINAL-PROTOTYPE\logs\app.log`.

---

## PHASE D6 — Support, updates, rollback

Owner: **Ashwin**. Ongoing.

### D6.1 How Ashwin ships an update

```powershell
# on Ashwin's machine, before pushing:
cd C:\QA-QC-FINAL-PROTOTYPE-bkp\backend;  py -3.11 -m pytest -q     # must be green
cd ..\frontend;                           npx playwright test        # must be green
cd ..;  git tag deploy-sagar-<yyyy-mm-dd>;  git push --tags

# on Sagar's machine (close the app first):
cd C:\QA-QC-FINAL-PROTOTYPE
git pull
cd backend;  py -3.11 -m pip install -r requirements.txt   # only if requirements changed
py -3.11 -m pytest -q                                      # the gate, on the target machine
# restart via the Startup shortcut
```

**The pytest gate runs on Sagar's machine, not just Ashwin's** — a green suite
on the dev box says nothing about a Python 3.11 install that drifted.

Sagar's `.env` and `artifacts/` are gitignored, so `git pull` never touches his
key or his project data. That is the whole reason D3.1 chose clone over copy.

### D6.2 Rollback

```powershell
cd C:\QA-QC-FINAL-PROTOTYPE
git log --oneline -5                       # find the last-good tag
git checkout deploy-sagar-<last-good>      # detached HEAD is fine for a rollback
cd backend;  py -3.11 -m pip install -r requirements.txt
```
Artifacts are **not** rolled back and must not be — they are Sagar's review
work. If a bad release corrupted a workspace, restore that one project folder
from a copy; `run_baseline.json` inside each workspace is the run-over-run
anchor for spotting the corruption in the first place.

### D6.3 Where the logs live

| What | Path |
|---|---|
| App + uvicorn access log | `C:\QA-QC-FINAL-PROTOTYPE\logs\app.log` — rotating, 5 MB × 5 backups (`maintenance.py:17-19`; tune with `QAQC_LOG_MAX_BYTES` / `QAQC_LOG_BACKUPS`) |
| OpenRouter call log | `artifacts/projects/<slug>/openrouter_call_log.json` |
| Pipeline phase summaries | `artifacts/projects/<slug>/phase_summaries.json` |
| Per-project run baseline | `artifacts/projects/<slug>/run_baseline.json` |

`logs/` is gitignored and never leaves the machine. **After D1.3 lands**, it is
safe to ask Sagar to send `app.log` when something breaks; **before** D1.3 it
contains the bearer token in cleartext, so do not.

### D6.4 The three most likely failures, and the one-line fix for each

| # | Symptom | Cause | One-line fix |
|---|---|---|---|
| **1** | Revit-live buttons are greyed out; the app otherwise works | A connector is off — the single most common failure, and by design it fails visibly | Nonica ribbon → **A.I. Connector → On**, and revitMCP ribbon → **Open Server**, then retry. |
| **2** | Connectors are on but every Revit call errors or times out (**R-35**) | A modal dialog in Revit — often revitMCP's own "Open Server" dialog — blocks all MCP tools (`AGENT_HANDOFF.md:140-141`) | Click into Revit, dismiss every open dialog, then retry. |
| **3** | Counts look wrong / elements the client added are missing | Stale export — the `.rvt` moved on but the uploaded JSON did not | Re-run **pyRevit → Livio QA-QC → Export** in the current model and re-upload; the Runs drawer will show the per-device diff. |

Runners-up worth knowing: **"Only 0 labeled grid intersections"** → use manual
grid picking (guide §6). **IFC "does not match the current Revit export"** →
the IFC came from a different model version; re-export both from the same one.
**409 "upload first"** → that stage's input artifact is missing; run the earlier
stage.

---

## Appendix · Open items requiring a human decision

| # | Item | Blocks | Decide by |
|---|---|---|---|
| 1 | **Nonica PRO seat for Sagar** — §0.4 (A) buy €85/yr, (B) ship degraded, (C) move Ashwin's seat | D2.1 item 4, D4 step 7, D5 min 21-26 | Before D2 |
| 2 | **Rotate the GitHub PAT** in `.git/config` — D1.1 | All of D3 | Before D3, today |
| 3 | **Revit version on Sagar's machine** — the add-in path is hardcoded to `Addins\2023\` | D2.1 items 2 & 5 | Before D2 |
| 4 | **Where the pyRevit exporter extension lives** — outside this repo, no packaged installer (`PRODUCTION_ROADMAP.md:45`) | D2.1 item 6 | Before D2 |
| 5 | **Does Sagar get the OpenRouter key** (chat on) or not (chat degrades honestly)? | D3.3 | Before D3 |
