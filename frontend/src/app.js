/* app.js — entry point (production-plan §1). Initialises the store-backed
   panels, loads project data, wires the header actions + pipeline modal, and
   boots the app. Panels self-wire on import and react to the store; app.js is
   the orchestration seam that ties data loading to them. */

import { $, esc, toast } from "./util.js";
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

/* ---------------- project switcher ---------------- */
async function loadProjects() {
  try {
    const p = await api("/api/projects");
    const sel = $("#proj-switch");
    sel.innerHTML = p.projects.map(x =>
      `<option value="${esc(x.slug)}" ${x.active ? "selected" : ""}>📁 ${esc(x.display_name.length > 26 ? x.slug : x.display_name)}</option>`).join("");
    sel.onchange = async () => {
      await api("/api/projects/activate", { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ slug: sel.value }) });
      toast(`Switched to project ${sel.value} — reloading…`);
      setTimeout(() => location.reload(), 600);
    };
    $("#btn-proj-del").disabled = !sel.value;
  } catch (e) { $("#proj-switch").style.display = "none"; }
}

$("#btn-proj-del").onclick = async () => {
  const sel = $("#proj-switch");
  const slug = sel.value;
  if (!slug) return;
  if (!confirm(`Delete project '${slug}'? This removes all its data and cannot be undone.`)) return;
  try {
    await api(`/api/projects/${encodeURIComponent(slug)}`, { method: "DELETE" });
    toast(`Deleted project ${slug}.`);
    const wasSelected = sel.value === slug;
    await loadProjects();
    if (wasSelected) location.reload();  // deleted the project we were viewing
  } catch (e) { toast("Delete failed: " + e.message, true); }
};

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
    if (store.openCats.size === 0) store.openCats.add("shear_wall");
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

/* ---------------- pipeline modal ---------------- */
const STEPS = [
  { key: "upload", icon: "📁", title: "Open a project", run: null,
    desc: "Give the system the client's drawing set PDF. The Revit side comes from the live model when the connector is on. The Madera sample is used when nothing is uploaded.",
    produces: "project_manifest.json", custom: "upload" },
  { key: "revit_convert", icon: "🏗", title: "1 · Read the Revit model", run: ["/api/revit/ai-convert?use_saved=true", "/api/revit/ai-convert?use_sample=true"],
    desc: "Reads the raw Revit export and groups loose parts (bodies + anchor bolts) into real hold-down assemblies, learning the family naming patterns.",
    produces: "AIConvert_revit.json — canonical assemblies" },
  { key: "pdf_intelligence", icon: "📄", title: "2 · PDF Page Intelligence", run: ["/api/pdf/page-intelligence?use_saved=true"],
    desc: "Finds the foundation plan page and detects every hold-down callout (H1–H4) with its physical location, following leader lines.",
    produces: "pdf_page_intelligence.json — detections + evidence crops" },
  { key: "pdf_convert", icon: "🔁", title: "3 · Line up the drawing data", run: ["/api/pdf/ai-convert"],
    desc: "Restructures the PDF detections into the same format as the Revit data so the two sides can be compared directly.",
    produces: "AIConvert_pdf.json" },
  { key: "ransac", icon: "🎯", title: "4 · Auto-align drawing to model", run: ["/api/registration/auto-holdown"],
    desc: "Automatically figures out how model coordinates map onto the paper drawing by finding the transform that lines up the most hold-downs.",
    produces: "registration_calibration.json — verified transform" },
  { key: "benchmark", icon: "📌", title: "4b · Benchmark calibration (2-point)", run: null, custom: "benchmark",
    desc: "Deterministic alternative to RANSAC: stamp BM-1/BM-2 crosshairs on the sheet in Bluebeam and place the matching benchmark family at the same grid intersections in Revit (docs/BENCHMARK-SOP.md). Two exact points pin translation + rotation + scale, cross-checked against the title-block scale — only a clean solve is saved.",
    produces: "pdf_benchmarks.json → registration_calibration.json (benchmark_verified)" },
  { key: "compare", icon: "⚖", title: "5 · AI Compare", run: ["/api/compare/ai"],
    desc: "Pairs Revit hold-downs with PDF hold-downs one-to-one. Within 16pt = MATCH; nothing is ever faked — leftovers are flagged honestly.",
    produces: "ai_compare_report.json — verdicts" },
  { key: "extract", icon: "🔍", title: "6 · Extract ALL elements", run: ["/api/elements/extract"],
    desc: "Scans every sheet, reads every schedule table (posts, shear walls, columns, walls…), learns which marks exist, and finds them all on the plans. Applies any rules you taught the AI.",
    produces: "element_intelligence.json — full element inventory" },
  { key: "teach", icon: "💬", title: "7 · Chat / Teach (optional)", run: null, custom: "teach",
    desc: "Ask the copilot about the results, have it highlight elements, or teach this project's conventions ('HD3 means H3') conversationally — it remembers and applies them on the next extract.",
    produces: "ai_teach_memory.json — persistent rules" },
  { key: "match", icon: "🔗", title: "8 · Match everything", run: ["/api/elements/match"],
    desc: "Registers each sheet, matches shear walls to Revit wall centerlines, joins hold-down verdicts, and builds the unified element list you review.",
    produces: "element_list.json + scene3d.json" },
  { key: "review", icon: "✅", title: "9 · Review & export", run: ["/api/review/build"], custom: "exports",
    desc: "Green = verified in the model. Red = discrepancy for human review. Export the punch list for the site team.",
    produces: "punch_list.csv · review overlay PNG/SVG" },
];

