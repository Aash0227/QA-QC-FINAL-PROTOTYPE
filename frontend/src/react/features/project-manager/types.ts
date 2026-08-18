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
  has_pdf: boolean;
  has_revit: boolean;
  updated_at?: string | null;
}

export interface ProjectDetail extends ProjectSummary {
  file_count?: number;
  size_bytes?: number;
}
