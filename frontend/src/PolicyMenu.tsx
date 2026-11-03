import { ArrowRight, Check, Clock3, FileText, Settings2, ShieldCheck, Sparkles } from "lucide-react";
import type { Workspace } from "./types";

const number = (value: string | number) => String(value);

export default function PolicyMenu({ workspace, onManage, onDrafts, onAISettings }: {
  workspace: Workspace;
  onManage: () => void;
  onDrafts: () => void;
  onAISettings: () => void;
}) {
  const policy = workspace.policy;
  const source = policy.evidence;
  const documents = workspace.documents.filter(d => d.kind === "policy");
  const drafts = Object.entries(workspace.reference_drafts || {}).filter(([, d]) => d.kind === "policy");
  const settings = [
    {
      title: "PO amount tolerance",
      value: `${number(policy.amount_tolerance_percent)}%`,
      detail: "Percentage of the full purchase order amount allowed above the remaining balance.",
    },
    {
      title: "Absolute amount tolerance",
      value: number(policy.amount_tolerance_absolute),
      detail: "In the PO’s currency. The greater of the percentage and absolute allowance is used.",
    },
    {
      title: "Unit-price tolerance",
      value: `${number(policy.unit_price_tolerance_percent)}%`,
      detail: "Permitted difference between an invoice item’s unit price and its contracted PO price.",
    },
    {
      title: "Invoice line items",
      value: policy.require_line_items ? "Required" : "Optional",
      detail: "When required, missing item details need clarification before approval can be recommended.",
    },
    {
      title: "Bank details comparison",
      value: policy.check_bank_details ? "Enabled" : "Disabled",
      detail: "When enabled, supplied invoice and vendor-master accounts are compared. A mismatch triggers a hold.",
    },
    {
      title: "Maximum invoice age",
      value: `${number(policy.max_invoice_age_days)} days`,
      detail: "Older invoices need clarification. Future and invalid dates are also flagged.",
    },
  ];

  return <>
    <div className="policy-menu-body">
      <div className="policy-menu-intro">
        <span className="eyebrow">CURRENT WORKSPACE</span>
        <h3>Your review policies</h3>
      </div>

      <section className="policy-menu-active" aria-labelledby="active-policy-title">
        <div className="policy-menu-section-heading">
          <span><ShieldCheck size={16} /> Active policy</span>
          <span className="policy-state active"><Check size={12} /> In use</span>
        </div>
        <h4 id="active-policy-title">{policy.name}</h4>
        <div className="policy-menu-source">
          <FileText size={13} />
          {source.document_id ? <a href={`/api/documents/${source.document_id}${source.page ? `#page=${source.page}` : ""}`} target="_blank" rel="noreferrer">{source.filename || "View source"}</a> : <span>{source.filename || "Workspace settings"}</span>}
          <small>{source.method === "human configured" ? "Set by a reviewer" : source.document_id ? "Source retained" : "Workspace policy"}</small>
        </div>
        <dl className="policy-menu-settings">
          {settings.map(setting => <div key={setting.title}>
            <dt>{setting.title}</dt><dd>{setting.value}</dd><p>{setting.detail}</p>
          </div>)}
        </dl>
        <div className="policy-menu-formula">
          <strong>PO balance allowance</strong>
          <p>Remaining balance + max({number(policy.amount_tolerance_percent)}% of PO amount, {number(policy.amount_tolerance_absolute)} in PO currency)</p>
          <small>Prior commitments and earlier ready invoices reduce the remaining balance. Item quantities are checked separately.</small>
        </div>
      </section>

      <section className="policy-menu-documents" aria-labelledby="policy-documents-title">
        <div className="policy-menu-section-heading"><h4 id="policy-documents-title">Saved policy documents</h4><span>{documents.length}</span></div>
        {documents.length ? documents.map(document => {
          const pending = drafts.some(([id]) => id === document.id);
          const active = source.document_id === document.id;
          return <div className="policy-document" key={document.id}>
            <FileText size={18} />
            <div><a href={`/api/documents/${document.id}`} target="_blank" rel="noreferrer">{document.filename}</a>
              <small>Uploaded {new Date(document.uploaded_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}</small>
              <span className={`policy-state ${pending ? "pending" : active ? "active" : ""}`}>{pending ? "Awaiting human review" : active ? "Active source" : "Saved source · not active"}</span>
            </div>
          </div>;
        }) : <p className="policy-menu-empty">No policy files uploaded.</p>}
      </section>

      {drafts.length > 0 && <section className="policy-menu-drafts" aria-labelledby="policy-drafts-title">
        <div className="policy-menu-section-heading"><h4 id="policy-drafts-title"><Sparkles size={15} /> Pending AI drafts</h4><span>{drafts.length}</span></div>
        {drafts.map(([id, draft]) => <div key={id}><Clock3 size={15} /><strong>{workspace.documents.find(d => d.id === id)?.filename || draft.values.name}</strong><small>{Object.keys(draft.changed_fields).length} proposed field(s)</small></div>)}
        <button className="button secondary small" onClick={onDrafts}>Review drafts <ArrowRight size={14} /></button>
      </section>}

      <details className="policy-menu-controls">
        <summary><ShieldCheck size={15} /> Other verification rules</summary>
        <ul>
          <li><strong>Required fields and arithmetic</strong>Invoice identity, date, currency, totals, tax reconciliation, and available item arithmetic.</li>
          <li><strong>Vendor approval and identity</strong>Match the supplied vendor master and check vendor approval status.</li>
          <li><strong>Duplicate submissions</strong>Compare vendor-scoped invoice numbers and available document fingerprints against history and earlier uploads.</li>
          <li><strong>PO authorization</strong>Check the explicit PO reference, vendor ownership, approval, currency, and supplied validity dates.</li>
          <li><strong>Cumulative PO limits</strong>Check remaining amounts, contracted rates, and quantities against prior commitments.</li>
          <li><strong>Human verification</strong>Scans and AI-proposed item equivalence require confirmation. Every recommendation needs human approval.</li>
        </ul>
        <div className="policy-menu-priority">Decision priority: hold → procurement review → clarification → ready for approval.</div>
      </details>
    </div>
    <div className="policy-menu-footer">
      <button className="button primary" onClick={onManage}><Settings2 size={15} /> Edit active policy <ArrowRight size={15} /></button>
      <button className="button secondary" onClick={onAISettings}><Sparkles size={15} /> AI settings <ArrowRight size={15} /></button>
    </div>
  </>;
}
