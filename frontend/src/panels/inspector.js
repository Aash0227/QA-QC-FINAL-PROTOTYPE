/* panels/inspector.js — the right-side drawer subsystem: evidence inspector,
   count-consistency, run comparison, and human review. Reacts to "select" to
   populate the inspector. The Chat drawer (§5) is a peer panel (panels/chat.js);
   this module owns the shared open/close manager for all of them.
   ponytail: the drawers share one module — one UI region (the drawer slot),
   one open/close manager. */

import gsap from "gsap";
import { $, esc, COL, CAT_LABEL, RUN_STATUSES, toast, reduceMotion } from "../util.js";
import { store, select, subscribe } from "../store.js";
import { api } from "../api.js";
import { loadAll } from "../app.js";
import { initChat } from "./chat.js";
import { showInRevitBtn, whyBlock, wireRevitLive, initRevitLookup } from "./revit_live.js";

/* ---------------- drawer manager ----------------
   Drawers are NOT modal: the panes behind stay live and readable, which is the
   whole point of having the drawing on screen while you judge a mismatch. So
   they get focus *management* (move in on open, hand back on close) rather than
   a focus trap — trapping would fight the deliberate drawer/wizard coexistence
   the smoke suite pins. Closed drawers are visibility:hidden, so they are
   already out of the tab order and the accessibility tree. */
const DRAWERS = ["inspector", "chat", "review", "runs", "revitlookup"];
let drawerReturnFocus = null;

function focusInto(id) {
  const el = $("#" + id);
  // The first thing you would reach for: an input if there is one, else the
  // close button. Never the drawer container — a focused div announces nothing.
  const target = el.querySelector("input:not([type=hidden]), textarea, select")
    || el.querySelector("button");
  target?.focus({ preventScroll: true });
}

export function openDrawer(name) {
  const opening = name && store.drawer !== name;
  if (opening) drawerReturnFocus = document.activeElement;
  store.drawer = name;
  for (const d of DRAWERS) {
    const el = $("#" + d);
    const on = d === name;
    el.classList.toggle("open", on);
    el.setAttribute("aria-hidden", String(!on));
  }
  if (name === "chat") initChat();
  if (name === "review") initReview();
  if (name === "runs") initRuns();
  if (name === "revitlookup") initRevitLookup();
  if (opening) focusInto(name);
  // Closing via this path (openDrawer(null)) hands focus back to whatever
  // opened the drawer, so keyboard users are not dumped at the top of the page.
  if (!name) { drawerReturnFocus?.focus?.(); drawerReturnFocus = null; }
}

document.querySelectorAll("[data-close]").forEach(b => b.onclick = () => {
  const id = b.dataset.close;
  const el = $("#" + id);
  el.classList.remove("open");
  el.setAttribute("aria-hidden", "true");
  if (store.drawer === id) store.drawer = null;
  drawerReturnFocus?.focus?.();
  drawerReturnFocus = null;
});
$("#btn-chat").onclick = () => openDrawer(store.drawer === "chat" ? null : "chat");
$("#btn-runs").onclick = () => openDrawer(store.drawer === "runs" ? null : "runs");
$("#btn-review").onclick = () => openDrawer(store.drawer === "review" ? null : "review");
$("#btn-revit-lookup").onclick = () => openDrawer(store.drawer === "revitlookup" ? null : "revitlookup");

