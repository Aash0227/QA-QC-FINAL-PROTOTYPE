/* panels/revit_live.js — Revit-live Phase 1 UI: "Show in Revit" selection,
   the plain-English "Why this verdict?" block, and the Revit ID lookup drawer.
   Leaf-ish panel: imports util/api only, so inspector.js can pull its helpers
   without a cycle. Every server string goes through esc().
   ponytail: one file for all three surfaces — they share the status cache,
   the analysis renderer and the connector-offline copy. */

import { $, esc, COL, toast } from "../util.js";
import { api } from "../api.js";

const MATCH_GATE_FT = 2;              // backend's LOCATION_MISMATCH gate
const OFFLINE_HINT = "Open Revit and enable the Nonica A.I. Connector";
const SUGGESTION_WORDS = {
  "lean-accept": "Likely false alarm — systematic drawing offset",
  "verify-then-accept": "Walk down and verify",
  "lean-reject": "Likely a real modeling discrepancy",
};

/* ---------------- cached connector status ---------------- */
let revitStatus = null, statusAt = 0;
async function connStatus() {
  if (revitStatus && Date.now() - statusAt < 15000) return revitStatus;
  try { revitStatus = await api("/api/revit/status"); }
  catch { revitStatus = { connected: false, reason: "status check failed" }; }
  statusAt = Date.now();
  return revitStatus;
}

/* Export freshness is a separate, cheap read (no exe spawn) — but it is
   feature-detected: a backend without it 404s and the pill degrades to the
   connector status alone. `false` is the cached "not deployed" answer. */
let exportStat = null, exportAt = 0;
async function exportStatus() {
  if (exportStat !== null && Date.now() - exportAt < 15000) return exportStat;
  try { exportStat = await api("/api/revit/export-status"); }
  catch { exportStat = false; }
  exportAt = Date.now();
  return exportStat;
}

const agoText = s => s < 90 ? `${Math.max(1, Math.round(s))}s ago`
  : s < 5400 ? `${Math.round(s / 60)}m ago`
  : `${Math.round(s / 3600)}h ago`;

/* Upload-card connection pill (§2). Same three states and the same
   .bw-revit-status visual the wizard renders — zero new CSS, and it goes
   through the 15s-cached connStatus() so opening the modal never spawns the
   Nonica exe on its own.
   ponytail: no "Check again" button — reopening the modal re-paints, and a
   manual re-check is exactly the uncached third caller the plan warns about. */
export async function paintRevitPill(sel) {
  const el = $(sel);
  if (!el) return;
  const s = await connStatus();
  // textContent, not esc()+innerHTML: it cannot interpolate markup at all, and
  // it renders "&" in a model title as "&" rather than "&amp;".
  if (!s.connected) {
    el.className = "bw-revit-status off";
    el.textContent = s.reason ? `${s.reason} — ${OFFLINE_HINT}` : OFFLINE_HINT;
    return;
  }
  const x = await exportStatus();
  el.className = "bw-revit-status on";
  if (x && x.synced) {
    el.textContent = "Model synced"
      + (x.age_s != null ? " · " + agoText(x.age_s) : "")
      + (x.model_title ? " · " + x.model_title : "");
  } else if (x) {
    el.textContent = "Connected — click Export QAQC in Revit";
  } else {
    el.textContent = "Revit connected" + (s.model_title ? " · " + s.model_title : "");
  }
}

/* ---------------- "Show in Revit" ---------------- */
/* Markup only — call wireRevitLive() after the innerHTML lands. */
export function showInRevitBtn(e) {
  if (e?.revit_ref?.kind !== "holdown_assembly") return "";
  return `<button class="btn revit-show" style="font-size:11px;padding:2px 8px"
    data-revit-asm="${esc(e.revit_ref.id)}">🎯 Show in Revit</button>`;
}

async function showInRevit(btn) {
  const label = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = "Selecting in Revit…";   // cold connector can take ~20s
  try {
    const r = await api("/api/revit/highlight", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ assembly_id: btn.dataset.revitAsm }),
    });
    if (r.ok) toast(r.note || "Selected in Revit — press BX in Revit to jump to it.");
    else toast("Revit: " + (r.reason || "nothing could be selected"), true);
    revitStatus = null;                       // response is fresher than the cache
  } catch (err) {
    toast("Show in Revit failed: " + err.message, true);
  }
  btn.disabled = false;
  btn.innerHTML = label;
}

async function paintRevitButtons(root) {
  const btns = [...root.querySelectorAll("[data-revit-asm]")];
  if (!btns.length) return;
  const s = await connStatus();
  for (const b of btns) {
    if (b.disabled && b.textContent === "Selecting in Revit…") continue;
    b.disabled = !s.connected;
    b.style.opacity = s.connected ? "" : ".45";
    b.title = s.connected ? "Select this assembly in the live model"
                          : (s.reason ? `${s.reason} — ${OFFLINE_HINT}` : OFFLINE_HINT);
  }
}

