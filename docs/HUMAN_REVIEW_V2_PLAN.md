# Human Review v2 — AI-first mismatch resolution (plan)

Company context: PDF→Revit QA-QC currently takes ~8 days. The review queue
is now honest (device-level LOCATION_MISMATCH only, real ft offsets), so
every minute a reviewer spends there must count.

## Flow per LOCATION_MISMATCH device

1. **AI analyzes FIRST (deterministic core).** `GET /api/review/{id}/analysis`
   computes from the device registry — no LLM required for the facts:
   - offset in feet + compass direction (model space, not PDF points);
   - **systematic-shift test**: mean offset vector of all mismatched
     devices on the same sheet/mark — if this device moves WITH the crowd
     (cosine ≥ .8, magnitude within 50%), the cause is registration/drafting
     shift, not a modeling error, and the AI says so with the count;
   - **isolation test**: offset direction unique → genuine deviation candidate;
   - ambiguity check: distance to the 2nd-nearest same-mark device;
   - optional LLM sentence (openrouter) that PHRASES these numbers — the
     LLM never invents facts, it only words them.
2. **Human adds their logic** (comment box — they are the experienced ones).
3. **AI evaluates the human's logic**: `POST /api/review/{id}/evaluate` —
   deterministic consistency check of the claim against the numbers + LLM
   verdict `{agrees, reasoning}` grounded ONLY in those numbers.
4. **Animated Accept / Reject** buttons appear.
   - **Accept** → `POST /api/review/{id}/resolve {action:"accept"}`:
     - device status LOCATION_MISMATCH → **MATCH** with a permanent
       `resolution` block: `{via:"human_review", original_status,
       distance_ft, comment, evaluated_by_ai, resolved_at}` — the audit
       trail never disappears, the honest distance stays on the row;
     - propagates EVERYWHERE at once: every sheet appearance of the device
       in element_list.json, device_registry.json, scene3d.json (3D marker
       turns green), review overlay + punch list (both read element_list);
     - a **teach-memory rule** (scope global) is saved from the comment, so
       the same reviewer logic auto-suggests on every future project;
   - **Reject** → status unchanged, comment stored, item flagged
     `reviewed_rejected` (stays on the punch list as a true defect).

## Honesty rules (unchanged)
- Only a HUMAN accept changes a status, and only via the resolution block —
  the pipeline itself never converts a mismatch.
- Re-running ② Match rebuilds statuses from geometry, then re-applies
  stored resolutions whose device still exists with the same pairing.
- The UI marks resolved rows "MATCH ✓ human" — never silently identical to
  geometric MATCH.

## Files
- `review.py`: `analyze(element_id)`, `evaluate(element_id, comment)`,
  `resolve(element_id, action, comment)` + resolution re-apply hook.
- `main.py`: 3 endpoints + re-apply call at the end of elements_match.
- `frontend/index.html`: review detail drawer — AI analysis card (loads on
  open), evaluate button, animated accept/reject pair, resolved styling.