/* ---------------- inspector + count consistency ---------------- */
export function renderInspector(e) {
  const spec = e.spec ? (e.spec.row_text || Object.values(e.spec).join(" · ")) : "—";
  const near = (e.nearest_revit_candidates || e.nearest_pdf_candidates || []).slice(0, 3)
    .map(n => `<div style="color:var(--dim)">↳ ${n.id || n.revit_assembly_id || n.pdf_holdown_id || "?"} · ${(n.distance_pdf_points ?? n.distance ?? "?")} pt</div>`).join("");
  $("#insp-body").innerHTML = `
    <h3 style="margin:0">${esc(e.mark) ?? ""} <span class="status-pill" style="background:${COL[e.status]}22;color:${COL[e.status]}">${e.status.replaceAll("_", " ")}</span></h3>
    <div class="kv">
      <b>ID</b><span style="word-break:break-all">${esc(e.id)}</span>
      <b>Category</b><span>${esc(CAT_LABEL[e.category] || e.category)}</span>
      <b>Sheet</b><span>${esc(e.sheet) || "—"}</span>
      <b>PDF point</b><span>${e.pdf_point ? `(${e.pdf_point.x.toFixed(1)}, ${e.pdf_point.y.toFixed(1)}) pt` : "—"}</span>
      <b>Distance</b><span>${e.distance_pdf_points != null ? e.distance_pdf_points + " pt" : "—"}</span>
      <b>Revit ref</b><span style="word-break:break-all">${e.revit_ref ? `${esc(e.revit_ref.kind)} · ${esc(e.revit_ref.id)}` : "none"}</span>
      ${e.revit_ref?.kind === "holdown_assembly" ? `<b>Revit ID</b><span id="insp-revit-id"><button class="btn" style="font-size:11px;padding:2px 8px" data-fetch-asm="${esc(e.revit_ref.id)}">⟳ fetch live ID</button></span>
      <b>Live model</b><span>${showInRevitBtn(e)}</span>` : ""}
      <b>In schedule</b><span>${e.schedule_listed ? "yes" : "NO"}</span>
      ${e.taught_by ? `<b>Taught</b><span>🧠 rule ${esc(e.taught_by)}</span>` : ""}
      <b>Spec</b><span>${esc(spec)}</span>
      <b>Reason</b><span>${esc(e.reason) || "—"}</span>
    </div>${near ? `<div style="margin-top:10px"><b style="color:var(--dim)">Nearest candidates</b>${near}</div>` : ""}
    ${whyBlock(e)}`;
  /* No inline onclick: esc() is an HTML escaper, and the HTML parser decodes
     &#39; back to ' before an inline handler compiles — a data- attribute plus
     a listener keeps the id in a string slot the parser never re-enters. */
  const fetchBtn = $("#insp-body").querySelector("[data-fetch-asm]");
  if (fetchBtn) fetchBtn.onclick = ev => window.__fetchRevitId(ev.currentTarget.dataset.fetchAsm);
  wireRevitLive($("#insp-body"));
}

/* Live Revit ElementId lookup (Nonica bridge) — QA copies the id into
   Revit's Manage > Inquiry > Select by ID to eyeball the device manually. */
window.__fetchRevitId = async (asmId) => {
  const el = $("#insp-revit-id");
  if (!el) return;
  el.innerHTML = `<span style="color:var(--dim)">querying live model…</span>`;
  try {
    const r = await api(`/api/revit/element-ids/${encodeURIComponent(asmId)}`);
    /* R-15: the bridge caches connection locations for 5 minutes. A cached
       answer must never read as a fresh look at the live model. */
    const age = r.live?.cached
      ? ` <small style="color:var(--locmis)">· as of ${esc(Math.round(r.live.age_s ?? 0))}s ago</small>`
      : "";
    const exportId = esc(r.export?.creation_element_ids?.[0] ?? "?");
    if (r.live?.connected && r.live.element_ids.length) {
      const id = esc(r.live.element_ids[0]);
      el.innerHTML = `<b style="color:var(--match)">${id}</b>
        <button class="btn" style="font-size:11px;padding:2px 8px" data-copy-id="${id}">copy</button>
        <small style="color:var(--dim)">${esc(r.live.distance_ft)} ft from export pt · Select by ID in Revit</small>${age}`;
      el.querySelector("[data-copy-id]").onclick =
        ev => navigator.clipboard.writeText(ev.currentTarget.dataset.copyId);
    } else if (r.live?.connected) {
      el.innerHTML = `<span style="color:var(--locmis)">no live device within 0.75 ft</span>
        <small style="color:var(--dim)">export id: ${exportId}</small>${age}`;
    } else {
      el.innerHTML = `<span style="color:var(--dim)">connector off · export id: ${exportId}</span>`;
    }
  } catch (err) {
    el.innerHTML = `<span style="color:var(--revitonly)">lookup failed</span>`;
    console.warn("revit id lookup:", err);
  }
};

export function renderCC() {
  const rows = (store.cc[store.activeSheet] || []).filter(r => r.category !== "wall_type");
  $("#cc-table").innerHTML = `<tr><th>Cat</th><th>Mark</th><th>Plan</th><th>Sched</th></tr>` +
    rows.map(r => `<tr><td>${esc(r.category.replace("_", " "))}</td><td>${esc(r.mark)}</td><td>${r.plan_count}</td>
      <td style="color:${r.schedule_listed ? "var(--match)" : "var(--revitonly)"}">${r.schedule_listed ? "✓" : "MISSING"}</td></tr>`).join("");
}

