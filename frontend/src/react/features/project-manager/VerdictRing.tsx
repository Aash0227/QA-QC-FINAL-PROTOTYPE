import { COL, RUN_STATUSES } from "../../../util";

import type { ProjectCounts } from "./types";

const R = 26;
const CIRC = 2 * Math.PI * R;

/** One donut per project, segmented by the same statuses/colours the element
 *  list and table use, so the card reads as a summary of the screen behind
 *  it rather than a second opinion. Ported 1:1 from the vanilla verdictRing()
 *  in panels/projects.js, as real SVG elements instead of an HTML string. */
export function VerdictRing({ counts }: { counts?: ProjectCounts }) {
  const total = counts?.total || 0;
  const by = counts?.by_status || {};
  const inner = total ? `${Math.round((100 * (by.MATCH || 0)) / total)}%` : "—";

  let offset = 0;
  const segs = (RUN_STATUSES as string[])
    .filter((s) => by[s])
    .map((s) => {
      const len = (CIRC * by[s]) / total;
      const el = (
        <circle
          key={s}
          className="pm-seg"
          r={R}
          cx={32}
          cy={32}
          stroke={(COL as Record<string, string>)[s] || "var(--dim)"}
          strokeDasharray={`${len.toFixed(2)} ${(CIRC - len).toFixed(2)}`}
          strokeDashoffset={(-offset).toFixed(2)}
        >
          <title>
            {s}: {by[s]}
          </title>
        </circle>
      );
      offset += len;
      return el;
    });

  return (
    <svg
      className="pm-ring"
      viewBox="0 0 64 64"
      role="img"
      aria-label={total ? `${by.MATCH || 0} of ${total} elements verified` : "Not analysed yet"}
    >
      <g transform="rotate(-90 32 32)">
        <circle className="pm-seg pm-seg-bg" r={R} cx={32} cy={32} />
        {segs}
      </g>
      <text x={32} y={32} className="pm-ring-num">
        {inner}
      </text>
    </svg>
  );
}
