# Production Roadmap — everything between this prototype and production-grade software

Honest inventory as of 2026-07-10. The prototype proves the concept end to end
(real matches, no fakes, 86 tests green). This lists what remains, ordered by
what blocks value first.

---

## 1. Accuracy gaps (highest value)

| Gap | Today | Fix |
|---|---|---|
| Steel columns / posts not matched | 211 columns NOT_IN_SCHEDULE on Country Side — the COLUMN SCHEDULE mark column doesn't parse (marks like `C1`/`C2` in a layout the table reader misses), so schedule-listing and Revit `C1-…` mark matching never activate | Extend the schedule parser for that column layout (or per-client teach rule); the matching path is already built and tested |
| Shear-wall marks on LGS sets | Country Side tags shear walls as numbers-in-hexagons (`#` column) — unreadable as text tokens | Detect hexagon symbol + number pairs on plans; or teach-rule per client |
| Secondary sheets unregistered | S5/S6/S8/SD1/SD2 → 52 hold-downs NOT_EVALUATED | Detail sheets have few/no grid bubbles; add viewport-crop-aware registration (use the sheet's callout references to its parent plan), or accept NOT_EVALUATED for detail sheets as policy |
| Leader-line accuracy | ~10pt uncertainty on hold-down anchors → some near-miss LOCATION_MISMATCH | Follow leader lines to the anchor symbol (the vector data is in the PDF) |
| Level scoping default | `scope_level` off by default on Madera (v2 exports lack level data) | v3 exports carry level+elevation per element — enable per-level comparison by default for v3 projects |
| Madera on v3 | Madera still uses the old noisy v2 export | Re-export Madera with the new pyRevit exporter; retire the v2 path after |

## 2. Robustness / correctness hardening

- **Scanned PDFs**: currently requires a text layer. Add OCR fallback (Tesseract) with confidence flags.
- **Rotated / multi-plan sheets**: registration assumes one plan per sheet, no rotation handling beyond the similarity fit.
- **Schedule parser coverage**: one layout family per client keeps appearing (SYMBOL columns, stacked headers, hexagon marks). Needs a corpus of client PDFs + regression fixtures per client.
- **Exporter edge cases**: linked models are not exported; design options/phases follow view visibility (document as policy); cloud/unsaved models fall back to Desktop output.
- **Concurrency**: one in-process pipeline at a time; SSE progress is a single global bus. Fine for one user, breaks for teams (see §4).

## 3. Product completeness

- **Report generation**: PDF report per project (summary + flagged items + evidence crops + reviewer dispositions) for clients/inspectors — the punch-list CSV exists, a formal report doesn't.
- **Batch / multi-sheet review UX**: bulk dispositions, filters by disposition, review progress persistence per reviewer.
- **Project management**: delete/archive projects, re-upload versions of the same project (v1 vs v2 model comparison — "what changed since last export").
- **Teach memory management UI**: scoping rules per client vs global, edit rules (today: create/delete only).
- **3D**: roof/framing category toggles, section cuts, click-through from framing members (currently non-pickable for performance).

## 4. Software engineering for production

- **Deployment**: today it's `run_backend.ps1` on one laptop. Needs a packaged install (Docker or a Windows service + installer), settings file, and a supported browser matrix.
- **Multi-user**: authentication, per-user review dispositions, concurrent project isolation (worker queue for pipeline runs instead of blocking HTTP calls).
- **Data layer**: JSON artifacts on disk → fine as an audit trail, but a small DB (SQLite → Postgres) is needed for comments/dispositions/projects once multiple users write concurrently.
- **API keys / secrets**: OpenRouter key lives in `.env` on the machine; needs a secrets store and per-deployment configuration. LLM calls should be rate-limited and budget-capped.
- **Error reporting & telemetry**: server logs only. Add structured logging, health monitoring, and user-visible error states for every pipeline step.
- **Test depth**: 86 backend unit/integration tests, but no end-to-end CI (pipeline on a fixture project), no frontend test suite beyond ad-hoc Playwright, no load tests for 100+ page PDFs.
- **The frontend is one 60KB HTML file**: fast to iterate, hard to maintain. Split into modules or migrate to a small build (Vite) once features stabilize.
- **Exporter distribution**: pyRevit extension is installed per machine by hand; package it as a pyRevit extension bundle (or installer) with a version check against the backend schema.

## 5. Validation before calling it "production"

1. **Ground-truth benchmark**: pick 3 projects, have a QA engineer produce the full manual answer key once, and measure precision/recall of every status — the `/api/metrics/accuracy` number needs a human baseline to mean anything.
2. **Acceptance thresholds**: agree what ships (e.g. ≥90% of hold-downs auto-resolved correctly on registered sheets, zero false MATCH).
3. **Pilot**: run it in parallel with the manual process on 2–3 live projects; count hours saved and misses in both directions.

---

**Bottom line:** the core engine (extract → register → compare → review → learn)
works end to end and is honest by construction. What remains is (1) squeezing
the known accuracy gaps — columns/posts parsing first, (2) hardening for
inputs we haven't seen, and (3) ordinary productization: packaging, users,
database, reports, CI. None of it is research risk; it's engineering hours.
