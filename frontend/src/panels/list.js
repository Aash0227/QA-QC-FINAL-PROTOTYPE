/* panels/list.js — grouped element list + filters (left pane).
   Reacts to the store's "select" event; renders the table alongside. */

import { $, esc, COL, CATS, CAT_LABEL } from "../util.js";
import { store, select, subscribe } from "../store.js";
import { renderTable } from "./table.js";

export function visibleElements() {
  const f = store.filters, q = f.search.toLowerCase();
  return store.elements.filter(e =>
    (!f.status || e.status === f.status)
    && (!f.sheet || e.sheet === f.sheet)
    && (!q || `${e.mark} ${e.id} ${e.status} ${e.sheet || ""} ${e.category}`.toLowerCase().includes(q)));
}

function dotBar(items) {
  const c = {};
  for (const e of items) c[e.status] = (c[e.status] || 0) + 1;
  return Object.entries(c).sort()
    .map(([s, n]) => `<span><span class="dot" style="background:${COL[s]}"></span>${n}</span>`).join("");
}

export function renderList() {
  const items = visibleElements();
  const searching = !!store.filters.search;
  const byCat = {};
  for (const e of items) (byCat[e.category] ??= []).push(e);
  let html = "";
  for (const cat of CATS) {
    const list = byCat[cat]; if (!list) continue;
    const open = searching || store.openCats.has(cat);
    html += `<div class="cat-hdr ${open ? "open" : ""}" data-cat="${cat}">
      <span class="car">▶</span>${CAT_LABEL[cat]} <span class="cnt">${list.length}</span>
      <span class="mini-dots">${dotBar(list)}</span></div>`;
    if (!open) continue;
    const byMark = {};
    for (const e of list) (byMark[e.mark || "—"] ??= []).push(e);
    for (const mark of Object.keys(byMark).sort()) {
      const grp = byMark[mark], mkey = `${cat}:${mark}`;
      const mopen = searching || store.openMarks.has(mkey);
      html += `<div class="mark-hdr" data-mark="${esc(mkey)}">
        <span class="car" style="${mopen ? "transform:rotate(90deg)" : ""}">▶</span>${esc(mark)}
        <span class="cnt">(${grp.length})</span><span class="mini-dots">${dotBar(grp)}</span></div>`;
      if (!mopen) continue;
      html += grp.map(e => `
        <div class="row ${store.selected === e.id ? "selected" : ""}" data-id="${esc(e.id)}">
          <span class="dot" style="background:${COL[e.status]}"></span>
          <span class="meta">${esc(e.sheet) || "—"}${e.distance_pdf_points != null ? ` · ${e.distance_pdf_points}pt` : ""}${e.taught_by ? " · 🧠" : ""}</span>
          <span class="pill" style="color:${COL[e.status]};border-color:${COL[e.status]}44">${e.status.replaceAll("_", " ")}</span>
        </div>`).join("");
    }
  }
  $("#list-rows").innerHTML = html || `<div class="empty-state">No elements match.</div>`;
  $("#list-rows").querySelectorAll(".cat-hdr").forEach(h => h.onclick = () => {
    const c = h.dataset.cat;
    store.openCats.has(c) ? store.openCats.delete(c) : store.openCats.add(c);
    renderList();
  });
  $("#list-rows").querySelectorAll(".mark-hdr").forEach(h => h.onclick = () => {
    const m = h.dataset.mark;
    store.openMarks.has(m) ? store.openMarks.delete(m) : store.openMarks.add(m);
    renderList();
  });
  $("#list-rows").querySelectorAll(".row").forEach(r => r.onclick = () => select(r.dataset.id, "list"));
  renderTable();
}

export function renderFilters() {
  const sts = [...new Set(store.elements.map(e => e.status))].sort();
  $("#status-filter").innerHTML = `<option value="">All statuses</option>` + sts.map(s => `<option>${s}</option>`).join("");
  $("#sheet-filter").innerHTML = `<option value="">All sheets</option>` + store.sheets.map(s => `<option>${s}</option>`).join("");
  $("#status-filter").value = store.filters.status || "";
  $("#sheet-filter").value = store.filters.sheet || "";
}

/* ---- wiring ---- */
$("#search").oninput = ev => { store.filters.search = ev.target.value; renderList(); };
$("#status-filter").onchange = ev => { store.filters.status = ev.target.value; renderList(); };
$("#sheet-filter").onchange = ev => { store.filters.sheet = ev.target.value; renderList(); };

subscribe("select", ({ id, origin }) => {
  renderList();
  if (!id) return;
  const row = document.querySelector(`.row[data-id="${CSS.escape(id)}"]`);
  if (row && origin !== "list") row.scrollIntoView({ block: "nearest", behavior: "smooth" });
});
