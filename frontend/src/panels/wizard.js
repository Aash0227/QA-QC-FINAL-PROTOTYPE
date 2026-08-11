/* panels/wizard.js — Benchmark Autopilot (2-point registration) wizard.
   Same state machine as the monolith; the only change is plumbing: it consumes
   the shared SSE stream (sse.onStep) + one slow fallback poll instead of
   opening its own EventSource and polling every 4s (§8). */

import { $, esc, toast } from "../util.js";
import { api, tokenized } from "../api.js";
import { onStep, startFallbackPoll } from "../sse.js";

const BM_STEPS = [
  ["proposing", "Propose"],
  ["awaiting_pdf_approval", "PDF approval"],
  ["stamping", "Stamp PDF"],
  ["awaiting_revit", "Revit connect"],
  ["placing_markers", "Place markers"],
  ["awaiting_revit_approval", "Revit approval"],
  ["awaiting_export", "Fresh export"],
  ["calibrating", "Calibrate"],
  ["done", "Done"],
];
const bmw = { wf: null, stopPoll: null };
// §3 "Pick manually": user-picked BM-1/BM-2 from detected grid intersections.
const bmPick = { on: false, gp: null, picks: [] };

function bmRail() {
  const st = bmw.wf?.state || "idle";
  const idx = BM_STEPS.findIndex(([s]) => s === st);
  $("#bm-rail").innerHTML = BM_STEPS.map(([s, lbl], i) => {
    const cls = st === "failed"
      ? (i === 0 ? "failed" : "")
      : i < idx ? "past" : i === idx ? "active" : "";
    return `<div class="bw-tick ${cls}"><span class="bw-dot"></span><span class="bw-lbl">${lbl}</span></div>`;
  }).join("") + (st === "failed"
    ? `<div class="bw-tick failed"><span class="bw-dot"></span><span class="bw-lbl">FAILED</span></div>` : "");
}

function bmProposalCard(p) {
  if (!p) return "";
  const rows = p.benchmarks.map(b => `<tr>
      <td>${esc(b.mark)}</td><td>${esc(b.grid_label)}</td>
      <td class="num">(${b.pdf_point_pt.x.toFixed(1)}, ${b.pdf_point_pt.y.toFixed(1)}) pt</td>
      <td class="num">(${b.revit_point_ft.x.toFixed(3)}, ${b.revit_point_ft.y.toFixed(3)}) ft</td>
    </tr>`).join("");
  const crops = p.benchmarks.map(b => `<div class="bw-crop">
      ${b.evidence_url ? `<img src="${esc(tokenized(b.evidence_url + "?t=" + Date.now()))}" alt="${esc(b.mark)} evidence">` : `<div style="aspect-ratio:1;display:grid;place-items:center;color:var(--bw-dim);font-size:11px">no crop</div>`}
      <span class="bw-x"></span><span class="bw-ring"></span>
      <span class="bw-tag">${esc(b.mark)} · ${esc(b.grid_label)}</span>
    </div>`).join("");
  return `<div class="bw-card"><h2>Proposal · ${esc(p.sheet_number)} (page ${p.page_index + 1})</h2>
    <div class="bw-crops">${crops}</div>
    <table><thead><tr><th>Mark</th><th>Grid</th><th>PDF point</th><th>Revit point</th></tr></thead>
    <tbody>${rows}</tbody></table>
    <p class="mono" style="color:var(--bw-dim);font-size:12px;margin:10px 0 0">
      Separation ${p.separation_pdf_pt} pt · ${p.separation_revit_ft} ft · ${p.candidates_considered} labeled intersections considered</p></div>`;
}

