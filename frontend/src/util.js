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

/* The toast host is created on demand rather than assumed to exist.
   #toast-box was only in index.html, so every toast() call from the pipeline
   page threw "Cannot read properties of null (reading 'appendChild')" — which
   meant a user clicking Report on a project with no results got SILENCE
   instead of the explanation the code was trying to give them. Creating it
   lazily fixes every caller on every page at once, rather than adding the
   markup to one more HTML file and waiting for the next page to hit this. */
function toastHost() {
  let host = document.getElementById("toast-box");
  if (!host) {
    host = document.createElement("div");
    host.id = "toast-box";
    /* Positioning is applied inline ONLY on the host we create. #toast-box is
       styled in app.css, which the pipeline page does not load; a page that
       already ships the element keeps its own styling untouched. */
    Object.assign(host.style, {
      position: "fixed", bottom: "18px", left: "50%",
      transform: "translateX(-50%)", display: "flex",
      flexDirection: "column", gap: "8px", zIndex: "200",
      pointerEvents: "none",
    });
    document.body.appendChild(host);
  }
  return host;
}

export function toast(msg, err = false) {
  const d = document.createElement("div");
  d.className = "toast" + (err ? " err" : "");
  d.textContent = msg;
  const host = toastHost();
  host.appendChild(d);
  /* Fallback styling, applied AFTER insertion so computed style reflects any
     stylesheet the page actually loaded. app.css styles .toast on the
     dashboard; the pipeline page loads a different stylesheet entirely, and an
     unstyled message is barely better than the silence this replaced. */
  if (getComputedStyle(d).borderRadius === "0px") {
    Object.assign(d.style, {
      background: "rgba(15,23,42,.96)",
      border: "1px solid " + (err ? "#ef4444" : "rgba(255,255,255,.14)"),
      borderRadius: "11px", padding: "9px 18px", fontSize: "12.5px",
      color: "#e6edf3", pointerEvents: "auto",
    });
  }
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

/* ---------------------------------------------------------------------------
   PRODUCT VERDICTS — what a QA engineer actually reads.

   The engine reasons in ten internal statuses (COL above); the product speaks
   four. matching_engine.product_verdict() does the collapse on the backend and
   stamps `product` on every element row, so nothing here re-derives it — these
   are only the labels and colours for rendering what the backend decided.

   Colours are contrast-checked on the #0B0D10 ground (design direction §2) and
   are deliberately NOT cyan: cyan means "you can click this", a verdict colour
   means "the engine decided this". Every verdict also carries a glyph so a
   result is never conveyed by colour alone.
--------------------------------------------------------------------------- */
export const VERDICTS = ["LOCATION_MATCH", "LOCATION_MISMATCH", "NEEDS_REVIEW", "NOT_APPLICABLE"];

export const VERDICT_COL = {
  LOCATION_MATCH: "#34D399",     // 10.4:1
  LOCATION_MISMATCH: "#FF5A36",  //  6.3:1
  NEEDS_REVIEW: "#FBBF24",       // 11.6:1
  NOT_APPLICABLE: "#8A93A0",     //  6.3:1
};

export const VERDICT_GLYPH = {
  LOCATION_MATCH: "✓", LOCATION_MISMATCH: "✕",
  NEEDS_REVIEW: "?", NOT_APPLICABLE: "–",
};

export const VERDICT_LABEL = {
  LOCATION_MATCH: "Match",
  LOCATION_MISMATCH: "Mismatch",
  NEEDS_REVIEW: "Needs review",
  NOT_APPLICABLE: "Not applicable",
};

/* Longer-form copy for tooltips/empty states — says what the verdict MEANS to
   a reviewer, not what the engine did internally. */
export const VERDICT_HELP = {
  LOCATION_MATCH: "The drawing and the model agree on where this element is.",
  LOCATION_MISMATCH: "An established discrepancy — wrong place, wrong mark, drawn but not modelled, or modelled but not drawn.",
  NEEDS_REVIEW: "The engine could not settle this one and refused to guess. A human decision is needed.",
  NOT_APPLICABLE: "Out of scope — the model export never included this category, so no location verdict is possible.",
};

/* The verdict for a row, read from the backend's `product` block. Falls back to
   the row's own product_verdict field, then to NEEDS_REVIEW — never guesses a
   MATCH for a row whose verdict is missing. */
export const rowVerdict = row =>
  row?.product?.verdict || row?.product_verdict || "NEEDS_REVIEW";

export const CATS = ["holdown", "shear_wall", "post", "steel_column", "wall_type"];
export const CAT_LABEL = { holdown: "Hold-downs", shear_wall: "Shear walls", post: "Posts", steel_column: "Steel columns", wall_type: "Wall types" };
export const DEFAULT_LAYERS = new Set(Object.keys(COL).filter(s => s !== "NOT_EVALUATED" && s !== "SPEC_ONLY"));
export const BENCHMARK_COLOR = "#ff6a00";
export const RUN_STATUSES = ["MATCH", "LOCATION_MISMATCH", "MARK_MISMATCH", "PDF_ONLY", "REVIT_ONLY",
  "NOT_IN_SCHEDULE", "NOT_EVALUATED", "NO_REVIT_DATA", "SPEC_ONLY"];
