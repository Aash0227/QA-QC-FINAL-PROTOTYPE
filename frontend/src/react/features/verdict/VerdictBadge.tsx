/** Product verdict UI — the vocabulary a QA engineer actually reads.
 *
 *  The backend collapses ten internal engine statuses into four product
 *  verdicts (matching_engine.product_verdict) and stamps `product` on every
 *  element row. Nothing here re-derives that: these components only render
 *  what the backend decided, so the screen and the API can never disagree.
 *
 *  Colour is never the only signal — every badge carries a glyph, so the
 *  verdict survives a monochrome print of a punch list and stays readable for
 *  a colour-blind reviewer. */
import { VERDICT_COL, VERDICT_GLYPH, VERDICT_HELP, VERDICT_LABEL, VERDICTS } from "../../../util.js";

export type Verdict =
  | "LOCATION_MATCH"
  | "LOCATION_MISMATCH"
  | "NEEDS_REVIEW"
  | "NOT_APPLICABLE";

const COL = VERDICT_COL as Record<string, string>;
const GLYPH = VERDICT_GLYPH as Record<string, string>;
const LABEL = VERDICT_LABEL as Record<string, string>;
const HELP = VERDICT_HELP as Record<string, string>;

export function VerdictBadge({ verdict, size = "md" }: {
  verdict: string;
  size?: "sm" | "md";
}) {
  const colour = COL[verdict] ?? COL.NOT_APPLICABLE;
  return (
    <span
      className={`verdict-badge verdict-badge--${size}`}
      style={{ "--vcol": colour } as React.CSSProperties}
      title={HELP[verdict] ?? verdict}
      data-verdict={verdict}
    >
      <span className="verdict-badge__glyph" aria-hidden="true">
        {GLYPH[verdict] ?? "–"}
      </span>
      {LABEL[verdict] ?? verdict}
    </span>
  );
}

/** Whole-project verdict summary, driven by `product_counts` from
 *  GET /api/elements. Out-of-scope elements are shown apart from the bar
 *  rather than inside it: including 226 never-exported posts would make the
 *  bar read as "mostly unresolved" when every in-scope element was answered. */
export function VerdictBar({ counts, onSelect, selected }: {
  counts: Record<string, number> | null | undefined;
  onSelect?: (verdict: string | null) => void;
  selected?: string | null;
}) {
  if (!counts) return null;
  const inScope = VERDICTS.filter((v: string) => v !== "NOT_APPLICABLE");
  const total = inScope.reduce((n: number, v: string) => n + (counts[v] || 0), 0);
  if (!total) return null;
  const na = counts.NOT_APPLICABLE || 0;

  return (
    <div className="verdict-bar">
      <div className="verdict-bar__track" role="img"
           aria-label={inScope.map((v: string) => `${counts[v] || 0} ${LABEL[v]}`).join(", ")}>
        {inScope.map((v: string) => {
          const n = counts[v] || 0;
          if (!n) return null;
          return (
            <div key={v} className="verdict-bar__seg"
                 style={{ width: `${(n / total) * 100}%`, background: COL[v] }} />
          );
        })}
      </div>
      <div className="verdict-bar__legend">
        {inScope.map((v: string) => {
          const n = counts[v] || 0;
          const isSel = selected === v;
          return (
            <button key={v} type="button"
                    className={`verdict-bar__item${isSel ? " is-selected" : ""}`}
                    style={{ "--vcol": COL[v] } as React.CSSProperties}
                    title={HELP[v]}
                    aria-pressed={isSel}
                    onClick={() => onSelect?.(isSel ? null : v)}>
              <span className="verdict-bar__dot" aria-hidden="true" />
              <strong>{n}</strong> {LABEL[v]}
            </button>
          );
        })}
        {na > 0 && (
          <span className="verdict-bar__na" title={HELP.NOT_APPLICABLE}>
            {na} not applicable
          </span>
        )}
      </div>
    </div>
  );
}
