import { Fragment } from "react";

import { CATS, CAT_LABEL, statusLabel,
         VERDICT_COL, VERDICT_GLYPH, VERDICT_LABEL, rowVerdict } from "../../../util";
import { store, select, emit } from "../../../store";

import { visibleElements } from "./elements";
import type { ElementRow } from "./types";
import { useStoreVersion } from "./useStoreVersion";

const CAT_LIST = CATS as string[];
const LABELS = CAT_LABEL as Record<string, string>;
const VCOL = VERDICT_COL as Record<string, string>;
const VGLYPH = VERDICT_GLYPH as Record<string, string>;
const VLABEL = VERDICT_LABEL as Record<string, string>;

/** Count-per-status dot bar on category/mark headers -- carries a glyph as
 *  well as a colour and a titled label, so the breakdown reads without
 *  colour vision and on a greyscale printout. Ported from list.js::dotBar. */
function DotBar({ items }: { items: ElementRow[] }) {
  // Summarises by PRODUCT VERDICT, not internal status. A header that reads
  // "12 PDF_ONLY, 9 REVIT_ONLY, 4 LOCATION_MISMATCH" makes a reviewer do the
  // collapsing in their head; "25 mismatch" is the same fact, already answered.
  // Ordered worst-first so the thing needing attention leads.
  const counts: Record<string, number> = {};
  for (const e of items) {
    const v = rowVerdict(e);
    counts[v] = (counts[v] || 0) + 1;
  }
  const ORDER = ["LOCATION_MISMATCH", "NEEDS_REVIEW", "LOCATION_MATCH", "NOT_APPLICABLE"];
  const entries = Object.entries(counts)
    .sort(([a], [b]) => ORDER.indexOf(a) - ORDER.indexOf(b));
  // Titles stay lowercase, matching the convention statusLabel() set for every
  // other titled count in the app (asserted by tests/projects.spec.js).
  return (
    <span className="mini-dots">
      {entries.map(([v, n]) => (
        <span key={v} title={`${n} ${(VLABEL[v] || v).toLowerCase()}`}>
          <span className="dot" style={{ background: VCOL[v] }}>
            {VGLYPH[v] || ""}
          </span>
          {n}
        </span>
      ))}
    </span>
  );
}

/** React port of panels/list.js's renderList() -- the grouped element list
 *  (category -> mark -> instance rows). Mounted directly into the existing
 *  #list-rows container (see react/dashboard-main.tsx); search/filter input
 *  wiring stays in panels/list.js (now a thin compatibility shim) because it
 *  only mutates store.filters and calls the renderList() bridge, which this
 *  component reacts to via useStoreVersion -- moving that trivial wiring to
 *  React would add risk for no behavioral gain. */
