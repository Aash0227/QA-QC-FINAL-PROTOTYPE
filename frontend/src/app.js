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
import { openProjects } from "./panels/projects.js";
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
   overlay (panels/projects.js). The header keeps only the name of the project
   you are looking at, which is the one thing you need on screen at all times —
   every verdict below it is scoped to this workspace. */
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
$("#btn-projects").onclick = openProjects;

/* ---------------- data load ---------------- */
export async function loadAll(first = false) {
  let ok = true;
  try {
    const el = await api("/api/elements");
    store.elements = el.elements; store.sheets = el.sheets; store.cc = el.count_consistency || {};
    store.scopeWarnings = el.scope_warnings || [];   /* R-07 export-scope honesty */
    $("#hdr-stats").textContent =
      `${el.counts.total} elements · ${el.counts.by_status.MATCH || 0} verified · ` +
      // "flagged", not "need review": this counts every discrepancy, while the
      // header CTA counts the review QUEUE. Two different numbers under one
      // label is exactly the kind of thing a reviewer stops trusting.
      `${(el.counts.by_status.PDF_ONLY || 0) + (el.counts.by_status.REVIT_ONLY || 0) + (el.counts.by_status.LOCATION_MISMATCH || 0)} flagged`;
  } catch (e) {
    ok = false;
    $("#hdr-stats").textContent = "no data yet — open ▶ Run the check";
  }
  if (!ok) { if (first) openPipeline(); return; }
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
    if ($("#pipe-modal").classList.contains("open")) return $("#pipe-modal").classList.remove("open");
    store.selected = null; renderList(); syncIsolation();
    resetView3D();
  }
});

/* ---------------- pipeline modal — guided QA/QC flow ---------------- */
function pipeState() {
  // State: "upload_pdf" | "upload_revit" | "ready" | "running" | "complete"
  // Check run_state first (background runs survive page refresh), fall back to
  // artifact checklist for older/disabled-run states.
  return api("/api/pipeline/run").then(rs => {
    if (rs && rs.status === "running") return "running";
    return api("/api/pipeline/status").then(st => {
      if (!st.steps) return "upload_pdf";
      const d = Object.fromEntries(st.steps.map(s => [s.key, s.done]));
      if (d.match) return "complete";
      if (d.upload && d.revit_convert) return "ready";
      if (d.upload) return "upload_revit";
      return "upload_pdf";
    });
  }).catch(() => api("/api/pipeline/status").then(st => {
    // no run yet — use artifact state
    if (!st?.steps) return "upload_pdf";
    const d = Object.fromEntries(st.steps.map(s => [s.key, s.done]));
    if (d.match) return "complete";
    if (d.upload) return "upload_revit";
    return "upload_pdf";
  })).catch(() => "upload_pdf");
}

async function renderPipeline() {
  const body = $("#pipe-body");
  const state = await pipeState();
  if (state === "running") {
    body.innerHTML = `<div class="pipe-guide">
      <div class="pipe-running">⏳ Pipeline running…</div>
      <div id="pipe-stage-list"></div>
    </div>`;
    pollRunState();
    return;
  }
  if (state === "upload_pdf") {
    body.innerHTML = `<div class="pipe-guide">
      <div class="pipe-drop glass" id="pipe-drop">
        <div class="pipe-drop-icon">📄</div>
        <p class="pipe-drop-label">Drop the structural PDF here</p>
        <p class="pipe-drop-hint">PDF is required to begin &middot; click to browse</p>
        <input id="up-pdf" type="file" accept=".pdf" style="display:none">
      </div>
      <p class="pipe-note">Or upload the <a href="#" id="pipe-adv-revit">Revit export JSON instead</a> (advanced)</p>
    </div>`;
    const drop = $("#pipe-drop"), input = $("#up-pdf");
    drop.onclick = () => input.click();
    drop.ondragover = e => { e.preventDefault(); drop.classList.add("drag-over"); };
    drop.ondragleave = () => drop.classList.remove("drag-over");
    drop.ondrop = e => { e.preventDefault(); drop.classList.remove("drag-over");
      if (e.dataTransfer.files[0]) pdfUpload(e.dataTransfer.files[0]); };
    input.onchange = () => input.files[0] && pdfUpload(input.files[0]);
    const adv = $("#pipe-adv-revit");
    if (adv) adv.onclick = (e) => { e.preventDefault(); showRevitOnly(); };
    return;
  }
  if (state === "upload_revit") {
    body.innerHTML = `<div class="pipe-guide">
      <div class="pipe-done">✓ Drawings read — ${store.elements?.length || "?"} elements detected</div>
      <div class="pipe-drop glass" id="pipe-drop-revit">
        <div class="pipe-drop-icon">🏗</div>
        <p class="pipe-drop-label">Upload the Revit export JSON</p>
        <p class="pipe-drop-hint">In Revit: Livio QA-QC tab → Export → upload the resulting JSON</p>
        <input id="up-revit" type="file" accept=".json" style="display:none">
      </div>
    </div>`;
    const drop = $("#pipe-drop-revit"), input = $("#up-revit");
    drop.onclick = () => input.click();
    drop.ondragover = e => { e.preventDefault(); drop.classList.add("drag-over"); };
    drop.ondragleave = () => drop.classList.remove("drag-over");
    drop.ondrop = e => { e.preventDefault(); drop.classList.remove("drag-over");
      if (e.dataTransfer.files[0]) revitUpload(e.dataTransfer.files[0]); };
    input.onchange = () => input.files[0] && revitUpload(input.files[0]);
    return;
  }
  if (state === "ready") {
    const el = await api("/api/elements").catch(() => ({ counts: { total: "?" } }));
    body.innerHTML = `<div class="pipe-guide">
      <div class="pipe-done">✓ Drawings ready · Revit model loaded</div>
      <button class="primary" id="pipe-run-btn" style="font-size:16px;padding:12px 32px;margin:20px 0">▶ Run QA/QC</button>
      <p class="pipe-note">This compares the full drawing set to the model — may take a minute.</p>
    </div>`;
    $("#pipe-run-btn").onclick = () => startRun();
    return;
  }
  if (state === "complete") {
    const el = await api("/api/elements").catch(() => ({ counts: {}, elements: [] }));
    const c = el.counts || {};
    body.innerHTML = `<div class="pipe-guide">
      <div class="pipe-done">✓ QA/QC complete — ${c.total || 0} elements analysed</div>
      <div class="pipe-counts">${Object.entries(c.by_status||{}).map(([k,v]) =>
        `<span class="pipe-chip chip-${k}">${v} ${k.replace(/_/g,' ')}</span>`).join(" ")}</div>
      <button class="primary" id="pipe-review-btn" style="margin-top:16px">Open results</button>
      <p class="pipe-note"><a href="#" id="pipe-rerun">Re-run</a> after updating files</p>
    </div>`;
    $("#pipe-review-btn").onclick = () => { $("#pipe-modal").classList.remove("open"); };
    $("#pipe-rerun")?.addEventListener("click", (e) => { e.preventDefault(); startRun(true); });
    return;
  }
}

