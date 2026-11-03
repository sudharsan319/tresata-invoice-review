import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  Check,
  CheckCheck,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleAlert,
  CircleHelp,
  Clock3,
  FileCheck2,
  FileSearch,
  Files,
  FileText,
  FolderOpen,
  History,
  LayoutDashboard,
  LoaderCircle,
  LockKeyhole,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Sun,
  Trash2,
  UploadCloud,
  X,
  Moon,
} from "lucide-react";
import { api } from "./api";
import AISettings from "./AISettings";
import AIReview from "./AIReview";
import PolicyMenu from "./PolicyMenu";
import PurchaseOrderDraftForm from "./PurchaseOrderDraftForm";
import UploadProgress, { ProcessingTrace } from "./UploadProgress";
import type {
  Check as CheckType,
  Decision,
  Evidence,
  Invoice,
  Policy,
  PurchaseOrder,
  PurchaseOrderDraft,
  Review,
  Workspace,
  UploadJob,
  ProcessingEvent,
} from "./types";

const labels: Record<Decision, string> = {
  ready: "Ready for approval",
  clarification: "Needs clarification",
  procurement: "Procurement review",
  hold: "Hold for investigation",
};
const shortLabels: Record<Decision, string> = {
  ready: "Ready for approval",
  clarification: "Clarification",
  procurement: "Procurement",
  hold: "On hold",
};
const icons = {
  ready: CheckCircle2,
  clarification: CircleHelp,
  procurement: FileSearch,
  hold: ShieldAlert,
};
const categories = [
  {
    id: "invoice",
    name: "Invoices",
    accept: ".pdf",
    icon: FileText,
  },
  {
    id: "purchase_orders",
    name: "Purchase orders",
    accept: ".pdf,.png,.jpg,.jpeg,.webp,.csv,.json,.xlsx",
    icon: FileCheck2,
  },
  {
    id: "vendors",
    name: "Vendor master",
    accept: ".pdf,.csv,.json,.xlsx",
    icon: ShieldCheck,
  },
  {
    id: "history",
    name: "Invoice history",
    accept: ".csv,.json,.xlsx",
    icon: History,
  },
  {
    id: "policy",
    name: "Company policy",
    accept: ".pdf,.json,.txt",
    icon: Settings2,
  },
];