export function ElementList() {
  useStoreVersion("select", "refresh");

  const items = visibleElements();
  const searching = !!store.filters.search;
  const byCat: Record<string, ElementRow[]> = {};
  for (const e of items) (byCat[e.category] ??= []).push(e);

  const toggleCat = (cat: string) => {
    store.openCats.has(cat) ? store.openCats.delete(cat) : store.openCats.add(cat);
    emit("refresh");
  };
  const toggleMark = (mkey: string) => {
    store.openMarks.has(mkey) ? store.openMarks.delete(mkey) : store.openMarks.add(mkey);
    emit("refresh");
  };

  const groups = CAT_LIST.filter((cat) => byCat[cat]);

  // No results at all for this project: say why, and offer the actual next
  // step. This replaces a silent redirect to /pipeline.html, which made a
  // project awaiting input indistinguishable from a broken backend.
  const loadError = (store as Record<string, unknown>).loadError as string | null;
  if (loadError && !(store.elements as unknown[]).length) {
    const nextAction = (store as Record<string, unknown>).nextAction as
      | { kind?: string; message?: string }
      | null;
    return (
      <div className="empty-state empty-state--block">
        {loadError === "no-results" ? (
          <>
            <strong>No results for this project yet.</strong>
            <p>{nextAction?.message || "Run the pipeline to compare the drawings against the model."}</p>
            <button className="mini primary" onClick={() => { window.location.href = "/pipeline.html"; }}>
              Open pipeline
            </button>
            {nextAction?.kind === "upload_revit" && (
              <button
                className="mini"
                onClick={() => window.dispatchEvent(new CustomEvent("open-project-manager"))}
              >
                Add Revit export
              </button>
            )}
          </>
        ) : (
          <>
            <strong>Could not load results.</strong>
            <p>The backend did not answer. Check that it is running, then retry.</p>
            <button className="mini" onClick={() => window.location.reload()}>Retry</button>
          </>
        )}
      </div>
    );
  }

  if (!groups.length) {
    // An empty list must always say WHY it is empty and offer the way out.
    // The verdict filter is set from a different pane (the verdict bar above
    // the results), so a reviewer who lands here can otherwise be left
    // staring at "No elements match." with no idea what to undo.
    const vf = (store as Record<string, unknown>).verdictFilter as string | null;
    return (
      <div className="empty-state">
        No elements match.
        {vf && (
          <>
            {" "}
            <button
              className="mini"
              onClick={() => {
                (store as Record<string, unknown>).verdictFilter = null;
                emit("refresh");
              }}
            >
              Clear {(VLABEL[vf] || vf).toLowerCase()} filter
            </button>
          </>
        )}
      </div>
    );
  }

  return (
    <>
      {groups.map((cat) => {
        const list = byCat[cat];
        const open = searching || store.openCats.has(cat);
        const byMark: Record<string, ElementRow[]> = {};
        for (const e of list) (byMark[e.mark || "—"] ??= []).push(e);
        const marks = Object.keys(byMark).sort();

        return (
          <Fragment key={cat}>
            {/* Expanders are real buttons for the keyboard. They were plain
                divs with onClick, so a keyboard-only reviewer could not open a
                category at all -- the entire element list was unreachable
                without a mouse. */}
            <div
              className={`cat-hdr ${open ? "open" : ""}`}
              data-cat={cat}
              role="button"
              tabIndex={0}
              aria-expanded={open}
              onClick={() => toggleCat(cat)}
              onKeyDown={(ev) => {
                if (ev.key === "Enter" || ev.key === " ") {
                  ev.preventDefault();
                  toggleCat(cat);
                }
              }}
            >
              <span className="car">▶</span>
              {LABELS[cat]} <span className="cnt">{list.length}</span>
              <DotBar items={list} />
            </div>
            {open &&
              marks.map((mark) => {
                const grp = byMark[mark];
                const mkey = `${cat}:${mark}`;
                const mopen = searching || store.openMarks.has(mkey);
                return (
                  <Fragment key={mkey}>
                    <div
                      className="mark-hdr"
                      data-mark={mkey}
                      role="button"
                      tabIndex={0}
                      aria-expanded={mopen}
                      onClick={() => toggleMark(mkey)}
                      onKeyDown={(ev) => {
                        if (ev.key === "Enter" || ev.key === " ") {
                          ev.preventDefault();
                          toggleMark(mkey);
                        }
                      }}
                    >
                      <span className="car" style={mopen ? { transform: "rotate(90deg)" } : undefined}>
                        ▶
                      </span>
                      {mark} <span className="cnt">({grp.length})</span>
                      <DotBar items={grp} />
                    </div>
                    {mopen &&
                      grp.map((e) => (
                        <div
                          key={e.id}
                          className={`row ${store.selected === e.id ? "selected" : ""}`}
                          data-id={e.id}
                          role="option"
                          aria-selected={store.selected === e.id}
                          aria-label={`${e.mark || "unmarked"} on sheet ${e.sheet || "unknown"}, ${VLABEL[rowVerdict(e)] || statusLabel(e.status)}`}
                          onClick={() => select(e.id, "list")}
                        >
                          {/* Dot and pill carry the PRODUCT verdict so the
                              list, the results table and the inspector all say
                              the same thing about the same element. The
                              internal engine status moves into the meta line,
                              where the detail is still available but no longer
                              competes with the answer. */}
                          <span className="dot" style={{ background: VCOL[rowVerdict(e)] }}>
                            {VGLYPH[rowVerdict(e)] || ""}
                          </span>
                          <span className="meta">
                            {e.sheet || "—"}
                            {e.distance_pdf_points != null ? ` · ${e.distance_pdf_points}pt` : ""}
                            {` · ${statusLabel(e.status)}`}
                            {e.taught_by ? " · 🧠" : ""}
                          </span>
                          <span
                            className="pill"
                            style={{ color: VCOL[rowVerdict(e)], borderColor: `${VCOL[rowVerdict(e)]}44` }}
                          >
                            {VLABEL[rowVerdict(e)] || statusLabel(e.status)}
                          </span>
                        </div>
                      ))}
                  </Fragment>
                );
              })}
          </Fragment>
        );
      })}
    </>
  );
}