/* ---------------- run comparison ---------------- */
function runDelta(a, b) {
  const d = (b || 0) - (a || 0);
  if (!d) return "";
  return ` <small style="color:${d > 0 ? "#4ade80" : "#f87171"}">(${d > 0 ? "+" : ""}${d})</small>`;
}
async function initRuns() {
  const body = $("#runs-body");
  try {
    const r = await api("/api/runs/compare");
    $("#runs-label").textContent = r.project;
    const cats = [...new Set([...Object.keys(r.baseline.by_category),
                              ...Object.keys(r.current.by_category)])].sort();
    const row = (label, a, b, bold) => `<tr${bold ? ' style="font-weight:700"' : ""}>
      <td>${esc(label)}</td>` + RUN_STATUSES.map(s => {
        const av = a[s] || 0, bv = b[s] || 0;
        return `<td style="text-align:right">${esc(av)} → ${esc(bv)}${s === "MATCH" ? runDelta(av, bv) : ""}</td>`;
      }).join("") + "</tr>";
    body.innerHTML = `
      <p style="font-size:12px;color:var(--dim)">
        <b>${esc(r.baseline.label)}</b> (${esc(r.baseline.row_count)} rows, saved ${esc(String(r.baseline.saved_at || "").slice(0, 10))}) → <b>current run</b>
        (${esc(r.current.row_count)} rows). Every cell is honest — statuses are
        never rewritten, only re-measured.</p>
      <table style="width:100%;font-size:11px;border-collapse:collapse" class="runs-table">
        <tr style="color:var(--dim)"><th style="text-align:left">category</th>
          ${RUN_STATUSES.map(s => `<th style="text-align:right;padding:2px 4px">${
            s.replace("LOCATION_MISMATCH", "LOC_MIS").replace("NOT_IN_SCHEDULE", "NO_SCHED")
             .replace("NOT_EVALUATED", "NOT_EVAL").replace("NO_REVIT_DATA", "NO_DATA")}</th>`).join("")}</tr>
        ${cats.map(c => row(c, r.baseline.by_category[c] || {}, r.current.by_category[c] || {})).join("")}
        ${row("TOTAL", r.baseline.totals, r.current.totals, true)}
      </table>
      ${r.device_changes === null ? `<p style="font-size:11px;color:var(--dim);margin-top:10px">
          Per-device diff unavailable — ${esc(r.device_note || "")}.</p>`
        : (r.device_changes || []).length ? `<h4 style="margin:14px 0 4px">What changed</h4>
          <table style="width:100%;font-size:11px;border-collapse:collapse" class="runs-table">
            ${r.device_changes.map(c => `<tr><td>${esc(c.key)}</td>
              <td style="color:${COL[c.old_status] || "#94a3b8"}">${esc(c.old_status).replaceAll("_", " ")}</td>
              <td>→</td><td style="color:${COL[c.new_status] || "#94a3b8"}">${esc(c.new_status).replaceAll("_", " ")}</td>
              <td style="text-align:right">${c.old_distance_ft ?? "—"} → ${c.new_distance_ft ?? "—"} ft</td>
            </tr>`).join("")}
          </table>` : `<p style="font-size:11px;color:var(--dim);margin-top:10px">No device changed status.</p>`}
      <style>.runs-table td{padding:3px 4px;border-top:1px solid #1c2740}</style>`;
  } catch (e) {
    body.innerHTML = `<span style="color:var(--dim)">No baseline saved for this
      project yet. Run the pipeline, then press “Save as baseline” — the next
      run will compare against it.</span>`;
    $("#runs-label").textContent = "no baseline";
  }
  $("#runs-save-baseline").onclick = async () => {
    const label = prompt("Label for this baseline:", "current run");
    if (!label) return;
    await api(`/api/runs/baseline?label=${encodeURIComponent(label)}`, { method: "POST" });
    toast(`Baseline “${label}” saved.`); initRuns();
  };
}

/* ---------------- human review workspace ---------------- */
/* M4 — the header CTA carries the queue size, so a change in it has to be seen.
   One-shot scale pop, only when the number actually moved. */
function setRevCount(n) {
  const el = $("#rev-count");
  if (!el) return;
  const changed = el.textContent !== String(n);
  el.textContent = n;
  if (changed && !reduceMotion())
    gsap.fromTo(el, { scale: 1.35 },
      { scale: 1, duration: .35, ease: "back.out(2)", transformOrigin: "50% 50%" });
}

let revQueue = null, revCurrent = null;
/* One shared queue fetch: the boot badge and a drawer opened right after boot
   reuse the same in-flight/very-recent request instead of hitting
   /api/review/queue twice. Older than 10 s = refetch, so the drawer never
   serves stale queue state. */
