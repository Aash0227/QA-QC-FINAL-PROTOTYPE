/* panels/pdf.js — drawing (PDF) pane: tabs, pan/zoom, overlay, measure,
   layers, benchmark markers. Reacts to the store's "select" event. */

import gsap from "gsap";
import { $, esc, COL, BENCHMARK_COLOR } from "../util.js";
import { store, select, subscribe } from "../store.js";
import { api } from "../api.js";
import { renderList } from "./list.js";
import { renderCC } from "./inspector.js";
import { resize3D } from "./viewer3d.js";

const cam = { x: 0, y: 0, s: 0.3 };
function applyCam() { $("#cam").style.transform = `translate(${cam.x}px,${cam.y}px) scale(${cam.s})`; }

export function renderTabs() {
  $("#tabs").innerHTML = store.sheets.map(s =>
    `<span class="tab ${s === store.activeSheet ? "on" : ""}" data-s="${s}">${s}</span>`).join("");
  $("#tabs").querySelectorAll(".tab").forEach(t => t.onclick = () => showSheet(t.dataset.s));
}

export async function showSheet(sheet, instant = false) {
  if (!sheet) return;
  store.activeSheet = sheet; renderTabs();
  const img = $("#page-img");
  const [w, h] = store.pageSize[sheet] || [2592, 1728];
  if (!instant) gsap.to("#cam", { opacity: .15, duration: .2 });
  await new Promise(res => { img.onload = res; img.onerror = res; img.src = `/api/sheets/${sheet}/page.png?dpi=150`; });
  img.style.width = w + "px"; img.style.height = h + "px";
  const ov = $("#overlay");
  ov.setAttribute("viewBox", `0 0 ${w} ${h}`);
  ov.style.width = w + "px"; ov.style.height = h + "px";
  renderOverlay(); fitView(); ensureSheetScale(sheet); renderCC();
  if (!instant) gsap.to("#cam", { opacity: 1, duration: .35 });
}

export function fitView() {
  const vp = $("#viewport"), [w, h] = store.pageSize[store.activeSheet] || [2592, 1728];
  if (vp.clientWidth < 10) return;
  const s = Math.min(vp.clientWidth / w, vp.clientHeight / h) * 0.98;
  gsap.to(cam, { x: (vp.clientWidth - w * s) / 2, y: (vp.clientHeight - h * s) / 2, s, duration: .6, ease: "power3.out", onUpdate: applyCam });
}

function renderOverlay() {
  const ov = $("#overlay");
  const els = store.elements.filter(e =>
    e.sheet === store.activeSheet && e.drawable && (e.pdf_point || e.revit_point_transformed_to_pdf)
    && store.layers.has(e.status));
  ov.innerHTML = els.map(e => {
    const p = e.pdf_point || e.revit_point_transformed_to_pdf;
    const c = COL[e.status]; let inner = "";
    if (e.bbox_pdf) {
      const [x0, y0, x1, y1] = e.bbox_pdf, pad = 7;
      inner += `<rect x="${x0 - pad}" y="${y0 - pad}" width="${x1 - x0 + 2 * pad}" height="${y1 - y0 + 2 * pad}" rx="4" stroke="${c}" stroke-dasharray="${e.status === "MATCH" ? "" : "7 4"}"/>`;
    } else {
      inner += `<rect x="${p.x - 16}" y="${p.y - 16}" width="32" height="32" rx="4" stroke="${c}" stroke-dasharray="${e.status === "MATCH" ? "" : "7 4"}"/>`;
    }
    if (e.status === "LOCATION_MISMATCH" && e.pdf_point && e.revit_point_transformed_to_pdf) {
      const t = e.revit_point_transformed_to_pdf;
      inner += `<line x1="${t.x}" y1="${t.y}" x2="${e.pdf_point.x}" y2="${e.pdf_point.y}" stroke="${c}" stroke-width="2" stroke-dasharray="4 3"/><circle cx="${t.x}" cy="${t.y}" r="5" stroke="${c}"/>`;
    }
    if (e.wall_segment_pdf) {
      const [[ax, ay], [bx, by]] = e.wall_segment_pdf;
      inner += `<line x1="${ax}" y1="${ay}" x2="${bx}" y2="${by}" stroke="${c}" stroke-width="3" opacity=".8"/>`;
    }
    return `<g class="el" data-id="${esc(e.id)}"><title>${esc(e.mark)} · ${e.status} · ${esc(e.reason) || ""}</title>${inner}</g>`;
  }).join("") + renderBenchmarkMarkers() + `<g id="measure-layer"></g><g id="focus-layer"></g>`;
  ov.querySelectorAll("g.el").forEach(g => g.onclick = ev => { ev.stopPropagation(); select(g.dataset.id, "sheet"); });
  syncIsolation();
}

