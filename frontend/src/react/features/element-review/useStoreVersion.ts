import { useEffect, useState } from "react";

import { subscribe } from "../../../store";

/** Forces a re-render whenever any of the given store.js pub/sub event keys
 *  fire. store.js is the shared bridge between this migrated React feature
 *  and the still-vanilla panels (pdf.js, viewer3d.js, chat.js, app.js) that
 *  mutate `store.elements`/`store.selected`/etc. directly and call the
 *  renderList()/renderTable() bridge functions in panels/list.js afterward
 *  (see that file) — those bridges just emit("refresh"), which lands here.
 *
 *  This is a plain useState-bump force-update, not useSyncExternalStore,
 *  because store.js's mutable object + ad-hoc pub/sub isn't a real
 *  external-store snapshot API (no getSnapshot). Fine at this scale (a few
 *  hundred elements, event-driven, not high-frequency). */
export function useStoreVersion(...keys: string[]): number {
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const bump = () => setVersion((v) => v + 1);
    const offs = keys.map((k) => subscribe(k, bump));
    return () => offs.forEach((off) => off());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return version;
}