let revQP = null, revQAt = 0;
function fetchQueue() {
  if (revQP && Date.now() - revQAt < 10000) return revQP;
  revQAt = Date.now();
  revQP = api("/api/review/queue").catch(e => { revQP = null; throw e; });
  return revQP;
}
async function initReview() {
  try { revQueue = await fetchQueue(); }
  catch (e) { $("#rev-list").innerHTML = `<span style="color:var(--dim)">${e.message}</span>`; return; }
  $("#rev-progress").textContent = `${revQueue.reviewed} of ${revQueue.total} reviewed`;
  setRevCount(revQueue.total - revQueue.reviewed);
  $("#rev-detail").style.display = "none";
  $("#rev-list").style.display = "block";
  $("#rev-list").innerHTML = revQueue.items.length ? revQueue.items.map((it, i) => {
    const e = it.element;
    const d = e.distance_pdf_points ? ` · ${e.distance_pdf_points.toFixed(1)}pt off` : "";
    const done = it.disposition ? ` <span class="badge">✓ ${it.disposition}</span>` : "";
    return `<div class="row" data-rev="${i}" style="cursor:pointer">
      <b>${e.mark || "?"}</b> ${e.category.replace("_", " ")} · ${e.sheet || "—"} ·
      <span style="color:${e.status === "LOCATION_MISMATCH" ? "var(--warn)" : "#94a3b8"}">${e.status}</span>${d}${done}
      ${it.comments.length ? ` · 💬${it.comments.length}` : ""}
    </div>`;
  }).join("") : `<span style="color:var(--dim)">Nothing needs review — no LOCATION_MISMATCH or NEEDS_REVIEW elements. 🎉</span>`;
  $("#rev-list").querySelectorAll("[data-rev]").forEach(r =>
    r.onclick = () => openReviewItem(+r.dataset.rev));
}
function openReviewItem(i) {
  revCurrent = revQueue.items[i];
  const e = revCurrent.element;
  $("#rev-list").style.display = "none";
  $("#rev-detail").style.display = "block";
  $("#rev-head").innerHTML = `<b style="font-size:15px">${e.mark} · ${e.status}</b><br>
    <span style="color:var(--dim);font-size:12px">${e.category.replace("_", " ")} · sheet ${e.sheet || "—"} · id ${e.id}</span>
    <div style="margin-top:8px">${showInRevitBtn(e)}</div>`;
  wireRevitLive($("#rev-head"));
  $("#rev-crop").src = `/api/review/${encodeURIComponent(e.id)}/evidence.png?t=${Math.random()}`;
  $("#rev-crop").onerror = () => { $("#rev-crop").style.display = "none"; };
  const dist = e.distance_pdf_points ? `The two positions are <b>${e.distance_pdf_points.toFixed(1)} pt apart</b> (MATCH needs ≤16pt). ` : "";
  $("#rev-why").innerHTML = `${dist}${esc(e.reason || "")}`;
  $("#rev-verdict").innerHTML = "";
  if (e.resolution) {
    $("#rev-ai").innerHTML = `<span class="resolved-chip">✓ ${e.resolution.action === "accept" ? "Accepted as MATCH" : "Rejected"} by ${esc(e.resolution.author || "reviewer")}</span>
      <div style="font-size:11px;color:var(--dim);margin-top:4px">${esc(e.resolution.comment || "")} · was ${e.resolution.original_status} (${e.resolution.distance_ft ?? "?"} ft)</div>`;
  } else {
    $("#rev-ai").innerHTML = `<div class="ai-card">🤖 analyzing…</div>`;
    api(`/api/review/${encodeURIComponent(e.id)}/analysis`).then(a => {
      if (revCurrent?.element?.id !== e.id) return;
      $("#rev-ai").innerHTML = a.analysis_available ? `<div class="ai-card">
        <b class="sys">🤖 AI analysis (deterministic)</b><br>${esc(a.finding)}
        <div style="margin-top:6px;color:var(--dim)">offset ${a.distance_ft} ft ${a.direction}
          · ${a.systematic ? `systematic (${a.aligned_peers}/${a.peer_count} peers move together)` : "isolated"}
          · sheets: ${(a.sheets || []).join(", ")}</div>
        <div style="margin-top:6px;color:#94a3b8">Add your reasoning below — the AI will check it against these numbers, then you accept or reject.</div>
      </div>` : `<div class="ai-card">${esc(a.note || "No analysis for this element.")}</div>`;
    }).catch(() => { $("#rev-ai").innerHTML = ""; });
  }
  renderThread();
  select(e.id, "review");
  document.querySelectorAll("[data-disp]").forEach(b => b.onclick = async () => {
    try {
      await api(`/api/review/${encodeURIComponent(e.id)}/disposition`, { method: "POST",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ disposition: b.dataset.disp }) });
      toast(`Marked ${e.mark} as ${b.dataset.disp}. Status stays honest — the punch list shows both.`);
      revCurrent.disposition = b.dataset.disp;
    } catch (err) { toast(err.message, true); }
  });
}
function renderThread() {
  $("#rev-thread").innerHTML = (revCurrent.comments || []).map(c => `
    <div style="margin:8px 0;font-size:12px">
      <div><b>${esc(c.author)}</b>: ${esc(c.comment)}</div>
      <div style="color:#7dd3fc;margin-top:3px">🤖 ${esc(c.ai_reply || "")}
        ${c.derived_rule_id && c.derived_rule_kind !== "note" ? '<span class="badge">🧠 rule saved to memory</span>' : ""}</div>
    </div>`).join("") || `<span style="color:var(--dim);font-size:12px">No comments yet.</span>`;
}
$("#rev-back").onclick = () => initReview();
/* #rev-investigate (a copy-a-prompt-for-Claude button) was removed with its
   handler — pure developer affordance, UI plan §1e. */
