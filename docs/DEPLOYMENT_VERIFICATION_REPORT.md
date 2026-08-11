# QA-QC Deployment Verification Report — 2026-08-07

**Verdict: PIPELINE HEALTHY — deploy after rotating one live credential.**

| Phase | Result |
|-------|--------|
| A. Pre-flight (backend, project, connectors) | ✅ PASS |
| B. Pipeline E2E on Madera (post-de-hardcoding) | ✅ PASS — bit-identical to baseline |
| C. Revit-live features (live model) | ✅ 10/10 PASS |
| D. Frontend smoke (Playwright) | ✅ 7/7 PASS |
| E. Deployment package | ⚠️ 2 items need your action |

---

## Phase A — Pre-flight ✅

- Backend: `uvicorn app.main:app` on `127.0.0.1:8077`, Application startup complete
- `GET /api/health` → `{"status":"ok"}`, all 14 artifacts present
- `POST /api/projects/activate {"slug":"madera"}` → `{"active":"madera"}`
- `GET /api/revit/status` → `connected: true`, `model_title: "10510 Madera Dr_LGS model_08052026"` — your open Revit session is answering

## Phase B — Pipeline E2E ✅

**323/323 pytest green (23.2s).** Live counts vs frozen `run_baseline.json`:

| Metric | Baseline | Observed | Delta |
|--------|----------|----------|-------|
| Total elements | 356 | 356 | 0 |
| MATCH | 106 | 106 | 0 |
| LOCATION_MISMATCH | 37 | 37 | 0 |
| PDF_ONLY | 175 | 175 | 0 |
| REVIT_ONLY | 24 | 24 | 0 |
| Devices (total) | 116 | 116 | 0 |
| Device MATCH | 55 | 55 | 0 |

**De-hardcoding verification:**
- `AIConvert_revit.json` — 0 hardcoded baseline mentions, 0 bogus "Revit body assemblies=X vs PDF baseline=10" warnings
- `element_intelligence.json` — vocabulary learned dynamically: H1–H4, C-1..C-4, P-1..P-10, SW-1..SW-4, wall_type 1/2/5
- `GET /api/sheets/primary` → `{"sheet":"S-201"}` — dynamic discovery, not hardcoded
- `registration_calibration.json` — `source: benchmark_verified`, scale 17.966 pt/ft (drift 0.187%), chirality reflection=true, RMS 0.0
- `phase_summaries.json` — schema 1.0, live counts quoted consistently
- `scope_warnings` — `[]` (no hidden-category traps)

**⚠ One stale artifact (harmless):** `pdf_page_intelligence.json` (generated 2026-07-21, pre-de-hardcoding) still carries the old `expected_baseline {H1:10,...}` + `matches_expected_baseline:true` block. It passes today because Madera genuinely has those counts, but the new code path no longer writes that field. **Action: regenerate on next fresh run — not a blocker.**

**Note on my earlier context numbers** (holdown 44 M/16 LM/4 PO/1 MM/11 RO): the saved baseline file is the authority and current output matches it exactly. My context numbers were approximations, not a regression.

## Phase C — Revit-live features ✅ (10/10)

Against your live open model:

| Feature | Result | Evidence |
|---------|--------|----------|
| Connector status | ✅ | `connected:true`, live (not cached) |
| Highlight MATCH (`rev_asm_009`) | ✅ | `selected_ids:[1222842]`, dist 0.004 ft, fresh read |
| Highlight LOCATION_MISMATCH (`rev_asm_072`) | ✅ | `selected_ids:[1248940, 1248941, 1928168]`, dist 0.003 ft |
| Selection readback | ✅ | `GET /api/revit/selection` returns exact same 3 ids — **round-trip confirmed** |
| Lookup 1248940 verdict chain | ✅ | Full chain: family→variant→mark, 3.29 ft NE offset, `lean-reject`, per-sheet registration quality |
| Live 3D scene | ✅ | walls 270, framing 3000/9551 (honest truncation), columns 19, connections 1187, `status_joined:376` |
| Export-status honesty | ✅ | `synced:false, reason:"no export ingested yet"` — correct, no fake sync |
| Offline code paths | ✅ | Every disconnect/block surfaces a `reason`, never a silent failure |

