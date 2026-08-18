export interface Point {
  x: number;
  y: number;
}
export interface Benchmark {
  mark: string;
  grid_label?: string;
  grid_id?: string;
  pdf_point_pt: Point;
  revit_point_ft: Point;
  evidence_url?: string;
}
export interface Proposal {
  sheet_number: string;
  page_index: number;
  benchmarks: Benchmark[];
  separation_pdf_pt: number;
  separation_revit_ft: number;
  candidates_considered: number;
}
export interface HistoryEntry {
  to: string;
  note?: string;
  payload?: {
    readback?: Record<string, Point>;
    verified?: boolean;
    verification?: Verification;
    calibration_source?: string;
    scale?: number;
  };
}
export interface Verification {
  checks: { mark: string; expected: Point; found?: Point; ok: boolean; delta_pt?: number }[];
}
export interface Workflow {
  state: string;
  proposal?: Proposal;
  verification?: Verification;
  history?: HistoryEntry[];
}
export interface GridPoint {
  id: string;
  label: string;
  point: Point;
}
export interface GridPointsResponse {
  sheet_number: string;
  page_index: number;
  page_size: [number, number];
  points: GridPoint[];
}
export interface RevitStatus {
  connected: boolean;
  reason?: string;
  model_title?: string;
}
export interface WizardSseEvent {
  kind: string;
  ts: number;
  message: string;
}
