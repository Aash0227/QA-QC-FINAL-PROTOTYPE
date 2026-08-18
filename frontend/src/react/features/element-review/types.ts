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
}