**👁 Your cross-check:** after the LOCATION_MISMATCH highlight, Revit should have shown **3 structural-connection elements selected** near coordinates (60.44, 61.92) — mark H2 zone, grid NE area. Did you see the selection happen in the UI?

## Phase D — Frontend smoke ✅

**7/7 Playwright green (49.7s)** — after I fixed `playwright.config.js` (webServer was spawning bare `python` = Hermes venv without fitz; now pins Python 3.11 explicitly).

- App load, header shows 106 verified
- 3-pane select sync (list → PDF + inspector)
- Results table sort/filter
- Benchmark wizard propose→approve
- Chat drawer + count card
- Drawer independence
- Revit ID lookup drawer in plain English

## Phase E — Deployment package

| Item | Status |
|------|--------|
| `scripts/install_qa_laptop.ps1` | ✅ Created (Python 3.11 gate, pip install, .env scaffold, startup shortcut, connector checklist) |
| `scripts/update_qaqc.ps1` | ✅ Created (git pull + pip install + restart hint) |
| `docs/QA_TEAM_RUNBOOK.md` | ✅ Created (daily start, update, troubleshooting, honest limitations, no-Vercel architecture note) |
| `.gitignore` coverage | ✅ All patterns verified via `git check-ignore`; only `artifacts/memory/global.json` tracked (intentional — shared teach memory) |
| PowerShell runtime verification | ⚠️ **Blocked** — `powershell.exe` invocation hit the approval gate (twice: agent + me). Scripts are code-reviewed, not executed. Run `install_qa_laptop.ps1` on a clean laptop before handoff. |
| **Secrets in git history** | ❌ **ACTION REQUIRED** — see below |

---

## ❌ Deployment blocker — credential hygiene

Two exposures found in the local repo:

1. **Live token in git remote URL** — `origin` currently embeds `ghp_FD...NB0g` in plaintext. This token is pushed with every fetch/push URL reference.
   **Fix (30 seconds):**
   ```bash
   git remote set-url origin https://github.com/Aash0227/QA-QC-FINAL-PROTOTYPE.git
   ```
   Then rotate the token on GitHub (Settings → Developer settings → revoke `ghp_FD...`). Use a credential manager or SSH key instead of embedding in the URL.

2. **Documentation references to a burned token** — commit `008ed02` contains text about the *old* `ghp_4dPySM...` token that was already rotated in July. Harmless (dead token, mentioned only as "rotate this"), but if you want a clean history, `git filter-repo` before the first public/private push.

**The `sk-or-v1` hits are also documentation** (`.env.example` instructions saying "put your key here") — no live OpenRouter key in history. Clean.

---

## Deployment checklist (in order)

```
[ ] 1. git remote set-url origin https://github.com/Aash0227/QA-QC-FINAL-PROTOTYPE.git
[ ] 2. Rotate ghp_FD... token on GitHub, delete the old one
[ ] 3. git add -A && git commit -m "chore: pre-deployment verification + deploy package"
[ ] 4. git push origin main (to private repo Livio-QA-QC-AI if renaming, or current)
[ ] 5. git tag v1.0.0-qaqc-handoff && git push --tags
[ ] 6. On ONE QA laptop: clone, run scripts/install_qa_laptop.ps1, verify backend auto-starts
[ ] 7. QA laptop: open Madera in Revit, both connectors on, browse http://127.0.0.1:8077
[ ] 8. QA runs one full pipeline + one Show-in-Revit — confirm selection happens in their Revit
[ ] 9. Regenerate pdf_page_intelligence.json (fresh extract) to drop the stale baseline block
[ ] 10. Hand docs/QA_TEAM_RUNBOOK.md to the QA lead
```

**Architecture note (runbook intro):** frontend is served by the backend via StaticFiles — deliberately **no Vercel**. The backend must sit on the same Windows machine as Revit for the localhost MCP loop. Never a Windows service (session 0 kills Revit-live). Distribution = private GitHub repo + tagged release zip.

**Skipped:** Google Drive mirror (GitHub release zip covers distribution; Drive adds a second source of truth to keep in sync). Add only if QA laptops can't reach GitHub.
