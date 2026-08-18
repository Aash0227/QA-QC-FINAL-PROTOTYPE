import { useState } from "react";

import { store, emit } from "../../../store";
import { VerdictBar } from "../verdict/VerdictBadge";

import { useStoreVersion } from "./useStoreVersion";

interface ScopeWarning {
  message: string;
  pdf_count: number;
  revit_count: number;
  export_view?: string;
}

/** R-07: a category with PDF callouts but zero Revit targets means the
 *  export view probably hid it -- say so above the verdicts instead of
 *  letting the PDF_ONLY rows accuse the modeller. Display-only, dismissible.
 *  Ported from panels/table.js::renderScopeBanner(). Mounted into the
 *  existing #scope-banner div. */
export function ScopeBanner() {
  useStoreVersion("refresh");
  const [dismissed, setDismissed] = useState(false);

  const warns = (dismissed ? [] : (store.scopeWarnings as ScopeWarning[]) || []);
  const counts = (store as Record<string, unknown>).productCounts as Record<string, number> | null;

  // The verdict bar is the first thing a reviewer should see: how many
  // elements the system could answer for, and how many it is handing back.
  // Clicking a segment filters the list to that verdict.
  const verdictBar = counts ? (
    <div style={{ margin: "10px 10px 12px" }}>
      <VerdictBar
        counts={counts}
        selected={(store as Record<string, unknown>).verdictFilter as string | null}
        onSelect={(v) => {
          (store as Record<string, unknown>).verdictFilter = v;
          emit("refresh");
        }}
      />
    </div>
  ) : null;

  if (!warns.length) return verdictBar;

  return (
    <>
      {verdictBar}
    <div
      style={{
        margin: "8px 10px",
        padding: "8px 10px",
        borderRadius: 8,
        border: "1px solid #b4530044",
        background: "#3a250855",
        color: "var(--warn)",
        fontSize: 12,
      }}
    >
      <b>⚠ Export scope</b>
      <button className="mini" style={{ float: "right" }} onClick={() => setDismissed(true)}>
        Dismiss
      </button>
      {warns.map((w, i) => (
        <div key={i} style={{ marginTop: 4 }}>
          {w.message}{" "}
          <span style={{ color: "var(--dim)" }}>
            ({w.pdf_count} PDF callouts, {w.revit_count} Revit targets
            {w.export_view ? ` · export view "${w.export_view}"` : ""})
          </span>
        </div>
      ))}
    </div>
    </>
  );
}
