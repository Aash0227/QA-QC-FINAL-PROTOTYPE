/** Shared API core — the ONE fetch/auth/error contract for both frontend
 *  surfaces (vanilla dashboard + React Pipeline Island).
 *
 *  Before this file, src/api.js and src/react/lib/api.ts each independently
 *  reimplemented authToken()/tokenized()/error-unwrapping — same contract,
 *  two copies that could silently drift. This is the single source; both
 *  surfaces' own api modules now delegate here (see src/api.js and
 *  src/react/lib/api.ts) so every existing `import { api } from "../api.js"`
 *  or `import { api } from "@/lib/api"` call site is unchanged.
 *
 *  Auth contract (BUG-18): backend may run with QAQC_AUTH_TOKEN; the token
 *  lives in localStorage as "qaqc_token". Bearer header for fetch, ?token=
 *  for consumers that cannot set headers (EventSource SSE, <img> crops,
 *  window.open exports). */

import type {
  AiStatusResponse,
  PipelineStatus,
  ProjectInfo,
  RunState,
} from "../react/types/pipeline";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function authToken(): string {
  try {
    return localStorage.getItem("qaqc_token") || "";
  } catch {
    return "";
  }
}

export function tokenized(url: string): string {
  const t = authToken();
  return t ? url + (url.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(t) : url;
}

// Project preference (BUG-03): active project is a UI-only preference today —
// /api/projects/activate persists it server-side, so no X-Project header is
// required yet. This is the seam for when routes go header-scoped.
let projectHeader: string | null = null;
export function setProjectHeader(slug: string | null): void {
  projectHeader = slug || null;
}

function authHeaders(): Record<string, string> {
  const t = authToken();
  const h: Record<string, string> = {};
  if (t) h.Authorization = `Bearer ${t}`;
  if (projectHeader) h["X-Project"] = projectHeader;
  return h;
}

/** Generic fetch wrapper — same signature/behavior as the original vanilla
 *  api(path, opts): unwraps the backend's {detail} error envelope into a
 *  thrown ApiError (has .status, unlike the old plain Error), passes through
 *  arbitrary fetch opts (FormData bodies for uploads, custom headers, etc). */
export async function apiFetch<T = unknown>(path: string, opts: RequestInit = {}): Promise<T> {
  const headers = { ...(opts.headers || {}), ...authHeaders() };
  const res = await fetch(path, { ...opts, headers });
  const text = await res.text();
  let body: any;
  try {
    body = JSON.parse(text);
  } catch {
    body = { raw: text };
  }
  if (!res.ok) {
    const d = body?.detail;
    const message =
      (d && typeof d === "object" ? d.message || JSON.stringify(d) : d) ||
      body?.reason ||
      `${res.status} ${res.statusText}`;
    throw new ApiError(res.status, String(message));
  }
  return body as T;
}

const BASE = "./api";

function post<T>(url: string, body?: unknown, project?: string): Promise<T> {
  return apiFetch<T>(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(project ? { "X-Project": project } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

function get<T>(url: string, project?: string): Promise<T> {
  return apiFetch<T>(url, {
    headers: project ? { "X-Project": project } : {},
  });
}

/** Typed convenience methods for the pipeline contract (used by the React
 *  Pipeline Island). Vanilla panels use apiFetch/api() directly for their
 *  more varied, less-typed call shapes (FormData uploads, dynamic paths). */
export const pipelineApi = {
  runPipeline: (force = false, project?: string) =>
    post<RunState>(`${BASE}/pipeline/run?force=${force}`, undefined, project),
  runState: (project?: string) => get<RunState>(`${BASE}/pipeline/run`, project),
  pipelineStatus: (project?: string) => get<PipelineStatus>(`${BASE}/pipeline/status`, project),
  aiStatus: (stage: string, title: string, project?: string) =>
    post<AiStatusResponse>(`${BASE}/pipeline/ai-status`, { stage, title }, project),
  projects: () => get<ProjectInfo[]>(`${BASE}/projects`),
};
