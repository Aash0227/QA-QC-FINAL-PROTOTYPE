# Agent Execution Guide — Vite, Project Manager, Installer

Unambiguous reproduction guide for the Livio QA-QC work that added a Vite frontend build, Project Manager CRUD, UI polish, a PowerShell launcher, and a thin Inno Setup installer. An agent can follow each phase without reading the original plan.

**Repo root:** `C:\QA-QC-FINAL-PROTOTYPE-bkp`  
**Stack decisions (locked):** Vite (not Next.js); thin Inno Setup installer that runs `scripts\setup_qaqc.ps1` (no embedded Python).  
**Do not edit the plan file.** Commit only when the human asks.

---

## Global invariants

| Rule | Why |
|------|-----|
| Additive `project_manifest.json` keys only | Old workspaces must list/open without migration |
| `status` is human-set (`active` / `archived`), never derived | Same contract as “no fake matches” |
| Never recompute verdicts client-side | Server is source of truth |
| Backend binds `127.0.0.1` by default; no firewall rule | Loopback does not prompt Defender |
| No Windows service | Revit bridge needs the interactive user session |
| Ship `frontend/dist` in the installer, never bare `frontend/src` | Bare sources use npm bare imports Vite must resolve |
| Tests must not shadow `config.ARTIFACT_DIR` as a real attribute | Monkeypatch can clobber live `artifacts/projects/*/project_manifest.json` |

**Known baseline (as of this work):** pytest ~355 pass / ~11 fail in frozen normalization/control_points modules; Playwright smoke may fail the hardcoded “106 verified” assertion when the active project is not Madera (e.g. country-side-ct). Do not “fix” those by changing production data unless asked.

---

## Phase 0 — Vite migration

### Role
Frontend build engineer. Make the UI identical and offline-capable; no visual redesign.

### Required inputs
- Node.js + npm on the build/dev machine
- Existing `frontend/index.html`, `frontend/src/**`, Playwright suite
- Backend that serves static files via `config.frontend_dir()` / `FRONTEND_DIR`

### Ordered steps
1. Add `frontend/vite.config.js`: root `.`, `build.outDir: "dist"`, `base: "./"`, proxy `/api` and `/artifacts` to `http://127.0.0.1:8077`, alias `three/addons/` → `three/examples/jsm/`.
2. Add npm deps: `vite`, `three@0.160.0`, `gsap@3.12.5`, `@fontsource` packages for IBM Plex Sans/Mono and Big Shoulders Display; scripts `dev` / `build` / `preview`. Keep `@playwright/test`.
3. Remove from `frontend/index.html`: Google Fonts `<link>`, GSAP CDN `<script>`, `<script type="importmap">`.
4. Bundle fonts via `frontend/src/fonts.js` (extensionless `@fontsource/.../latin-600` style imports — a `.css` suffix can fail for some packages). Import fonts from the app entry.
5. Replace CDN GSAP with `import gsap from "gsap"` in panels that need it (`util.js`, `pdf.js`, `viewer3d.js`, `inspector.js`, `chat.js`, and/or a `window.gsap` bridge in `app.js` if globals remain).
6. Make the backend prefer `frontend/dist` when `dist/index.html` exists, else source. Prefer call-time resolve in `frontend_dir()` so tests and prod both see the right tree.
7. Add Playwright `tests/global-setup.js` that runs `vite build`; raise timeouts if the build needs ~60s cold.
8. Confirm `.gitignore` already ignores `dist/`.

### Expected outputs
- `frontend/vite.config.js`, `frontend/src/fonts.js`
- Built `frontend/dist/index.html` + hashed assets with **no** remote `<script src="https://…">` / `<link href="https://…">` (ignore HTML comments when scanning)
- Backend serves the bundle when present

### Validation
```powershell
cd C:\QA-QC-FINAL-PROTOTYPE-bkp\frontend
npm ci
npm run build
# Pass: dist\index.html exists; strip comments then regex for https script/link → 0 matches

cd C:\QA-QC-FINAL-PROTOTYPE-bkp\backend
py -3.11 -m pytest -q
# Pass: no new failures vs pre-change baseline (do not require 0 failures if frozen modules already fail)

cd C:\QA-QC-FINAL-PROTOTYPE-bkp\frontend
npx playwright test
# Pass: existing smoke suite except environment-specific count assertions
```

