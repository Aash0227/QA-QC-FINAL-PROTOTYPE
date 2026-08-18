/* panels/table.js — compatibility shim (Stage 2 of the frontend migration).
   The results table body and scope-warning banner are now rendered by
   src/react/features/element-review/{ResultsTable,ScopeBanner}.tsx, mounted
   directly into the existing #results-tbody / #scope-banner containers by
   react/dashboard-main.tsx.

   This file keeps only the trivial event wiring that mutates store.js state
   (sort column/direction, panel open/closed) and calls the renderTable()
   bridge (= emit("refresh")) — see panels/list.js's header comment for why
   this wiring stays vanilla rather than moving to React. */

import { $ } from "../util.js";
import { store, emit } from "../store.js";

export function renderTable() {
  emit("refresh");
}

/* ---- wiring ---- */
$("#results-table thead").addEventListener("click", ev => {
  const th = ev.target.closest("th"); if (!th) return;
  const k = th.dataset.k;
  store.tableSort.dir = store.tableSort.key === k ? -store.tableSort.dir : 1;
  store.tableSort.key = k;
  renderTable();
  document.querySelectorAll("#results-table thead th").forEach(el => {
    el.classList.toggle("sorted", el.dataset.k === store.tableSort.key);
    el.dataset.dir = store.tableSort.dir === 1 ? "▲" : "▼";
  });
});
$("#btn-table").onclick = () => { $("#table-panel").classList.toggle("hidden"); renderTable(); };
$("#btn-table-close").onclick = () => $("#table-panel").classList.add("hidden");