function bmReadbackCard() {
  const placed = (bmw.wf.history || []).findLast(h => h.to === "awaiting_revit_approval");
  const rb = placed?.payload?.readback;
  const p = bmw.wf.proposal;
  if (!p) return "";
  const unverified = placed && placed.payload?.verified === false
    ? `<div class="bw-unverified">⚠ Agent-reported placement — not server-verified. Confirm against Revit before approving.</div>`
    : "";
  const rows = p.benchmarks.map(b => {
    const got = rb?.[b.mark];
    const dx = got ? got.x - b.revit_point_ft.x : null;
    const dy = got ? got.y - b.revit_point_ft.y : null;
    const d = got ? Math.hypot(dx, dy) : null;
    return `<tr><td>${esc(b.mark)}</td>
      <td class="num">(${b.revit_point_ft.x.toFixed(3)}, ${b.revit_point_ft.y.toFixed(3)})</td>
      <td class="num">${got ? `(${got.x.toFixed(3)}, ${got.y.toFixed(3)})` : "— not reported —"}</td>
      <td class="num ${d != null && d < 0.05 ? "bw-delta-ok" : "bw-delta-bad"}">${d != null ? d.toFixed(4) + " ft" : "?"}</td></tr>`;
  }).join("");
  return `<div class="bw-card"><h2>Revit read-back vs intended</h2>
    <table><thead><tr><th>Mark</th><th>Intended (ft)</th><th>Read-back (ft)</th><th>Δ</th></tr></thead>
    <tbody>${rows}</tbody></table>${unverified}</div>`;
}

