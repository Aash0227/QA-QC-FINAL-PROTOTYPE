/* panels/list.js — compatibility shim (Stage 2 of the frontend migration).
   The grouped element list is now rendered by
   src/react/features/element-review/ElementList.tsx, mounted directly into
   the existing #list-rows container by react/dashboard-main.tsx.

   This file keeps only the trivial event wiring that mutates store.js state
   and calls the renderList() bridge (= emit("refresh")) — the React
   component reacts to that via useStoreVersion. Moving this wiring itself
   to React would add risk for no behavioral gain: it's a handful of
   onchange/oninput handlers around a shared mutable store, not rendering
   logic.

   renderList() itself is still exported because panels/pdf.js, panels/chat.js
   and app.js all call it directly after mutating store.elements/store.selected
   outside of the store's own select()/emit() path — see the header comment
   in useStoreVersion.ts for the full chain. */

import { $ } from "../util.js";
import { store, select, subscribe, emit } from "../store.js";

export function renderList() {
  emit("refresh");
}

export function renderFilters() {
  const sts = [...new Set(store.elements.map(e => e.status))].sort();
  $("#status-filter").innerHTML = `<option value="">All statuses</option>` + sts.map(s => `<option>${s}</option>`).join("");
  $("#sheet-filter").innerHTML = `<option value="">All sheets</option>` + store.sheets.map(s => `<option>${s}</option>`).join("");
  $("#status-filter").value = store.filters.status || "";
  $("#sheet-filter").value = store.filters.sheet || "";
}

/* ---- wiring ---- */
/* Search debounces the render otherwise (per keystroke) — the store filter
   still updates instantly, so J/K and the table see the current filter on
   their next render. */
let searchT = null;
$("#search").oninput = ev => {
  store.filters.search = ev.target.value;
  clearTimeout(searchT);
  searchT = setTimeout(renderList, 200);
};
$("#status-filter").onchange = ev => { store.filters.status = ev.target.value; renderList(); };
$("#sheet-filter").onchange = ev => { store.filters.sheet = ev.target.value; renderList(); };

/* ---- keyboard: J / K step through the list ----
   J/K move through exactly the rows that are on screen right now (same
   filters, same expanded groups), so what you step through is what you see.
   Ignored while typing: the search box is one Tab away. */
function rowIds() {
  return [...document.querySelectorAll("#list-rows .row")].map(r => r.dataset.id);
}

function step(delta) {
  const ids = rowIds();
  if (!ids.length) return;
  const at = ids.indexOf(store.selected);
  const next = at === -1 ? (delta > 0 ? 0 : ids.length - 1)
    : Math.min(Math.max(at + delta, 0), ids.length - 1);
  select(ids[next], "keyboard");
}

document.addEventListener("keydown", ev => {
  if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
  const t = ev.target;
  if (t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement
      || t instanceof HTMLSelectElement || t?.isContentEditable) return;
  // Overlays own the keyboard while they are up.
  if ($("#projects")?.classList.contains("open")) return;
  if ($("#bmwizard")?.classList.contains("open")) return;

  if (ev.key === "j" || ev.key === "J") { ev.preventDefault(); step(1); }
  else if (ev.key === "k" || ev.key === "K") { ev.preventDefault(); step(-1); }
});

/* Scroll the selected row into view when selection came from somewhere other
   than a click on the row itself (keyboard, PDF, 3D). The React list
   component re-renders on this same "select" event independently. */
subscribe("select", ({ id, origin }) => {
  if (!id) return;
  const row = document.querySelector(`.row[data-id="${CSS.escape(id)}"]`);
  if (row && origin !== "list") row.scrollIntoView({ block: "nearest", behavior: "smooth" });
});
