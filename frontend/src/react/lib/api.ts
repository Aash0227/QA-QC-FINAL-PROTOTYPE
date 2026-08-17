/** Typed client for the existing Phase 1 backend contracts.
 *  No logic here — thin fetch wrappers only. Base path "./api" resolves to the
 *  same origin (dev server proxies /api to :8077; production serves same-origin). */

import type {
  AiStatusResponse,
  PipelineStatus,
  ProjectInfo,
  RunState,
} from "@/types/pipeline";

const BASE = "./api";

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (body.detail?.message) detail = body.detail.message;
    } catch {
      /* non-JSON error body — keep status text */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function post<T>(url: string, body?: unknown, project?: string): Promise<T> {
  return fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(project ? { "X-Project": project } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  }).then((r) => jsonOrThrow<T>(r));
}

function get<T>(url: string, project?: string): Promise<T> {
  return fetch(url, {
    headers: project ? { "X-Project": project } : {},
  }).then((r) => jsonOrThrow<T>(r));
}

export const api = {
  /** POST /api/pipeline/run?force= — 202 with run state; 409 when already running. */
  runPipeline: (force = false, project?: string) =>
    post<RunState>(`${BASE}/pipeline/run?force=${force}`, undefined, project),

  /** GET /api/pipeline/run — persisted state (404 before the first run). */
  runState: (project?: string) => get<RunState>(`${BASE}/pipeline/run`, project),

  /** GET /api/pipeline/status — legacy artifact checklist (compat). */
  pipelineStatus: (project?: string) =>
    get<PipelineStatus>(`${BASE}/pipeline/status`, project),

  /** POST /api/pipeline/ai-status — non-blocking; deterministic fallback. */
  aiStatus: (stage: string, title: string, project?: string) =>
    post<AiStatusResponse>(`${BASE}/pipeline/ai-status`, { stage, title }, project),

  /** GET /api/projects — list + active project. */
  projects: () => get<ProjectInfo[]>(`${BASE}/projects`),
};