function renderBenchmarkMarkers() {
  const bm = store.pdfBenchmarks;
  if (!bm || !store.showBenchmarks || bm.page_index !== store.pageIndex[store.activeSheet]) return "";
  return (bm.benchmarks || []).map(b => `<g class="bm-marker">
      <circle class="pulse-ring" cx="${b.point_pt.x}" cy="${b.point_pt.y}" r="20" fill="none" stroke="${BENCHMARK_COLOR}" stroke-width="2"/>
      <line x1="${b.point_pt.x - 14}" y1="${b.point_pt.y}" x2="${b.point_pt.x + 14}" y2="${b.point_pt.y}" stroke="${BENCHMARK_COLOR}" stroke-width="2"/>
      <line x1="${b.point_pt.x}" y1="${b.point_pt.y - 14}" x2="${b.point_pt.x}" y2="${b.point_pt.y + 14}" stroke="${BENCHMARK_COLOR}" stroke-width="2"/>
      <text x="${b.point_pt.x + 24}" y="${b.point_pt.y - 18}" fill="${BENCHMARK_COLOR}">${esc(b.mark)}</text>
    </g>`).join("");
}

export function syncIsolation() {
  const ov = $("#overlay");
  ov.classList.toggle("iso", !!store.selected);
  ov.querySelectorAll("g.el").forEach(g => g.classList.toggle("selected", g.dataset.id === store.selected));
  const fl = $("#focus-layer"); if (!fl) return;
  fl.innerHTML = "";
  if (!store.selected) return;
  const e = store.elements.find(x => x.id === store.selected);
  const p = e && (e.pdf_point || e.revit_point_transformed_to_pdf);
  if (e && p && e.sheet === store.activeSheet) {
    fl.innerHTML = `<circle class="pulse-ring" cx="${p.x}" cy="${p.y}" r="26" fill="none" stroke="${COL[e.status]}"/>
      <text x="${p.x + 30}" y="${p.y - 24}" fill="${COL[e.status]}">${esc(e.mark)} · ${e.status.replaceAll("_", " ")}${e.distance_pdf_points != null ? ` · ${e.distance_pdf_points} pt` : ""}</text>`;
  }
}

function flyToPoint(p) {
  const vp = $("#viewport"), s = 2.6;
  gsap.to(cam, { x: vp.clientWidth / 2 - p.x * s, y: vp.clientHeight / 2 - p.y * s, s, duration: 1.1, ease: "power3.inOut", onUpdate: applyCam });
}

/* pan / zoom */
const measure = { on: false, pts: [] };
(() => {
  const vp = $("#viewport");
  let drag = null;
  vp.addEventListener("pointerdown", ev => {
    if (measure.on) return;
    drag = { x: ev.clientX, y: ev.clientY, cx: cam.x, cy: cam.y };
    vp.setPointerCapture(ev.pointerId);
  });
  vp.addEventListener("pointermove", ev => {
    if (!drag) return;
    cam.x = drag.cx + ev.clientX - drag.x; cam.y = drag.cy + ev.clientY - drag.y; applyCam();
  });
  vp.addEventListener("pointerup", () => drag = null);
  vp.addEventListener("wheel", ev => {
    ev.preventDefault();
    const r = vp.getBoundingClientRect();
    const mx = ev.clientX - r.left, my = ev.clientY - r.top;
    const k = ev.deltaY < 0 ? 1.15 : 1 / 1.15;
    const ns = Math.min(8, Math.max(0.05, cam.s * k));
    cam.x = mx - (mx - cam.x) * (ns / cam.s); cam.y = my - (my - cam.y) * (ns / cam.s); cam.s = ns; applyCam();
  }, { passive: false });
  vp.addEventListener("dblclick", () => { store.selected = null; renderList(); syncIsolation(); });
})();

