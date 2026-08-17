/* panels/chat.js — the agentic chatbot (production-plan §5), living in the
   right-side drawer slot the Teach drawer used to occupy. Sends messages to
   POST /api/chat, renders the structured blocks (count_card / table /
   status_breakdown) reusing the app's pill + table classes, and executes the
   bot's ui_actions (select an element so all panes fly to it, apply a filter,
   open a view). Teaching now happens conversationally via save_teach_rule. */

import gsap from "gsap";
import { $, esc, COL, toast } from "../util.js";
import { store, select } from "../store.js";
import { api } from "../api.js";
import { renderList } from "./list.js";

const history = [];          // {role, content} — trimmed context for the model
let started = false;

/* ---------------- message bubbles ---------------- */
function bubble(who, html) {
  const d = document.createElement("div");
  d.className = `msg ${who}`;
  d.innerHTML = html;
  $("#chat-log").appendChild(d);
  gsap.from(d, { y: 10, opacity: 0, duration: .3 });
  d.scrollIntoView({ block: "nearest", behavior: "smooth" });
  return d;
}

/* ---------------- block renderers ---------------- */
function statusPill(status, n) {
  const c = COL[status] || "var(--dim)";
  return `<span class="status-pill" style="background:${c}22;color:${c}">${
    esc(status.replaceAll("_", " "))}${n != null ? ` · ${n}` : ""}</span>`;
}

function renderBlock(b) {
  if (b.type === "count_card") {
    const cats = Object.entries(b.by_category || {})
      .map(([k, v]) => `${esc(k.replace("_", " "))} <b>${v}</b>`).join(" · ");
    return `<div class="chat-card"><div class="chat-card-num">${b.total}</div>
      <div class="chat-card-lbl">${esc(b.label || "elements")}</div>
      ${cats ? `<div class="chat-card-sub">${cats}</div>` : ""}</div>`;
  }
  if (b.type === "status_breakdown") {
    const pills = Object.entries(b.by_status || {})
      .map(([s, n]) => statusPill(s, n)).join(" ");
    return `<div class="chat-block">${b.title ? `<b>${esc(b.title)}</b><br>` : ""}${
      pills || `<span style="color:var(--dim)">no data</span>`}</div>`;
  }
  if (b.type === "table") {
    const cols = b.columns || [];
    const head = cols.map(c => `<th>${esc(c)}</th>`).join("");
    const body = (b.rows || []).map(r => {
      const cells = cols.map(c => {
        let v = r[c];
        if (c === "status" && typeof v === "string") return `<td>${statusPill(v)}</td>`;
        return `<td>${v == null ? "—" : esc(String(v))}</td>`;
      }).join("");
      return `<tr${r.id ? ` data-el="${esc(r.id)}" style="cursor:pointer"` : ""}>${cells}</tr>`;
    }).join("");
    const more = (b.total != null && b.shown != null && b.total > b.shown)
      ? `<div class="chat-card-sub">Showing ${b.shown} of ${b.total}.</div>` : "";
    return `<div class="chat-block">${b.title ? `<b>${esc(b.title)}</b>` : ""}
      <table class="chat-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>${more}</div>`;
  }
  return "";
}

function renderBlocks(container, blocks) {
  for (const b of blocks || []) {
    const wrap = document.createElement("div");
    wrap.className = "msg ai";
    wrap.innerHTML = renderBlock(b);
    $("#chat-log").appendChild(wrap);
    wrap.querySelectorAll("[data-el]").forEach(tr =>
      tr.onclick = () => select(tr.dataset.el, "chat"));
    wrap.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
}

/* ---------------- ui_action executor (the "agentic" half) ---------------- */
function openPanel(panel) {
  if (panel === "table") {
    const p = $("#table-panel");
    if (p && p.classList.contains("hidden")) $("#btn-table").click();
    return;
  }
  const btn = { review: "#btn-review", runs: "#btn-runs",
                autopilot: "#btn-autopilot" }[panel];
  const el = btn && $(btn);
  if (el) el.click();
}

function applyUiAction(a) {
  if (!a || !a.type) return;
  if (a.type === "select" && a.element_id) {
    select(a.element_id, "chat");
  } else if (a.type === "filter" && a.filters) {
    Object.assign(store.filters, { search: "", status: "", sheet: "" }, a.filters);
    const map = { search: "#search", status: "#status-filter", sheet: "#sheet-filter" };
    for (const [k, sel] of Object.entries(map)) {
      const inp = $(sel); if (inp) inp.value = store.filters[k] || "";
    }
    renderList();
  } else if (a.type === "open_panel" && a.panel) {
    openPanel(a.panel);
  }
}

/* ---------------- unrecognized aggregate (BUG-10: ONE card, expandable) ---- */
async function loadUnknownCard() {
  let items = [];
  try { items = (await api("/api/teach/unrecognized")).items || []; } catch { return; }
  if (!items.length) return;
  const detail = items.map(it => `<div class="unk-row">⚠ ${esc(it.hint || it.type)}</div>`).join("");
  const card = bubble("ai",
    `<b>${items.length} thing${items.length !== 1 ? "s" : ""} I couldn't recognize</b> in this
     drawing set. <button class="mini" data-unk-toggle>Show details</button>
     <div class="unk-detail" style="display:none;margin-top:8px">${detail}</div>
     <div class="chat-card-sub">Teach me one ("HD3 means H3") and I'll re-extract.</div>`);
  const btn = card.querySelector("[data-unk-toggle]");
  const box = card.querySelector(".unk-detail");
  btn.onclick = () => {
    const open = box.style.display === "none";
    box.style.display = open ? "block" : "none";
    btn.textContent = open ? "Hide details" : "Show details";
  };
}

/* ---------------- send ---------------- */
async function send() {
  const inp = $("#chat-input");
  const msg = (inp.value || "").trim();
  if (!msg) return;
  inp.value = "";
  bubble("me", esc(msg));
  history.push({ role: "user", content: msg });
  const typing = bubble("ai", `<span class="typing"><i></i><i></i><i></i></span>`);
  try {
    const r = await api("/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: msg, history: history.slice(-8) }),
    });
    typing.innerHTML = esc(r.reply || "");
    history.push({ role: "assistant", content: r.reply || "" });
    renderBlocks(null, r.blocks);
    for (const a of r.ui_actions || []) applyUiAction(a);
  } catch (e) {
    typing.innerHTML = "Something went wrong: " + esc(e.message);
  }
}

/* ---------------- init (called by the drawer manager on first open) -------- */
export function initChat() {
  if (started) return;
  started = true;
  bubble("ai",
    `Hi — I'm the QA-QC copilot. Ask me things like "how many holdowns?",
     "what's PDF-only on the foundation plan?", or "highlight H2". I can re-run extract/match/
     compare and remember client conventions ("HD3 means H3").`);
  loadUnknownCard();
}

$("#chat-send").onclick = send;
$("#chat-input").addEventListener("keydown", ev => { if (ev.key === "Enter") send(); });