### Error handling / rollback
- Blank page after build → check console for unresolved bare imports; ensure backend is serving `dist`, not stale source with broken importmap.
- Fonts 404 in Vite → drop `.css` from `@fontsource` import paths.
- Rollback: restore CDN/importmap in `index.html`, remove vite deps, revert `frontend_dir` preference, delete `frontend/dist`.

### Checklist
- [ ] No CDN tags in source `index.html`
- [ ] `npm run build` produces `frontend/dist`
- [ ] Offline CDN scan on built HTML is clean
- [ ] Playwright globalSetup builds before tests
- [ ] Backend prefers `dist` when present

---

## Phase 1a — Project API CRUD

### Role
Backend API engineer. Extend projects routes; keep manifests additive.

### Required inputs
- `backend/app/routers/projects.py`, `backend/app/config.py` (`slugify`, `bind_project`, `PROJECTS_DIR`)
- Existing `DELETE` / activate / upload routes

### Ordered steps
1. Extend `GET /api/projects` with optional metadata: `display_name`, `client`, `revision`, `status`, `notes`, timestamps, `has_pdf`, `has_revit`, page/sheet counts, existing `counts`.
2. Add `GET /api/projects/{slug}` with `size_bytes` and `file_count`.
3. Add `POST /api/projects` body `{name, client?, revision?, notes?}` → slugify, 409 on collision, create under `PROJECTS_DIR` (hermetic; do **not** write into ambient `ARTIFACT_DIR`), **do not auto-activate**.
4. Add `PATCH /api/projects/{slug}` whitelist only: `display_name`, `client`, `revision`, `status`, `notes`; bump `updated_at`; never touch artifact files.
5. Leave `DELETE` 409-on-active unchanged.
6. Reject path traversal on slug routes.

### Expected outputs
- Updated `projects.py`
- New `backend/tests/test_projects_crud.py`
- Autouse guard in `backend/tests/conftest.py` that pops a shadowing real `ARTIFACT_DIR` attribute around tests (prevents clobbering live manifests)

### Validation
```powershell
cd C:\QA-QC-FINAL-PROTOTYPE-bkp\backend
py -3.11 -m pytest tests/test_projects_crud.py -q
# Pass: all new CRUD tests green
```

### Error handling / rollback
- If a test wrote into live `artifacts/projects/<slug>/project_manifest.json`, restore via `scripts/repair_manifest.py` (or known good manifest) **before** continuing. Never leave `display_name`/`pdf` fields wrong for real projects.
- Rollback: remove new routes/tests; manifests with extra keys remain harmless.

### Checklist
- [ ] POST create does not activate
- [ ] PATCH rejects unknown keys
- [ ] Traversal rejected
- [ ] Manifests without new keys still list
- [ ] conftest does not leave `ARTIFACT_DIR` as a real path attribute

---

## Phase 1b — Project Manager UI

### Role
Frontend panel engineer. Card-grid overlay; replace header select/trash UX.

### Required inputs
- Phase 1a API live
- Existing modal/overlay CSS patterns (`#pipe-modal`)
- Header wiring in `app.js` / `index.html` (keep `#proj-switch` / `#btn-proj-del` ids if anything still binds them)

### Ordered steps
1. Add `frontend/src/panels/projects.js` and `#projects` overlay.
2. Header: `📁` / `#btn-projects` + `#proj-name` instead of primary select+trash.
3. Cards: name, client, revision, counts, verdict progress ring (inline SVG from server counts), status, Open / Edit / Delete.
4. Create/upload card → create API and/or `POST /api/upload?project=`.
5. Open → activate then `location.reload()`.
6. Delete → typed confirmation using detail `file_count` / `size_bytes`; if active, activate another first; if sole project, disable with reason.

