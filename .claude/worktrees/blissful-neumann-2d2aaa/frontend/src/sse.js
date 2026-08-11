/* sse.js — ONE EventSource for /api/pipeline/events, fanned out by step (§8).
   Replaces the monolith's two private EventSources (pipeline modal + wizard)
   plus the wizard's 4s poll with a single shared stream and one slow fallback
   poll. Consumers register onStep(step, cb) / onAny(cb). */

import { tokenized } from "./api.js";

let es = null;
const stepSubs = {};   // step -> [cb]
const anySubs = [];

function ensure() {
  if (es) return;
  try {
    es = new EventSource(tokenized("/api/pipeline/events"));
    es.onmessage = ev => {
      let e; try { e = JSON.parse(ev.data); } catch { return; }
      for (const cb of anySubs) { try { cb(e); } catch (err) { console.error(err); } }
      for (const cb of (stepSubs[e.step] || [])) { try { cb(e); } catch (err) { console.error(err); } }
    };
    es.onerror = () => { /* browser auto-reconnects */ };
  } catch { /* SSE unsupported — fallback polls still run */ }
}

export function onStep(step, cb) {
  (stepSubs[step] ??= []).push(cb);
  ensure();
  return () => { stepSubs[step] = (stepSubs[step] || []).filter(f => f !== cb); };
}

export function onAny(cb) {
  anySubs.push(cb);
  ensure();
  return () => { const i = anySubs.indexOf(cb); if (i >= 0) anySubs.splice(i, 1); };
}

/* One slow fallback poll (§8): a safety net for state an external agent may
   advance out-of-band that the SSE stream doesn't surface. Returns a stop fn. */
export function startFallbackPoll(cb, ms = 8000) {
  const id = setInterval(cb, ms);
  return () => clearInterval(id);
}
