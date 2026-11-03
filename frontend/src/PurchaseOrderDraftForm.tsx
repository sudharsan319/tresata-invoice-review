import { useState, type FormEvent } from "react";
import { ArrowRight, FileText, Plus, Trash2 } from "lucide-react";
import { api } from "./api";
import type { Document, LineItem, PurchaseOrderDraft, Workspace } from "./types";

type Props = {
  document: Document;
  draft: PurchaseOrderDraft;
  onClose: () => void;
  update: (workspace: Workspace) => void;
  notify: (message: string, error?: boolean) => void;
};

export default function PurchaseOrderDraftForm({ document, draft, onClose, update, notify }: Props) {
  const [values, setValues] = useState(() => ({ ...draft.values, items: draft.values.items.map((item) => ({ ...item })) }));
  const [note, setNote] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const image = /\.(png|jpe?g|webp)$/i.test(document.filename);
  const setField = (field: keyof typeof values, value: string) => setValues((current) => ({ ...current, [field]: value }));
  const setItem = (index: number, field: keyof LineItem, value: string) => setValues((current) => ({
    ...current,
    items: current.items.map((item, i) => i === index ? { ...item, [field]: value } : item),
  }));
  const validItems = values.items.every((item) => item.description.trim() && Number(item.quantity) > 0 &&
    item.unit_price != null && item.unit_price !== "" && Number(item.unit_price) >= 0 &&
    (item.amount == null || item.amount === "" || Number.isFinite(Number(item.amount))));
  const canApprove = !!values.po_number.trim() && !!(values.vendor_id.trim() || values.vendor_name.trim()) &&
    /^[A-Z]{3}$/.test(values.currency.trim().toUpperCase()) && Number(values.amount) > 0 &&
    !!values.amount_basis && !!values.status.trim() && validItems && note.trim().length >= 5 && confirmed;
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!canApprove) return;
    setBusy(true);
    try {
      const workspace = await api<Workspace>(`/purchase-orders/drafts/${document.id}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmed: true, note: note.trim(), po: {
          ...values,
          currency: values.currency.trim().toUpperCase(),
          items: values.items.map(({ description, sku, quantity, unit_price, amount }) => ({
            description: description.trim(), sku: sku || "", quantity,
            unit_price, amount: amount === "" ? null : amount,
          })),
        } }),
      });
      update(workspace);
      notify(`Purchase order ${values.po_number} activated. Invoice checks updated.`);
      onClose();
    } catch (error) {
      notify((error as Error).message, true);
    } finally {
      setBusy(false);
    }
  };
  return <div className="po-draft-layout">
    <form className="po-draft-form" onSubmit={(event) => void submit(event)}>
      <div className="po-draft-status"><span>Pending review</span><span>{draft.method}</span></div>
      {!!draft.uncertainties.length && <div className="po-draft-issues"><strong>Check before activation</strong><ul>{draft.uncertainties.map((issue, index) => <li key={index}>{issue}</li>)}</ul></div>}
      <div className="po-draft-fields">
        <label>PO number<input required value={values.po_number} onChange={(e) => setField("po_number", e.target.value)} /></label>
        <label>Vendor name<input value={values.vendor_name} onChange={(e) => setField("vendor_name", e.target.value)} /></label>
        <label>Vendor ID<input value={values.vendor_id} onChange={(e) => setField("vendor_id", e.target.value)} /></label>
        <label>Currency<input required maxLength={3} value={values.currency} onChange={(e) => setField("currency", e.target.value.toUpperCase())} placeholder="INR" /></label>
        <label>Authorized amount<input required type="number" min="0.0001" step="any" value={values.amount} onChange={(e) => setField("amount", e.target.value)} /></label>
        <label>Amount basis<select required value={values.amount_basis} onChange={(e) => setField("amount_basis", e.target.value)}><option value="">Select basis</option><option value="net">Net (before tax)</option><option value="gross">Gross (including tax)</option></select></label>
        <label>PO status<input required list="po-status-options" value={values.status} onChange={(e) => setField("status", e.target.value)} /><datalist id="po-status-options"><option value="approved" /><option value="pending" /><option value="closed" /><option value="cancelled" /><option value="unknown" /></datalist></label>
        <label>Valid from<input type="date" value={values.valid_from} onChange={(e) => setField("valid_from", e.target.value)} /></label>
        <label>Valid to<input type="date" value={values.valid_to} onChange={(e) => setField("valid_to", e.target.value)} /></label>
      </div>
      <div className="po-draft-lines-heading"><h3>PO line items <span>{values.items.length}</span></h3><button type="button" className="button secondary small" onClick={() => setValues((current) => ({ ...current, items: [...current.items, { description: "", sku: "", quantity: "", unit_price: "", amount: "" }] }))}><Plus size={14} /> Add line</button></div>
      <div className="po-draft-lines">{values.items.map((item, index) => <div className="po-draft-line" key={index}>
        <div className="po-draft-line-title"><strong>Line {index + 1}</strong><button type="button" className="icon-button danger-text" aria-label={`Remove line ${index + 1}`} onClick={() => setValues((current) => ({ ...current, items: current.items.filter((_, i) => i !== index) }))}><Trash2 size={15} /></button></div>
        <label>Description<input required value={item.description} onChange={(e) => setItem(index, "description", e.target.value)} /></label>
        <div className="po-draft-line-grid"><label>SKU<input value={item.sku || ""} onChange={(e) => setItem(index, "sku", e.target.value)} /></label><label>Quantity<input required type="number" min="0.000001" step="any" value={item.quantity ?? ""} onChange={(e) => setItem(index, "quantity", e.target.value)} /></label><label>Unit price<input required type="number" min="0" step="any" value={item.unit_price ?? ""} onChange={(e) => setItem(index, "unit_price", e.target.value)} /></label><label>Line amount<input type="number" step="any" value={item.amount ?? ""} onChange={(e) => setItem(index, "amount", e.target.value)} /></label></div>
      </div>)}</div>
      <details className="po-draft-evidence"><summary>Extraction evidence</summary>{Object.entries(draft.sources).map(([field, source]) => <div key={field}><strong>{field.replaceAll("_", " ")}{source.page ? ` · p${source.page}` : ""}</strong><span>{source.excerpt}</span></div>)}</details>
      <label className="po-draft-note">Review note<textarea required minLength={5} rows={3} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Record what was checked or corrected" /></label>
      <label className="po-draft-confirm"><input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />I verified the PO identity, status, amount, dates, and line items against the source or authorized records.</label>
      <div className="po-draft-actions"><button className="button primary" type="submit" disabled={!canApprove || busy}>{busy ? "Saving…" : "Confirm & activate PO"}<ArrowRight size={15} /></button></div>
    </form>
    <aside className="po-draft-preview"><div><FileText size={16} /><strong>{document.filename}</strong><a href={`/api/documents/${document.id}`} target="_blank" rel="noreferrer">Open original</a></div>{image ? <img src={`/api/documents/${document.id}`} alt={`Original ${document.filename}`} /> : <iframe title={`Original ${document.filename}`} src={`/api/documents/${document.id}#view=FitH`} />}</aside>
  </div>;
}
