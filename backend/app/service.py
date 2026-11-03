import hashlib
import json
import re
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from . import store, progress
from .engine import review_invoice
from .extraction import read_pdf, read_image_document, image_to_pdf, extract_invoice, read_rows, normalize
from .models import Vendor, PurchaseOrder, HistoricalInvoice, Policy, Invoice, Evidence
from .po_extraction import extract_po_draft
from . import ai
from .interpretation import matching_key, propose_item_matches, policy_proposal, fingerprint

KINDS = {'invoice', 'purchase_orders', 'vendors', 'history', 'policy'}
MAX_BYTES = 20 * 1024 * 1024


def validate_purchase_order(item: PurchaseOrder) -> PurchaseOrder:
    item.currency = item.currency.upper().strip()
    if not item.po_number.strip() or item.amount <= 0 or not re.fullmatch(r'[A-Z]{3}', item.currency) or not (item.vendor_id.strip() or item.vendor_name.strip()):
        raise ValueError('PO requires a reference, positive amount, ISO currency, and vendor identity.')
    if any(i.quantity is None or i.quantity <= 0 or i.unit_price is None or i.unit_price < 0 for i in item.items):
        raise ValueError('PO lines require positive quantities and nonnegative unit prices.')
    return item


def audit(state, action, message, document_id=''):
    state['audit'].append({'id': str(uuid.uuid4()), 'timestamp': datetime.now().astimezone().isoformat(), 'action': action, 'message': message, 'document_id': document_id})


def _keys(row):
    result = {re.sub(r'[^a-z0-9]+', '_', str(k).lower()).strip('_'): v for k, v in row.items() if k and v is not None and v != ''}
    for key in ('aliases', 'items'):
        if isinstance(result.get(key), str):
            result[key] = json.loads(result[key]) if result[key].strip().startswith('[') else [v.strip() for v in result[key].split(';') if v.strip()]
    return result


def _pdf_reference(kind, document):
    invoice = extract_invoice(document, use_ai=False)
    text = '\n'.join(p['text'] for p in document['pages'])

    def label(name, default=''):
        match = re.search(r'^\s*' + name + r'\s*[:|]\s*(.+)$', text, re.I | re.M)
        return match.group(1).strip() if match else default

    if kind == 'vendors':
        if not invoice.vendor_id or not invoice.vendor_name:
            raise ValueError('Vendor PDF must contain labelled Vendor ID and Vendor Name. For a multi-vendor master, use CSV/JSON/XLSX.')
        return [{'vendor_id': invoice.vendor_id, 'name': invoice.vendor_name, 'status': label(r'(?:vendor\s*)?status', 'unknown'), 'tax_id': invoice.tax_id, 'bank_account': invoice.bank_account}]
    if kind == 'history':
        raise ValueError('Upload history as CSV, JSON, or XLSX so each prior invoice has an explicit status, vendor, and amount.')
    return [_parse_policy_text(text)]


def _parse_policy_text(text):
    parsed = {}
    fields = Policy.model_fields
    for line in text.splitlines():
        if ':' in line:
            key, value = line.split(':', 1)
            key = re.sub(r'[^a-z0-9]+', '_', key.lower()).strip('_')
            if key in fields and key != 'evidence':
                parsed[key] = value.strip().rstrip('%')
    if not (set(parsed) - {'name'}):
        raise ValueError('Policy could not be read. Use the policy JSON template or parameter: value lines; prose is not silently interpreted.')
    return parsed


