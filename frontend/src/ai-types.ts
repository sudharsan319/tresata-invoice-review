export type AITask = "extraction" | "vision" | "matching" | "policy" | "review";
export type AIConfig = {
  enabled: boolean;
  ready: boolean;
  key_configured: boolean;
  provider: string;
  models: Record<AITask, string>;
  defaults: Record<AITask, string>;
  vision_enabled: boolean;
  matching_enabled: boolean;
  max_vision_pages: number;
  max_output_tokens: number;
  timeout_seconds: number;
};
export type AIRun = {
  task: AITask;
  model: string;
  status: string;
  timestamp: string;
  duration_ms?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  cost_usd?: number | null;
  message?: string;
};
export type SemanticProposal = {
  invoice_line: number;
  po_line: number | null;
  equivalence: string;
  reason: string;
  invoice_quote: string;
  po_quote: string;
  confirmed: boolean;
};
export type AIAnalysis = {
  extraction_runs?: AIRun[];
  matching?: {
    analysis_key: string;
    po_number: string;
    matches: SemanticProposal[];
    run: AIRun;
  } | null;
  brief?: {
    observations: { text: string; check_codes: string[] }[];
    next_steps: { text: string; check_codes: string[] }[];
    run: AIRun;
  };
};
export type AIJob = {
  id: string;
  status: string;
  total: number;
  completed: number;
  skipped: number;
  current_file: string;
  errors: { filename: string; message: string }[];
  warnings: { filename: string; message: string }[];
};