function formatAmount(value: string | null | undefined, currency = "INR") {
  if (value == null || value === "") return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  try {
    return new Intl.NumberFormat("en-IN", {
      style: "currency",
      currency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(number);
  } catch {
    return `${currency} ${value}`;
  }
}
function dateTime(value: string) {
  return new Date(value).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}
function displayDate(value: string) {
  if (!value) return "—";
  const date = new Date(`${value}T00:00:00`);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}
function Badge({ decision }: { decision: Decision }) {
  const Icon = icons[decision];
  return (
    <span className={`badge ${decision}`}>
      <Icon size={13} />
      {shortLabels[decision]}
    </span>
  );
}
function Button({
  children,
  busy,
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { busy?: boolean }) {
  return (
    <button
      className={`button ${className}`}
      {...props}
      disabled={busy || props.disabled}
    >
      {busy && <LoaderCircle size={15} className="spin" />}
      {children}
    </button>
  );
}

function Modal({
  title,
  children,
  onClose,
  wide = false,
  side = false,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  wide?: boolean;
  side?: boolean;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const before = document.activeElement as HTMLElement;
    panel.current?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopImmediatePropagation();
        closeRef.current();
      }
      if (e.key === "Tab" && panel.current) {
        const nodes = Array.from(
          panel.current.querySelectorAll<HTMLElement>(
            'button:not(:disabled), input:not(:disabled), select, textarea, a[href], [tabindex="0"]',
          ),
        );
        const first = nodes[0],
          last = nodes[nodes.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", key);
    const priorOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", key);
      document.body.style.overflow = priorOverflow;
      before?.focus();
    };
  }, []);
  return (
    <div
      className={`modal-backdrop ${side ? "policy-menu-backdrop" : ""}`}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        ref={panel}
        className={`modal ${wide ? "wide" : ""} ${side ? "policy-menu-panel" : ""}`}
        id={side ? "policy-menu" : undefined}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
      >
        <div className="modal-heading">
          <h2>{title}</h2>
          <button
            className="icon-button"
            onClick={onClose}
            aria-label="Close dialog"
          >
            <X size={20} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

export default function App() {
  const [theme, setTheme] = useState<"light" | "dark">(
    () => document.documentElement.dataset.theme === "dark" ? "dark" : "light",
  );
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [page, setPage] = useState("workspace");
  const [filter, setFilter] = useState<Decision | "all" | "attention">("all");
  const [query, setQuery] = useState("");
  const [poQuery, setPoQuery] = useState("");
  const [poStatus, setPoStatus] = useState<"all" | "approved" | "other">("all");
  const [selectedPo, setSelectedPo] = useState<string | null>(null);
  const [selectedPoDraft, setSelectedPoDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  const [notice, setNotice] = useState<{
    message: string;
    error: boolean;
  } | null>(null);
  const [upload, setUpload] = useState<string | null>(() => localStorage.getItem("ledger-active-upload") ? "invoice" : null);
  const [selected, setSelected] = useState<string | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [removeId, setRemoveId] = useState<string | null>(null);
  const [menu, setMenu] = useState(false);
  const [policiesOpen, setPoliciesOpen] = useState(false);
  const notify = (message: string, error = false) =>
    setNotice({ message, error });
  const refresh = async () => {
    try {
      setWorkspace(await api<Workspace>("/workspace"));
    } catch (e) {
      notify((e as Error).message, true);
    }
  };
  useEffect(() => {
    void refresh();
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute(
      "content", theme === "dark" ? "#111d17" : "#f6f7f5",
    );
  }, [theme]);
  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    try { localStorage.setItem("ledger-theme", next); } catch { /* Keep the in-page choice. */ }
  };
  useEffect(() => {
    if (notice && !notice.error) {
      const timer = setTimeout(() => setNotice(null), 6000);
      return () => clearTimeout(timer);
    }
  }, [notice]);
  const act = async (name: string, path: string, method = "POST") => {
    setBusy(name);
    try {
      const next = await api<Workspace>(path, { method });
      setWorkspace(next);
      notify(
        name === "demo"
          ? "13 synthetic invoices reviewed. Open an invoice to inspect the evidence."
          : name === "clear"
            ? "Workspace cleared."
            : "Recommendations updated.",
      );
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setBusy("");
    }
  };
  const reviews = workspace?.reviews || [];
  const selectedReview = reviews.find((r) => r.id === selected);
  const purchaseOrders = workspace?.purchase_orders || [];
  const poDrafts: [string, PurchaseOrderDraft][] = Object.entries(workspace?.po_drafts || {});
  const selectedDraft = selectedPoDraft ? workspace?.po_drafts?.[selectedPoDraft] : null;
  const selectedDraftDocument = workspace?.documents.find((document) => document.id === selectedPoDraft);
  const selectedPoRecord = purchaseOrders.find((po) => po.po_number === selectedPo);
  const approvedPoCount = purchaseOrders.filter((po) => po.status.trim().toLowerCase() === "approved").length;
  const visiblePurchaseOrders = purchaseOrders.filter((po) => {
    const approved = po.status.trim().toLowerCase() === "approved";
    return (poStatus === "all" || (poStatus === "approved" ? approved : !approved)) &&
      `${po.po_number} ${po.vendor_name} ${po.vendor_id} ${po.currency} ${po.status} ${po.items.map((item) => item.description).join(" ")}`
        .toLowerCase().includes(poQuery.trim().toLowerCase());
  }).sort((a, b) => a.po_number.localeCompare(b.po_number, undefined, { numeric: true }));
  const filtered = reviews.filter(
    (r) =>
      (filter === "all" ||
        (filter === "attention"
          ? r.decision !== "ready"
          : r.decision === filter)) &&
      `${r.invoice.invoice_number} ${r.invoice.vendor_name} ${r.invoice.po_number} ${r.filename}`
        .toLowerCase()
        .includes(query.toLowerCase()),
  );
  const counts = Object.fromEntries(
    (Object.keys(labels) as Decision[]).map((key) => [
      key,
      reviews.filter((r) => r.decision === key).length,
    ]),
  ) as Record<Decision, number>;
  const readyPercent = reviews.length
    ? Math.round((counts.ready / reviews.length) * 100)
    : 0;
  const missingCurrencyCount = reviews.filter(
    (r) => r.invoice.total && !r.invoice.currency,
  ).length;
  const docToRemove = workspace?.documents.find((d) => d.id === removeId);
  const update = (next: Workspace) => {
    setWorkspace(next);
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setPage("workspace");
          }}
        >
          Invoices
        </a>
        <span className="nav-label">WORKSPACE</span>
        <nav>
          {[
            {
              id: "workspace",
              label: "Invoice review",
              icon: LayoutDashboard,
              count: reviews.length,
            },
            {
              id: "documents",
              label: "Source documents",
              icon: FolderOpen,
              count: workspace?.documents.length,
            },
            {
              id: "purchase_orders",
              label: "Purchase orders",
              icon: FileCheck2,
              count: purchaseOrders.length + poDrafts.length,
            },
            { id: "policy", label: "Review policy", icon: Settings2 },
            { id: "activity", label: "Activity log", icon: History },
          ].map((item) => (
            <button
              key={item.id}
              aria-label={item.label}
              className={`nav-item ${page === item.id ? "active" : ""}`}
              onClick={() => setPage(item.id)}
            >
              <item.icon size={18} />
              <span>{item.label}</span>
              {!!item.count && <span className="nav-count">{item.count}</span>}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div>
            <strong>Finance operations</strong>
            <small>No sign-in needed</small>
          </div>
          <span className="online-dot" />
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            Accounts payable <ChevronRight size={13} />
            <span>
              {page === "workspace"
                ? "Invoice review"
                : page === "documents"
                  ? "Source documents"
                  : page === "purchase_orders"
                    ? "Purchase orders"
                  : page === "policy"
                    ? "Review policy"
                    : page === "ai"
                      ? "AI settings"
                      : "Activity log"}
            </span>
          </div>
          <div className="topbar-right">
            <button
              type="button"
              className="icon-button theme-toggle"
              onClick={toggleTheme}
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
              aria-pressed={theme === "dark"}
              title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
            >
              {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
            </button>
            <button
              className="button secondary small policies-menu-trigger"
              disabled={!workspace}
              aria-haspopup="dialog"
              aria-controls="policy-menu"
              aria-expanded={policiesOpen}
              onClick={() => setPoliciesOpen(true)}
            >
              <ShieldCheck size={15} />
              Policies
              <ChevronDown size={13} />
            </button>
            <button
              className="icon-button"
              aria-label="Refresh workspace"
              onClick={() => void refresh()}
            >
              <RefreshCw size={16} />
            </button>
          </div>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">FINANCE OPERATIONS</div>
              <h1>
                {page === "workspace"
                  ? "Invoice review"
                  : page === "documents"
                    ? "Source documents"
                    : page === "purchase_orders"
                      ? "Purchase orders"
                    : page === "policy"
                      ? "Review policy"
                      : page === "ai"
                        ? "AI settings"
                        : "Activity log"}
                <span className="heading-dot">.</span>
              </h1>
            </div>
            <div className="heading-actions">
              {page === "workspace" && (
                <div className="export-wrapper">
                  <Button
                    className="secondary"
                    onClick={() => setMenu(!menu)}
                    disabled={!reviews.length}
                  >
                    <ArrowDownToLine size={15} />
                    Export
                    <ChevronDown size={13} />
                  </Button>
                  {menu && (
                    <div className="export-menu">
                      <a
                        href="/api/export?format=csv"
                        onClick={() => setMenu(false)}
                      >
                        Summary CSV
                      </a>
                      <a
                        href="/api/export?format=json"
                        onClick={() => setMenu(false)}
                      >
                        Full evidence JSON
                      </a>
                    </div>
                  )}
                </div>
              )}
              {(page !== "purchase_orders" || purchaseOrders.length > 0 || poDrafts.length > 0) && (
                <Button className="primary" onClick={() => setUpload(page === "purchase_orders" ? "purchase_orders" : "invoice")}>
                  <Plus size={17} />
                  {page === "purchase_orders" ? "Upload purchase orders" : "Upload documents"}
                </Button>
              )}
            </div>
          </div>

          {!workspace && (
            <div className="loading-panel">
              <LoaderCircle className="spin" />
              <p>Connecting to your workspace…</p>
              <Button onClick={() => void refresh()}>Try again</Button>
            </div>
          )}
          {workspace && page === "workspace" && (
            <>
              <section className="dashboard-overview" aria-label="Invoice overview">
                <div className="dashboard-heading">
                  <div>
                    <span className="eyebrow">OVERVIEW</span>
                    <h2>Workspace insights</h2>
                  </div>
                  <span>{reviews.length} invoice{reviews.length === 1 ? "" : "s"} reviewed</span>
                </div>
                <div className="dashboard-kpis">
                  <button className={`dashboard-kpi ${filter === "all" ? "chosen" : ""}`} aria-pressed={filter === "all"} onClick={() => setFilter("all")}>
                    <span>Total invoices <Files size={17} /></span>
                    <strong>{reviews.length}</strong>
                  </button>
                  <button className={`dashboard-kpi ready ${filter === "ready" ? "chosen" : ""}`} aria-pressed={filter === "ready"} onClick={() => setFilter("ready")}>
                    <span>Ready for approval <CheckCircle2 size={17} /></span>
                    <strong>{counts.ready}</strong>
                    <small>{readyPercent}% of invoices</small>
                  </button>
                  <button className={`dashboard-kpi attention ${filter === "attention" ? "chosen" : ""}`} aria-pressed={filter === "attention"} onClick={() => setFilter("attention")}>
                    <span>Needs attention <CircleAlert size={17} /></span>
                    <strong>{reviews.length - counts.ready}</strong>
                  </button>
                  <div className="dashboard-kpi value">
                    <span>Known-currency total <ArrowUpRight size={17} /></span>
                    <div className="dashboard-values">
                      {Object.keys(workspace.totals_by_currency).length
                        ? Object.entries(workspace.totals_by_currency).map(([currency, total]) => <strong key={currency}>{formatAmount(total, currency)}</strong>)
                        : <strong>—</strong>}
                    </div>
                    <small>{missingCurrencyCount ? `${missingCurrencyCount} missing currency excluded · ` : ""}Includes held/duplicates</small>
                  </div>
                </div>
                <div className="dashboard-breakdown">
                  <div className="dashboard-breakdown-head"><strong>Recommendation breakdown</strong><span>{reviews.length} total</span></div>
                  <div className="dashboard-segments" role="img" aria-label={`${counts.ready} ready, ${counts.clarification} clarification, ${counts.procurement} procurement, ${counts.hold} on hold`}>
                    {(Object.keys(labels) as Decision[]).map((key) => counts[key] > 0 && <span key={key} className={key} style={{ width: `${counts[key] / reviews.length * 100}%` }} />)}
                  </div>
                  <div className="dashboard-legend">
                    {(Object.keys(labels) as Decision[]).map((key) => <button key={key} className={filter === key ? "chosen" : ""} aria-pressed={filter === key} onClick={() => setFilter(filter === key ? "all" : key)}><i className={key} />{shortLabels[key]} <strong>{counts[key]}</strong></button>)}
                  </div>
                </div>
              </section>
              <section className="queue-panel">
                <div className="queue-heading">
                  <div>
                    <h2>
                      Invoice queue <span>{reviews.length}</span>
                    </h2>
                  </div>
                  <Button
                    className="secondary small"
                    busy={busy === "review"}
                    onClick={() => void act("review", "/review")}
                    disabled={!reviews.length || !!busy}
                  >
                    {busy !== "review" && <RefreshCw size={14} />}Run checks
                  </Button>
                </div>
                <div className="queue-tools">
                  <div className="filter-tabs">
                    <button
                      className={filter === "all" ? "active" : ""}
                      onClick={() => setFilter("all")}
                    >
                      All invoices <span>{reviews.length}</span>
                    </button>
                    <button
                      className={filter === "attention" ? "active" : ""}
                      onClick={() => setFilter("attention")}
                    >
                      Needs attention{" "}
                      <span>{reviews.length - counts.ready}</span>
                    </button>
                    {filter !== "all" && filter !== "attention" && (
                      <button
                        className="clear-filter"
                        onClick={() => setFilter("all")}
                      >
                        {shortLabels[filter]}
                        <X size={11} />
                      </button>
                    )}
                  </div>
                  <div className="search-field">
                    <Search size={15} />
                    <input
                      aria-label="Search invoices"
                      placeholder="Search invoice, vendor or PO"
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                    />
                    {query && (
                      <button
                        aria-label="Clear search"
                        onClick={() => setQuery("")}
                      >
                        <X size={13} />
                      </button>
                    )}
                  </div>
                </div>
                {reviews.length > 0 ? (
                  <div className="table-scroll">
                    <table className="invoice-table">
                      <thead>
                        <tr>
                          <th>INVOICE</th>
                          <th>VENDOR</th>
                          <th>PO REFERENCE</th>
                          <th className="amount-cell">TOTAL AMOUNT</th>
                          <th>RECOMMENDATION</th>
                          <th>
                            <span className="sr-only">Open</span>
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {filtered.map((r) => (
                          <tr key={r.id} onClick={() => setSelected(r.id)}>
                            <td>
                              <div className="invoice-name">
                                <span className="file-icon">
                                  <FileText size={18} />
                                </span>
                                <div>
                                  <button
                                    className="table-open"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setSelected(r.id);
                                    }}
                                  >
                                    {r.invoice.invoice_number ||
                                      "Missing number"}
                                  </button>
                                  <small>
                                    {r.invoice.invoice_date || "Date not found"}
                                    {r.invoice.extraction_method ===
                                      "AI assisted" && " · AI extracted"}
                                  </small>
                                </div>
                              </div>
                            </td>
                            <td>
                              <strong className="vendor-name">
                                {r.invoice.vendor_name || "Unknown vendor"}
                              </strong>
                              <small>
                                {r.matched_vendor?.vendor_id || "Not verified"}
                              </small>
                            </td>
                            <td>
                              <span
                                className={`po-ref ${!r.invoice.po_number ? "muted" : ""}`}
                              >
                                {r.invoice.po_number || "Not provided"}
                              </span>
                            </td>
                            <td className="amount-cell">
                              <strong>
                                {formatAmount(
                                  r.invoice.total,
                                  r.invoice.currency,
                                )}
                              </strong>
                              <small>
                                {r.invoice.currency || "Currency unknown"}
                              </small>
                            </td>
                            <td>
                              <Badge decision={r.decision} />
                              {r.resolution && (
                                <small className="noted">
                                  Reviewer note recorded
                                </small>
                              )}
                            </td>
                            <td>
                              <button
                                className="row-arrow"
                                aria-label={`Review ${r.invoice.invoice_number || r.filename}`}
                              >
                                <ArrowUpRight size={17} />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {filtered.length === 0 && (
                      <div className="empty-search">
                        <Search size={25} />
                        <h3>No matching invoices</h3>
                        <Button
                          onClick={() => {
                            setFilter("all");
                            setQuery("");
                          }}
                        >
                          Clear filters
                        </Button>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="empty-workspace">
                    <div className="document-illustration">
                      <div className="illus-back" />
                      <div className="illus-front">
                        <FileText size={30} />
                        <span />
                        <span />
                        <span />
                        <div>
                          <Check size={14} />
                        </div>
                      </div>
                      <span className="illus-spark">✦</span>
                    </div>
                    <h3>No invoices yet</h3>
                    <div className="empty-actions">
                      <Button
                        className="primary"
                        onClick={() => setUpload("invoice")}
                      >
                        <UploadCloud size={16} />
                        Upload your first invoice
                      </Button>
                      <Button
                        className="secondary"
                        busy={busy === "demo"}
                        disabled={!!busy || workspace.documents.length > 0}
                        onClick={() => void act("demo", "/demo")}
                      >
                        <Sparkles size={15} />
                        Try 13 sample invoices
                      </Button>
                    </div>
                    <a className="text-link" href="/api/samples">
                      Download synthetic sample documents{" "}
                      <ArrowDownToLine size={13} />
                    </a>
                  </div>
                )}
              </section>
              <div className="context-strip">
                <div className="context-title"><Files size={17} /><span>Reference data</span></div>
                {[
                  { name: "Purchase orders", count: workspace.purchase_orders.length, kind: "purchase_orders" },
                  { name: "Vendors", count: workspace.vendors.length, kind: "vendors" },
                  { name: "Prior invoices", count: workspace.history_count, kind: "history" },
                ].map((c) => (
                  <button key={c.kind} onClick={() => setUpload(c.kind)} className={`context-chip ${c.count ? "complete" : ""}`}>
                    {c.count ? <CheckCircle2 size={13} /> : <Plus size={13} />}
                    <span>{c.count} {c.name}</span>
                  </button>
                ))}
                <button className="policy-link" onClick={() => setPage("policy")}>
                  <Settings2 size={13} />{workspace.policy.amount_tolerance_percent}% amount tolerance<ArrowUpRight size={13} />
                </button>
              </div>
            </>
          )}

          {workspace && page === "documents" && (
            <>
              <div className="documents-explainer">
                <div><h2>Document categories</h2></div>
                <a className="button secondary" href="/api/samples">
                  <ArrowDownToLine size={16} />
                  Sample document pack
                </a>
              </div>
              <div className="category-grid">
                {categories.map((c) => (
                  <button
                    className="category-card"
                    key={c.id}
                    onClick={() => setUpload(c.id)}
                  >
                    <c.icon size={22} />
                    <strong>{c.name}</strong>
                    <span>
                      {
                        workspace.documents.filter((d) => d.kind === c.id)
                          .length
                      }{" "}
                      files
                    </span>
                    <Plus size={16} />
                  </button>
                ))}
              </div>
              <section className="queue-panel">
                <div className="queue-heading">
                  <div>
                    <h2>
                      Document library <span>{workspace.documents.length}</span>
                    </h2>
                  </div>
                  <Button
                    className="danger-ghost small"
                    disabled={!workspace.documents.length || !!busy}
                    onClick={() => setConfirmClear(true)}
                  >
                    <Trash2 size={14} />
                    Clear workspace
                  </Button>
                </div>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>DOCUMENT</th>
                        <th>CATEGORY</th>
                        <th>RECORDS / PAGES</th>
                        <th>UPLOADED</th>
                        <th>
                          <span className="sr-only">Actions</span>
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {workspace.documents.map((d) => (
                        <tr key={d.id}>
                          <td>
                            <a
                              className="document-link"
                              href={`/api/documents/${d.id}`}
                              target="_blank"
                              rel="noreferrer"
                            >
                              <FileText size={17} />
                              {d.filename}
                              <ArrowUpRight size={12} />
                            </a>
                            <small>
                              {(d.size / 1024).toFixed(1)} KB{" "}
                              {d.methods.includes("ocr") && "· OCR"}
                              {d.pending_interpretation && " · Awaiting review"}
                            </small>
                          </td>
                          <td>
                            <span className="neutral-tag">
                              {categories.find((c) => c.id === d.kind)?.name}
                            </span>
                          </td>
                          <td>
                            {d.record_count} records
                            {d.page_count > 0 && ` · ${d.page_count} pages`}
                          </td>
                          <td className="muted">{dateTime(d.uploaded_at)}</td>
                          <td>
                            <button
                              className="icon-button danger-text"
                              aria-label={`Remove ${d.filename}`}
                              onClick={() => setRemoveId(d.id)}
                            >
                              <Trash2 size={15} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!workspace.documents.length && (
                    <div className="empty-search">
                      <FolderOpen size={30} />
                      <h3>No documents yet</h3>
                    </div>
                  )}
                </div>
              </section>
            </>
          )}
          {workspace && page === "purchase_orders" && (
            <>
            {poDrafts.length > 0 && <section className="po-drafts-panel">
              <div className="po-drafts-heading"><h2>POs awaiting review <span>{poDrafts.length}</span></h2></div>
              <div className="po-draft-cards">{poDrafts.map(([id, draft]) => {
                const document = workspace.documents.find((item) => item.id === id);
                if (!document) return null;
                return <button key={id} className="po-draft-card" onClick={() => setSelectedPoDraft(id)}>
                  <FileCheck2 size={20} />
                  <div><strong>{draft.values.po_number || document.filename}</strong><span>{document.filename} · {draft.method} · Review required{draft.uncertainties.length ? ` · ${draft.uncertainties.length} extraction note${draft.uncertainties.length === 1 ? "" : "s"}` : ""}</span></div>
                  <span className="po-draft-review-link">Review PO <ArrowRight size={14} /></span>
                </button>;
              })}</div>
            </section>}
            <section className="queue-panel po-panel">
              <div className="queue-heading">
                <h2>Purchase orders <span>{purchaseOrders.length}</span></h2>
              </div>
              {purchaseOrders.length > 0 && <div className="queue-tools po-tools">
                <div className="filter-tabs">
                  <button className={poStatus === "all" ? "active" : ""} aria-pressed={poStatus === "all"} onClick={() => setPoStatus("all")}>All <span>{purchaseOrders.length}</span></button>
                  <button className={poStatus === "approved" ? "active" : ""} aria-pressed={poStatus === "approved"} onClick={() => setPoStatus("approved")}>Approved <span>{approvedPoCount}</span></button>
                  <button className={poStatus === "other" ? "active" : ""} aria-pressed={poStatus === "other"} onClick={() => setPoStatus("other")}>Other status <span>{purchaseOrders.length - approvedPoCount}</span></button>
                </div>
                <div className="search-field">
                  <Search size={15} />
                  <input aria-label="Search purchase orders" placeholder="Search PO, vendor or item" value={poQuery} onChange={(e) => setPoQuery(e.target.value)} />
                  {poQuery && <button aria-label="Clear PO search" onClick={() => setPoQuery("")}><X size={13} /></button>}
                </div>
              </div>}
              {purchaseOrders.length ? (
                <div className="table-scroll">
                  <table className="po-table">
                    <thead><tr><th>PO NUMBER</th><th>VENDOR</th><th>STATUS</th><th>VALIDITY</th><th>LINES</th><th className="amount-cell">AUTHORIZED AMOUNT</th><th><span className="sr-only">Open</span></th></tr></thead>
                    <tbody>
                      {visiblePurchaseOrders.map((po) => (
                        <tr key={po.po_number} onClick={() => setSelectedPo(po.po_number)}>
                          <td><button className="table-open" onClick={(e) => { e.stopPropagation(); setSelectedPo(po.po_number); }}>{po.po_number}</button></td>
                          <td><strong className="vendor-name">{po.vendor_name || "Vendor name unavailable"}</strong><small>{po.vendor_id || "No vendor ID"}</small></td>
                          <td><span className={`po-status ${po.status.trim().toLowerCase() === "approved" ? "approved" : "other"}`}>{po.status || "Unknown"}</span></td>
                          <td><span className="po-date">{po.valid_from || po.valid_to ? `${displayDate(po.valid_from)} → ${displayDate(po.valid_to)}` : "—"}</span></td>
                          <td>{po.items.length}</td>
                          <td className="amount-cell"><strong>{formatAmount(po.amount, po.currency)}</strong><small>{po.amount_basis} · {po.currency}</small></td>
                          <td><button className="row-arrow" aria-label={`Open purchase order ${po.po_number}`} onClick={(e) => { e.stopPropagation(); setSelectedPo(po.po_number); }}><ArrowUpRight size={17} /></button></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!visiblePurchaseOrders.length && <div className="empty-search"><Search size={25} /><h3>No matching purchase orders</h3><Button onClick={() => { setPoQuery(""); setPoStatus("all"); }}>Clear filters</Button></div>}
                </div>
              ) : (
                <div className="empty-search po-empty"><FileCheck2 size={30} /><h3>No active purchase orders yet</h3>{poDrafts.length === 0 && <Button className="primary" onClick={() => setUpload("purchase_orders")}><Plus size={15} /> Upload purchase orders</Button>}</div>
              )}
            </section>
            </>
          )}
          {workspace && page === "ai" && (
            <AISettings workspace={workspace} update={update} notify={notify} />
          )}
          {workspace &&
            Object.keys(workspace.reference_drafts || {}).length > 0 &&
            page !== "ai" && (
              <div className="external-banner">
                <Sparkles size={16} />
                <span>
                  An AI policy interpretation is waiting for human review. Your
                  active policy is unchanged.
                </span>
                <button className="text-link" onClick={() => setPage("ai")}>
                  Review draft
                </button>
              </div>
            )}
          {workspace && page === "policy" && (
            <PolicyForm
              policy={workspace.policy}
              update={update}
              notify={notify}
            />
          )}
          {workspace && page === "activity" && (
            <section className="activity-panel">
              <div className="queue-heading">
                <div>
                  <h2>
                    Workspace activity <span>{workspace.audit.length}</span>
                  </h2>
                </div>
                <a
                  className="button secondary small"
                  href="/api/export?format=json"
                >
                  <ArrowDownToLine size={14} />
                  Export audit trail
                </a>
              </div>
              <div className="activity-list">
                {workspace.audit.map((a) => (
                  <div className="activity-item" key={a.id}>
                    <div className={`activity-icon ${a.action}`}>
                      <History size={16} />
                    </div>
                    <div>
                      <strong>{a.action.replaceAll("_", " ")}</strong>
                      <p>{a.message}</p>
                      <span>{dateTime(a.timestamp)}</span>
                    </div>
                    {a.document_id &&
                      reviews.some((r) => r.id === a.document_id) && (
                        <button
                          className="text-link"
                          onClick={() => setSelected(a.document_id)}
                        >
                          View invoice
                          <ArrowUpRight size={13} />
                        </button>
                      )}
                  </div>
                ))}
                {!workspace.audit.length && (
                  <div className="empty-search">
                    <Clock3 size={28} />
                    <h3>No activity yet</h3>
                  </div>
                )}
              </div>
            </section>
          )}
          <footer className="page-footer">
            <span>
              INVOICES <span> / </span> ACCOUNTS PAYABLE
            </span>
            <span>
              <LockKeyhole size={12} />
              Source files stored locally
            </span>
          </footer>
        </main>
      </div>
      {notice && (
        <div
          className={`toast ${notice.error ? "error" : ""}`}
          role={notice.error ? "alert" : "status"}
        >
          {notice.error ? (
            <CircleAlert size={19} />
          ) : (
            <CheckCircle2 size={19} />
          )}
          <span>{notice.message}</span>
          <button
            className="icon-button"
            onClick={() => setNotice(null)}
            aria-label="Dismiss notification"
          >
            <X size={16} />
          </button>
        </div>
      )}
      {policiesOpen && workspace && (
        <Modal title="Workspace policies" side onClose={() => setPoliciesOpen(false)}>
          <PolicyMenu
            workspace={workspace}
            onManage={() => { setPoliciesOpen(false); setPage("policy"); }}
            onDrafts={() => { setPoliciesOpen(false); setPage("ai"); }}
            onAISettings={() => { setPoliciesOpen(false); setPage("ai"); }}
          />
        </Modal>
      )}
      {upload && (
        <UploadModal
          initialKind={upload}
          onReview={(id) => { setUpload(null); setSelected(id); }}
          onPoDraft={(id) => { setUpload(null); setPage("purchase_orders"); setSelectedPoDraft(id); }}
          onClose={() => setUpload(null)}
          update={update}
          notify={notify}
        />
      )}
      {selectedReview && (
        <ReviewDrawer
          aiEnabled={workspace?.ai_settings?.ready || false}
          processingTrace={workspace?.documents.find(d => d.id === selected)?.processing_trace}
          review={selectedReview}
          onClose={() => setSelected(null)}
          update={update}
          notify={notify}
        />
      )}
      {selectedPoRecord && (
        <Modal title={`Purchase order ${selectedPoRecord.po_number}`} wide onClose={() => setSelectedPo(null)}>
          <PurchaseOrderDetails
            po={selectedPoRecord}
            reviews={reviews}
            onOpenInvoice={(id) => { setSelectedPo(null); setSelected(id); }}
          />
        </Modal>
      )}
      {selectedDraft && selectedDraftDocument && (
        <Modal title={`Review PO · ${selectedDraftDocument.filename}`} wide onClose={() => setSelectedPoDraft(null)}>
          <PurchaseOrderDraftForm document={selectedDraftDocument} draft={selectedDraft} update={update} notify={notify} onClose={() => setSelectedPoDraft(null)} />
        </Modal>
      )}
      {confirmClear && (
        <Modal
          title="Clear this workspace?"
          onClose={() => setConfirmClear(false)}
        >
          <div className="confirm-content">
            <p>
              This deletes uploaded files, reference records, corrections, and
              the activity log from this local workspace. Download the evidence
              export first if you need a copy.
            </p>
            <div className="form-actions">
              <Button
                className="secondary"
                onClick={() => setConfirmClear(false)}
              >
                Keep workspace
              </Button>
              <Button
                className="danger"
                onClick={() => {
                  setConfirmClear(false);
                  setSelected(null);
                  void act("clear", "/workspace", "DELETE");
                }}
              >
                Clear workspace
              </Button>
            </div>
          </div>
        </Modal>
      )}
      {docToRemove && (
        <Modal
          title="Remove source document?"
          onClose={() => setRemoveId(null)}
        >
          <div className="confirm-content">
            <p>
              <strong>{docToRemove.filename}</strong> and its imported records
              will be removed. Dependent recommendations will be recomputed.
            </p>
            <div className="form-actions">
              <Button className="secondary" onClick={() => setRemoveId(null)}>
                Keep document
              </Button>
              <Button
                className="danger"
                onClick={() => {
                  setRemoveId(null);
                  void act("remove", `/documents/${docToRemove.id}`, "DELETE");
                }}
              >
                Remove document
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

function PurchaseOrderDetails({ po, reviews, onOpenInvoice }: {
  po: PurchaseOrder;
  reviews: Review[];
  onOpenInvoice: (id: string) => void;
}) {
  const normalizePo = (value: string) => value.toLowerCase().replace(/[^a-z0-9]/g, "");
  const invoices = reviews.filter((review) => review.invoice.po_number && normalizePo(review.invoice.po_number) === normalizePo(po.po_number));
  const source = po.evidence;
  return (
    <div className="po-detail">
      <div className="po-detail-lead">
        <div><span className="eyebrow">PURCHASE ORDER</span><h3>{po.po_number}</h3><span className={`po-status ${po.status.trim().toLowerCase() === "approved" ? "approved" : "other"}`}>{po.status || "Unknown"}</span></div>
        <div className="po-detail-amount"><small>AUTHORIZED AMOUNT · {po.amount_basis.toUpperCase()}</small><strong>{formatAmount(po.amount, po.currency)}</strong></div>
      </div>
      <div className="po-detail-facts">
        <div><span>Vendor</span><strong>{po.vendor_name || "—"}</strong></div>
        <div><span>Vendor ID</span><strong>{po.vendor_id || "—"}</strong></div>
        <div><span>Currency</span><strong>{po.currency}</strong></div>
        <div><span>Amount basis</span><strong>{po.amount_basis === "net" ? "Net (before tax)" : "Gross (including tax)"}</strong></div>
        <div><span>Valid from</span><strong>{displayDate(po.valid_from)}</strong></div>
        <div><span>Valid to</span><strong>{displayDate(po.valid_to)}</strong></div>
      </div>
      <section className="po-detail-section">
        <div className="po-detail-section-heading"><h4>Line items</h4><span>{po.items.length}</span></div>
        {po.items.length ? <div className="table-scroll"><table className="po-line-table"><thead><tr><th>DESCRIPTION</th><th>SKU</th><th>QUANTITY</th><th className="amount-cell">UNIT PRICE</th><th className="amount-cell">LINE AMOUNT</th></tr></thead><tbody>{po.items.map((item, index) => <tr key={`${item.sku || item.description}-${index}`}><td><strong>{item.description}</strong></td><td>{item.sku || "—"}</td><td>{item.quantity ?? "—"}</td><td className="amount-cell">{formatAmount(item.unit_price, po.currency)}</td><td className="amount-cell">{formatAmount(item.amount, po.currency)}</td></tr>)}</tbody></table></div> : <p className="po-detail-empty">No line items in this PO record.</p>}
      </section>
      <section className="po-detail-section">
        <div className="po-detail-section-heading"><h4>Invoice references</h4><span>{invoices.length}</span></div>
        {invoices.length ? <div className="po-related-invoices">{invoices.map((review) => <button key={review.id} onClick={() => onOpenInvoice(review.id)}><span>{review.invoice.invoice_number || review.filename}</span><Badge decision={review.decision} /><ArrowUpRight size={15} /></button>)}</div> : <p className="po-detail-empty">No uploaded invoice references this PO.</p>}
      </section>
      <section className="po-detail-section">
        <div className="po-detail-section-heading"><h4>Source document</h4></div>
        {source?.document_id ? <a className="po-source-link" href={`/api/documents/${source.document_id}${source.page ? `#page=${source.page}` : ""}`} target="_blank" rel="noreferrer"><FileText size={16} />{source.filename || "Open source"}{source.page ? ` · page ${source.page}` : ""}<ArrowUpRight size={14} /></a> : <span className="po-detail-empty">{source?.filename || "Source unavailable"}</span>}
        {source?.excerpt && <details className="po-source-excerpt"><summary>Source excerpt <ChevronDown size={14} /></summary><blockquote>{source.excerpt}</blockquote></details>}
      </section>
    </div>
  );
}

function UploadModal({
  initialKind,
  onReview,
  onPoDraft,
  onClose,
  update,
  notify,
}: {
  initialKind: string;
  onReview: (id: string) => void;
  onPoDraft: (id: string) => void;
  onClose: () => void;
  update: (w: Workspace) => void;
  notify: (s: string, error?: boolean) => void;
}) {
  const [kind, setKind] = useState(initialKind);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(!!localStorage.getItem("ledger-active-upload"));
  const [jobId, setJobId] = useState<string | null>(() => localStorage.getItem("ledger-active-upload"));
  const [job, setJob] = useState<UploadJob | null>(null);
  const [monitorError, setMonitorError] = useState("");
  const callbacks = useRef({ update, notify });
  callbacks.current = { update, notify };
  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await api<UploadJob>(`/uploads/${jobId}`);
        if (cancelled) return;
        setJob(next);
        setMonitorError("");
        if (next.status === "completed" || next.status === "failed") {
          const state = await api<Workspace>("/workspace");
          if (cancelled) return;
          callbacks.current.update(state);
          localStorage.removeItem("ledger-active-upload");
          setBusy(false);
          if (next.status === "completed" && next.accepted.length)
            callbacks.current.notify(`${next.accepted.length} document(s) saved. Processing results are ready.`);
          return;
        }
      } catch (e) {
        if (cancelled) return;
        const message = (e as Error).message;
        setMonitorError(message);
        if (message.includes("progress is unavailable")) {
          localStorage.removeItem("ledger-active-upload");
          setBusy(false);
          return;
        }
      }
      if (!cancelled) timer = setTimeout(poll, 700);
    };
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [jobId]);
  const [errors, setErrors] = useState<{ filename: string; message: string }[]>(
    [],
  );
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const category = categories.find((c) => c.id === kind)!;
  const addFiles = (list: FileList | null) => {
    if (!list) return;
    // FileList is live: clearing the picker below empties it before React runs
    // a queued state update. Capture the File objects while they still exist.
    const selectedFiles = Array.from(list);
    setErrors([]);
    setFiles((previous) => [...previous, ...selectedFiles].slice(0, 25));
  };
  const send = async () => {
    setBusy(true);
    setErrors([]);
    const form = new FormData();
    form.set("kind", kind);
    files.forEach((file) => form.append("files", file));
    try {
      const next = await api<UploadJob>("/uploads", { method: "POST", body: form });
      localStorage.setItem("ledger-active-upload", next.id);
      setJob(next);
      setJobId(next.id);
    } catch (e) {
      setErrors([{ filename: "Upload", message: (e as Error).message }]);
      setBusy(false);
    }
  };
  return (
    <Modal
      title="Upload documents"
      onClose={() => {
        if (!busy) onClose();
      }}
      wide
    >
      {monitorError && <div className="upload-errors" role="alert">{monitorError}{busy && " Reconnecting to progress updates…"}</div>}
      {job ? <UploadProgress job={job} onReview={onReview} onPoDraft={onPoDraft} /> : jobId ? <div className="processing-note"><LoaderCircle className="spin" size={18} /> Reconnecting to your upload…</div> : <div className="upload-layout">
        <div className="upload-kinds">
          {categories.map((c) => (
            <button
              disabled={busy}
              key={c.id}
              className={kind === c.id ? "active" : ""}
              onClick={() => {
                setKind(c.id);
                setFiles([]);
                setErrors([]);
              }}
            >
              <c.icon size={17} />
              <span>{c.name}</span>
              <ChevronRight size={13} />
            </button>
          ))}
        </div>
        <div className="upload-main">
          <h3>{category.name}</h3>
          <div
            className={`dropzone ${dragging ? "dragging" : ""} ${busy ? "disabled" : ""}`}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if ((e.key === "Enter" || e.key === " ") && !busy)
                input.current?.click();
            }}
            onClick={() => {
              if (!busy) input.current?.click();
            }}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              if (!busy) addFiles(e.dataTransfer.files);
            }}
          >
            <span className="upload-cloud">
              <UploadCloud size={27} />
            </span>
            <strong>
              Drop your files here, or <span>browse</span>
            </strong>
            <small>
              {category.accept
                .replaceAll(".", "")
                .toUpperCase()
                .split(",")
                .join(", ")}{" "}
              · Up to 20 MB per file · 25 files per upload
            </small>
            <input
              ref={input}
              type="file"
              multiple
              accept={category.accept}
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => {
                addFiles(e.target.files);
                e.target.value = "";
              }}
              hidden
            />
          </div>
          {kind !== "invoice" && (
            <div className="template-help">
              <FileText size={16} />
              <a href={`/api/templates/${kind}`}>
                Get JSON template
                <ArrowDownToLine size={13} />
              </a>
            </div>
          )}
          <div className="selected-files">
            {files.map((f, i) => (
              <div key={`${f.name}-${i}`}>
                <FileText size={17} />
                <span>
                  <strong>{f.name}</strong>
                  <small>{(f.size / 1024).toFixed(1)} KB</small>
                </span>
                <button
                  disabled={busy}
                  className="icon-button"
                  onClick={() => setFiles(files.filter((_, n) => n !== i))}
                  aria-label={`Remove ${f.name}`}
                >
                  <X size={15} />
                </button>
              </div>
            ))}
          </div>
          {errors.length > 0 && (
            <div className="upload-errors" role="alert">
              {errors.map((e, i) => (
                <p key={i}>
                  <strong>{e.filename}</strong>
                  <br />
                  {e.message}
                </p>
              ))}
            </div>
          )}
          {busy && (
            <p className="processing-note">
              <LoaderCircle size={15} className="spin" />
              Processing documents…
            </p>
          )}
        </div>
      </div>}
      <div className="modal-footer">
        <div>
          <Button className="secondary" onClick={onClose} disabled={busy}>
            {jobId ? "Done" : "Cancel"}
          </Button>
          {!jobId && <Button
            className="primary"
            disabled={!files.length || busy}
            busy={busy}
            onClick={() => void send()}
          >
            {busy
              ? "Uploading documents…"
              : `Upload & review${files.length ? ` (${files.length})` : ""}`}
            <ArrowRight size={15} />
          </Button>}
        </div>
      </div>
    </Modal>
  );
}

function EvidenceList({ sources }: { sources: Evidence[] }) {
  return (
    <div className="evidence-list">
      {sources.map((source, i) => (
        <div className="source-card" key={i}>
          <div>
            <FileText size={13} />
            {source.document_id ? (
              <a
                href={`/api/documents/${source.document_id}${source.page ? `#page=${source.page}` : ""}`}
                target="_blank"
                rel="noreferrer"
              >
                {source.filename}
                {source.page ? ` · Page ${source.page}` : ""}
                <ArrowUpRight size={12} />
              </a>
            ) : (
              <strong>{source.filename}</strong>
            )}
            <small>{source.method}</small>
          </div>
          <blockquote>
            {source.excerpt ||
              "Source record available in the original document."}
          </blockquote>
        </div>
      ))}
    </div>
  );
}
function CheckRow({ check }: { check: CheckType }) {
  const Icon =
    check.status === "pass"
      ? CheckCircle2
      : check.status === "info"
        ? CircleHelp
        : CircleAlert;
  return (
    <div className={`check-row ${check.status}`}>
      <Icon size={17} />
      <div className="check-content">
        <div className="check-title">
          <strong>{check.title}</strong>
          <span>
            {check.status === "pass"
              ? "Passed"
              : check.status === "info"
                ? "Information"
                : "Review needed"}
          </span>
        </div>
        <p>{check.message}</p>
        {check.evidence.length > 0 && (
          <details>
            <summary>
              <Files size={12} />
              {check.evidence.length} source
              {check.evidence.length !== 1 ? "s" : ""}
              <ChevronDown size={12} />
            </summary>
            <EvidenceList sources={check.evidence} />
          </details>
        )}
      </div>
    </div>
  );
}

function ReviewDrawer({
  aiEnabled,
  processingTrace,
  review,
  onClose,
  update,
  notify,
}: {
  aiEnabled: boolean;
  processingTrace?: ProcessingEvent[];
  review: Review;
  onClose: () => void;
  update: (w: Workspace) => void;
  notify: (s: string, error?: boolean) => void;
}) {
  const [tab, setTab] = useState("decision");
  const [editing, setEditing] = useState(false);
  const [showPassed, setShowPassed] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    panel.current?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !editing) onClose();
    };
    document.addEventListener("keydown", key);
    const original = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", key);
      document.body.style.overflow = original;
    };
  }, [onClose, editing]);
  const Icon = icons[review.decision];
  const attention = review.checks.filter(
    (c) => c.status === "fail" || c.status === "warning",
  );
  const passed = review.checks.filter(
    (c) => c.status === "pass" || c.status === "info",
  );
  const inv = review.invoice;
  const record = async () => {
    setBusy(true);
    try {
      const action = {
        ready: "acknowledge",
        clarification: "request_clarification",
        procurement: "send_to_procurement",
        hold: "investigate",
      }[review.decision];
      update(
        await api<Workspace>(`/reviews/${review.id}/resolution`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action, note }),
        }),
      );
      notify("Reviewer action recorded locally.");
      setNote("");
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div
      className="drawer-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <aside
        className="review-drawer"
        ref={panel}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={`Review ${inv.invoice_number || review.filename}`}
      >
        <div className="drawer-header">
          <span>
            <FileSearch size={16} />
            INVOICE REVIEW
          </span>
          <button
            className="icon-button"
            onClick={onClose}
            aria-label="Close invoice review"
          >
            <X size={20} />
          </button>
        </div>
        <div className="drawer-identity">
          <div>
            <span className="eyebrow">
              {inv.vendor_name || "Unknown vendor"}
            </span>
            <h2>{inv.invoice_number || "Missing invoice number"}</h2>
            <p>
              {review.filename} <span>·</span>{" "}
              {inv.invoice_date || "Date unavailable"}
            </p>
          </div>
          <div className="drawer-amount">
            <strong>{formatAmount(inv.total, inv.currency)}</strong>
            <span>{inv.currency || "Currency unknown"} · Gross total</span>
          </div>
        </div>
        <div className="drawer-tabs">
          {[
            { id: "decision", label: "Decision & checks" },
            { id: "fields", label: "Extracted fields" },
            { id: "original", label: "Original PDF" },
            { id: "notes", label: "Reviewer notes" },
          ].map((t) => (
            <button
              key={t.id}
              className={tab === t.id ? "active" : ""}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="drawer-body">
          {tab === "decision" && (
            <>
              <div className={`decision-banner ${review.decision}`}>
                <Icon size={23} />
                <div>
                  <span>RECOMMENDATION</span>
                  <h3>{labels[review.decision]}</h3>
                  <p>{review.summary}</p>
                </div>
              </div>
              <div className="review-meta">
                <span>
                  <ShieldCheck size={13} />
                  Human approval required
                </span>
                <span>
                  {review.checks.filter((c) => c.status === "pass").length}/
                  {review.checks.length} checks passed
                </span>
              </div>
              {!!processingTrace?.length && <details className="saved-processing-trace"><summary><History size={16} /> Upload processing timeline</summary><ProcessingTrace events={processingTrace} /></details>}
              <AIReview
                review={review}
                enabled={aiEnabled}
                update={update}
                notify={notify}
              />
              {Object.keys(review.po_context).length > 0 && (
                <div className="balance-card">
                  <div>
                    <h3>{review.matched_po?.po_number} · Commitment check</h3>
                    <span>{review.po_context.basis} amounts</span>
                  </div>
                  <div className="balance-values">
                    {[
                      ["PO amount", "po_amount"],
                      ["Prior invoices", "historical_committed"],
                      ["Earlier in batch", "batch_reserved"],
                      [review.po_context.pending_invoices?.length ? "Confirmed balance" : "Available balance", "remaining"],
                      ...(review.po_context.pending_invoices?.length && review.po_context.pending_amount !== null
                        ? [["Unresolved invoices", "pending_amount"], ["Possible balance", "potential_remaining"]]
                        : []),
                    ].map(([label, key]) => (
                      <div key={key}>
                        <small>{label}</small>
                        <strong>
                          {formatAmount(
                            review.po_context[key] as string,
                            review.matched_po?.currency,
                          )}
                        </strong>
                      </div>
                    ))}
                  </div>
                  <p>
                    Prior records:{" "}
                    {(review.po_context.historical_invoices as string[])?.join(
                      ", ",
                    ) || "None"}{" "}
                    · Batch reservations:{" "}
                    {(review.po_context.batch_invoices as string[])?.join(
                      ", ",
                    ) || "None"}
                    {!!(review.po_context.pending_invoices as string[] | undefined)?.length && <>
                      {" "}· Awaiting review: {(review.po_context.pending_invoices as string[]).join(", ")}
                    </>}
                  </p>
                </div>
              )}
              <div className="section-heading">
                <h3>
                  {attention.length
                    ? "Items needing attention"
                    : "All checks passed"}
                </h3>
                <span>{attention.length}</span>
              </div>
              {attention.map((c) => (
                <CheckRow key={c.code} check={c} />
              ))}
              <button
                className="passed-toggle"
                onClick={() => setShowPassed(!showPassed)}
              >
                <CheckCheck size={16} />
                {passed.length} passed or informational checks
                <ChevronDown
                  size={15}
                  className={showPassed ? "rotated" : ""}
                />
              </button>
              {showPassed &&
                passed.map((c) => <CheckRow key={c.code} check={c} />)}
              <div className="review-action-row">
                <Button
                  className="secondary small"
                  onClick={() => setTab("notes")}
                >
                  Record reviewer action
                  <ArrowRight size={14} />
                </Button>
              </div>
            </>
          )}
          {tab === "fields" && (
            <>
              <div className="field-heading">
                <div>
                  <h3>Extracted invoice information</h3>
                  <p>{inv.extraction_method} · Source excerpts retained</p>
                </div>
                <Button
                  className="secondary small"
                  onClick={() => setEditing(true)}
                >
                  <CheckCheck size={15} />
                  Verify / correct
                </Button>
              </div>
              <div className="extracted-fields">
                {[
                  ["invoice_number", "Invoice number"],
                  ["invoice_date", "Invoice date"],
                  ["vendor_name", "Vendor name"],
                  ["vendor_id", "Vendor ID"],
                  ["tax_id", "Tax ID"],
                  ["po_number", "PO reference"],
                  ["currency", "Currency"],
                  ["subtotal", "Net subtotal"],
                  ["tax_amount", "Tax amount"],
                  ["total", "Gross total"],
                  ["bank_account", "Bank account"],
                ].map(([key, label]) => (
                  <div className="extracted-field" key={key}>
                    <span>{label}</span>
                    <strong>
                      {String(inv[key as keyof Invoice] ?? "") || (
                        <em>Not found</em>
                      )}
                    </strong>
                    {inv.evidence[key] && (
                      <details>
                        <summary>
                          <FileText size={12} />
                          Source
                          <ChevronDown size={11} />
                        </summary>
                        <EvidenceList sources={[inv.evidence[key]]} />
                      </details>
                    )}
                  </div>
                ))}
              </div>
              <div className="section-heading">
                <h3>Invoice line items</h3>
                <span>{inv.items.length}</span>
              </div>
              <div className="table-scroll">
                <table className="line-table">
                  <thead>
                    <tr>
                      <th>DESCRIPTION</th>
                      <th>QTY</th>
                      <th>UNIT PRICE</th>
                      <th>AMOUNT</th>
                    </tr>
                  </thead>
                  <tbody>
                    {inv.items.map((item, i) => (
                      <tr key={i}>
                        <td>{item.description}</td>
                        <td>{item.quantity}</td>
                        <td>{formatAmount(item.unit_price, inv.currency)}</td>
                        <td>{formatAmount(item.amount, inv.currency)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {!inv.items.length && (
                  <p className="field-help">
                    No complete line items extracted. Verify against the
                    original.
                  </p>
                )}
              </div>
              {inv.extraction_notes.length > 0 && (
                <div className="extraction-notes">
                  <h3>Extraction notes</h3>
                  {inv.extraction_notes.map((n, i) => (
                    <p key={i}>{n}</p>
                  ))}
                </div>
              )}
            </>
          )}
          {tab === "original" && (
            <div className="original-preview">
              <div>
                <span>
                  <FileText size={15} />
                  {review.filename}
                </span>
                <a
                  className="text-link"
                  href={`/api/documents/${review.document_id}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open in new tab
                  <ArrowUpRight size={13} />
                </a>
              </div>
              <iframe
                title="Original invoice PDF"
                src={`/api/documents/${review.document_id}#view=FitH`}
              />
            </div>
          )}
          {tab === "notes" && (
            <>
              <div className="field-heading">
                <div>
                  <h3>Record the human review</h3>
                </div>
              </div>
              {review.resolution && (
                <div className="recorded-note">
                  <CheckCircle2 size={18} />
                  <div>
                    <strong>
                      {review.resolution.action.replaceAll("_", " ")}
                    </strong>
                    <p>{review.resolution.note}</p>
                    <small>
                      {dateTime(review.resolution.timestamp)} · Recommendation
                      at the time: {labels[review.resolution.decision_at_time]}
                    </small>
                  </div>
                </div>
              )}
              <label className="form-label">
                Review note
                <textarea
                  rows={5}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="Document what you checked, the information requested, or the next internal owner."
                  maxLength={2000}
                />
              </label>
              <div className="form-actions">
                <Button
                  className="primary"
                  disabled={note.trim().length < 5}
                  busy={busy}
                  onClick={() => void record()}
                >
                  <Check size={15} />
                  {
                    {
                      ready: "Acknowledge recommendation",
                      clarification: "Record clarification request",
                      procurement: "Record procurement referral",
                      hold: "Record investigation",
                    }[review.decision]
                  }
                </Button>
              </div>
            </>
          )}
        </div>
        <div className="drawer-footer">
          <span>
            <Clock3 size={13} />
            Checked {dateTime(review.reviewed_at)}
          </span>
          <Button className="secondary small" onClick={onClose}>
            Back to queue
            <ArrowRight size={14} />
          </Button>
        </div>
      </aside>
      {editing && (
        <CorrectionModal
          review={review}
          onClose={() => setEditing(false)}
          update={update}
          notify={notify}
        />
      )}
    </div>
  );
}

function CorrectionModal({
  review,
  onClose,
  update,
  notify,
}: {
  review: Review;
  onClose: () => void;
  update: (w: Workspace) => void;
  notify: (s: string, error?: boolean) => void;
}) {
  const [invoice, setInvoice] = useState<Invoice>(
    structuredClone(review.invoice),
  );
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const setField = (key: string, value: string) =>
    setInvoice((i) => ({
      ...i,
      [key]: ["subtotal", "tax_amount", "total"].includes(key)
        ? value || null
        : value,
    }));
  const save = async () => {
    setBusy(true);
    setError("");
    try {
      update(
        await api<Workspace>(`/reviews/${review.id}/correction`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ invoice, reason }),
        }),
      );
      notify(
        "Fields verified. All dependent recommendations have been recomputed.",
      );
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      title="Verify extracted information"
      onClose={() => {
        if (!busy) onClose();
      }}
      wide
    >
      <div className="correction-form">
        <div className="form-callout">
          <FileSearch size={18} />
          <p>
            Compare every field and line item with the original PDF. Saving
            confirms this extraction; it does not override policy checks.
          </p>
          <a
            className="text-link"
            href={`/api/documents/${review.id}`}
            target="_blank"
            rel="noreferrer"
          >
            Open original
            <ArrowUpRight size={12} />
          </a>
        </div>
        <div className="form-grid">
          {[
            ["invoice_number", "Invoice number"],
            ["invoice_date", "Invoice date"],
            ["vendor_name", "Vendor name"],
            ["vendor_id", "Vendor ID"],
            ["tax_id", "Tax ID"],
            ["po_number", "PO reference"],
            ["currency", "Currency"],
            ["bank_account", "Bank account"],
            ["subtotal", "Net subtotal"],
            ["tax_amount", "Tax amount"],
            ["total", "Gross total"],
          ].map(([key, label]) => (
            <label className="form-label" key={key}>
              {label}
              <input
                type={
                  key === "invoice_date"
                    ? "date"
                    : ["subtotal", "tax_amount", "total"].includes(key)
                      ? "number"
                      : "text"
                }
                step="0.01"
                value={String(invoice[key as keyof Invoice] ?? "")}
                onChange={(e) => setField(key, e.target.value)}
              />
            </label>
          ))}
        </div>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={invoice.tax_inclusive}
            onChange={(e) =>
              setInvoice((i) => ({ ...i, tax_inclusive: e.target.checked }))
            }
          />
          Line-item amounts include tax
        </label>
        <div className="section-heading">
          <h3>Line items</h3>
          <Button
            className="secondary small"
            onClick={() =>
              setInvoice((i) => ({
                ...i,
                items: [
                  ...i.items,
                  {
                    description: "",
                    quantity: "1",
                    unit_price: "0",
                    amount: "0",
                  },
                ],
              }))
            }
          >
            <Plus size={13} />
            Add line
          </Button>
        </div>
        <div className="edit-line-header">
          <span>Description</span>
          <span>Qty</span>
          <span>Unit price</span>
          <span>Amount</span>
          <span />
        </div>
        {invoice.items.map((item, index) => (
          <div className="edit-line" key={index}>
            {(["description", "quantity", "unit_price", "amount"] as const).map(
              (key) => (
                <input
                  aria-label={`Line ${index + 1} ${key}`}
                  key={key}
                  type={key === "description" ? "text" : "number"}
                  step="0.01"
                  value={item[key] ?? ""}
                  onChange={(e) =>
                    setInvoice((i) => ({
                      ...i,
                      items: i.items.map((line, n) =>
                        n === index
                          ? {
                              ...line,
                              [key]:
                                key === "description"
                                  ? e.target.value
                                  : e.target.value || null,
                            }
                          : line,
                      ),
                    }))
                  }
                />
              ),
            )}
            <button
              className="icon-button danger-text"
              aria-label={`Remove line ${index + 1}`}
              onClick={() =>
                setInvoice((i) => ({
                  ...i,
                  items: i.items.filter((_, n) => n !== index),
                }))
              }
            >
              <Trash2 size={14} />
            </button>
          </div>
        ))}
        <label className="form-label">
          Reason or verification note
          <textarea
            rows={2}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="For example: Verified invoice number and all amounts against page 1."
            maxLength={1000}
          />
        </label>
        <label className="checkbox-label">
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
          />
          I verified all extracted fields and the complete item list against the
          source.
        </label>
        {error && (
          <p className="inline-error" role="alert">
            {error}
          </p>
        )}
      </div>
      <div className="modal-footer">
        <span>Original extraction and correction reason are retained.</span>
        <div>
          <Button className="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            className="primary"
            disabled={!confirmed || reason.trim().length < 5}
            busy={busy}
            onClick={() => void save()}
          >
            Save & rerun checks
            <ArrowRight size={14} />
          </Button>
        </div>
      </div>
    </Modal>
  );
}

function PolicyForm({
  policy,
  update,
  notify,
}: {
  policy: Policy;
  update: (w: Workspace) => void;
  notify: (s: string, error?: boolean) => void;
}) {
  const [draft, setDraft] = useState(policy);
  const [busy, setBusy] = useState(false);
  useEffect(() => setDraft(policy), [policy]);
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      update(
        await api<Workspace>("/policy", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(draft),
        }),
      );
      notify("Review policy saved. All invoice recommendations updated.");
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="policy-layout">
      <form className="policy-form" onSubmit={(e) => void save(e)}>
        <div className="queue-heading">
          <div>
            <h2>Company review rules</h2>
          </div>
          <ShieldCheck size={23} />
        </div>
        <div className="policy-body">
          <label className="form-label">
            Policy name
            <input
              required
              value={draft.name}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
          </label>
          <div className="form-grid">
            <label className="form-label">
              PO amount tolerance (%)
              <input
                required
                type="number"
                min="0"
                max="20"
                step="0.1"
                value={draft.amount_tolerance_percent}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    amount_tolerance_percent: e.target.value,
                  })
                }
              />
              <small>Percentage of the full PO amount.</small>
            </label>
            <label className="form-label">
              Absolute amount tolerance
              <input
                required
                type="number"
                min="0"
                max="1000000"
                step="0.01"
                value={draft.amount_tolerance_absolute}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    amount_tolerance_absolute: e.target.value,
                  })
                }
              />
              <small>In each PO’s own currency units.</small>
            </label>
            <label className="form-label">
              Unit-price tolerance (%)
              <input
                required
                type="number"
                min="0"
                max="20"
                step="0.1"
                value={draft.unit_price_tolerance_percent}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    unit_price_tolerance_percent: e.target.value,
                  })
                }
              />
            </label>
            <label className="form-label">
              Maximum invoice age (days)
              <input
                required
                type="number"
                min="1"
                max="3650"
                value={draft.max_invoice_age_days}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    max_invoice_age_days: Number(e.target.value),
                  })
                }
              />
            </label>
          </div>
          <div className="policy-formula">
            <span>HOW TOLERANCE WORKS</span>
            <p>
              Allowed overage = the greater of the percentage tolerance and the
              absolute tolerance.
            </p>
            <code>
              Invoice ≤ PO − historical commitments − batch reservations +
              tolerance
            </code>
          </div>
          <label className="toggle-row">
            <div>
              <strong>Require invoice line items</strong>
              <span>Missing item detail routes to clarification.</span>
            </div>
            <input
              type="checkbox"
              checked={draft.require_line_items}
              onChange={(e) =>
                setDraft({ ...draft, require_line_items: e.target.checked })
              }
            />
          </label>
          <label className="toggle-row">
            <div>
              <strong>Compare invoice bank details</strong>
              <span>
                Changed bank accounts trigger a hold for investigation.
              </span>
            </div>
            <input
              type="checkbox"
              checked={draft.check_bank_details}
              onChange={(e) =>
                setDraft({ ...draft, check_bank_details: e.target.checked })
              }
            />
          </label>
          <div className="form-actions">
            <Button type="submit" className="primary" busy={busy}>
              Save policy & rerun
              <ArrowRight size={15} />
            </Button>
          </div>
        </div>
      </form>
    </div>
  );
}
