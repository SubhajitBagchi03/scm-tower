// ── Core App ──────────────────────────────────────────────────

export type AppHealth = {
  status: string;
  system: string;
  agents_active: string[];
  api_key_configured: boolean;
  db_configured: boolean;
};

// ── Inventory ────────────────────────────────────────────────

export type InventoryItem = {
  product_id: string;
  product_name: string;
  quantity_in_stock: number;
  reorder_threshold: number;
  warehouse?: string;
  supplier_info?: string | null;
  unit_cost?: number | null;
  avg_daily_consumption?: number | null;
  lead_time_days?: number | null;
};

export type InventoryAnalysis = {
  product_id: string;
  product_name: string;
  status: "Red" | "Yellow" | "Green";
  days_until_stockout: number;
  recommended_action: string;
  safety_stock: number;
  eoq: number;
  reorder_point: number;
  estimated_cost: number;
  reasoning: string;
  used_avg_daily_consumption: number;
  used_unit_cost: number;
  used_lead_time_days: number;
  data_completeness: string;
};

// ── Upload ────────────────────────────────────────────────────

export type UploadPreviewResponse = {
  file_id: string;
  original_filename: string;
  file_type: string;
  total_rows: number;
  column_mapping: Record<string, string>;
  missing_required: string[];
  preview_rows: Array<Record<string, unknown>>;
  conflicts: Array<Record<string, unknown>>;
  can_commit: boolean;
  message: string;
};

export type CommitRequest = {
  file_id: string;
  confirmed_mapping?: Record<string, string>;
  missing_field_defaults?: Record<string, unknown>;
  conflict_resolutions?: Array<{
    product_name: string;
    field_name: string;
    resolution: "use_existing" | "use_incoming" | "keep_both";
  }>;
};

export type CommitResult = {
  message: string;
  file_id: string;
  file_type: string;
  rows_saved: number;
  conflicts_recorded: number;
};

export type FileRecord = {
  file_id: string;
  filename: string;
  file_type: string;
  row_count: number;
  status: string;
  uploaded_at: string;
  column_mapping: Record<string, string>;
};

export type ConflictItem = {
  id: number;
  table: string;
  product_name: string;
  field: string;
  existing_value: string;
  incoming_value: string;
  resolution: string;
  resolved_at: string | null;
};

// ── RAG / Ask ─────────────────────────────────────────────────

export type RagRequest = {
  question: string;
  top_k: number;
  use_only_last_document: boolean;
};

export type RagResponse = {
  question?: string;
  answer: string;
  sources: Array<{ text: string; source: string; page: number | string }>;
  show_sources?: boolean;
  filtered_to_last_document: boolean;
  document_used?: string;
};

// ── Agentic Layer — NEW ───────────────────────────────────────

export type PlanStep = {
  agent: string;
  task: string;
  depends_on: number[];
};

export type SupervisorPlan = {
  reasoning: string;
  steps: PlanStep[];
};

export type AgentStep = {
  step_index: number;
  agent_name: string;
  task: string;
  finding: string;
  data: Record<string, unknown>;
  confidence: number;
  duration_ms: number;
  timestamp: string;
};

export type JudgeVerdict = {
  is_valid: boolean;
  overall_confidence: number;
  contradictions: string[];
  warnings: string[];
  improvements: string[];
  reasoning: string;
};

export type AgentTrace = {
  run_id: string;
  goal: string;
  action: string;
  plan?: SupervisorPlan;
  steps: AgentStep[];
  judge_verdict?: JudgeVerdict;
  synthesis: string;
  total_duration_ms: number;
  timestamp: string;
};

// ── Agent API ─────────────────────────────────────────────────

export type AgentAction =
  | "analyze_inventory"
  | "select_supplier"
  | "track_shipment"
  | "generate_report"
  | "ask"
  | "full_assessment";

export type AgentRequest = {
  action: AgentAction;
  product_id?: string;
  query?: string;
  quantity?: number;
  urgency?: string;
  shipment_id?: string;
};

export type AgentResponse = {
  result?: string;
  issue?: Record<string, unknown>;
  recommendation?: unknown;
  reasoning?: string;
  context?: string;
  kpis?: Record<string, unknown>;
  cascade_risk?: string;
  carrier_flag?: string;
  executive_summary?: string;
  root_causes?: string[];
  forward_projections?: string[];
  // New agentic fields
  trace?: AgentTrace;
  judge_verdict?: JudgeVerdict;
};