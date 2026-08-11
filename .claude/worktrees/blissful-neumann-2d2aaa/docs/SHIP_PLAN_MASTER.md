# Master Ship Plan — Deploy to Sagar Karpe (QA-QC)

**Date:** 2026-07-28 · **Status: PLAN ONLY — no code written.** Detail docs:
[UI](UI_DEPLOY_PLAN_UI.md) · [Pipeline](UI_DEPLOY_PLAN_PIPELINE.md) · [Deployment](UI_DEPLOY_PLAN_DEPLOYMENT.md)

---

## 0 · Decisions Ashwin must make first

| # | Decision | Blocks | Options |
|---|---|---|---|
| 1 | 🔴 **Rotate the GitHub PAT** now — it sits in cleartext in `.git/config`; any folder copy leaks it | Everything in D3 | Rotate at github.com, then we strip it from the local remote URL |
| 2 | **Nonica seat for Sagar's machine** | 🎯 Show in Revit + marker placement on his machine | (a) buy 2nd seat €85/yr · (b) ship degraded (buttons grey out honestly, free tier still gives live 3D + lookups) · (c) move your seat |
| 3 | **Approve pipeline shape A2** (zero-upload auto-ingest; export stays the math source) | Pipeline work | A2 today (~4h, baseline-safe) vs waiting 4-5 days for full live fetch (B) |
| 4 | **OpenRouter key on Sagar's machine** | Chat/AI polish features | share existing key vs create a scoped new key |

## 1 · UI declutter (P1 ≈ 2-4h)

"The app isn't ugly, it's addressed to a developer." Sagar needs 4 verbs: open project → see what's flagged → judge it → export.

- Header 9 → 5: `▶ Run the check` · `▤ All results` · **`⚠ Needs review (N)`** (primary CTA) · `💬 Ask` · `⚙` (Extract/Match/Autopilot/Runs/Revit ID demoted into a native details-popover)
- Benchmark wizard leaves the header; its only front door is the auto-benchmark banner's "Review the points"
- Upload card: PDF-only + live Revit connection pill; `▸ Advanced: upload a Revit export JSON` keeps the old path alive (DOM nodes demoted, never deleted — module-import-time `$("#id").onclick` wiring crashes the app if nodes vanish)
- 4 true removals only (dev affordances); pipeline modal stops narrating artifact filenames
- Motion: 6 GSAP/CSS micro-interactions (Framer Motion rejected — React-only, app is build-free); `prefers-reduced-motion` block added; 2 defects fixed en route (3.1:1 contrast label, infinite keyframes)
- Known cost: 5 Playwright assertion edits in one file (enumerated)

## 2 · Pipeline: PDF-only upload, zero-JSON UX (Design A2 ≈ 4h)

**Truth to preserve:** the verdict math runs on the pyRevit JSON export; live MCP is interaction-only. Full live-fetch (Design B) is blocked on 4 unproven data links **and a hardcoded product whitelist discovered inside Livio's own C# DLL** (covers Madera, misses Country Side + Dogwood families entirely — adopting it today would silently under-report 2 of 3 projects).

**A2 — ship today:** the human never touches JSON. Sagar clicks **Export QAQC** in Revit (existing button) → backend watches the export folder → auto-ingests in ~3s → UI shows "Model synced · N minutes ago". Adds `GET /api/revit/export-status`, `POST /api/revit/ingest`, manifest field `revit_model_title` (project↔model binding — closes the wrong-model hole and R-14 staleness as side effects). Export stays byte-identical as math source → 106-MATCH baseline safe by construction. No frozen modules touched.

**B — next sprint (4-5 days):** probe the 4 links live → fix the C# whitelist → `live_export.py` emitting schema-v3-shaped output (adapters unchanged) → field-diff validation on all 3 projects → cutover behind `QAQC_REVIT_SOURCE` env.

Also fix: orphaned `RevitMCPConnection.exe` processes (bridge spawns per-call and something isn't reaping — add cleanup).

## 3 · Deployment phases

**Architecture: Option 1 — everything on Sagar's workstation.** LAN mode is structurally broken for live features (the bridge spawns the connector exe and dials 127.0.0.1:8080 — it would drive *Ashwin's* Revit, not Sagar's). Fallback: LAN co-review mode with `BIND_HOST=0.0.0.0` + `QAQC_AUTH_TOKEN`, days-scale stopgap only.

| Phase | What | Owner | Est |
|---|---|---|---|
| D1 | Pre-flight hardening: PAT rotation (Ashwin) + strip from remote; redacting log filter for `?token=` (root cause: `maintenance.py` file handler on `uvicorn.access`); `-Prod` path in run_backend.ps1 (drop `--reload`); fix team-guide log path; orphan-exe reaper | agent (except PAT) | ≈2h |
| D2 | Provision Sagar's machine: Python 3.11, Revit + model, Nonica (per decision 2), revit-mcp add-in copy, pyRevit + Export QAQC extension | Ashwin | ≈90m |
| D3 | Install: git clone (code only) + hand-ship Madera sample trimmed of `evidence/`+`pages/` (repo artifacts are gitignored — sample doesn't travel via git); `.env`; Startup-folder shortcut (NOT a Windows service — session 0 can't reach Revit's UI; DEPLOY.md's NSSM advice is wrong) | Ashwin | ≈45m |
| D4 | Acceptance smoke on his machine: 14 steps (connectors on → upload PDF → auto-benchmark banner → match → Show in Revit + BX → selected-element → live 3D badge → runs drawer) | both | ≈25m |
| D5 | Training: 30-min walkthrough agenda + one-page quick-reference card for Sagar | Ashwin | 30m |
| D6 | Support: update = `git pull` + pytest gate; rollback = pre-deploy git tag; logs at `logs/app.log`; top-3 failure modes card (connector off / Revit dialog blocking [R-35] / stale export) | — | — |

## 4 · Execution order today (once approved)

1. Ashwin rotates PAT (5 min, only human-blocking step) — agents start everything else in parallel
2. Wave A (parallel): UI P1 · Pipeline A2 · D1 hardening
3. Gate: 300+ pytest, Playwright (with the 5 updated assertions), Madera/CS/Dogwood invariance
4. Tag `pre-deploy-sagar`, commit, then D2→D5 on Sagar's machine with Ashwin