### Expected outputs
- `frontend/src/panels/projects.js`, HTML/CSS hooks, header changes

### Validation
```powershell
cd C:\QA-QC-FINAL-PROTOTYPE-bkp\frontend
npx playwright test tests/projects.spec.js
# Pass: PM overlay CRUD flows covered by the spec
```

### Error handling / rollback
- Overlay blocks Advanced menu → raise header `z-index` when `#adv-menu[open]`.
- Rollback: hide overlay entrypoint; restore select/trash visibility.

### Checklist
- [ ] Overlay opens from header
- [ ] Create without upload works
- [ ] Edit patches whitelist fields only
- [ ] Delete confirmation quotes real size/count
- [ ] Active delete path activates another project first

---

## Phase 1c — PM tests

### Role
QA automation. Cover CRUD, 409s, traversal, backward-compatible manifests.

### Required inputs
- Phases 1a–1b

### Ordered steps
1. Backend: create, duplicate 409, patch whitelist, patch preserves artifacts, delete-active 409, traversal, legacy manifest list.
2. Frontend: `frontend/tests/projects.spec.js` for overlay flows.

### Validation
Same commands as 1a/1b; also full backend suite for regressions.

### Checklist
- [ ] `test_projects_crud.py` green
- [ ] `projects.spec.js` green
- [ ] No live artifact corruption after suite run

---

## Phase 2 — UI polish

### Role
Accessibility / UX polish. No new product features.

### Ordered steps
1. Status glyphs + titles (`GLYPH` / `statusLabel` in `util.js`) — not color-only.
2. List `role="listbox"` / row a11y; **J/K** navigation in `list.js`.
3. Drawer `aria-hidden` + focus management (full trap optional if drawers coexist with wizard).
4. Project grid skeleton; responsive PM CSS (~1280px wrap).
5. Prefer busiest category for initial open (do not hardcode `shear_wall`) so empty-list / mark-hdr smoke stays stable across projects.
6. Header `z-index` when Advanced menu is open.

### Validation
```powershell
cd C:\QA-QC-FINAL-PROTOTYPE-bkp\frontend
npx playwright test
```

### Rollback
Revert polish commits; leave PM CRUD intact.

### Checklist
- [ ] J/K moves selection
- [ ] Status readable without color alone
- [ ] Skeleton shows while projects load
- [ ] Grid usable at 1280px width

---

## Phase 3a — Launcher

### Role
Desktop packaging / ops. Make Start Menu / desktop icon behave like an app.

### Required inputs
- `run_backend.ps1 -Prod`
- Loopback health at `/api/health`

### Ordered steps
1. Write `scripts/launch_qaqc.ps1`:
   - Probe health on preferred port; if healthy, open browser only (single instance).
   - If port busy but not ours, scan upward for a free port (or pin `-Port`).
   - Start hidden `run_backend.ps1 -Prod`.
   - Poll health (tens of seconds); open `http://127.0.0.1:$port`.
   - On failure: MessageBox + `logs/launcher.log` (and point at `logs/app.log`).
2. Cold-start smoke from an interactive session.

### Validation
```powershell
# With nothing on 8077:
powershell -NoProfile -ExecutionPolicy Bypass -File C:\QA-QC-FINAL-PROTOTYPE-bkp\scripts\launch_qaqc.ps1
# Pass: browser opens; GET /api/health 200
# Second run: does not start a second server; still opens browser
# Kill backend / break path: MessageBox names logs\launcher.log
```

### Rollback
Remove launcher; point shortcuts at `run_backend.ps1` temporarily (worse UX).

### Checklist
- [ ] Single-instance reuse
- [ ] Hidden backend start
- [ ] Loud failure with log paths
- [ ] No Windows service / no firewall rule added

---

## Phase 3b — Installer

### Role
Release engineer on a **build** machine (Node + Inno Setup 6). Target QA laptops never need npm.

