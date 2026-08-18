import { store } from "../../../store";

import type { ElementRow } from "./types";

/** Ported 1:1 from panels/list.js::visibleElements(). Pure filter logic
 *  shared by ElementList and ResultsTable — both read the same store.filters. */
export function visibleElements(): ElementRow[] {
  const f = store.filters;
  const q = f.search.toLowerCase();
  return (store.elements as ElementRow[]).filter(
    (e) =>
      (!f.status || e.status === f.status) &&
      (!f.sheet || e.sheet === f.sheet) &&
      (!q ||
        `${e.mark} ${e.id} ${e.status} ${e.sheet || ""} ${e.category}`.toLowerCase().includes(q)),
  );
}