/* Live progress: the shared SSE stream drives the pipeline cards while open. */
let stepStart = {};
onAny(e => {
  const card = document.querySelector(`.step[data-step="${e.step}"]`);
  const log = document.querySelector(`.steplog[data-log="${e.step}"]`);
  if (!log) return;
  log.classList.add("on");
  const t = new Date(e.ts * 1000).toLocaleTimeString();
  const line = document.createElement("div");
  line.className = "ev-" + e.kind;
  let msg = e.message;
  if (e.kind === "start") { stepStart[e.step] = e.ts; card?.classList.add("running"); msg = "▶ running…"; }
  if (e.kind === "done" || e.kind === "error") {
    card?.classList.remove("running");
    const dt = stepStart[e.step] ? ` · ${(e.ts - stepStart[e.step]).toFixed(1)}s` : "";
    msg = (e.kind === "done" ? "✓ " : "✗ ") + e.message + dt;
    if (e.kind === "done") {
      card?.classList.add("done");
      const strip = document.querySelector(`.resultstrip[data-result="${e.step}"]`);
      if (strip) { strip.style.display = "block"; strip.textContent = "Result: " + e.message + dt; }
    }
  }
  line.textContent = `${t}  ${msg}`;
  log.appendChild(line);
  while (log.children.length > 40) log.removeChild(log.firstChild);
  log.scrollTop = log.scrollHeight;
});

/* Per-phase 🤖 summaries arrive live on the SSE stream (rendered by the handler
   above like any other event), but the modal is usually closed when a phase
   finishes. phase_summaries.json keeps the latest one per phase; replay them
   into the freshly-rendered step logs so reopening the modal shows them.
   Mirrors phase_summary.PHASE_STEPS on the backend. */
const PHASE_STEPS = { upload: "upload", auto_benchmark: "benchmark",
  registration: "ransac", match: "match" };

async function replaySummaries() {
  let ps;
  try { ps = await api("/api/artifacts/phase_summaries.json"); } catch { return; }
  for (const [phase, s] of Object.entries(ps.phases || {})) {
    const log = document.querySelector(`.steplog[data-log="${PHASE_STEPS[phase] || phase}"]`);
    if (!log || !s?.text) continue;
    log.classList.add("on");
    const line = document.createElement("div");
    line.className = "ev-info";
    line.textContent = `${new Date(s.ts).toLocaleTimeString()}  🤖 ${s.text}`;
    log.appendChild(line);
  }
}

function openPipeline() { $("#pipe-modal").classList.add("open"); renderPipeline(); }
$("#btn-pipe").onclick = openPipeline;
$("#btn-pipe-close").onclick = () => $("#pipe-modal").classList.remove("open");

