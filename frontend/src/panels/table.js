/* panels/table.js — results table (sortable, filter-linked). */

import { $, esc, COL } from "../util.js";
import { store, select, subscribe } from "../store.js";
import { visibleElements } from "./list.js";

/* R-07: a category with PDF callouts but zero Revit targets means the export
   view probably hid it — say so above the verdicts instead of letting the
   PDF_ONLY rows accuse the modeller. Display-only, dismissible. */
let scopeDismissed = false;
function renderScopeBanner() {
  const box = $("#scope-banner");
  if (!box) return;
  const warns = scopeDismissed ? [] : (store.scopeWarnings || []);
  box.innerHTML = warns.length ? `
    <div style="margin:8px 10px;padding:8px 10px;border-radius:8px;
      border:1px solid #b4530044;background:#3a250855;color:var(--warn);font-size:12px">
      <b>⚠ Export scope</b>
      <button class="mini" id="scope-dismiss" style="float:right">Dismiss</button>
      ${warns.map(w => `<div style="margin-top:4px">${esc(w.message)}
        <span style="color:var(--dim)">(${w.pdf_count} PDF callouts,
        ${w.revit_count} Revit targets${w.export_view
          ? ` · export view “${esc(w.export_view)}”` : ""})</span></div>`).join("")}
    </div>` : "";
  const btn = $("#scope-dismiss");
  if (btn) btn.onclick = () => { scopeDismissed = true; renderScopeBanner(); };
}

export function renderTable() {
  const tbl = $("#table-panel");
  if (!tbl || tbl.classList.contains("hidden")) return;
  renderScopeBanner();
  const { key, dir } = store.tableSort;
  const items = visibleElements().slice().sort((a, b) => {
    const av = a[key], bv = b[key];
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    return typeof av === "number" && typeof bv === "number"
      ? (av - bv) * dir
      : String(av).localeCompare(String(bv)) * dir;
  });
  $("#results-tbody").innerHTML = items.map(e => `
    <tr class="${store.selected === e.id ? "selected" : ""}" data-id="${e.id}">
      <td>${esc(e.mark) || "—"}</td>
      <td>${esc(e.category) || "—"}</td>
      <td>${esc(e.sheet) || "—"}</td>
      <td><span class="status-pill" style="color:${COL[e.status]};border:1px solid ${COL[e.status]}66">${e.status.replaceAll("_", " ")}</span>${
        /* R-18: which flavour of REVIT_ONLY — a vocabulary gap reads very
           differently from a genuinely extra device. */
        e.status_detail && e.status_detail !== e.status
          ? ` <span class="status-pill" style="color:#a78bfa;border:1px solid #a78bfa66" title="The Revit family matched no schedule row — vocabulary gap, teachable">${esc(e.status_detail.replaceAll("_", " "))}</span>`
          : ""}</td>
      <td class="num">${e.distance_ft != null ? e.distance_ft.toFixed(2) : "—"}</td>
      <td>${esc(e.device_id) || "—"}</td>
      <td>${esc(e.reason) || "—"}</td>
    </tr>`).join("") || `<tr><td colspan="7" class="empty-state">No elements match.</td></tr>`;
  $("#results-tbody").querySelectorAll("tr[data-id]").forEach(r => r.onclick = () => select(r.dataset.id, "table"));
  document.querySelectorAll("#results-table thead th").forEach(th => {
    th.classList.toggle("sorted", th.dataset.k === key);
    th.dataset.dir = dir === 1 ? "▲" : "▼";
  });
}

/* ---- wiring ---- */
$("#results-table thead").addEventListener("click", ev => {
  const th = ev.target.closest("th"); if (!th) return;
  const k = th.dataset.k;
  store.tableSort.dir = store.tableSort.key === k ? -store.tableSort.dir : 1;
  store.tableSort.key = k;
  renderTable();
});
$("#btn-table").onclick = () => { $("#table-panel").classList.toggle("hidden"); renderTable(); };
$("#btn-table-close").onclick = () => $("#table-panel").classList.add("hidden");

subscribe("select", () => renderTable());
