import { store } from "../../../store";
import { rowVerdict } from "../../../util.js";

import type { ElementRow } from "./types";

/** Ported 1:1 from panels/list.js::visibleElements(). Pure filter logic
 *  shared by ElementList and ResultsTable — both read the same store.filters. */
export function visibleElements(): ElementRow[] {
  const f = store.filters;
  const q = f.search.toLowerCase();
  // Verdict filter comes from the verdict bar. It sits alongside the existing
  // internal-status filter rather than replacing it: the bar is what a
  // reviewer drives, the status filter is still used by the older panels.
  const verdict = (store as Record<string, unknown>).verdictFilter as string | null;
  return (store.elements as ElementRow[]).filter(
    (e) =>
      (!verdict || rowVerdict(e) === verdict) &&
      (!f.status || e.status === f.status) &&
      (!f.sheet || e.sheet === f.sheet) &&
      (!q ||
        `${e.mark} ${e.id} ${e.status} ${e.sheet || ""} ${e.category}`.toLowerCase().includes(q)),
  );
}
