/** Project Manager types — mirror the /api/projects contract exactly
 *  (backend/app/routers/projects.py). */

export interface ProjectCounts {
  total: number;
  by_status: Record<string, number>;
}

export interface ProjectSummary {
  slug: string;
  display_name: string;
  client: string | null;
  revision: string | null;
  status: "active" | "archived";
  notes: string | null;
  active: boolean;
  counts?: ProjectCounts;
  sheet_count?: number;
  page_count?: number;
  /** Computed once on the backend so every surface agrees whether this
   *  project can produce an answer:
   *    ready      — results exist
   *    runnable   — both inputs present, pipeline can run
   *    incomplete — `missing_inputs` names what to supply */
  readiness?: "ready" | "runnable" | "incomplete";
  missing_inputs?: string[];
  has_pdf: boolean;
  has_revit: boolean;
  updated_at?: string | null;
}

export interface ProjectDetail extends ProjectSummary {
  file_count?: number;
  size_bytes?: number;
}
