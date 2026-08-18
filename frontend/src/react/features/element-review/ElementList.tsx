import { Fragment } from "react";

import { COL, CATS, CAT_LABEL, GLYPH, statusLabel } from "../../../util";
import { store, select, emit } from "../../../store";

import { visibleElements } from "./elements";
import type { ElementRow } from "./types";
import { useStoreVersion } from "./useStoreVersion";

const CAT_LIST = CATS as string[];
const LABELS = CAT_LABEL as Record<string, string>;
const COLORS = COL as Record<string, string>;
const GLYPHS = GLYPH as Record<string, string>;

/** Count-per-status dot bar on category/mark headers -- carries a glyph as
 *  well as a colour and a titled label, so the breakdown reads without
 *  colour vision and on a greyscale printout. Ported from list.js::dotBar. */
function DotBar({ items }: { items: ElementRow[] }) {
  const counts: Record<string, number> = {};
  for (const e of items) counts[e.status] = (counts[e.status] || 0) + 1;
  const entries = Object.entries(counts).sort(([a], [b]) => a.localeCompare(b));
  return (
    <span className="mini-dots">
      {entries.map(([s, n]) => (
        <span key={s} title={`${n} ${statusLabel(s)}`}>
          <span className="dot" style={{ background: COLORS[s] }}>
            {GLYPHS[s] || ""}
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

  if (!groups.length) {
    return <div className="empty-state">No elements match.</div>;
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
            <div
              className={`cat-hdr ${open ? "open" : ""}`}
              data-cat={cat}
              onClick={() => toggleCat(cat)}
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
                    <div className="mark-hdr" data-mark={mkey} onClick={() => toggleMark(mkey)}>
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
                          aria-label={`${e.mark || "unmarked"} on sheet ${e.sheet || "unknown"}, ${statusLabel(e.status)}`}
                          onClick={() => select(e.id, "list")}
                        >
                          <span className="dot" style={{ background: COLORS[e.status] }}>
                            {GLYPHS[e.status] || ""}
                          </span>
                          <span className="meta">
                            {e.sheet || "—"}
                            {e.distance_pdf_points != null ? ` · ${e.distance_pdf_points}pt` : ""}
                            {e.taught_by ? " · 🧠" : ""}
                          </span>
                          <span
                            className="pill"
                            style={{ color: COLORS[e.status], borderColor: `${COLORS[e.status]}44` }}
                          >
                            {e.status.replaceAll("_", " ")}
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