async function pdfUpload(file) {
  const fd = new FormData(); fd.append("pdf", file);
  try {
    const m = await api("/api/upload", { method: "POST", body: fd });
    toast(`PDF uploaded (${m.page_count || "?"} pages). Processing…`);
    await startRun(false);  // auto-run PDF-side stages
  } catch (e) { toast("Upload failed: " + e.message, true); renderPipeline(); }
}
async function revitUpload(file) {
  const fd = new FormData(); fd.append("revit_json", file);
  try {
    await api("/api/upload", { method: "POST", body: fd });
    toast("Revit export uploaded. Continuing…");
    await startRun(false);  // auto-run remaining stages
  } catch (e) { toast("Upload failed: " + e.message, true); renderPipeline(); }
}
async function showRevitOnly() {
  // Show a Revit JSON file input inline (advanced path).
  $("#pipe-body").innerHTML = `<div class="pipe-guide">
    <label class="file" style="display:block;margin:20px auto;max-width:320px">Revit export JSON<input id="up-revit" type="file" accept=".json"></label>
    <button class="mini" id="pipe-upload-rv-btn">Upload</button>
    <button class="mini" id="pipe-back">← Back</button>
  </div>`;
  $("#pipe-upload-rv-btn").onclick = () => { const f = $("#up-revit").files[0]; f && revitUpload(f); };
  $("#pipe-back").onclick = renderPipeline;
}

async function startRun(force = false) {
  $("#pipe-body").innerHTML = `<div class="pipe-guide">
    <div class="pipe-running">⏳ Running QA/QC pipeline… this may take a minute.</div>
    <div id="pipe-stage-list"></div>
  </div>`;
  try {
    // 202 = background run started; poll the persisted run state until it settles.
    await api("/api/pipeline/run" + (force ? "?force=true" : ""), { method: "POST" });
    pollRunState();
  } catch (e) {
    if (e.message?.includes("already in progress") || e.status === 409) {
      // Reuse the in-flight run.
      toast("Run already in progress — showing live state.");
      pollRunState();
    } else {
      toast("QA/QC run failed: " + e.message, true);
      renderPipeline();
    }
  }
}

async function pollRunState() {
  const list = $("#pipe-stage-list");
  try {
    const rs = await api("/api/pipeline/run");
    if (rs && rs.status === "running" && list) {
      list.innerHTML = rs.stages.map(s => `<div class="pipe-stage pipe-${s.status}">
        ${s.status === "running" ? "◌" : s.status === "done" ? "✓" : s.status === "failed" ? "✗" : "·"}
        ${s.title} ${s.duration_s ? `(${s.duration_s}s)` : ""}</div>`).join("");
      setTimeout(pollRunState, 1500);
      return;
    }
  } catch { /* 404 = no run — fall through */ }
  await loadAll();
  renderPipeline();
}

$("#btn-pipe").onclick = () => { window.location.href = "/"; };
$("#btn-pipe-close").onclick = () => $("#pipe-modal").classList.remove("open");

/* ---------------- boot ---------------- */
paintProjectName();
renderLayerToggles();
loadAll(true);
