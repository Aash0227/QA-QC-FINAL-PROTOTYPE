/* util.js — DOM helpers, escaping, toasts, and the app-wide constants.
   Shared by every panel; imports nothing but gsap (leaf module). */

import gsap from "gsap";

export const $ = s => document.querySelector(s);
export const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* The global CSS kill-switch in tokens.css does not reach GSAP. Anything that
   loops forever or is purely decorative checks this first (UI plan §7.3).
   Read live, not cached: the OS setting can flip mid-session. */
export const reduceMotion = () =>
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;

export function toast(msg, err = false) {
  const d = document.createElement("div");
  d.className = "toast" + (err ? " err" : "");
  d.textContent = msg;
  $("#toast-box").appendChild(d);
  gsap.from(d, { y: 16, opacity: 0, duration: .3 });
  setTimeout(() => gsap.to(d, { opacity: 0, duration: .4, onComplete: () => d.remove() }), 4600);
}

/* Status legend colors — semantic, documented baselines (left alone, §7). */
export const COL = {
  MATCH: "#22c55e", LOCATION_MISMATCH: "#f59e0b", MARK_MISMATCH: "#e879f9", PDF_ONLY: "#3b82f6",
  REVIT_ONLY: "#ef4444", NEEDS_REVIEW: "#a78bfa", NO_REVIT_DATA: "#94a3b8",
  NOT_IN_SCHEDULE: "#e879f9", NOT_EVALUATED: "#475569", SPEC_ONLY: "#64748b",
};
/* A glyph per status, so a verdict is never conveyed by colour alone (UI plan
   §4). Rows already carry the status as text; these cover the places that only
   had a coloured dot — the category/mark count bars. Chosen to be legible at
   9px and to survive a monochrome print of a punch list. */
export const GLYPH = {
  MATCH: "✓", LOCATION_MISMATCH: "↔", MARK_MISMATCH: "≠", PDF_ONLY: "P",
  REVIT_ONLY: "R", NEEDS_REVIEW: "?", NO_REVIT_DATA: "–",
  NOT_IN_SCHEDULE: "!", NOT_EVALUATED: "·", SPEC_ONLY: "S",
};

/* "LOCATION_MISMATCH" -> "location mismatch". Used wherever a status is shown
   to a human; the raw token stays the value we compare on. */
export const statusLabel = s => String(s ?? "").replaceAll("_", " ").toLowerCase();

export const CATS = ["holdown", "shear_wall", "post", "steel_column", "wall_type"];
export const CAT_LABEL = { holdown: "Hold-downs", shear_wall: "Shear walls", post: "Posts", steel_column: "Steel columns", wall_type: "Wall types" };
export const DEFAULT_LAYERS = new Set(Object.keys(COL).filter(s => s !== "NOT_EVALUATED" && s !== "SPEC_ONLY"));
export const BENCHMARK_COLOR = "#ff6a00";
export const RUN_STATUSES = ["MATCH", "LOCATION_MISMATCH", "MARK_MISMATCH", "PDF_ONLY", "REVIT_ONLY",
  "NOT_IN_SCHEDULE", "NOT_EVALUATED", "NO_REVIT_DATA", "SPEC_ONLY"];
