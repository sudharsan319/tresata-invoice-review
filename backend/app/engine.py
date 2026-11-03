"""Deterministic AP checks using Decimal. No model can approve an invoice."""
import re
from datetime import datetime, date
from decimal import Decimal, ROUND_HALF_UP
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo
import os

from . import progress
from .extraction import normalize
from .models import Check, Evidence, Invoice, Vendor, PurchaseOrder, HistoricalInvoice, Policy, Review

CENT = Decimal('0.01')
COMMITTED_STATUSES = {'approved', 'paid', 'pending', 'submitted', 'processing'}
INACTIVE_STATUSES = {'rejected', 'cancelled', 'canceled', 'void'}
LABELS = {'ready': 'Ready for approval', 'clarification': 'Needs clarification', 'procurement': 'Procurement review', 'hold': 'Hold for investigation'}


def rounded(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def review_invoice(document: dict, invoice: Invoice, vendors: list[Vendor], pos: list[PurchaseOrder],
                   history: list[HistoricalInvoice], policy: Policy, earlier: list[dict],
                   reservations: dict, verified: bool = False, today: date | None = None,
                   history_provided: bool | None = None, semantic: dict | None = None) -> Review:
    today = today or datetime.now(ZoneInfo(os.getenv('AP_TIMEZONE', 'Asia/Kolkata'))).date()
    checks: list[Check] = []

    def ev(*fields):
        return [invoice.evidence[f] for f in fields if f in invoice.evidence]

    def add(code, title, status, message, route='ready', evidence=None):
        check = Check(code=code, title=title, status=status, message=message, route=route, evidence=evidence or [])
        checks.append(check)
        progress.emit('verification', status, title, message, code=code, route=route, evidence=[e.model_dump(mode='json') for e in check.evidence])

    missing = [label for field, label in [('invoice_number', 'invoice number'), ('invoice_date', 'invoice date'), ('vendor_name', 'vendor name'), ('currency', 'currency'), ('total', 'invoice total')] if getattr(invoice, field) in ('', None)]
    if missing:
        add('required_fields', 'Required invoice fields', 'fail', 'Missing or unreadable: ' + ', '.join(missing) + '.', 'clarification')
    else:
        add('required_fields', 'Required invoice fields', 'pass', 'Invoice number, date, vendor, currency, and total are present.', evidence=ev('invoice_number', 'invoice_date', 'vendor_name', 'currency', 'total'))
    if invoice.currency and not re.fullmatch(r'[A-Z]{3}', invoice.currency):
        add('currency_format', 'Currency code', 'fail', 'Confirm a three-letter currency code; a currency symbol alone may be ambiguous.', 'clarification', ev('currency'))
    if invoice.invoice_date:
        try:
            when = date.fromisoformat(invoice.invoice_date)
            if when > today:
                add('invoice_date', 'Invoice date', 'fail', f'Invoice date {when} is in the future relative to {today}.', 'clarification', ev('invoice_date'))
            elif (today - when).days > policy.max_invoice_age_days:
                add('invoice_date', 'Invoice date', 'warning', f'Invoice is older than the {policy.max_invoice_age_days}-day policy limit.', 'clarification', ev('invoice_date') + [policy.evidence])
            else:
                add('invoice_date', 'Invoice date', 'pass', 'Invoice date is valid and within the configured age limit.', evidence=ev('invoice_date'))
        except ValueError:
            add('invoice_date', 'Invoice date', 'fail', 'Invoice date is invalid. Confirm the date in YYYY-MM-DD format.', 'clarification', ev('invoice_date'))
    risky_notes = [n for n in invoice.extraction_notes if any(w in n.lower() for w in ('disagree', 'unsupported', 'completeness', 'unrecognized', 'ambiguous'))]
    if (any(p['method'] in ('ocr', 'unreadable') for p in document.get('pages', [])) or any(run.get('task') == 'vision' and run.get('status') == 'completed' for run in invoice.ai_runs)) and not verified:
        add('extraction_review', 'Scanned document verification', 'warning', 'This PDF used OCR or contains an unreadable page. Confirm extracted fields and item completeness against the original before continuing.', 'clarification')
    elif risky_notes and not verified:
        add('extraction_review', 'Extraction uncertainty', 'warning', ' '.join(risky_notes), 'clarification')
    else:
        add('extraction_review', 'Extraction verification', 'pass', 'A human confirmed the extracted fields.' if verified else 'Readable PDF processed; source excerpts are available for verification.')

    amounts = [invoice.total, invoice.subtotal, invoice.tax_amount]
    if any(a is not None and a < 0 for a in amounts) or invoice.total == 0:
        add('positive_amount', 'Invoice amount type', 'fail', 'Credit notes, zero-value invoices, or negative amounts require a separate review workflow.', 'clarification', ev('total', 'subtotal', 'tax_amount'))
    elif invoice.total is not None:
        add('positive_amount', 'Invoice amount type', 'pass', 'Positive invoice amount.', evidence=ev('total'))
    if all(a is not None for a in amounts):
        difference = abs(rounded(invoice.subtotal + invoice.tax_amount) - rounded(invoice.total))
        add('tax_math', 'Subtotal + tax = total', 'pass' if difference <= CENT else 'fail',
            f'{invoice.subtotal} + {invoice.tax_amount} = {rounded(invoice.subtotal + invoice.tax_amount)}; invoice total is {invoice.total}.',
            'ready' if difference <= CENT else 'clarification', ev('subtotal', 'tax_amount', 'total'))
    else:
        add('tax_math', 'Subtotal + tax = total', 'warning', 'Not enough explicit amounts to reconcile net, tax, and gross. Tax is not assumed to be zero.', 'clarification', ev('subtotal', 'tax_amount', 'total'))

    if not invoice.items:
        add('line_math', 'Invoice line items', 'warning' if policy.require_line_items else 'info', 'No complete line items were extracted. Confirm item completeness or upload an itemized invoice.', 'clarification' if policy.require_line_items else 'ready', [policy.evidence])
    else:
        bad = [i.description for i in invoice.items if i.quantity is None or i.unit_price is None or i.amount is None or i.quantity <= 0 or i.unit_price < 0 or i.amount < 0 or abs(rounded(i.quantity * i.unit_price) - rounded(i.amount)) > CENT]
        if bad:
            add('line_math', 'Quantity × unit price', 'fail', 'Missing values or arithmetic discrepancy in: ' + ', '.join(bad) + '.', 'clarification', [i.evidence for i in invoice.items if i.evidence])
        else:
            add('line_math', 'Quantity × unit price', 'pass', f'All {len(invoice.items)} extracted lines reconcile.', evidence=[i.evidence for i in invoice.items if i.evidence])
        expected = invoice.total if invoice.tax_inclusive else invoice.subtotal
        if expected is not None and all(i.amount is not None for i in invoice.items):
            line_sum = sum(i.amount for i in invoice.items)
            good = abs(rounded(line_sum) - rounded(expected)) <= CENT
            add('line_sum', 'Line-item completeness', 'pass' if good else 'fail', f'Extracted lines total {line_sum}; {"tax-inclusive total" if invoice.tax_inclusive else "net subtotal"} is {expected}.', 'ready' if good else 'clarification', [i.evidence for i in invoice.items if i.evidence] + ev('subtotal', 'total'))

    vendor = None
    name_matches = [v for v in vendors if normalize(invoice.vendor_name) in [normalize(v.name), *[normalize(a) for a in v.aliases]] and invoice.vendor_name]
    id_matches = [v for v in vendors if invoice.vendor_id and normalize(v.vendor_id) == normalize(invoice.vendor_id)]
    tax_matches = [v for v in vendors if invoice.tax_id and v.tax_id and normalize(v.tax_id) == normalize(invoice.tax_id)]
    candidates = {v.vendor_id: v for v in id_matches + tax_matches + name_matches}
    if len(candidates) == 1:
        vendor = next(iter(candidates.values()))
        conflicts = []
        if invoice.vendor_id and normalize(invoice.vendor_id) != normalize(vendor.vendor_id):
            conflicts.append('vendor ID')
        if invoice.tax_id and vendor.tax_id and normalize(invoice.tax_id) != normalize(vendor.tax_id):
            conflicts.append('tax ID')
        if invoice.vendor_name and normalize(invoice.vendor_name) not in [normalize(vendor.name), *[normalize(a) for a in vendor.aliases]]:
            conflicts.append('vendor name (not a registered alias)')
        if conflicts:
            add('vendor_identity', 'Vendor identity', 'fail', 'Invoice conflicts with vendor master: ' + ', '.join(conflicts) + '.', 'hold', ev('vendor_id', 'vendor_name', 'tax_id') + [vendor.evidence])
        else:
            add('vendor_identity', 'Vendor identity', 'pass', f'Exact match to {vendor.vendor_id} · {vendor.name}.', evidence=ev('vendor_id', 'vendor_name', 'tax_id') + [vendor.evidence])
        if vendor.status.casefold() in ('active', 'approved'):
            add('vendor_status', 'Approved vendor', 'pass', f'{vendor.name} is {vendor.status} in the supplied vendor master.', evidence=[vendor.evidence])
        elif vendor.status.casefold() in ('blocked', 'inactive', 'suspended'):
            add('vendor_status', 'Approved vendor', 'fail', f'Vendor is {vendor.status}. AP must investigate before proceeding.', 'hold', [vendor.evidence])
        else:
            add('vendor_status', 'Approved vendor', 'warning', 'Vendor approval status is unknown; procurement must confirm it.', 'procurement', [vendor.evidence])
        if policy.check_bank_details and invoice.bank_account:
            if vendor.bank_account:
                same = normalize(invoice.bank_account) == normalize(vendor.bank_account)
                add('bank_match', 'Bank account consistency', 'pass' if same else 'fail', 'Invoice bank account matches the vendor master.' if same else 'Invoice bank account differs from the vendor master. Independently verify the change with the vendor.', 'ready' if same else 'hold', ev('bank_account') + [vendor.evidence])
            else:
                add('bank_match', 'Bank account consistency', 'warning', 'Invoice contains bank details, but vendor master has no account to compare. Verify independently.', 'clarification', ev('bank_account') + [vendor.evidence])
        else:
            add('bank_match', 'Bank account consistency', 'info', 'No invoice bank account to compare; this review does not authorize payment.' if not invoice.bank_account else 'Bank comparison disabled by policy.', evidence=[policy.evidence])
    elif len(candidates) > 1:
        add('vendor_identity', 'Vendor identity', 'fail', 'Vendor identifiers resolve to multiple master records. Resolve the conflicting identities.', 'hold', [v.evidence for v in candidates.values()])
    else:
        add('vendor_identity', 'Vendor identity', 'fail', 'No exact approved-vendor identity match. Upload the vendor master or confirm the vendor details.', 'clarification', ev('vendor_id', 'vendor_name', 'tax_id'))

    duplicates = []
    if vendor and invoice.invoice_number:
        duplicates = [h for h in history if normalize(h.vendor_id) == normalize(vendor.vendor_id) and normalize(h.invoice_number) == normalize(invoice.invoice_number) and h.status.casefold() not in INACTIVE_STATUSES]
    batch_duplicates = [e for e in earlier if e['hash'] == document['sha256'] or (vendor and e.get('vendor_id') == vendor.vendor_id and invoice.invoice_number and normalize(e.get('invoice_number', '')) == normalize(invoice.invoice_number))]
    hash_duplicates = [h for h in history if h.document_hash and h.document_hash == document['sha256'] and h.status.casefold() not in INACTIVE_STATUSES]
    if duplicates or batch_duplicates or hash_duplicates:
        refs = list({h.invoice_number for h in duplicates + hash_duplicates}) + [e['filename'] for e in batch_duplicates]
        add('duplicate', 'Duplicate submission', 'fail', 'Possible duplicate: ' + ', '.join(refs) + '. Same vendor/invoice number or identical PDF hash already exists.', 'hold', [h.evidence for h in duplicates + hash_duplicates] + [Evidence(document_id=e['id'], filename=e['filename'], excerpt='Earlier invoice in this workspace with matching identity or file hash.') for e in batch_duplicates])
    elif not (bool(history) if history_provided is None else history_provided):
        add('duplicate', 'Duplicate submission', 'warning', 'No historical invoice register supplied. Batch duplicates were checked, but previous submissions cannot be ruled out.', 'clarification')
    elif not vendor or not invoice.invoice_number:
        add('duplicate', 'Duplicate submission', 'warning', 'Vendor identity and invoice number are required for a reliable duplicate check.', 'clarification')
    else:
        add('duplicate', 'Duplicate submission', 'pass', f'No active match in {len(history)} historical records or earlier workspace invoices.', evidence=ev('invoice_number') + list({h.evidence.document_id: h.evidence for h in history}.values()))

    po = None
    po_candidates = []
    context = {}
    matches = [p for p in pos if invoice.po_number and normalize(p.po_number) == normalize(invoice.po_number)]
    if len(matches) == 1:
        po = matches[0]
        add('po_match', 'Purchase order match', 'pass', f'Explicit reference matches {po.po_number}.', evidence=ev('po_number') + [po.evidence])
    elif len(matches) > 1:
        add('po_match', 'Purchase order match', 'fail', 'Multiple purchase orders share this normalized reference. Resolve conflicting PO records.', 'procurement', [p.evidence for p in matches])
    else:
        po_candidates = [p.po_number for p in pos
                         if p.status.casefold() == 'approved'
                         and (not invoice.currency or p.currency == invoice.currency)
                         and ((vendor and p.vendor_id and normalize(p.vendor_id) == normalize(vendor.vendor_id))
                              or (invoice.vendor_name and p.vendor_name and normalize(p.vendor_name) == normalize(invoice.vendor_name)))]
        message = f'PO reference {invoice.po_number} was not found.' if invoice.po_number else 'Invoice has no PO reference.'
        message += ' Candidate POs: ' + ', '.join(po_candidates[:5]) + '. Confirm the intended PO; candidates are not auto-matched.' if po_candidates else ' Confirm the PO reference and provide the approved order if it is missing.'
        add('po_match', 'Purchase order match', 'fail', message, 'procurement' if invoice.po_number else 'clarification', ev('po_number'))

    if po:
        po_vendor_ok = bool(vendor and ((po.vendor_id and normalize(po.vendor_id) == normalize(vendor.vendor_id)) or (not po.vendor_id and po.vendor_name and normalize(po.vendor_name) in [normalize(vendor.name), *[normalize(a) for a in vendor.aliases]])))
        add('po_vendor', 'PO vendor ownership', 'pass' if po_vendor_ok else 'fail', 'PO belongs to the matched vendor.' if po_vendor_ok else 'PO vendor does not agree with the verified invoice vendor.', 'ready' if po_vendor_ok else 'procurement', [po.evidence] + ([vendor.evidence] if vendor else []))
        approved = po.status.casefold() == 'approved'
        add('po_approval', 'PO approval status', 'pass' if approved else 'fail', f'PO status: {po.status}.', 'ready' if approved else 'procurement', [po.evidence])
        currency_ok = invoice.currency == po.currency
        add('po_currency', 'Currency agreement', 'pass' if currency_ok else 'fail', f'Invoice: {invoice.currency or "unknown"}; PO: {po.currency}. No currency conversion is assumed.', 'ready' if currency_ok else 'procurement', ev('currency') + [po.evidence])
        try:
            when = date.fromisoformat(invoice.invoice_date) if invoice.invoice_date else None
        except ValueError:
            when = None  # Already routed to clarification by the invoice-date check.
        try:
            start = date.fromisoformat(po.valid_from) if po.valid_from else None
            end = date.fromisoformat(po.valid_to) if po.valid_to else None
            if (start or end) and when:
                valid = (not start or when >= start) and (not end or when <= end)
                add('po_validity', 'PO validity period', 'pass' if valid else 'fail', f'Invoice date {when}; PO validity {po.valid_from or "open"} to {po.valid_to or "open"}.', 'ready' if valid else 'procurement', [po.evidence] + ev('invoice_date'))
        except ValueError:
            add('po_validity', 'PO validity period', 'fail', 'PO has an invalid validity date. Confirm the effective period.', 'procurement', [po.evidence])
        committed = [h for h in history if normalize(h.po_number) == normalize(po.po_number) and h.status.casefold() in COMMITTED_STATUSES]
        invalid_history = [h for h in committed if h.currency != po.currency or (po.amount_basis == 'net' and h.subtotal is None) or (po.vendor_id and normalize(h.vendor_id) != normalize(po.vendor_id))]
        unknown_status = [h for h in history if normalize(h.po_number) == normalize(po.po_number) and h.status.casefold() not in COMMITTED_STATUSES | INACTIVE_STATUSES]
        used = sum((h.subtotal if po.amount_basis == 'net' else h.total) for h in committed if h not in invalid_history)
        reserved = reservations.get(normalize(po.po_number), [])
        batch_used = sum(r['amount'] for r in reserved)
        remaining = po.amount - used - batch_used
        tolerance = max(po.amount * policy.amount_tolerance_percent / 100, policy.amount_tolerance_absolute)
        amount = invoice.subtotal if po.amount_basis == 'net' else invoice.total
        context = {'basis': po.amount_basis, 'po_amount': str(po.amount), 'historical_committed': str(used), 'batch_reserved': str(batch_used), 'remaining': str(remaining), 'invoice_amount': str(amount) if amount is not None else None, 'tolerance': str(tolerance), 'after_invoice': str(remaining - amount) if amount is not None else None, 'historical_invoices': [h.invoice_number for h in committed], 'batch_invoices': [r['invoice_number'] for r in reserved]}
        if invalid_history or unknown_status:
            add('po_balance', 'Cumulative PO balance', 'fail', 'Historical records for this PO have missing net amounts, conflicting currency/vendor, or unknown status. Remaining commitment cannot be verified.', 'procurement', [h.evidence for h in invalid_history + unknown_status])
        elif amount is None:
            add('po_balance', 'Cumulative PO balance', 'fail', f'PO uses {po.amount_basis} amounts; the corresponding invoice amount is missing.', 'clarification', [po.evidence])
        elif currency_ok:
            within = amount <= remaining + tolerance
            add('po_balance', 'Cumulative PO balance', 'pass' if within else 'fail', f'{po.currency} {amount} {po.amount_basis} against {remaining} remaining ({used} historical + {batch_used} reserved in this batch). Permitted tolerance: {rounded(tolerance)} = max({policy.amount_tolerance_percent}% of PO, {policy.amount_tolerance_absolute}).' + (' Within tolerance.' if within else ' PO capacity exceeded.'), 'ready' if within else 'procurement', [po.evidence, policy.evidence] + [h.evidence for h in committed] + ev('subtotal' if po.amount_basis == 'net' else 'total'))
        pending = [entry for entry in earlier if entry.get('source_unverified') and normalize(entry.get('po_number', '')) == normalize(po.po_number)]
        if pending:
            names = [entry.get('invoice_number') or entry['filename'] for entry in pending]
            known_amounts = [Decimal(entry['amount']) for entry in pending if entry.get('amount') is not None and Decimal(entry['amount']) > 0]
            pending_total = sum(known_amounts, Decimal(0))
            complete = len(known_amounts) == len(pending)
            context['pending_invoices'] = names
            context['pending_amount'] = str(pending_total) if complete else None
            context['potential_remaining'] = str(remaining - pending_total) if complete else None
            exposure = (f' They claim {po.currency} {pending_total} {po.amount_basis}; possible remaining capacity is {po.currency} {remaining - pending_total} if they are valid.'
                        if complete else ' Their full amount is not known.')
            add('po_pending', 'Earlier PO invoices awaiting source verification', 'warning',
                f'Earlier invoice(s) for {po.po_number} need source verification: {", ".join(names[:5])}. The confirmed PO balance excludes them.' + exposure +
                ' Verify the earlier source before treating this invoice as ready.', 'clarification',
                [Evidence(document_id=entry['id'], filename=entry['filename'], excerpt='Earlier invoice needs source verification; its PO commitment is not confirmed.') for entry in pending])
        if po.items and invoice.items:
            suggestions = {entry['invoice_line']: entry for entry in (semantic or {}).get('matches', [])}
            assignments = {}
            for n, entry in enumerate(invoice.items):
                exact_indices = [i for i, item in enumerate(po.items) if (entry.sku and item.sku and normalize(entry.sku) == normalize(item.sku)) or normalize(entry.description) == normalize(item.description)]
                proposal = suggestions.get(n)
                if len(exact_indices) == 1:
                    assignments[n] = exact_indices[0]
                elif proposal and proposal.get('equivalence') == 'equivalent' and type(proposal.get('po_line')) is int and 0 <= proposal['po_line'] < len(po.items):
                    assignments[n] = proposal['po_line']
            context['line_assignments'] = {str(k): v for k, v in assignments.items()}
            for index, line in enumerate(invoice.items):
                scored = [(i, p, SequenceMatcher(None, normalize(line.description), normalize(p.description)).ratio()) for i, p in enumerate(po.items)]
                exact = [(i, p, s) for i, p, s in scored if (line.sku and p.sku and normalize(line.sku) == normalize(p.sku)) or normalize(line.description) == normalize(p.description)]
                # Similar descriptions are suggestions, never authority to approve an item.
                if len(exact) != 1:
                    proposal = suggestions.get(index)
                    if index in assignments:
                        po_index = assignments[index]
                        item = po.items[po_index]
                        confirmed = bool(proposal and proposal.get('confirmed'))
                        add(f'semantic_{index}', 'Semantic item equivalence', 'pass' if confirmed else 'warning',
                            f'Invoice "{line.description}" ↔ PO "{item.description}". ' + (proposal.get('reason', '') if proposal else '') +
                            (' Human confirmed this equivalence.' if confirmed else ' AI proposal requires human confirmation; rates and quantities are checked separately.'),
                            'ready' if confirmed else 'clarification', ([line.evidence] if line.evidence else []) + [po.evidence])
                    else:
                        closest = max(scored, key=lambda x: x[2])
                        hint = f' Closest PO description: {closest[1].description}.' if closest[2] > .4 else ''
                        reason = f' AI comparison: {proposal["reason"]}' if proposal else ''
                        add(f'item_{index}', 'Item description match', 'warning', f'"{line.description}" has no unique exact item match.' + hint + reason + ' Procurement must confirm equivalence.', 'procurement', ([line.evidence] if line.evidence else []) + [po.evidence])
                        continue
                else:
                    po_index, item, _ = exact[0]
                if line.unit_price is None or item.unit_price is None:
                    add(f'item_{index}', 'Contracted unit price', 'warning', f'Missing unit price for {line.description}.', 'clarification', [po.evidence])
                elif invoice.tax_inclusive and po.amount_basis == 'net':
                    add(f'item_{index}', 'Contracted unit price', 'warning', 'Invoice line prices include tax while PO prices are net. Confirm comparable line prices; no tax allocation is guessed.', 'procurement', [po.evidence])
                else:
                    allowed = abs(item.unit_price) * policy.unit_price_tolerance_percent / 100
                    price_ok = abs(line.unit_price - item.unit_price) <= allowed + CENT
                    same_item = lambda other: normalize(other.description) == normalize(item.description) or bool(item.sku and other.sku and normalize(other.sku) == normalize(item.sku))
                    quantity = sum((l.quantity or Decimal(0)) for n, l in enumerate(invoice.items) if assignments.get(n) == po_index)
                    history_lines = [l for h in committed for l in h.items if same_item(l)]
                    batch_lines = [l for r in reserved for n, l in enumerate(r.get('items', [])) if r.get('line_assignments', {}).get(str(n)) == po_index or (str(n) not in r.get('line_assignments', {}) and same_item(l))]
                    previous_quantity = sum((l.quantity or Decimal(0)) for l in history_lines + batch_lines)
                    qty_ok = item.quantity is not None and quantity + previous_quantity <= item.quantity
                    add(f'item_{index}', 'Contracted item rate & quantity', 'pass' if price_ok and qty_ok else 'fail', f'{line.description}: invoice rate {line.unit_price}, PO rate {item.unit_price}; quantity {quantity} + {previous_quantity} previously committed / {item.quantity if item.quantity is not None else "unknown"} ordered. Unit-price tolerance {policy.unit_price_tolerance_percent}%.', 'ready' if price_ok and qty_ok else 'procurement', ([line.evidence] if line.evidence else []) + [po.evidence, policy.evidence] + [h.evidence for h in committed])
            history_incomplete = any(not h.items or any(l.quantity is None for l in h.items) or abs(sum((l.amount if l.amount is not None else (l.quantity * l.unit_price if l.quantity is not None and l.unit_price is not None else Decimal(0))) for l in h.items) - (h.subtotal if h.subtotal is not None else h.total)) > CENT for h in committed)
            if history_incomplete:
                add('historical_quantity', 'Cumulative item quantities', 'warning', 'Historical invoices have incomplete item-level quantities or amounts. Procurement must confirm remaining quantities.', 'procurement', [h.evidence for h in committed])
            elif any(sum(1 for p in po.items if normalize(l.description) == normalize(p.description) or bool(l.sku and p.sku and normalize(l.sku) == normalize(p.sku))) != 1 for h in committed for l in h.items):
                add('historical_quantity', 'Historical item equivalence', 'warning', 'Some historical item descriptions do not uniquely match PO items. Confirm their quantities before relying on the remaining item balance.', 'procurement', [h.evidence for h in committed] + [po.evidence])
        elif not po.items:
            add('po_lines', 'Contracted line-item checks', 'warning', 'PO has no itemized rates or quantities. An amount-only comparison cannot establish that the goods or services match.', 'procurement', [po.evidence])

    priority = {'ready': 0, 'clarification': 1, 'procurement': 2, 'hold': 3}
    decision = max((c.route for c in checks), key=lambda route: priority[route])
    issues = [c for c in checks if c.route == decision and c.status in ('warning', 'fail')]
    summary = ('All available checks passed. A human approver must confirm receipt and business authorization before approval.' if decision == 'ready' else ' '.join(c.message for c in issues[:2]))
    return Review(id=document['id'], document_id=document['id'], filename=document['filename'], invoice=invoice, decision=decision, summary=summary, checks=checks, matched_vendor=vendor, matched_po=po, po_candidates=po_candidates, po_context=context, reviewed_at=datetime.now().astimezone().isoformat(), ai_analysis={'extraction_runs': invoice.ai_runs, 'matching': semantic} if invoice.ai_runs or semantic else {})
