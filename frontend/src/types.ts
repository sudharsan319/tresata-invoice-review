import type { AIAnalysis, AIConfig } from "./ai-types";
export type Decision = "ready" | "clarification" | "procurement" | "hold";
export type Evidence = {
  document_id: string;
  filename: string;
  page: number | null;
  excerpt: string;
  method: string;
};
export type LineItem = {
  description: string;
  sku?: string;
  quantity: string | number | null;
  unit_price: string | null;
  amount: string | null;
  evidence?: Evidence;
};
export type Invoice = {
  invoice_number: string;
  invoice_date: string;
  due_date: string;
  vendor_name: string;
  vendor_id: string;
  tax_id: string;
  po_number: string;
  currency: string;
  subtotal: string | null;
  tax_amount: string | null;
  total: string | null;
  bank_account: string;
  tax_inclusive: boolean;
  items: LineItem[];
  evidence: Record<string, Evidence>;
  extraction_notes: string[];
  extraction_method: string;
};
export type Check = {
  code: string;
  title: string;
  status: "pass" | "warning" | "fail" | "info";
  message: string;
  route: Decision;
  evidence: Evidence[];
};
export type Review = {
  ai_analysis?: AIAnalysis;
  id: string;
  document_id: string;
  filename: string;
  invoice: Invoice;
  decision: Decision;
  summary: string;
  checks: Check[];
  matched_vendor: { name: string; vendor_id: string } | null;
  matched_po: { po_number: string; currency: string } | null;
  po_candidates: string[];
  po_context: Record<string, string | string[] | null>;
  reviewed_at: string;
  resolution: {
    action: string;
    note: string;
    timestamp: string;
    decision_at_time: Decision;
  } | null;
};
export type Document = {
  pending_interpretation?: boolean;
  processing_trace?: ProcessingEvent[];
  id: string;
  filename: string;
  kind: string;
  size: number;
  uploaded_at: string;
  record_count: number;
  page_count: number;
  methods: string[];
  notes: string[];
};
export type PurchaseOrder = {
  po_number: string;
  vendor_id: string;
  vendor_name: string;
  currency: string;
  amount: string;
  amount_basis: "net" | "gross";
  status: string;
  valid_from: string;
  valid_to: string;
  items: LineItem[];
  evidence: Evidence;
};
export type PurchaseOrderDraft = {
  kind: "purchase_orders";
  values: Omit<PurchaseOrder, "evidence" | "amount" | "amount_basis"> & {
    amount: string;
    amount_basis: "net" | "gross" | "";
  };
  sources: Record<string, Evidence>;
  uncertainties: string[];
  method: string;
  run: { model?: string; status?: string } | null;
};
export type ProcessingEvent = {
  timestamp: string;
  stage: string;
  status: string;
  title: string;
  detail: string;
  task?: string;
  model?: string;
  duration_ms?: number;
  code?: string;
  route?: Decision;
  decision?: Decision;
  evidence?: Evidence[];
};
export type UploadJob = {
  id: string;
  kind: string;
  status: "queued" | "running" | "completed" | "failed";
  started_at: string;
  accepted: { id: string; filename: string; pending_review?: boolean }[];
  errors: { filename: string; message: string }[];
  files: {
    id: string;
    filename: string;
    status: "queued" | "processing" | "verifying" | "completed" | "failed";
    events: ProcessingEvent[];
  }[];
};
export type Policy = {
  name: string;
  amount_tolerance_percent: string;
  amount_tolerance_absolute: string;
  unit_price_tolerance_percent: string;
  require_line_items: boolean;
  check_bank_details: boolean;
  max_invoice_age_days: number;
  evidence: Evidence;
};
export type Workspace = {
  ai_settings?: AIConfig;
  reference_drafts?: Record<
    string,
    {
      kind: string;
      values: Policy;
      changed_fields: Partial<Policy>;
      uncertainties: string[];
      sources: Record<string, Evidence>;
      run: import("./ai-types").AIRun;
    }
  >;
  documents: Document[];
  reviews: Review[];
  vendors: unknown[];
  purchase_orders: PurchaseOrder[];
  po_drafts: Record<string, PurchaseOrderDraft>;
  history_count: number;
  policy: Policy;
  audit: {
    id: string;
    timestamp: string;
    action: string;
    message: string;
    document_id: string;
  }[];
  totals_by_currency: Record<string, string>;
  revision: number;
  extraction: { mode: string; model: string; external_processing: boolean };
};