$("#btn-measure").onclick = () => {
  measure.on = !measure.on; measure.pts = [];
  $("#btn-measure").classList.toggle("active", measure.on);
  $("#viewport").classList.toggle("measuring", measure.on);
  const ml = $("#measure-layer"); if (ml) ml.innerHTML = "";
};
$("#viewport").addEventListener("click", ev => {
  if (!measure.on) return;
  const r = $("#viewport").getBoundingClientRect();
  const px = (ev.clientX - r.left - cam.x) / cam.s, py = (ev.clientY - r.top - cam.y) / cam.s;
  measure.pts.push([px, py]);
  const ml = $("#measure-layer");
  if (measure.pts.length === 1) {
    ml.innerHTML = `<circle cx="${px}" cy="${py}" r="4" fill="#5eead4"/>`;
  } else {
    const [[ax, ay], [bx, by]] = measure.pts;
    const dpt = Math.hypot(bx - ax, by - ay);
    const scale = store.sheetScale[store.activeSheet];
    const label = scale ? `${dpt.toFixed(1)} pt · ${(dpt / scale).toFixed(2)} ft` : `${dpt.toFixed(1)} pt (scale unverified)`;
    ml.innerHTML = `<line x1="${ax}" y1="${ay}" x2="${bx}" y2="${by}" stroke="#5eead4" stroke-width="2"/>
      <circle cx="${ax}" cy="${ay}" r="4" fill="#5eead4"/><circle cx="${bx}" cy="${by}" r="4" fill="#5eead4"/>
      <text x="${(ax + bx) / 2 + 8}" y="${(ay + by) / 2 - 8}" fill="#5eead4">${label}</text>`;
    measure.pts = [];
  }
});

/* The project's compare sheet owns the GLOBAL registration calibration; every
   other sheet has a per-sheet one. Which sheet that is comes from the backend
   (Madera S-201, Dogwood S-05, Country Side S7) — hardcoding "S-201" left the
   measure tool reporting "scale unverified" on any other project's main sheet.
   ponytail: one in-flight promise, cached for the page's life; the answer
   changes only when a different project is activated (full reload). */
let primarySheetPromise = null;
const primarySheet = () => (primarySheetPromise ??=
  api("/api/sheets/primary").then(r => r.sheet).catch(() => null));

async function ensureSheetScale(sheet) {
  if (sheet in store.sheetScale) return;
  store.sheetScale[sheet] = null;
  try {
    const primary = await primarySheet();
    const r = sheet === primary ? await api("/api/registration") : await api(`/api/registration/sheet/${sheet}`);
    if (r.match_allowed) store.sheetScale[sheet] = r.calibration?.transform?.scale || null;
  } catch { }
}

export function renderLayerToggles() {
  $("#layer-toggles").innerHTML = Object.keys(COL).map(s =>
    `<span class="chip ${store.layers.has(s) ? "on" : ""}" data-l="${s}" style="${store.layers.has(s) ? `color:${COL[s]};border-color:${COL[s]}66` : ""}">${s.replaceAll("_", " ")}</span>`).join("")
    + `<span class="chip ${store.showBenchmarks ? "on" : ""}" data-l="__benchmarks" style="${store.showBenchmarks ? `color:${BENCHMARK_COLOR};border-color:${BENCHMARK_COLOR}66` : ""}">Benchmarks</span>`;
  $("#layer-toggles").querySelectorAll(".chip").forEach(ch => ch.onclick = () => {
    const l = ch.dataset.l;
    if (l === "__benchmarks") { store.showBenchmarks = !store.showBenchmarks; }
    else { store.layers.has(l) ? store.layers.delete(l) : store.layers.add(l); }
    renderLayerToggles(); renderOverlay();
  });
}
$("#btn-layers").onclick = () => { const b = $("#layer-bar"); b.style.display = b.style.display === "none" ? "flex" : "none"; };
$("#opacity").oninput = ev => $("#overlay").style.opacity = ev.target.value / 100;
$("#btn-fit").onclick = fitView;

/* panel layout controls (touch both the PDF fit and the 3D size) */
$("#btn-left").onclick = () => {
  $("#main").classList.toggle("left-hidden");
  setTimeout(() => { fitView(); resize3D(); }, 60);
};
$("#btn-sheet-max").onclick = () => {
  const d = $("#dual");
  d.classList.toggle("sheet-max"); d.classList.remove("model-max");
  setTimeout(() => { fitView(); resize3D(); }, 60);
};
$("#btn-model-max").onclick = () => {
  const d = $("#dual");
  d.classList.toggle("model-max"); d.classList.remove("sheet-max");
  setTimeout(() => { fitView(); resize3D(); }, 60);
};

subscribe("select", ({ element: e, origin }) => {
  if (e && e.sheet && e.sheet !== store.activeSheet) {
    showSheet(e.sheet).then(() => { syncIsolation(); const p = e.pdf_point || e.revit_point_transformed_to_pdf; if (p) flyToPoint(p); });
  } else {
    syncIsolation();
    if (e) { const p = e.pdf_point || e.revit_point_transformed_to_pdf; if (p && origin !== "sheet") flyToPoint(p); }
  }
});
