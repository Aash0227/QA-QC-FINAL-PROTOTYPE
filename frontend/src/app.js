/* app.js — entry point (production-plan §1). Initialises the store-backed
   panels, loads project data, wires the header actions + pipeline modal, and
   boots the app. Panels self-wire on import and react to the store; app.js is
   the orchestration seam that ties data loading to them. */

import "./fonts.js";
import { $, toast } from "./util.js";
import { store } from "./store.js";
import { api, tokenized } from "./api.js";
import { onAny } from "./sse.js";
import { renderList, renderFilters } from "./panels/list.js";
import { renderTabs, showSheet, renderLayerToggles, syncIsolation } from "./panels/pdf.js";
import { loadScene, resize3D, resetView3D } from "./panels/viewer3d.js";
import { renderCC, openDrawer } from "./panels/inspector.js";
import { paintRevitPill } from "./panels/revit_live.js";
import "./panels/table.js";
import "./panels/wizard.js";
import "./panels/chat.js";

// Dynamically-generated pipeline export buttons use inline onclick=tokenized(…);
// module scope isn't global, so expose the one helper those handlers need.
// ponytail: one-line bridge for 3 inline handlers; convert to listeners if the
// export set ever grows.
window.tokenized = tokenized;

/* ---------------- project label ----------------
   Creating, switching and deleting projects all live in the Project Manager
   overlay — migrated to React (src/react/features/project-manager), mounted
   by src/react/dashboard-main.tsx and opened via a window event rather than
   a direct import (see that file's header comment for why). The header here
   keeps only the name of the project you are looking at, which is the one
   thing you need on screen at all times — every verdict below it is scoped
   to this workspace. */
async function paintProjectName() {
  try {
    const p = await api("/api/projects");
    const cur = p.projects.find(x => x.active);
    if (!cur) return;
    const label = cur.display_name.length > 28 ? cur.slug : cur.display_name;
    $("#proj-name").textContent = label;
    $("#btn-projects").title = `Project: ${cur.display_name} (${cur.slug}) — click to manage projects`;
  } catch { /* leave the generic "Projects" label */ }
}
$("#btn-projects").onclick = () => window.dispatchEvent(new CustomEvent("open-project-manager"));

/* ---------------- data load ---------------- */
export async function loadAll(first = false) {
  let ok = true;
  try {
    const el = await api("/api/elements");
    store.elements = el.elements; store.sheets = el.sheets; store.cc = el.count_consistency || {};
    store.scopeWarnings = el.scope_warnings || [];   /* R-07 export-scope honesty */
    /* Product verdicts, collapsed by the backend at the matching-engine seam.
       The header now speaks the same four words the results view does, instead
       of summing internal statuses here and risking a different total. */
    store.productCounts = el.product_counts || null;
    // Reset the verdict filter on every load. It otherwise survived Extract or
    // Match onto completely new data, silently hiding rows the reviewer had
    // never filtered.
    store.verdictFilter = null;
    const pc = store.productCounts;
    if (pc) {
      const inScope = (pc.LOCATION_MATCH || 0) + (pc.LOCATION_MISMATCH || 0) + (pc.NEEDS_REVIEW || 0);
      // "verified" (not "match") for the LOCATION_MATCH count: it is the word
      // a QA reviewer uses for an element they have confirmed, and it keeps
      // the standing accuracy gate in tests/smoke.spec.js meaningful --
      // LOCATION_MATCH is exactly the old internal MATCH count, so the
      // baseline it asserts still measures the same thing.
      $("#hdr-stats").textContent =
        `${inScope} in scope · ${pc.LOCATION_MATCH || 0} verified · ` +
        `${pc.LOCATION_MISMATCH || 0} mismatch` +
        (pc.NEEDS_REVIEW ? ` · ${pc.NEEDS_REVIEW} to review` : "");
    } else {
      $("#hdr-stats").textContent =
        `${el.counts.total} elements · ${el.counts.by_status.MATCH || 0} verified`;
    }
  } catch (e) {
    ok = false;
    $("#hdr-stats").textContent = "no data yet — open ⚡ Pipeline";
  }
  if (!ok) { if (first) window.location.href = "/pipeline.html"; return; }
  try {
    const ei = await api("/api/elements/intelligence");
    for (const s of ei.sheets) {
      store.pageSize[s.sheet_number] = s.page_size_pt;
      store.pageIndex[s.sheet_number] = s.page_index;
    }
  } catch { }
  try { store.pdfBenchmarks = await api("/api/pdf/benchmarks"); } catch { }
  if (!store.activeSheet) {
    const counts = {};
    for (const e of store.elements) if (e.sheet) counts[e.sheet] = (counts[e.sheet] || 0) + 1;
    store.activeSheet = Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0] || store.sheets[0];
    // Open the busiest category, the same way the busiest sheet is picked above.
    // This used to hardcode "shear_wall", which left the list fully collapsed on
    // any project without shear walls — the reviewer's first impression of a
    // holdown-only set was an empty panel.
    if (store.openCats.size === 0) {
      const byCat = {};
      for (const e of store.elements) if (e.category) byCat[e.category] = (byCat[e.category] || 0) + 1;
      const busiest = Object.entries(byCat).sort((a, b) => b[1] - a[1])[0]?.[0];
      if (busiest) store.openCats.add(busiest);
    }
  }
  renderTabs(); renderFilters(); renderList();
  await showSheet(store.activeSheet, true);
  renderCC(); loadScene();
}

/* ---------------- header actions ---------------- */
export async function runExtract() {
  try {
    toast("Scanning all pages (rules from memory applied)…");
    const r = await api("/api/elements/extract", { method: "POST" });
    const rules = r.applied_memory_rules || 0;
    toast(`Extracted ${Object.entries(r.summary.marks_by_category).map(([k, v]) => `${v} ${k}`).join(", ")}${rules ? ` · ${rules} taught rules applied` : ""}`);
    await api("/api/elements/match", { method: "POST" });
    await loadAll();
  } catch (e) { toast("Extract failed: " + e.message, true); }
}
$("#btn-extract").onclick = runExtract;
$("#btn-match").onclick = async () => {
  try {
    toast("Per-sheet registration + matching…");
    const r = await api("/api/elements/match", { method: "POST" });
    toast(`Element list: ${r.counts.total} elements, ${r.counts.by_status.MATCH || 0} MATCH.`);
    for (const [s, n] of Object.entries(r.registration_notes || {})) toast(`${s}: ${n}`, true);
    await loadAll();
  } catch (e) { toast("Match failed: " + e.message, true); }
};

/* ⚙ Advanced popover: click-outside closes it, and picking an item closes it
   too (the item's own handler already ran by the time this bubble fires). */
document.addEventListener("click", ev => {
  const m = $("#adv-menu");
  if (!m?.open) return;
  if (!m.contains(ev.target) || ev.target.closest(".adv-list button")) m.open = false;
});

/* keyboard */
document.addEventListener("keydown", ev => {
  if (ev.key === "Escape") {
    if ($("#adv-menu")?.open) return ($("#adv-menu").open = false);
    store.selected = null; renderList(); syncIsolation();
    resetView3D();
  }
});

/* ⚡ Pipeline navigates to the React Pipeline Island — the vanilla guided
   upload/run modal (pipeState/renderPipeline/startRun/pollRunState/
   pdfUpload/revitUpload/showRevitOnly) was superseded by it and removed. */
$("#btn-pipe").onclick = () => { window.location.href = "/pipeline.html"; };

/* ---------------- boot ---------------- */
paintProjectName();
renderLayerToggles();
loadAll(true);