/* ---------------- "Why this verdict?" ---------------- */
export function whyBlock(e) {
  if (e?.status !== "LOCATION_MISMATCH" && e?.status !== "MATCH") return "";
  return `<details class="why-block" data-why="${esc(e.id || "")}" style="margin-top:14px">
    <summary style="cursor:pointer;color:var(--accent);font-size:12.5px">Why this verdict?</summary>
    <div class="why-body" style="margin-top:8px;font-size:12px;color:#cbd5e1">
      <span style="color:var(--dim)">opening…</span></div>
  </details>`;
}

const noAnalysis = (why) =>
  `<span style="color:var(--dim)">No geometric analysis available for this element${why ? " — " + esc(why) : ""}.</span>`;

/* Shared renderer for the analysis facts (why-block + lookup drawer). */
export function analysisHtml(a) {
  if (!a) return noAnalysis();
  const d = a.distance_ft;
  const dist = d == null ? "" :
    `<div>Offset is <b>${esc(d)} ft</b>${a.direction ? ` to the <b>${esc(a.direction)}</b>` : ""} —
      the MATCH gate is ${MATCH_GATE_FT} ft, so this is
      <b>${Number(d) > MATCH_GATE_FT ? "outside" : "inside"}</b> it.</div>`;
  const sys = a.systematic
    ? `<div style="margin-top:5px">${esc(a.aligned_peers)} of ${esc(a.peer_count)} other mismatches
        shifted the same way — likely a systematic drawing offset, not a modeling error.</div>`
    : (a.peer_count != null
      ? `<div style="margin-top:5px">Only ${esc(a.aligned_peers ?? 0)} of ${esc(a.peer_count)} other
          mismatches shift this way — this one looks isolated.</div>`
      : "");
  const key = String(a.suggestion || "").replace(/_/g, "-");
  const sug = SUGGESTION_WORDS[key];
  const verdict = a.suggestion
    ? `<div style="margin-top:7px"><b class="sys">Suggested next step:</b>
        ${esc(sug || a.suggestion)}</div>`
    : "";
  const finding = a.finding ? `<div style="margin-top:5px">${esc(a.finding)}</div>` : "";
  if (!dist && !sys && !verdict && !finding) return noAnalysis();
  return `<div class="ai-card">${dist}${finding}${sys}${verdict}</div>`;
}

async function loadWhy(det) {
  if (det.__loaded) return;
  det.__loaded = true;
  const body = det.querySelector(".why-body");
  const rowId = det.dataset.why;
  if (!rowId) { body.innerHTML = noAnalysis("no element id"); return; }
  body.innerHTML = `<span style="color:var(--dim)">reading the geometry…</span>`;
  try {
    const a = await api(`/api/review/${encodeURIComponent(rowId)}/analysis`);
    body.innerHTML = analysisHtml(a);
  } catch (err) {
    det.__loaded = false;                     // let the user retry by re-opening
    body.innerHTML = noAnalysis(err.message);
  }
}

/* ---------------- wiring (call after any innerHTML render) ---------------- */
export function wireRevitLive(root = document) {
  root.querySelectorAll("[data-revit-asm]").forEach(b => {
    if (b.__wired) return;
    b.__wired = true;
    b.onclick = () => showInRevit(b);
  });
  paintRevitButtons(root);
  root.querySelectorAll("details[data-why]").forEach(d => {
    if (d.__wired) return;
    d.__wired = true;
    d.addEventListener("toggle", () => { if (d.open) loadWhy(d); });
  });
}

/* ---------------- Revit ID lookup drawer ---------------- */
export async function initRevitLookup() {
  const s = await connStatus();
  const pill = $("#rl-status");
  if (pill) pill.textContent = s.connected
    ? "connected" + (s.model_title ? " · " + s.model_title : "")
    : (s.reason || "not connected");
  $("#rl-input")?.focus();
}

