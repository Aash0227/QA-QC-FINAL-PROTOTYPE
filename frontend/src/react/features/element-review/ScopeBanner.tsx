import { useState } from "react";

import { store } from "../../../store";

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

  if (!warns.length) return null;

  return (
    <>
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
