/* store.js — single source of truth + tiny pub/sub (production-plan §8).
   Panels read state from `store` and react to events via subscribe(key, fn).
   Selection is a store mutation (select) that every panel reacts to — one code
   path instead of the old cross-panel direct calls. */

import { DEFAULT_LAYERS } from "./util.js";

export const store = {
  elements: [], sheets: [], cc: {}, scene: null, scopeWarnings: [],
  /* product_counts from GET /api/elements — the four product verdicts the
     backend already collapsed to. Null until the first load. */
  productCounts: null,
  /* Verdict filter chosen from the verdict bar (null = show everything). */
  verdictFilter: null,
  /* Set when /api/elements fails: "no-results" (409/404 — pipeline has not
     produced results yet) or "fetch-failed" (a real fault). Drives the
     dashboard empty state that replaced the old silent redirect. */
  loadError: null,
  /* run_state.next_action from the backend — the concrete remedy for this
     project (e.g. upload the Revit export). */
  nextAction: null,
  activeSheet: null, selected: null,
  filters: { search: "", status: "", sheet: "" },
  layers: new Set(DEFAULT_LAYERS),
  openCats: new Set(), openMarks: new Set(),
  sheetScale: {}, pageSize: {}, pageIndex: {},
  drawer: null, swOnly: false,
  pdfBenchmarks: null, showBenchmarks: true,
  tableSort: { key: "mark", dir: 1 },
};

/* ---- pub/sub ---- */
const subs = {};
export function subscribe(key, fn) {
  (subs[key] ??= []).push(fn);
  return () => { subs[key] = (subs[key] || []).filter(f => f !== fn); };
}
export function emit(key, ...args) {
  (subs[key] || []).forEach(fn => { try { fn(...args); } catch (e) { console.error(e); } });
}

/* ---- selection: one mutation all panels react to (§8) ----
   Sets selected, auto-opens the element's group in the list, and emits
   "select" with {id, origin, element}. Subscribers (list/pdf/viewer3d/
   inspector) each render their own reaction. */
export function select(id, origin) {
  store.selected = id;
  const e = store.elements.find(x => x.id === id);
  if (e) { store.openCats.add(e.category); store.openMarks.add(`${e.category}:${e.mark || "—"}`); }
  emit("select", { id, origin, element: e });
}