function lookupHtml(r) {
  // r.source is only set by /api/revit/selected-element — a live selection read
  // succeeded there even if the Nonica coordinate cache is cold.
  if (!r.connected && !r.source)
    return `<span style="color:var(--dim)">Revit is not connected — ${esc(r.reason || OFFLINE_HINT)}.</span>`;
  if (!r.found)
    return `<span style="color:var(--dim)">Element ${esc(r.element_id)} is not in the live model
      ${r.reason ? "— " + esc(r.reason) : ""}.</span>`;
  const dev = r.device, asm = r.assembly;
  const pill = dev?.status
    ? `<span class="status-pill" style="background:${COL[dev.status] || "#64748b"}22;color:${COL[dev.status] || "#64748b"}">${esc(dev.status).replaceAll("_", " ")}</span>`
    : "";
  const pt = p => p ? `(${esc(p[0] ?? p.x)}, ${esc(p[1] ?? p.y)})` : "—";
  return `
    <h3 style="margin:0 0 6px">Element ${esc(r.element_id)} ${pill}</h3>
    <div class="kv">
      ${r.family ? `<b>Family</b><span>${esc(r.family)}</span>` : ""}
      ${r.type ? `<b>Type</b><span>${esc(r.type)}</span>` : ""}
      ${r.category ? `<b>Category</b><span>${esc(r.category)}</span>` : ""}
      ${r.level ? `<b>Level</b><span>${esc(r.level)}</span>` : ""}
      <b>Live point</b><span>${pt(r.live_point)}</span>
      <b>Assembly</b><span style="word-break:break-all">${asm ? `${esc(asm.id)}${asm.mark_candidate ? " · " + esc(asm.mark_candidate) : ""}` : "—"}</span>
      <b>Assembly point</b><span>${pt(asm?.center_point)}</span>
      <b>Device</b><span style="word-break:break-all">${dev ? esc(dev.id) : "—"}</span>
      <b>Mark</b><span>${dev?.mark ? esc(dev.mark) : "—"}</span>
      <b>Distance</b><span>${dev?.distance_ft != null ? esc(dev.distance_ft) + " ft" : "—"}</span>
      <b>Sheets</b><span>${esc((dev?.sheets || []).join(", ")) || "—"}</span>
      <b>Appearances</b><span>${dev?.appearances != null ? esc(dev.appearances) : "—"}</span>
      <b>Reason</b><span>${esc(dev?.reason) || "—"}</span>
      ${asm?.classification_reason ? `<b>Classified</b><span>${esc(asm.classification_reason)}</span>` : ""}
    </div>
    ${r.source ? `<div style="margin-top:8px;font-size:11px;color:var(--dim)">Read via ${esc(r.source)}</div>` : ""}
    ${r.plain_english ? `<p style="font-size:12.5px;color:#cbd5e1;margin-top:12px">${esc(r.plain_english)}</p>` : ""}
    <div style="margin-top:10px">${analysisHtml(r.analysis)}</div>
    ${regQualityHtml(r.registration_quality, dev)}`;
}

/* One dim line: how trustworthy the transform behind this verdict is. */
function regQualityHtml(rq, dev) {
  const sheet = dev?.sheets?.[0];
  const q = rq && sheet ? rq[sheet] : null;
  if (!q || !q.source) return "";
  const rms = q.rms_residual_pt != null ? ` · RMS ${esc(q.rms_residual_pt)} pt` : "";
  return `<div style="margin-top:8px;font-size:11px;color:var(--dim)">
    Registration (${esc(sheet)}): ${esc(q.source)} · confidence ${esc(q.confidence || "?")}${rms}</div>`;
}

async function doLookup(id) {
  const body = $("#rl-body");
  if (!id) { body.innerHTML = `<span style="color:var(--dim)">Enter a Revit Element ID first.</span>`; return; }
  if (!/^\d+$/.test(String(id).trim())) {
    // Revit ElementIds are always integers — catch a pasted mark/device id
    // here instead of surfacing the backend's raw 422 validation error.
    body.innerHTML = `<span style="color:var(--dim)">"${esc(id)}" isn't a Revit Element ID —
      those are plain numbers (e.g. 5478428). In Revit: select the element and read the ID
      from Manage &gt; Inquiry &gt; IDs of Selection, or just click
      <b>Use current Revit selection</b> below.</span>`;
    return;
  }
  body.innerHTML = `<span style="color:var(--dim)">querying the live model…</span>`;
  try {
    const r = await api(`/api/revit/lookup/${encodeURIComponent(id)}`);
    body.innerHTML = lookupHtml(r);
    wireRevitLive(body);
  } catch (err) {
    body.innerHTML = `<span style="color:var(--revitonly)">Lookup failed — ${esc(err.message)}</span>`;
  }
}

if ($("#rl-go")) {
  $("#rl-go").onclick = () => doLookup($("#rl-input").value.trim());
  $("#rl-input").addEventListener("keydown", ev => { if (ev.key === "Enter") $("#rl-go").click(); });
  /* One round trip: the full selected element + its QA join. Falls back to the
     old two-step (/selection then /lookup) only if that endpoint itself errors. */
  $("#rl-selection").onclick = async () => {
    const body = $("#rl-body");
    body.innerHTML = `<span style="color:var(--dim)">reading the Revit selection…</span>`;
    try {
      const r = await api("/api/revit/selected-element");
      if (!r.ok) {
        body.innerHTML = `<span style="color:var(--dim)">${esc(r.reason || "Nothing selected in Revit — pick an element there first.")}</span>`;
        return;
      }
      $("#rl-input").value = r.element_id;
      body.innerHTML = lookupHtml(r);
      wireRevitLive(body);
      return;
    } catch (err) {
      body.innerHTML = `<span style="color:var(--dim)">selection endpoint unavailable (${esc(err.message)}) — retrying the older two-step read…</span>`;
    }
    try {
      const s = await api("/api/revit/selection");
      const id = (s.element_ids || [])[0];
      if (!s.ok || id == null) {
        body.innerHTML = `<span style="color:var(--dim)">${esc(s.reason || "Nothing selected in Revit — pick an element there first.")}</span>`;
        return;
      }
      $("#rl-input").value = id;
      doLookup(id);
    } catch (err) {
      body.innerHTML = `<span style="color:var(--revitonly)">Could not read the selection — ${esc(err.message)}</span>`;
    }
  };
}