async function renderPipeline() {
  let status = { steps: [] };
  try { status = await api("/api/pipeline/status"); } catch { }
  const done = Object.fromEntries(status.steps.map(s => [s.key, s.done]));
  $("#pipe-steps").innerHTML = STEPS.map((s, i) => `
    <div class="step ${done[s.key] ? "done" : ""}" data-step="${s.key}">
      <div class="rail"><div class="ic">${s.icon}</div></div>
      <div class="card glass">
        <h3>${s.title} <span class="st ${done[s.key] ? "done" : "todo"}">${done[s.key] ? "✓ done" : "not run"}</span></h3>
        <p>${s.desc}</p>
        <div class="actions">
          ${s.custom === "upload" ? `
            <div class="upload-card">
              <label class="file">Drawing set (PDF)<input id="up-pdf" type="file" accept=".pdf"></label>
              <div id="up-revit-pill" class="bw-revit-status">checking Revit connection…</div>
              <details class="adv-fold"><summary>▸ Advanced: upload a Revit export JSON instead</summary>
                <label class="file">Revit export JSON<input id="up-revit" type="file" accept=".json"></label>
              </details>
              <button class="mini" id="btn-upload">Upload</button>
            </div>` : ""}
          ${s.custom === "teach" ? `<button class="mini" data-open-teach>Open Chat</button>
            <span class="badge">🧠 ${status.memory_rules || 0} rules in memory</span>` : ""}
          ${s.custom === "exports" ? `
            <button class="primary mini" onclick="window.open(tokenized('/api/export/punch-list.csv'))">⬇ Punch list CSV</button>
            <button class="mini" onclick="window.open(tokenized('/api/review/overlay.png'))">⬇ Marked-up drawing (PNG)</button>` : ""}
        </div>
        <details class="step-adv"><summary>Advanced</summary>
          <p class="produces">→ ${s.produces}</p>
          <div class="actions">
            ${s.run ? `<button class="mini" data-runstep="${i}">Run this step</button>` : ""}
            ${s.custom === "benchmark" ? `
              <button class="mini" data-bm-extract>1 · Extract PDF stamps</button>
              <button class="mini" data-bm-calibrate>2 · Calibrate from benchmarks</button>
              <span class="badge" data-bm-status></span>` : ""}
          </div>
          <div class="steplog" data-log="${s.key}"></div>
        </details>
        <div class="resultstrip" data-result="${s.key}" style="display:none"></div>
      </div>
    </div>`).join("");
  await replaySummaries();
  paintRevitPill("#up-revit-pill");
  $("#pipe-steps").querySelectorAll("[data-runstep]").forEach(b => b.onclick = () => runStep(+b.dataset.runstep));
  const t = $("#pipe-steps").querySelector("[data-open-teach]");
  if (t) t.onclick = () => { $("#pipe-modal").classList.remove("open"); openDrawer("chat"); };
  const bmStatus = $("#pipe-steps").querySelector("[data-bm-status]");
  const bmSay = (msg, err = false) => { if (bmStatus) bmStatus.textContent = msg; toast(msg, err); };
  const bmE = $("#pipe-steps").querySelector("[data-bm-extract]");
  if (bmE) bmE.onclick = async () => {
    try {
      const r = await api("/api/pdf/benchmarks", { method: "POST" });
      const marks = (r.benchmarks || []).map(b => b.mark).join(", ");
      if (r.error) return bmSay("✗ " + r.error, true);
      if ((r.benchmarks || []).length < 2)
        return bmSay(`Found ${marks || "none"} — ${(r.warnings || []).join(" ")}`, true);
      bmSay(`✓ Stamps found: ${marks} (page ${r.page_index + 1})`);
    } catch (e) { bmSay("✗ " + e.message, true); }
  };
  const bmC = $("#pipe-steps").querySelector("[data-bm-calibrate]");
  if (bmC) bmC.onclick = async () => {
    try {
      const r = await api("/api/registration/benchmarks", { method: "POST" });
      const q = r.quality || {}, b = r.benchmark || {};
      if (!r.saved)
        return bmSay("✗ Not saved: " + (q.confidence_reason || "calibration failed"), true);
      bmSay(`✓ Calibrated (${q.confidence}) — scale ${b.derived_scale_pt_per_ft} pt/ft`
        + (b.scale_drift_pct != null ? ` (${b.scale_drift_pct}% drift)` : "")
        + " · saved as benchmark_verified");
      renderPipeline();
    } catch (e) { bmSay("✗ " + e.message, true); }
  };
  const up = $("#btn-upload");
  if (up) up.onclick = async () => {
    const fd = new FormData();
    const p = $("#up-pdf").files[0], rv = $("#up-revit").files[0];
    if (!p && !rv) return toast("Choose a PDF first (or a Revit JSON under Advanced).", true);
    if (p) fd.append("pdf", p);
    if (rv) fd.append("revit_json", rv);
    try {
      const m = await api("/api/upload", { method: "POST", body: fd });
      toast(`Uploaded (${m.page_count || "?"} pages).`); renderPipeline();
    }
    catch (e) { toast("Upload failed: " + e.message, true); }
  };
}
async function runStep(i) {
  const s = STEPS[i]; if (!s.run) return true;
  const el = document.querySelector(`.step[data-step="${s.key}"]`);
  el?.classList.add("running");
  try {
    try { await api(s.run[0], { method: "POST" }); }
    catch (e) { if (s.run[1]) await api(s.run[1], { method: "POST" }); else throw e; }
    el?.classList.remove("running"); el?.classList.add("done");
    toast(`${s.title} ✓`);
    return true;
  } catch (e) {
    el?.classList.remove("running");
    toast(`${s.title} failed: ${e.message}`, true);
    return false;
  }
}
$("#btn-run-all").onclick = async () => {
  for (let i = 0; i < STEPS.length; i++) {
    if (!STEPS[i].run) continue;
    const ok = await runStep(i);
    if (!ok) return;
  }
  toast("Full pipeline complete.");
  renderPipeline();
  await loadAll();
};

/* ---------------- boot ---------------- */
loadProjects();
renderLayerToggles();
loadAll(true);
