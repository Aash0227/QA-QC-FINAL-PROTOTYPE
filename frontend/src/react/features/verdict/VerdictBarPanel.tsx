/** The verdict bar, mounted in the always-visible left list panel.
 *
 *  It previously lived inside #table-panel (the results panel), which starts
 *  hidden and can be closed by the user. Filtering to a verdict and then
 *  closing that panel left the element list filtered with the only control
 *  that could clear it inside a `display:none` subtree — a trap with no
 *  visible way out. A filter must never outlive the reach of its own control,
 *  so the bar now sits beside the list it filters. */
import { emit, store } from "../../../store";
import { VerdictBar } from "./VerdictBadge";
import { useStoreVersion } from "../element-review/useStoreVersion";

export function VerdictBarPanel() {
  useStoreVersion("refresh");
  const counts = (store as Record<string, unknown>).productCounts as
    | Record<string, number>
    | null;
  if (!counts) return null;
  return (
    <div style={{ margin: "12px 0 4px" }}>
      <VerdictBar
        counts={counts}
        selected={(store as Record<string, unknown>).verdictFilter as string | null}
        onSelect={(v) => {
          (store as Record<string, unknown>).verdictFilter = v;
          emit("refresh");
        }}
      />
    </div>
  );
}