function bmVerificationCard(wf) {
  const v = wf.verification || (wf.history || []).findLast(h => h.to === "awaiting_revit")?.payload?.verification;
  if (!v) return "";
  const rows = v.checks.map(c => `<tr><td>${esc(c.mark)}</td>
    <td class="num">(${c.expected.x.toFixed(1)}, ${c.expected.y.toFixed(1)})</td>
    <td class="num">${c.found ? `(${c.found.x.toFixed(1)}, ${c.found.y.toFixed(1)})` : "— not found —"}</td>
    <td class="num ${c.ok ? "bw-delta-ok" : "bw-delta-bad"}">${c.delta_pt ?? "?"} pt</td></tr>`).join("");
  return `<table><thead><tr><th>Mark</th><th>Expected</th><th>Found</th><th>Δ</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function bmCards() {
  const wf = bmw.wf, st = wf?.state || "idle";
  let html = "";
  if (["idle", "failed", "done"].includes(st)) {
    if (bmPick.on) {
      html += bmPickCard();
    } else {
      const note = st === "failed"
        ? `<p style="color:var(--bw-markup)" class="mono">Run failed: ${esc((wf.history || []).findLast(h => h.to === "failed")?.note || "")}</p>`
        : st === "done" ? `<p style="color:var(--bw-signal)" class="mono">Calibration is benchmark-verified. Re-run any time.</p>` : "";
      html += `<div class="bw-card"><h2>Start</h2>${note}
        <p style="color:var(--bw-dim);font-size:13px">Scans the plan sheet for labeled grid intersections and proposes the two with maximum diagonal separation. No transform needed — works on unregistered projects.</p>
        <div class="bw-actions">
          <button class="bw-btn" id="bm-propose">◎ Propose benchmarks</button>
          <button class="bw-btn" id="bm-pick-manual">✎ Pick manually</button>
        </div></div>`;
    }
  }
  if (wf?.proposal && st !== "idle") html += bmProposalCard(wf.proposal);
  if (st === "awaiting_pdf_approval")
    html += `<div class="bw-card"><h2>Approval · PDF stamps</h2>
      <p style="color:var(--bw-dim);font-size:13px">Approve to let the agent stamp BM-1/BM-2 circle annotations at these exact points (original PDF backed up first).</p>
      <input class="bw-reject-comment" id="bm-reject-comment" placeholder="reason if rejecting (audit-logged, optional)">
      <div class="bw-actions">
        <button class="resolve-btn resolve-accept" id="bm-approve">✓ Approve — stamp the PDF</button>
        <button class="resolve-btn resolve-reject" id="bm-reject">✕ Reject</button>
      </div></div>`;
  if (st === "stamping")
    html += `<div class="bw-card"><h2>Stamp PDF</h2>
      <p style="color:var(--bw-dim);font-size:13px">Writes BM-1/BM-2 circle annotations at the approved points (PDF backed up first), then reads them back to verify before advancing.</p>
      <div class="bw-actions"><button class="bw-btn" id="bm-stamp">◎ Stamp PDF</button></div>
      ${bmVerificationCard(wf)}</div>`;
  if (st === "awaiting_revit")
    html += `<div class="bw-card"><h2>Connect Revit</h2>
      <p style="color:var(--bw-dim);font-size:13px">The backend drives Revit directly through the Nonica MCP bridge — open Revit with the model and enable the NonicaTab PRO AI Connector.</p>
      ${bmRevitPill()}
      <div class="bw-actions"><button class="bw-btn" id="bm-revit-connected" disabled>Revit connected — continue</button></div></div>`;
  if (st === "placing_markers")
    html += `<div class="bw-card"><h2>Place markers in Revit</h2>
      <p style="color:var(--bw-dim);font-size:13px">The backend copies the benchmark family to each approved point, sets its Mark, and reads the placement back — no Claude in the loop. Server-verified before advancing.</p>
      ${bmRevitPill()}
      <div class="bw-actions"><button class="bw-btn" id="bm-place">◆ Place BM-1 / BM-2</button></div></div>`;
  if (st === "awaiting_revit_approval") {
    html += bmReadbackCard();
    html += `<div class="bw-card"><h2>Approval · Revit markers</h2>
      <p style="color:var(--bw-dim);font-size:13px">Markers are placed session-only. Approve if read-back matches intended; then save the model and re-export.</p>
      <input class="bw-reject-comment" id="bm-reject-comment" placeholder="reason if rejecting (audit-logged, optional)">
      <div class="bw-actions">
        <button class="resolve-btn resolve-accept" id="bm-approve">✓ Approve placement</button>
        <button class="resolve-btn resolve-reject" id="bm-reject">✕ Reject</button>
      </div></div>`;
  }
  if (st === "awaiting_export")
    html += `<div class="bw-card"><h2>Waiting for fresh export</h2>
      <div class="bw-wait">Save the Revit model (Ctrl+S), run the Livio exporter — dialog must show "Benchmarks: 2" — then upload the JSON. This auto-detects and advances once both benchmarks are present; no manual step needed.</div></div>`;
  if (st === "calibrating")
    html += `<div class="bw-card"><h2>Calibrating</h2>
      <div class="bw-wait">Extract stamps → gated 2-point solve. Saved only if quality gates pass.</div></div>`;
  if (st === "done") {
    const cal = (wf.history || []).findLast(h => h.to === "done")?.payload || {};
    html += `<div class="bw-card"><h2>Calibration verified</h2>
      <p class="mono" style="color:var(--bw-signal)">source: ${esc(cal.calibration_source)} · scale ${cal.scale ?? "?"} pt/ft</p></div>`;
  }
  $("#bm-cards").innerHTML = html;
  const on = (id, fn) => { const b = $(id); if (b) b.onclick = fn; };
  on("#bm-propose", () => bmAction("/api/benchmark-workflow/propose", { actor: "human_ui" }));
  on("#bm-stamp", () => bmAction("/api/benchmark-workflow/stamp", { actor: "human_ui" }));
  on("#bm-place", () => bmAction("/api/benchmark-workflow/place-markers", { actor: "human_ui" }));
  on("#bm-revit-connected", () => bmAction("/api/benchmark-workflow/advance", { step: "revit_connected", actor: "human_ui" }));
  if ($("#bw-revit-status")) bmMaybeCheckRevit();
  on("#bm-reject", () => {
    const comment = ($("#bm-reject-comment")?.value || "").trim() || "Rejected from wizard.";
    bmAction("/api/benchmark-workflow/approve", { approved: false, comment, actor: "human_ui" });
  });
  // §3: approve both gates (awaiting_pdf_approval, awaiting_revit_approval).
  on("#bm-approve", () => {
    const comment = ($("#bm-reject-comment")?.value || "").trim();
    bmAction("/api/benchmark-workflow/approve", { approved: true, comment, actor: "human_ui" });
  });
  // §3 Pick manually
  on("#bm-pick-manual", bmStartPick);
  on("#bm-pick-cancel", () => { bmPick.on = false; bmPick.picks = []; bmCards(); });
  on("#bm-pick-clear", () => { bmPick.picks = []; bmCards(); });
  on("#bm-pick-propose", () => {
    const points = bmPick.picks.map(k => ({ grid_id: k.grid_id, mark: k.mark }));
    bmPick.on = false; bmPick.picks = [];
    bmAction("/api/benchmark-workflow/propose", { points, actor: "human_ui" });
  });
  const svg = $("#bm-pick-svg");
  if (svg) svg.onclick = ev => bmPickClick(svg, ev);
}

function bmPickCard() {
  const gp = bmPick.gp;
  if (!gp) return `<div class="bw-card"><h2>Pick manually</h2>
    <p style="color:var(--bw-dim);font-size:13px">Loading detected grid intersections…</p></div>`;
  const [w, h] = gp.page_size;
  const dots = (gp.points || []).map(p => {
    const picked = bmPick.picks.find(k => k.grid_id === p.id);
    const col = picked ? "var(--bw-signal)" : "var(--bw-dim)";
    return `<circle cx="${p.point.x}" cy="${p.point.y}" r="${picked ? 10 : 5}" fill="none" stroke="${col}" stroke-width="${picked ? 3 : 1.5}"/>`
      + (picked ? `<text x="${p.point.x + 14}" y="${p.point.y - 12}" fill="var(--bw-signal)" font-size="20" font-family="'IBM Plex Mono',monospace">${esc(picked.mark)}</text>` : "");
  }).join("");
  const labels = bmPick.picks.length
    ? bmPick.picks.map(k => `${esc(k.mark)} · ${esc(k.label)}`).join("   ·   ")
    : "Click two intersections — first snaps to BM-1, second to BM-2.";
  const ready = bmPick.picks.length === 2;
  return `<div class="bw-card"><h2>Pick manually · ${esc(gp.sheet_number)} (page ${gp.page_index + 1})</h2>
    <p style="color:var(--bw-dim);font-size:13px">${(gp.points || []).length} labeled intersections detected — clicks snap to the nearest. Evidence crops + approval gate are identical to auto-propose.</p>
    <div class="bw-pick" style="aspect-ratio:${w}/${h}">
      <img src="${tokenized('/api/sheets/' + encodeURIComponent(gp.sheet_number) + '/page.png?dpi=150')}" alt="${esc(gp.sheet_number)}">
      <svg id="bm-pick-svg" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">${dots}</svg>
    </div>
    <p class="mono" id="bm-pick-labels" style="color:var(--bw-signal);font-size:13px;margin:10px 0 0">${labels}</p>
    <div class="bw-actions">
      <button class="bw-btn" id="bm-pick-propose"${ready ? "" : " disabled"}>◎ Propose these 2</button>
      <button class="resolve-btn resolve-reject" id="bm-pick-clear">Clear</button>
      <button class="resolve-btn resolve-reject" id="bm-pick-cancel">Cancel</button>
    </div></div>`;
}

async function bmStartPick() {
  bmPick.on = true; bmPick.picks = []; bmPick.gp = null;
  bmCards();  // render the loading state immediately
  try { bmPick.gp = await api("/api/benchmark-workflow/grid-points"); }
  catch (e) { toast("Grid points: " + e.message, true); bmPick.on = false; }
  bmCards();
}

function bmPickClick(svg, ev) {
  const gp = bmPick.gp;
  if (!gp || bmPick.picks.length >= 2) return;
  const pt = svg.createSVGPoint();
  pt.x = ev.clientX; pt.y = ev.clientY;
  const loc = pt.matrixTransform(svg.getScreenCTM().inverse());
  let best = null, bd = Infinity;
  for (const p of gp.points || []) {
    const d = Math.hypot(p.point.x - loc.x, p.point.y - loc.y);
    if (d < bd) { bd = d; best = p; }
  }
  if (!best) return;
  if (bmPick.picks.some(k => k.grid_id === best.id)) { toast("Already picked that intersection.", true); return; }
  bmPick.picks.push({ grid_id: best.id, mark: bmPick.picks.length === 0 ? "BM-1" : "BM-2", label: best.label });
  bmCards();
}

// Revit connection status is EXPENSIVE (spawns the MCP exe). Render from a
// cached value and debounce the live check so the fallback poll can't pile up
// overlapping spawns.
const bmRevit = { status: null, checking: false, at: 0 };
function bmRevitPill() {
  const s = bmRevit.status;
  const cls = !s ? "" : s.connected ? "on" : "off";
  const txt = !s ? "checking connection…"
    : s.connected ? ("Revit connected" + (s.model_title ? " · " + s.model_title : ""))
    : (s.reason || "Revit not connected");
  return `<div id="bw-revit-status" class="bw-revit-status ${cls}">${esc(txt)}</div>`;
}
function bmPaintRevit() {
  const el = $("#bw-revit-status"); if (!el) return;
  const s = bmRevit.status;
  el.className = "bw-revit-status " + (!s ? "" : s.connected ? "on" : "off");
  el.textContent = !s ? "checking connection…"
    : s.connected ? ("Revit connected" + (s.model_title ? " · " + s.model_title : ""))
    : (s.reason || "Revit not connected");
  const btn = $("#bm-revit-connected");
  if (btn && s?.connected) btn.disabled = false;
}
async function bmMaybeCheckRevit() {
  if (bmRevit.checking || Date.now() - bmRevit.at < 12000) { bmPaintRevit(); return; }
  bmRevit.checking = true;
  try { bmRevit.status = await api("/api/revit/status"); }
  catch { bmRevit.status = { connected: false, reason: "status check failed" }; }
  bmRevit.checking = false; bmRevit.at = Date.now();
  bmPaintRevit();
}
/* Approval banner — the auto-benchmark that runs on upload leaves a proposal
   parked at the awaiting_pdf_approval gate. Surface it at the top of the main
   content so nobody has to know the wizard exists; both buttons reuse existing
   endpoints/UI (approve, or open this same wizard). */
function bmBanner() {
  const wf = bmw.wf;
  const bms = wf?.proposal?.benchmarks || [];
  let el = $("#bm-banner");
  if (wf?.state !== "awaiting_pdf_approval" || bms.length < 2) { el?.remove(); return; }
  if (!el) {
    el = document.createElement("div");
    el.id = "bm-banner";
    el.className = "glass";
    el.style.cssText = "margin:8px 12px;padding:10px 14px;display:flex;gap:12px;"
      + "align-items:center;flex-wrap:wrap;border-left:3px solid var(--bw-signal,#22c55e)";
    $("#main").insertAdjacentElement("beforebegin", el);
  }
  // "Approve to continue" is asserted verbatim by tests/smoke.spec.js — keep it.
  el.innerHTML = `<span style="flex:1;min-width:280px">The system picked two reference `
    + `points on this sheet — <b>${esc(bms[0].grid_label || bms[0].grid_id)}</b> &amp; `
    + `<b>${esc(bms[1].grid_label || bms[1].grid_id)}</b> — to line the drawing up with the `
    + `Revit model. Approve to continue.</span>`
    + `<button class="mini primary" id="bmb-approve">✓ Approve</button>`
    + `<button class="mini" id="bmb-review">Review the points</button>`;
  $("#bmb-approve").onclick = () => bmAction("/api/benchmark-workflow/approve",
    { approved: true, actor: "human_ui", comment: "Approved from banner." });
  $("#bmb-review").onclick = () => $("#btn-autopilot").click();
}

async function bmRefresh() {
  try { bmw.wf = await api("/api/benchmark-workflow"); } catch { return; }
  bmRail(); bmCards(); bmBanner();
}
async function bmAction(url, body) {
  try {
    bmw.wf = await api(url, { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    bmRail(); bmCards(); bmBanner();
  } catch (e) { toast("Autopilot: " + e.message, true); bmRefresh(); }
}
function bmLog(e) {
  const box = $("#bm-log");
  const line = document.createElement("div");
  line.className = "ev-" + e.kind;
  line.textContent = `${new Date(e.ts * 1000).toLocaleTimeString()} · ${e.message}`;
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
}
$("#btn-autopilot").onclick = () => {
  $("#bmwizard").classList.add("open");
  bmRefresh();
  if (!bmw.stopPoll) bmw.stopPoll = startFallbackPoll(bmRefresh, 8000); // agent may advance out-of-band
};
$("#bm-close").onclick = () => {
  $("#bmwizard").classList.remove("open");
  if (bmw.stopPoll) { bmw.stopPoll(); bmw.stopPoll = null; }
};

/* Subscribe + load at boot (not on wizard open): the approval banner has to
   appear on its own after an upload's auto-benchmark, wizard untouched. */
onStep("benchmark_workflow", e => { bmLog(e); bmRefresh(); });
bmRefresh();
