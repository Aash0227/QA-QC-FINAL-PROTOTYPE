/* panels/wizard.js — compatibility shim (frontend migration).
   The Benchmark Autopilot wizard is now rendered by
   react/features/benchmark-wizard/Wizard.tsx (mounted into the existing
   #bm-rail/#bm-cards/#bm-log) and its approval banner by WizardBanner
   (mounted into a new #wizard-banner-root placed before #main in index.html).

   This file keeps only the #bmwizard open/close class toggle -- the same
   show/hide-by-class contract used throughout the app (#projects, #table-panel)
   -- since Wizard.tsx doesn't own #bmwizard itself, only its inner containers.
   "wizard-open"/"wizard-close" window events tell the React component when to
   fetch/poll, matching the pattern used for #chat-log and #rev-body. */

import { $ } from "../util.js";

$("#btn-autopilot").onclick = () => {
  $("#bmwizard").classList.add("open");
  window.dispatchEvent(new CustomEvent("wizard-open"));
};
$("#bm-close").onclick = () => {
  $("#bmwizard").classList.remove("open");
  window.dispatchEvent(new CustomEvent("wizard-close"));
};
