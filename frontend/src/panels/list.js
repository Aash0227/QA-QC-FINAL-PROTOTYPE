/* panels/list.js — grouped element list + filters (left pane).
   Reacts to the store's "select" event; renders the table alongside. */

import { $, esc, COL, CATS, CAT_LABEL, GLYPH, statusLabel } from "../util.js";
import { store, select, subscribe } from "../store.js";
import { renderTable } from "./table.js";

export function visibleElements() {
  const f = store.filters, q = f.search.toLowerCase();
  return store.elements.filter(e =>
    (!f.status || e.status === f.status)
    && (!f.sheet || e.sheet === f.sheet)
    && (!q || `${e.mark} ${e.id} ${e.status} ${e.sheet || ""} ${e.category}`.toLowerCase().includes(q)));
}

/* Count-per-status bar on the category/mark headers. The dot carries a glyph
   as well as a colour, and the whole group is titled, so the breakdown is
   readable without colour vision and on a greyscale printout. */
function dotBar(items) {
  const c = {};
  for (const e of items) c[e.status] = (c[e.status] || 0) + 1;
  return Object.entries(c).sort()
    .map(([s, n]) => `<span title="${esc(n)} ${esc(statusLabel(s))}">
      <span class="dot" style="background:${COL[s]}">${esc(GLYPH[s] || "")}</span>${n}</span>`).join("");
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
        <div class="row ${store.selected === e.id ? "selected" : ""}" data-id="${esc(e.id)}"
             role="option" aria-selected="${store.selected === e.id}"
             aria-label="${esc(e.mark || "unmarked")} on sheet ${esc(e.sheet) || "unknown"}, ${esc(statusLabel(e.status))}">
          <span class="dot" style="background:${COL[e.status]}">${esc(GLYPH[e.status] || "")}</span>
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
/* Search rebuilds the whole grouped list per keystroke otherwise — debounce
   the render (the store filter still updates instantly, so J/K and the table
   see the current filter on their next render). */
let searchT = null;
$("#search").oninput = ev => {
  store.filters.search = ev.target.value;
  clearTimeout(searchT);
  searchT = setTimeout(renderList, 200);
};
$("#status-filter").onchange = ev => { store.filters.status = ev.target.value; renderList(); };
$("#sheet-filter").onchange = ev => { store.filters.sheet = ev.target.value; renderList(); };

/* ---- keyboard: J / K step through the list, like the blueprint's reviewer ----
   The list was mouse-only, which made walking a 300-element punch list a drag
   marathon. J/K move through exactly the rows that are on screen right now
   (same filters, same expanded groups), so what you step through is what you
   see. Ignored while typing: the search box is one Tab away. */
function rowIds() {
  return [...document.querySelectorAll("#list-rows .row")].map(r => r.dataset.id);
}

function step(delta) {
  const ids = rowIds();
  if (!ids.length) return;
  const at = ids.indexOf(store.selected);
  // Nothing selected yet: J starts at the top, K at the bottom.
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
  if ($("#pipe-modal")?.classList.contains("open")) return;
  if ($("#bmwizard")?.classList.contains("open")) return;

  if (ev.key === "j" || ev.key === "J") { ev.preventDefault(); step(1); }
  else if (ev.key === "k" || ev.key === "K") { ev.preventDefault(); step(-1); }
});

subscribe("select", ({ id, origin }) => {
  renderList();
  if (!id) return;
  const row = document.querySelector(`.row[data-id="${CSS.escape(id)}"]`);
  if (row && origin !== "list") row.scrollIntoView({ block: "nearest", behavior: "smooth" });
});
