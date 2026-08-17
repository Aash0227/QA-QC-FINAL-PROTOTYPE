/** Backend contract types — mirror the Phase 1 run-state + SSE shapes exactly.
 *  The backend owns these contracts; this file only types them for TS. */

export type StageStatus = "pending" | "running" | "done" | "failed" | "skipped";

export interface RunStage {
  key: string;
  title: string;
  status: StageStatus;
  started_at: string | null;
  completed_at: string | null;
  duration_s: number | null;
  reason: string | null;
  error: string | null;
}

export type RunStatus = "running" | "completed" | "failed";

export interface NextAction {
  kind: string; // "upload_pdf" | "upload_revit" | "review" | "retry" | ...
  message: string;
}

export interface RunState {
  run_id: string;
  project: string;
  status: RunStatus;
  force: boolean;
  started_at: string;
  completed_at: string | null;
  stages: RunStage[];
  next_action: NextAction | null;
}

/** SSE event from GET /api/pipeline/events (progress.py emit). */
export interface PipelineEvent {
  seq: number;
  ts: number;
  step: string;
  kind: "start" | "done" | "error" | "skip";
  message: string;
  data?: Record<string, unknown>;
}

export interface AiStatusResponse {
  text: string;
  source: "ai" | "deterministic";
}

export interface ProjectInfo {
  slug: string;
  name: string;
  is_active: boolean;
  created_at?: string;
}

export interface PipelineStatusStage {
  key: string;
  title: string;
  done: boolean;
  missing: string[];
}

export interface PipelineStatus {
  project: string;
  stages: PipelineStatusStage[];
  complete: boolean;
  next_action: NextAction | null;
}