def ingest(state: dict, kind: str, filename: str, data: bytes, document_id: str | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError('Unknown document category.')
    if not data:
        raise ValueError('This file is empty.')
    if len(data) > MAX_BYTES:
        raise ValueError('Each file must be at most 20 MB.')
    if len(state['documents']) >= 120:
        raise ValueError('Workspace limit is 120 documents; remove old documents first.')
    filename = re.sub(r'[^\w .()\-]', '_', Path(filename).name)[:180] or 'document'
    extension = Path(filename).suffix.casefold()
    image_pdf = None
    if (kind == 'invoice' and extension != '.pdf') or (kind == 'purchase_orders' and extension not in {'.pdf', '.csv', '.json', '.xlsx'}):
        try:
            image_pdf, detected_extension = image_to_pdf(data)
        except ValueError as exc:
            if str(exc).startswith('Image exceeds'):
                raise
            allowed = 'Invoices must be PDF, PNG, JPG, or WEBP files.' if kind == 'invoice' else 'Purchase orders must be PDF, PNG, JPG, WEBP, CSV, JSON, or XLSX files.'
            raise ValueError(allowed) from exc
        if extension != detected_extension:
            stem = filename[:-len(extension)] if extension else filename
            filename = stem[:180 - len(detected_extension)] + detected_extension
            extension = detected_extension
    document_id = document_id or str(uuid.uuid4())
    with progress.document_scope(document_id, filename):
        digest = hashlib.sha256(data).hexdigest()
        document = {'id': document_id, 'document_id': document_id, 'filename': filename, 'kind': kind, 'sha256': digest, 'size': len(data), 'uploaded_at': datetime.now().astimezone().isoformat(), 'pages': [], 'notes': [], 'record_count': 0}
        progress.emit('validation', 'completed', 'File accepted', 'File type and size validated; SHA-256 fingerprint recorded.')
        # Do not skip identical invoice PDFs: uploading the same PDF must raise a duplicate alert.
        pdf_bytes = image_pdf or data
        if extension == '.pdf':
            document.update(read_pdf(data, document_id, filename))
        elif image_pdf is not None:
            document.update(read_image_document(image_pdf, document_id, filename))
        source = Evidence(document_id=document_id, filename=filename, excerpt='Imported structured reference record.', method='structured upload')
        additions = []
        if kind == 'invoice':
            document['extracted'] = Invoice.model_validate(extract_invoice(document, pdf_bytes=pdf_bytes).model_dump()).model_dump(mode='json')
            document['record_count'] = 1
        else:
            progress.emit('extraction', 'running', 'Reading reference records', 'Validating the supplied reference data and source evidence.')
            if kind == 'purchase_orders' and (extension == '.pdf' or image_pdf is not None):
                state['po_drafts'][document_id] = extract_po_draft(document, pdf_bytes)
                document['pending_interpretation'] = True
                document['notes'].append('PO extraction pending human review; invoice matching is unchanged.')
                rows = []
            elif extension == '.pdf':
                try:
                    rows = _pdf_reference(kind, document)
                except ValueError:
                    if kind != 'policy' or not ai.enabled():
                        raise
                    proposal = policy_proposal(document, state['policy'])
                    document['pending_interpretation'] = True
                    document['notes'].append('AI policy proposal needs human review; the active policy has not changed.')
                    state['reference_drafts'][document_id] = proposal
                    rows = []
                source = Evidence(document_id=document_id, filename=filename, page=1, excerpt=document['pages'][0]['text'][:1500] if document['pages'] else '', method='PDF reference extraction')
                if not document.get('pending_interpretation') and any(p['method'] != 'text' for p in document['pages']):
                    raise ValueError('Scanned vendor and policy PDFs need verification. Use a reviewed CSV/JSON/XLSX export.')
            elif kind == 'policy' and extension in ('.txt', '.md'):
                policy_text = data.decode('utf-8-sig')
                try:
                    rows = [_parse_policy_text(policy_text)]
                except ValueError:
                    if not ai.enabled():
                        raise
                    document['pages'] = [{'page': 1, 'text': policy_text, 'method': 'text', 'confidence': 1}]
                    proposal = policy_proposal(document, state['policy'])
                    document['pending_interpretation'] = True
                    document['notes'].append('AI policy proposal needs human review; the active policy has not changed.')
                    state['reference_drafts'][document_id] = proposal
                    rows = []
            else:
                rows = read_rows(data, filename)
            if not rows and kind != 'history' and not document.get('pending_interpretation'):
                raise ValueError('No records found. Include a header and at least one record.')
            if len(rows) > 10000:
                raise ValueError('Reference uploads are limited to 10,000 rows.')
            for index, row in enumerate(rows, start=1):
                if not isinstance(row, dict):
                    raise ValueError(f'Row {index} must be an object.')
                row = _keys(row)
                row_source = source.model_copy(update={'excerpt': f'Row {index}: ' + json.dumps(row, default=str)[:2500] if extension != '.pdf' else source.excerpt})
                row['evidence'] = row_source
                if kind == 'vendors':
                    if 'vendor_name' in row and 'name' not in row:
                        row['name'] = row.pop('vendor_name')
                    item = Vendor.model_validate(row)
                    if not item.vendor_id.strip() or not item.name.strip():
                        raise ValueError(f'Row {index}: vendor_id and name must not be blank.')
                elif kind == 'purchase_orders':
                    item = validate_purchase_order(PurchaseOrder.model_validate(row))
                elif kind == 'history':
                    item = HistoricalInvoice.model_validate(row)
                    item.currency = item.currency.upper()
                    if not item.invoice_number.strip() or not item.vendor_id.strip() or item.total < 0 or (item.subtotal is not None and item.subtotal < 0):
                        raise ValueError(f'Row {index}: invalid prior invoice identity or amount.')
                else:
                    if len(rows) != 1:
                        raise ValueError('Policy upload must contain exactly one object.')
                    if not (set(row) & (set(Policy.model_fields) - {'name', 'evidence'})):
                        raise ValueError('Policy must include at least one recognized rule parameter; see the policy template.')
                    item = Policy.model_validate(row)
                additions.append(item.model_dump(mode='json'))
            if kind != 'policy':
                # Conflicting reference identities are rejected; never silently overwrite approved master data.
                key = 'vendor_id' if kind == 'vendors' else 'po_number' if kind == 'purchase_orders' else None
                if key:
                    seen = {normalize(r[key]) for r in state[kind]}
                    for item in additions:
                        identity = normalize(item[key])
                        if not identity or identity in seen:
                            raise ValueError(f'Duplicate {key}: {item[key]}. Remove the earlier reference document before replacing it.')
                        seen.add(identity)
                state[kind].extend(additions)
            elif additions:
                state['policy'] = additions[0]
            document['record_count'] = len(additions)
        progress.emit('extraction', 'completed', 'Document interpreted', f'{document["record_count"]} active record(s).' + (' Human review pending.' if document.get('pending_interpretation') else ''))
        store.connection().close()  # Ensure the document directory exists.
        path = store.DATA / 'documents' / (document_id + extension)
        path.write_bytes(data)
        document['stored_name'] = path.name
        state['documents'].append(document)
        audit(state, 'uploaded', f'Uploaded {filename} as {kind}; {document["record_count"]} record(s).', document_id)
        return document


def run_reviews(state: dict):
    vendors = [Vendor.model_validate(v) for v in state['vendors']]
    pos = [PurchaseOrder.model_validate(p) for p in state['purchase_orders']]
    history = [HistoricalInvoice.model_validate(h) for h in state['history']]
    policy = Policy.model_validate(state['policy'])
    reviews, earlier, reservations = [], [], {}
    # Upload order is stable and visible in PO reservation evidence. Recompute every review after any change.
    for document in [d for d in state['documents'] if d['kind'] == 'invoice']:
        with progress.document_scope(document['id'], document['filename']):
            correction = state['corrections'].get(document['id'])
            invoice = Invoice.model_validate(correction['invoice'] if correction else document['extracted'])
            progress.emit('matching', 'running', 'Finding reference records', f'{len(vendors)} vendors, {len(pos)} POs, {len(history)} historical invoices available.')
            semantic = None
            matched_pos = [p for p in pos if invoice.po_number and normalize(p.po_number) == normalize(invoice.po_number)]
            if len(matched_pos) == 1 and invoice.items and matched_pos[0].items:
                po = matched_pos[0]
                ambiguous = any(sum(1 for item in po.items if (line.sku and item.sku and normalize(line.sku) == normalize(item.sku)) or normalize(line.description) == normalize(item.description)) != 1 for line in invoice.items)
                if ambiguous:
                    key = matching_key(invoice, po)
                    cached = state['ai_matches'].get(document['id'])
                    if cached and cached.get('analysis_key') != key:
                        cached = None
                    if ai.enabled() and ai.settings()['matching_enabled'] and (not cached or cached.get('model_key') != ai.config_fingerprint('matching')):
                        try:
                            cached = propose_item_matches(invoice, po)
                        except ai.AIError as exc:
                            cached = {'analysis_key': key, 'model_key': ai.config_fingerprint('matching'), 'matches': [], 'run': ai.failure_record('matching', str(exc))}
                        state['ai_matches'][document['id']] = cached
                    elif cached:
                        progress.emit('ai', 'cached', 'Reusing item comparison', 'The invoice, PO items, and model configuration match the saved comparison. No new API call.', task='matching', model=cached.get('run', {}).get('model', ''))
                    else:
                        progress.emit('ai', 'skipped', 'AI item comparison skipped', 'AI matching is disabled; non-exact items require procurement review.', task='matching')
                    semantic = json.loads(json.dumps(cached)) if cached else None
                    confirmations = state['semantic_confirmations'].get(document['id'], {})
                    for proposal in (semantic or {}).get('matches', []):
                        proposal['confirmed'] = proposal.get('po_line') is not None and confirmations.get(f'{key}:{proposal["invoice_line"]}') == proposal.get('po_line')
                else:
                    progress.emit('matching', 'info', 'Items matched directly', 'Descriptions or product codes have unique exact PO matches. No AI item-comparison call is needed.')
            progress.emit('matching', 'completed', 'Reference lookup complete', f'Explicit PO reference: {invoice.po_number or "not extracted"}; {len(matched_pos)} matching PO record(s).')
            progress.emit('verification', 'running', 'Running verification checks', 'Checking fields, arithmetic, vendor identity, duplicates, PO ownership, approval, currency, rates, quantities, and cumulative commitment where data is available.')
            review = review_invoice(document, invoice, vendors, pos, history, policy, earlier, reservations, verified=bool(correction), history_provided=any(d['kind'] == 'history' for d in state['documents']), semantic=semantic)
            review.resolution = state['resolutions'].get(review.id)
            if review.decision == 'ready' and review.matched_po:
                amount = invoice.subtotal if review.matched_po.amount_basis == 'net' else invoice.total
                reservations.setdefault(normalize(review.matched_po.po_number), []).append({'amount': amount, 'invoice_number': invoice.invoice_number, 'items': invoice.items, 'line_assignments': review.po_context.get('line_assignments', {})})
            prior_amount = (invoice.subtotal if review.matched_po.amount_basis == 'net' else invoice.total) if review.matched_po else None
            earlier.append({'id': document['id'], 'hash': document['sha256'], 'filename': document['filename'],
                            'vendor_id': review.matched_vendor.vendor_id if review.matched_vendor else '',
                            'invoice_number': invoice.invoice_number, 'po_number': review.matched_po.po_number if review.matched_po else invoice.po_number,
                            'source_unverified': any(c.code == 'extraction_review' and c.route == 'clarification' for c in review.checks),
                            'amount': str(prior_amount) if prior_amount is not None else None})
            result = review.model_dump(mode='json')
            brief = state['ai_briefs'].get(document['id'])
            checks_key = fingerprint([{k: c[k] for k in ('code', 'title', 'status', 'message', 'route')} for c in result['checks']])
            if brief and brief.get('review_key') == checks_key:
                result['ai_analysis']['brief'] = brief
            reviews.append(result)
            attention = sum(c.status in ('warning', 'fail') for c in review.checks)
            progress.emit('verification', 'completed', 'Verification complete', f'{len(review.checks)} checks performed; {attention} need attention. Completed does not mean approved.', checks_count=len(review.checks), attention_count=attention)
            progress.emit('recommendation', 'completed', {'ready': 'Ready for approval', 'clarification': 'Needs clarification', 'procurement': 'Procurement review', 'hold': 'Hold for investigation'}[review.decision], review.summary, decision=review.decision)
    state['reviews'] = reviews


def public_state(state):
    documents = [{k: v for k, v in d.items() if k not in ('stored_name', 'extracted', 'pages', 'original_extracted', 'extraction_history')} | {'page_count': len(d['pages']), 'methods': list({p['method'] for p in d['pages']})} for d in state['documents']]
    totals = {}
    for review in state['reviews']:
        invoice = review['invoice']
        if invoice['total'] is not None and invoice['currency']:
            totals[invoice['currency']] = str(Decimal(totals.get(invoice['currency'], '0')) + Decimal(invoice['total']))
    return {'documents': documents, 'reviews': state['reviews'], 'vendors': state['vendors'], 'purchase_orders': state['purchase_orders'], 'po_drafts': state.get('po_drafts', {}), 'history_count': len(state['history']), 'policy': state['policy'], 'audit': list(reversed(state['audit'])), 'totals_by_currency': totals, 'revision': state['revision'], 'reference_drafts': state.get('reference_drafts', {})}
