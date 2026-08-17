/** PipelineIsland-specific types and the stage → artifact mapping
 *  (mirrors backend app/stage_graph.py STAGE_OUTPUT + app/config.py ARTIFACT_FILES).
 *  Keep in sync with the backend contract; the backend owns this truth. */

export type IslandStepStatus = "pending" | "active" | "success" | "error" | "skipped";

/** Map backend StageStatus (likely from RunStage) to Island timeline statuses. */
export function toIslandStatus(
  backend: "pending" | "running" | "done" | "failed" | "skipped",
): IslandStepStatus {
  switch (backend) {
    case "running":
      return "active";
    case "done":
      return "success";
    case "failed":
      return "error";
    case "skipped":
      return "skipped";
    case "pending":
      return "pending";
  }
}

export interface IslandStep {
  id: string; // backend stage key
  title: string;
  status: IslandStepStatus;
  duration_s: number | null;
  started_at: string | null;
  completed_at: string | null;
  /** Human-readable message from SSE (the reason/summary). */
  message: string | null;
  /** AI explanation — fetched after stage.done, shown under the expanded step. */
  aiText: string | null;
  aiSource: "ai" | "deterministic" | null;
  aiPending: boolean;
  /** Error details when a stage fails. */
  error: string | null;
  /** The artifact key whose file gate the stage's idempotent skip. */
  artifact: { key: string; filename: string } | null;
}

/** Artifact metadata for the technical-details panel.
 *  Mirror of app/stage_graph STAGE_OUTPUT + app/config ARTIFACT_FILES. */
export const STAGE_ARTIFACT: Record<string, { key: string; filename: string }> = {
  extract:         { key: "element_intelligence",    filename: "element_intelligence.json" },
  revit_convert:   { key: "ai_revit",                filename: "AIConvert_revit.json" },
  pdf_intelligence: { key: "pdf_page_intelligence",  filename: "pdf_page_intelligence.json" },
  pdf_convert:     { key: "ai_pdf",                  filename: "AIConvert_pdf.json" },
  ransac:          { key: "registration",            filename: "registration_calibration.json" },
  compare:         { key: "compare",                 filename: "ai_compare_report.json" },
  match:           { key: "element_list",            filename: "element_list.json" },
};