### Required inputs
- Inno Setup 6 (`ISCC.exe` under Program Files, Program Files (x86), or `%LOCALAPPDATA%\Programs\Inno Setup 6\`)
- `installer/qaqc.iss`, `scripts/build_installer.ps1`
- Built frontend policy: ship `frontend/dist` only

### Ordered steps
1. Keep `installer/qaqc.iss`: `PrivilegesRequired=lowest`, fixed `AppId`, `{localappdata}\Livio\QA-QC`, files as documented in the ISS header, postinstall optional `setup_qaqc.ps1`, shortcuts → `launch_qaqc.ps1`, uninstall prompts before deleting `artifacts\` and `.env`.
2. `scripts/build_installer.ps1`: read `PROTOTYPE_VERSION` from `backend/app/config.py` → `npm ci` + `npm run build` → CDN check (strip HTML comments first) → `ISCC /DAppVersion=…`.
3. Run:
```powershell
cd C:\QA-QC-FINAL-PROTOTYPE-bkp
.\scripts\build_installer.ps1 -SkipTests   # packaging iterate
# or full: .\scripts\build_installer.ps1
```

### Expected outputs
- `dist\LivioQAQC-Setup-<version>.exe` (e.g. `LivioQAQC-Setup-0.1.0.exe`)

### Validation
```powershell
Test-Path C:\QA-QC-FINAL-PROTOTYPE-bkp\dist\LivioQAQC-Setup-0.1.0.exe
# Pass: True; build script prints [OK] built ... (N MB)

# Clean-machine (manual):
# Install → tick Python/deps task → desktop icon → browser + health 200
# Uninstall → shortcuts gone; artifacts/.env only removed if user confirms
```

### Error handling / rollback
- ISCC not found → install Inno Setup 6 or pass `-ISCC "C:\path\to\ISCC.exe"`; build script also checks `%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe`.
- CDN check fails on comments → strip `<!-- … -->` before matching (already in script).
- Rollback: stop distributing the exe; git install path via `update_qaqc.ps1` remains.

### Checklist
- [ ] Version matches `PROTOTYPE_VERSION`
- [ ] Built HTML has no remote script/link
- [ ] Setup exe exists under `dist\`
- [ ] AppId left unchanged across versions

---

## Phase 4 — This guide

### Role
Docs. Capture roles, steps, validations, checklists, rollback so another agent can reproduce without the plan file.

### Expected output
- `docs/AGENT_EXECUTION_GUIDE.md` (this file)

### Checklist
- [ ] Every phase has role / inputs / steps / outputs / validation / rollback / checklist
- [ ] Commands match scripts actually in the repo

---

## Day-to-day commands

```powershell
# Dev: API on 8077, Vite on 5173 proxying /api
cd C:\QA-QC-FINAL-PROTOTYPE-bkp; .\run_backend.ps1
cd C:\QA-QC-FINAL-PROTOTYPE-bkp\frontend; npm install; npm run dev

# Production-style local (backend serves frontend/dist)
cd C:\QA-QC-FINAL-PROTOTYPE-bkp\frontend; npm run build
cd C:\QA-QC-FINAL-PROTOTYPE-bkp; .\run_backend.ps1 -Prod

# Or desktop-style
.\scripts\launch_qaqc.ps1

# Tests
cd C:\QA-QC-FINAL-PROTOTYPE-bkp\backend; py -3.11 -m pytest -q
cd C:\QA-QC-FINAL-PROTOTYPE-bkp\frontend; npx playwright test

# Installer (build machine only)
cd C:\QA-QC-FINAL-PROTOTYPE-bkp; .\scripts\build_installer.ps1
```

---

## Incident: live manifest clobber (do not repeat)

**Cause:** tests monkeypatched `config.ARTIFACT_DIR` in a way that left a real attribute pointing at live artifacts; create/PATCH tests overwrote a real `project_manifest.json`.

**Guard:** autouse fixture in `backend/tests/conftest.py` pops shadowing `ARTIFACT_DIR` around every test.

**Repair tool:** `scripts/repair_manifest.py` (supports `--ignore-existing` and restoring known PDF / `uploaded_at` fields).

**Rule for agents:** after any project API test run that touched paths under the real repo `artifacts\`, diff or spot-check active project manifests before declaring success.
