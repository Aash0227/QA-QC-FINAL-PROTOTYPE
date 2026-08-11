/* api.js — the fetch wrapper (production-plan §1).
   Unwraps the backend's error envelope and carries the optional bearer token.
   (BUG-18 client half): when the backend runs with QAQC_AUTH_TOKEN, put the same
   token in localStorage as "qaqc_token". api() sends it as a Bearer header;
   tokenized() appends ?token= for consumers that cannot set headers
   (EventSource SSE, <img> evidence crops, window.open exports).

   Project preference: the active project is a UI-only preference (BUG-03).
   /api/projects/activate persists it server-side today, so no X-Project header
   is required yet; setProjectHeader() is the seam for when routes go
   header-scoped. ponytail: header plumbing lands with the router change that
   needs it, not before. */

export const authToken = () => localStorage.getItem("qaqc_token") || "";

export function tokenized(url) {
  const t = authToken();
  return t ? url + (url.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(t) : url;
}

let projectHeader = null;
export function setProjectHeader(slug) { projectHeader = slug || null; }

export async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  const tok = authToken();
  if (tok) headers["Authorization"] = "Bearer " + tok;
  if (projectHeader) headers["X-Project"] = projectHeader;
  opts = { ...opts, headers };
  const r = await fetch(path, opts);
  const t = await r.text();
  let j; try { j = JSON.parse(t); } catch { j = { raw: t }; }
  if (!r.ok) {
    const d = j.detail;
    throw new Error((d && typeof d === "object" ? d.message || JSON.stringify(d) : d) || j.reason || r.status);
  }
  return j;
}