async function sendReviewComment() {
  const input = $("#rev-comment");
  const text = input.value.trim();
  if (!text || !revCurrent) return;
  const e = revCurrent.element;
  if (e.status === "LOCATION_MISMATCH" && !e.resolution) {
    input.value = "";
    $("#rev-verdict").innerHTML = `<div class="ai-card">🤖 checking your logic against the measurements…</div>`;
    try {
      const r = await api(`/api/review/${encodeURIComponent(e.id)}/evaluate`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ comment: text }) });
      const v = r.verdict;
      $("#rev-verdict").innerHTML = `<div class="ai-card">
        <b class="sys">🤖 AI on your reasoning:</b> ${v.agrees === true ? "✅ consistent with the numbers" : v.agrees === false ? "⚠ tension with the numbers" : "ℹ"}<br>
        ${esc(v.reasoning || "")}
        <div class="resolve-row">
          <button class="resolve-btn resolve-accept" id="rv-accept">✓ Accept — mark MATCH everywhere</button>
          <button class="resolve-btn resolve-reject" id="rv-reject">✕ Reject — keep as mismatch</button>
        </div></div>`;
      const decide = async (action) => {
        $("#rev-verdict").innerHTML = `<div class="ai-card">applying…</div>`;
        try {
          const out = await api(`/api/review/${encodeURIComponent(e.id)}/resolve`,
            { method: "POST", headers: { "Content-Type": "application/json" },
             body: JSON.stringify({ action, comment: text }) });
          toast(action === "accept"
            ? `✅ Accepted — ${out.updated_element_ids.length} appearance(s) now MATCH in the list, PDF and 3D. Rule saved to memory.`
            : "Rejected — stays a real mismatch on the punch list.");
          await loadAll(); openDrawer("review");
        } catch (err) { toast(err.message, true); }
      };
      $("#rv-accept").onclick = () => decide("accept");
      $("#rv-reject").onclick = () => decide("reject");
    } catch (err) { $("#rev-verdict").innerHTML = ""; toast("Evaluate failed: " + err.message, true); }
    return;
  }
  input.value = "";
  try {
    const r = await api(`/api/review/${encodeURIComponent(e.id)}/comment`,
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ comment: text }) });
    revCurrent.comments = revCurrent.comments || [];
    revCurrent.comments.push(r.comment);
    renderThread();
    if (r.comment.derived_rule_id && r.comment.derived_rule_kind !== "note")
      toast("🧠 Rule saved to global memory — re-run Extract to apply it (works on future projects too).");
  } catch (e) { toast("Comment failed: " + e.message, true); }
}
$("#rev-send").onclick = sendReviewComment;
$("#rev-comment").addEventListener("keydown", ev => { if (ev.key === "Enter") sendReviewComment(); });
// review badge on load — shares fetchQueue() with initReview so a boot that
// is followed by opening the review drawer does NOT hit the queue twice.
(async () => {
  try { const q = await fetchQueue(); setRevCount(q.total - q.reviewed); } catch { }
})();

/* ---------------- selection reaction ---------------- */
subscribe("select", ({ element: e }) => {
  if (!e) return;
  if (!e.pdf_point && !e.revit_point_transformed_to_pdf && !e.wall_segment_pdf)
    toast(e.status === "REVIT_ONLY" ? "Not drawable on the PDF — Revit-side only." :
      e.status === "SPEC_ONLY" ? "Schedule spec row — no plan location." :
      "No coordinates for this element (never faked).");
  renderInspector(e);
  // Inspector stays closed unless already open (it covers the 3D pane). A
  // glowing info-ball flies to the element in the 3D scene instead.
  if (store.drawer !== "inspector") toast("ℹ Click the glowing ball in the 3D model for details.");
});
