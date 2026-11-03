import type { Decision } from "./types";

export type SavedView = {
  page: "workspace" | "documents" | "purchase_orders" | "policy" | "ai" | "activity";
  filter: Decision | "all" | "attention";
  query: string;
  poQuery: string;
  poStatus: "all" | "approved" | "other";
  selected: string | null;
  selectedPo: string | null;
  selectedPoDraft: string | null;
};

const VIEW_KEY = "invoices-current-view";
const UPLOAD_KEY = "invoices-upload-job";
const LEGACY_UPLOAD_KEY = "ledger-active-upload";
const PAGES = new Set(["workspace", "documents", "purchase_orders", "policy", "ai", "activity"]);
const FILTERS = new Set(["all", "attention", "ready", "clarification", "procurement", "hold"]);
const PO_STATUSES = new Set(["all", "approved", "other"]);

const optionalString = (value: unknown) => typeof value === "string" ? value : null;

export function readView(): SavedView {
  const fallback: SavedView = {
    page: "workspace", filter: "all", query: "", poQuery: "", poStatus: "all",
    selected: null, selectedPo: null, selectedPoDraft: null,
  };
  try {
    const saved = JSON.parse(sessionStorage.getItem(VIEW_KEY) || "null");
    if (!saved || typeof saved !== "object") return fallback;
    return {
      page: PAGES.has(saved.page) ? saved.page : fallback.page,
      filter: FILTERS.has(saved.filter) ? saved.filter : fallback.filter,
      query: typeof saved.query === "string" ? saved.query : "",
      poQuery: typeof saved.poQuery === "string" ? saved.poQuery : "",
      poStatus: PO_STATUSES.has(saved.poStatus) ? saved.poStatus : fallback.poStatus,
      selected: optionalString(saved.selected),
      selectedPo: optionalString(saved.selectedPo),
      selectedPoDraft: optionalString(saved.selectedPoDraft),
    };
  } catch {
    return fallback;
  }
}

export function saveView(view: SavedView) {
  try { sessionStorage.setItem(VIEW_KEY, JSON.stringify(view)); } catch { /* Storage may be unavailable. */ }
}

export type SavedUpload = { id: string; kind: string };

export function readUploadJob(): SavedUpload | null {
  try {
    const saved = JSON.parse(localStorage.getItem(UPLOAD_KEY) || "null");
    if (saved && typeof saved.id === "string" && typeof saved.kind === "string") return saved;
    const legacy = localStorage.getItem(LEGACY_UPLOAD_KEY);
    return legacy ? { id: legacy, kind: "invoice" } : null;
  } catch {
    return null;
  }
}

export function saveUploadJob(job: SavedUpload) {
  try {
    localStorage.setItem(UPLOAD_KEY, JSON.stringify(job));
    localStorage.removeItem(LEGACY_UPLOAD_KEY);
  } catch { /* The current tab can still display the job. */ }
}

export function clearUploadJob() {
  const previous = readUploadJob();
  try {
    localStorage.removeItem(UPLOAD_KEY);
    localStorage.removeItem(LEGACY_UPLOAD_KEY);
  } catch { /* Ignore unavailable storage. */ }
  if (previous) {
    try { sessionStorage.removeItem(`invoices-upload-file:${previous.id}`); } catch { /* Ignore unavailable storage. */ }
  }
}

export function readUploadFile(jobId: string): string | null {
  try { return sessionStorage.getItem(`invoices-upload-file:${jobId}`); } catch { return null; }
}

export function saveUploadFile(jobId: string, fileId: string) {
  try { sessionStorage.setItem(`invoices-upload-file:${jobId}`, fileId); } catch { /* Keep the in-page selection. */ }
}

const aiKey = (documentId?: string) => `invoices-ai-job:${documentId || "all"}`;

export function readAIJob(documentId?: string): string | null {
  try { return sessionStorage.getItem(aiKey(documentId)); } catch { return null; }
}

export function saveAIJob(documentId: string | undefined, jobId: string) {
  try { sessionStorage.setItem(aiKey(documentId), jobId); } catch { /* Polling still works in this tab. */ }
}

export function clearAIJob(documentId?: string) {
  try { sessionStorage.removeItem(aiKey(documentId)); } catch { /* Ignore unavailable storage. */ }
}

export function readReviewTab(documentId: string): string {
  try {
    const tab = sessionStorage.getItem(`invoices-review-tab:${documentId}`);
    return tab && ["decision", "fields", "original", "notes"].includes(tab) ? tab : "decision";
  } catch {
    return "decision";
  }
}

export function saveReviewTab(documentId: string, tab: string) {
  try { sessionStorage.setItem(`invoices-review-tab:${documentId}`, tab); } catch { /* Keep the in-page tab. */ }
}
