/* panels/inspector.js — the right-side drawer subsystem: evidence inspector,
   count-consistency, run comparison, and human review. Reacts to "select" to
   populate the inspector. The Chat drawer (§5) is a peer panel (panels/chat.js);
   this module owns the shared open/close manager for all of them.
   ponytail: the drawers share one module — one UI region (the drawer slot),
   one open/close manager. */

import gsap from "gsap";
import { $, esc, COL, CAT_LABEL, RUN_STATUSES, toast, reduceMotion } from "../util.js";
import { store, select, subscribe, emit } from "../store.js";
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
  if (name === "review") window.dispatchEvent(new CustomEvent("open-review-drawer"));
  if (name === "runs") window.dispatchEvent(new CustomEvent("runs-init"));
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

/* ---------------- inspector + count consistency ----------------
   Rendering moved to react/features/inspector/{Inspector,CountConsistency}.tsx
   (mounted into #insp-body / #cc-table). renderCC() stays exported as a
   bridge (emit("refresh")) because panels/pdf.js calls it directly after
   showSheet() loads a new sheet — same pattern as renderList()/renderTable()
   in panels/list.js/table.js (Stage 2). The React Inspector subscribes to
   "select" directly, so no bridge is needed for it. */
export function renderCC() {
  emit("refresh");
}

/* ---------------- run comparison ----------------
   Rendering moved to react/features/inspector/RunsComparison.tsx, mounted
   into #runs-body. openDrawer('runs') now dispatches a "runs-init" window
   event instead of calling initRuns() directly — see this file's
   openDrawer() above and RunsComparison.tsx's listener. */

/* ---------------- human review workspace ----------------
   Rendering moved to react/features/inspector/ReviewWorkspace.tsx, mounted
   directly into #rev-body (which now owns #rev-list/#rev-detail/#rev-back/
   #rev-comment/#rev-send as React-rendered elements with the same ids).
   openDrawer('review') dispatches "open-review-drawer" instead of calling
   initReview() directly. The boot-time badge fetch also moved into
   ReviewWorkspace.tsx's module scope (runs once on import, same as before). */

/* ---------------- selection reaction ---------------- */
subscribe("select", ({ element: e }) => {
  if (!e) return;
  if (!e.pdf_point && !e.revit_point_transformed_to_pdf && !e.wall_segment_pdf)
    toast(e.status === "REVIT_ONLY" ? "Not drawable on the PDF — Revit-side only." :
      e.status === "SPEC_ONLY" ? "Schedule spec row — no plan location." :
      "No coordinates for this element (never faked).");
  // Inspector rendering itself is now react/features/inspector/Inspector.tsx,
  // which subscribes to "select" directly.
  // Inspector stays closed unless already open (it covers the 3D pane). A
  // glowing info-ball flies to the element in the 3D scene instead.
  if (store.drawer !== "inspector") toast("ℹ Click the glowing ball in the 3D model for details.");
});
