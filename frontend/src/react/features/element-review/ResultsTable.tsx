import { rowVerdict } from "../../../util.js";
import { VerdictBadge } from "../verdict/VerdictBadge";
import { store, select } from "../../../store";

import { visibleElements } from "./elements";
import type { ElementRow } from "./types";
import { useStoreVersion } from "./useStoreVersion";


/** React port of panels/table.js's renderTable() row-building. Mounted
 *  directly into the existing #results-tbody (a <tbody>, so this renders
 *  bare <tr> children into it -- see react/dashboard-main.tsx). Column
 *  sort-header clicks, and the show/hide toggle buttons, stay in
 *  panels/table.js (now a thin compatibility shim): they only mutate
 *  store.tableSort and call the renderTable() bridge, which this component
 *  reacts to via useStoreVersion. */
export function ResultsTable() {
  useStoreVersion("select", "refresh");

  const { key, dir } = store.tableSort as { key: keyof ElementRow | "verdict"; dir: number };
  // The Verdict column has no top-level `verdict` key -- it lives at
  // product.verdict -- so a naive a[key] lookup returned undefined for every
  // row and the comparator scored every pair equal: the header rendered
  // "sorted" while the order never changed. Sort verdicts by SEVERITY rather
  // than alphabetically; a reviewer sorting by verdict wants the problems
  // first, not "Match" before "Mismatch".
  const VERDICT_RANK: Record<string, number> = {
    LOCATION_MISMATCH: 0, NEEDS_REVIEW: 1, LOCATION_MATCH: 2, NOT_APPLICABLE: 3,
  };
  const sortValue = (row: ElementRow) =>
    key === "verdict" ? VERDICT_RANK[rowVerdict(row)] ?? 99 : row[key as keyof ElementRow];
  const items = visibleElements()
    .slice()
    .sort((a, b) => {
      const av = sortValue(a);
      const bv = sortValue(b);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return typeof av === "number" && typeof bv === "number"
        ? (av - bv) * dir
        : String(av).localeCompare(String(bv)) * dir;
    });

  if (!items.length) {
    return (
      <tr>
        <td colSpan={8} className="empty-state">
          No elements match.
        </td>
      </tr>
    );
  }

  return (
    <>
      {items.map((e) => (
        <tr
          key={e.id}
          className={store.selected === e.id ? "selected" : ""}
          data-id={e.id}
          onClick={() => select(e.id, "table")}
        >
          <td>{e.mark || "—"}</td>
          <td>{e.category || "—"}</td>
          <td>{e.sheet || "—"}</td>
          <td>
            {/* Product verdict first — that is the answer the reviewer needs.
                The internal engine status stays beside it, dimmed, so the
                detail behind the verdict is never hidden. */}
            <VerdictBadge verdict={rowVerdict(e)} size="sm" />
          </td>
          <td>
            {/* Deliberately NEUTRAL, not colour-coded. The internal status
                had its own palette (COL) in which LOCATION_MISMATCH is amber
                -- the same amber VERDICT_COL uses for NEEDS_REVIEW -- so a
                row could show a red "Mismatch" badge beside an amber pill,
                and a NEEDS_REVIEW row showed amber beside violet. Two
                palettes describing one element is worse than none. The
                verdict carries the colour; this carries the detail. */}
            <span className="status-pill status-pill--detail">
              {e.status.replaceAll("_", " ")}
            </span>
            {/* R-18: which flavour of REVIT_ONLY -- a vocabulary gap reads very
                differently from a genuinely extra device. */}
            {e.status_detail && e.status_detail !== e.status && (
              <span
                className="status-pill"
                style={{ color: "#a78bfa", border: "1px solid #a78bfa66" }}
                title="The Revit family matched no schedule row — vocabulary gap, teachable"
              >
                {" "}
                {e.status_detail.replaceAll("_", " ")}
              </span>
            )}
          </td>
          <td className="num">{e.distance_ft != null ? e.distance_ft.toFixed(2) : "—"}</td>
          <td>{e.device_id || "—"}</td>
          <td>{e.reason || "—"}</td>
        </tr>
      ))}
    </>
  );
}
