/** Element row shape — mirrors GET /api/elements' `elements[]` entries.
 *  Kept loose (most fields optional) since not every category/status
 *  combination populates every field, matching how the vanilla panels
 *  treated these as plain untyped objects. */
export interface ElementRow {
  id: string;
  mark: string | null;
  category: string;
  sheet: string | null;
  status: string;
  status_detail?: string;
  distance_ft?: number | null;
  distance_pdf_points?: number | null;
  device_id?: string | null;
  reason?: string | null;
  taught_by?: string | null;
  /** Product verdict block stamped by the backend
   *  (matching_engine.product_result). The UI renders this rather than
   *  re-deriving a verdict from `status`, so screen and API cannot diverge. */
  product?: {
    verdict: string;
    is_certain?: boolean;
    in_scope?: boolean;
    evidence?: Record<string, unknown>;
  } | null;
}
