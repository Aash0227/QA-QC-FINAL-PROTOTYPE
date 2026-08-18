export interface ChatBlock {
  type: "count_card" | "status_breakdown" | "table" | string;
  total?: number;
  label?: string;
  by_category?: Record<string, number>;
  by_status?: Record<string, number>;
  title?: string;
  columns?: string[];
  rows?: Record<string, unknown>[];
  shown?: number;
}

export interface ChatUiAction {
  type: "select" | "filter" | "open_panel" | string;
  element_id?: string;
  filters?: { search?: string; status?: string; sheet?: string };
  panel?: string;
}

export interface ChatApiResponse {
  reply?: string;
  blocks?: ChatBlock[];
  ui_actions?: ChatUiAction[];
}

export type ChatMsg =
  | { kind: "text"; role: "me" | "ai"; text: string }
  | { kind: "typing" }
  | { kind: "blocks"; blocks: ChatBlock[] }
  | { kind: "unknown-card"; items: { hint?: string; type?: string }[] };
