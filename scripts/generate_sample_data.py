"""Create physical, synthetic PDF fixtures and verify them with the AP pipeline.

Run from the project root: .venv/bin/python scripts/generate_sample_data.py
No real workspace is read or modified. Existing unrelated files are preserved.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
import zipfile

import pymupdf as fitz
from PIL import Image, ImageEnhance, ImageFilter
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import Table, TableStyle, Paragraph
from reportlab.lib.styles import ParagraphStyle

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app import demo, store
from app.extraction import extract_invoice, read_pdf
from app.service import ingest, run_reviews

OUT = ROOT / 'sample-data'
DAY = datetime.now(ZoneInfo('Asia/Kolkata')).date()
WIDTH, HEIGHT = A4
GREEN = colors.HexColor('#183c34')
MUTED = colors.HexColor('#61756b')
LINE = colors.HexColor('#dce5df')
STYLE = ParagraphStyle('table', fontName='Helvetica', fontSize=9, leading=13, textColor=GREEN)


def header(c, title='VENDOR INVOICE', page=1, pages=1, variant='standard'):
    c.setFillColor(GREEN if variant != 'table' else colors.HexColor('#233e66'))
    c.rect(0, HEIGHT - 94, WIDTH, 94, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont('Helvetica-Bold', 19)
    c.drawString(38, HEIGHT - 43, title)
    c.setFont('Helvetica', 8)
    c.drawString(38, HEIGHT - 65, 'SYNTHETIC TEST DATA - NOT A REAL BILL OR PAYMENT REQUEST')
    c.setStrokeColor(LINE)
    c.line(38, 49, WIDTH - 38, 49)
    c.setFont('Helvetica', 8)
    c.setFillColor(MUTED)
    c.drawString(38, 33, 'Ledger AP sample pack | Generated ' + DAY.isoformat())
    c.drawRightString(WIDTH - 38, 33, f'Page {page} of {pages}')


def text(c, value, x, y, size=10, bold=False, color=GREEN):
    c.setFillColor(color)
    c.setFont('Helvetica-Bold' if bold else 'Helvetica', size)
    c.drawString(x, y, str(value))


def metadata(c, invoice, two_column=False):
    fields = [('Vendor Name', 'vendor_name'), ('Vendor ID', 'vendor_id'), ('Tax ID', 'tax_id'),
              ('Invoice Number', 'invoice_number'), ('Invoice Date', 'invoice_date'),
              ('PO Number', 'po_number'), ('Currency', 'currency'), ('Bank Account', 'bank_account')]
    if two_column:
        # A realistic difficult layout: multiple labelled values share each baseline.
        for index, (label, field) in enumerate(fields):
            col, row = (0, index) if index < 3 else (1, index - 3)
            text(c, f'{label}: {invoice.get(field, "")}', 38 if col == 0 else 321,
                 HEIGHT - 132 - row * 26, size=8.5)
        return HEIGHT - 294
    for index, (label, field) in enumerate(fields):
        text(c, f'{label}: {invoice.get(field, "")}', 38, HEIGHT - 129 - index * 23, size=10)
    return HEIGHT - 340


def items(c, rows, y, tabular=False, inclusive=False):
    text(c, 'ITEMIZED CHARGES' + (' - TAX INCLUSIVE' if inclusive else ''), 38, y, size=8, bold=True, color=MUTED)
    y -= 27
    if tabular:
        values = [['Description', 'Quantity', 'Unit price', 'Amount']]
        for row in rows:
            values.append([Paragraph(row['description'], STYLE), str(row['quantity']), str(row['unit_price']), str(row['amount'])])
        table = Table(values, colWidths=[245, 65, 100, WIDTH - 486], repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#edf2f7')),
            ('TEXTCOLOR', (0, 0), (-1, -1), GREEN), ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9), ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('TOPPADDING', (0, 0), (-1, -1), 11),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 11), ('LINEBELOW', (0, 0), (-1, -1), .5, LINE),
        ]))
        _, height = table.wrap(WIDTH - 76, HEIGHT)
        table.drawOn(c, 38, y - height)
        return y - height - 33
    text(c, 'Description | Quantity | Unit Price | Amount', 38, y, size=10, bold=True)
    c.setStrokeColor(LINE)
    c.line(38, y - 10, WIDTH - 38, y - 10)
    y -= 33
    for row in rows:
        text(c, f'{row["description"]} | {row["quantity"]} | {row["unit_price"]} | {row["amount"]}', 38, y, size=10)
        y -= 27
    return y - 13


def totals(c, invoice, y, split_gst=False):
    entries = [('Subtotal', invoice.get('subtotal', ''))]
    if split_gst:
        half = Decimal(str(invoice['tax_amount'])) / 2
        entries += [('CGST 9%', str(half)), ('SGST 9%', str(half))]
    else:
        entries.append(('Total Tax', invoice.get('tax_amount', '')))
    entries.append(('Invoice Total', invoice.get('total', '')))
    for label, value in entries:
        text(c, f'{label}: {value}', 38, y, size=12 if label == 'Invoice Total' else 10, bold=label == 'Invoice Total')
        y -= 26
    text(c, 'Terms: payable within 30 days after internal approval.', 38, y - 17, size=9, color=MUTED)
    return y - 17


def make_invoice(invoice, style='standard'):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4, pageCompression=1, invariant=1)
    c.setTitle('Synthetic AP test - ' + invoice.get('invoice_number', 'missing identifier'))
    c.setAuthor('Ledger synthetic sample generator')
    page_count = 3 if style == 'multipage' else 2 if style == 'mixed' else 1
    header(c, page=1, pages=page_count, variant=style)
    y = metadata(c, invoice, two_column=style == 'two_column')
    if style in ('multipage', 'mixed'):
        text(c, 'Invoice item schedule continues on the following page.', 38, y - 15, size=11, bold=True)
        text(c, 'The complete invoice is this PDF, including its continuation pages.', 38, y - 39, size=9, color=MUTED)
        c.showPage()
        header(c, 'INVOICE - ITEM SCHEDULE', page=2, pages=page_count)
        y = items(c, invoice['items'], HEIGHT - 133, tabular=True)
        if style == 'multipage':
            text(c, 'Invoice amounts continue on page 3.', 38, y - 15, size=10, color=MUTED)
            c.showPage()
            header(c, 'INVOICE - AMOUNT SUMMARY', page=3, pages=3)
            totals(c, invoice, HEIGHT - 138)
        else:
            totals(c, invoice, y)
    else:
        y = items(c, invoice['items'], y, tabular=style in ('table', 'two_column'), inclusive=invoice.get('tax_inclusive', False))
        totals(c, invoice, y, split_gst=style == 'split_gst')
    c.save()
    result = buffer.getvalue()
    if style in ('scan', 'low_contrast', 'rotated', 'mixed'):
        result = rasterize(result, style)
    return result


def rasterize(data, style):
    output = fitz.open()
    with fitz.open(stream=data, filetype='pdf') as doc:
        for index, page in enumerate(doc):
            if style == 'mixed' and index == 0:
                output.insert_pdf(doc, from_page=index, to_page=index)
                continue
            image = Image.open(io.BytesIO(page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8)).tobytes('png'))).convert('L')
            if style == 'low_contrast':
                image = ImageEnhance.Contrast(image).enhance(.28)
                image = ImageEnhance.Brightness(image).enhance(1.3).filter(ImageFilter.GaussianBlur(.35))
            elif style == 'rotated':
                image = image.rotate(90, expand=True, fillcolor='white')
            else:
                image = image.filter(ImageFilter.GaussianBlur(.15))
            encoded = io.BytesIO()
            image.save(encoded, format='PNG')
            width, height = (HEIGHT, WIDTH) if style == 'rotated' else (WIDTH, HEIGHT)
            new_page = output.new_page(width=width, height=height)
            new_page.insert_image(new_page.rect, stream=encoded.getvalue())
    result = output.tobytes(garbage=4, deflate=True)
    output.close()
    return result


def make_po(po):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4, invariant=1)
    header(c, 'APPROVED PURCHASE ORDER')
    rows = [('PO Number', po['po_number']), ('Vendor ID', po['vendor_id']), ('Vendor Name', po['vendor_name']),
            ('Currency', po['currency']), ('Amount Basis', po['amount_basis']), ('Status', po['status']),
            ('Valid From', po['valid_from']), ('Valid To', po['valid_to']),
            ('Net Amount' if po['amount_basis'] == 'net' else 'Total', po['amount'])]
    for index, (label, value) in enumerate(rows):
        text(c, f'{label}: {value}', 38, HEIGHT - 131 - index * 23)
    items(c, po['items'], HEIGHT - 373)
    c.save()
    return buffer.getvalue()


def json_file(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + '\n')


def main():
    # Make sample generation reproducible without allowing an installed AI provider
    # to change its manifest or receive synthetic documents during this command.
    os.environ.pop('AI_BASE_URL', None)
    os.environ.pop('AI_MODEL', None)
    os.environ.pop('OPENROUTER_API_KEY', None)
    os.environ.pop('AI_API_KEY', None)
    (OUT / 'invoices').mkdir(parents=True, exist_ok=True)
    references, base_pdfs = {}, []
    for kind, name, content in demo.files(include_scan=False):
        if kind == 'invoice':
            base_pdfs.append((name, content))
        elif kind != 'manifest':
            references[kind] = (name, json.loads(content))
        else:
            base_manifest = json.loads(content)
    cases = []
    for (filename, content), expected in zip(base_pdfs, base_manifest):
        invoice = extract_invoice(read_pdf(content, 'base', filename), use_ai=False).model_dump(mode='json')
        cases.append({'filename': filename, 'invoice': invoice, 'style': 'standard', 'expected': expected['expected_decision'], 'focus': {
            'ready': 'Valid invoice; exact vendor, PO, line, and arithmetic checks.',
            'hold': 'Duplicate, blocked vendor, or changed bank account.',
            'clarification': 'Missing identifiers or inconsistent amounts.',
            'procurement': 'PO capacity, quantity, or unit-price discrepancy.'}[expected['expected_decision']]})

    vendor = references['vendors'][1][0]
    pos = references['purchase_orders'][1]

    def add(number, filename, style='standard', expected='ready', focus='', changes=None, po_changes=None):
        po_ref = f'PO-F{number:03d}'
        invoice = {'invoice_number': f'FMT-{number:03d}', 'invoice_date': (DAY - timedelta(days=3)).isoformat(),
                   'vendor_name': vendor['name'], 'vendor_id': vendor['vendor_id'], 'tax_id': vendor['tax_id'],
                   'bank_account': vendor['bank_account'], 'po_number': po_ref, 'currency': 'INR',
                   'subtotal': '1000', 'tax_amount': '0', 'total': '1000',
                   'items': [{'description': 'Storage units', 'quantity': '1', 'unit_price': '1000', 'amount': '1000'}]}
        po = {'po_number': po_ref, 'vendor_id': vendor['vendor_id'], 'vendor_name': vendor['name'], 'currency': 'INR',
              'amount': '5000', 'amount_basis': 'net', 'status': 'approved',
              'valid_from': (DAY - timedelta(days=180)).isoformat(), 'valid_to': (DAY + timedelta(days=180)).isoformat(),
              'items': [{'description': 'Storage units', 'quantity': '5', 'unit_price': '1000', 'amount': '5000'}]}
        invoice.update(changes or {})
        po.update(po_changes or {})
        pos.append(po)
        cases.append({'filename': f'{number:02d}-{filename}.pdf', 'invoice': invoice, 'style': style, 'expected': expected, 'focus': focus})

    add(13, 'scanned-invoice', 'scan', 'clarification', 'Image-only PDF: OCR must be verified by a human.')
    add(14, 'positioned-table', 'table', focus='Native PDF with a real positioned item table and separate columns.')
    add(15, 'three-page-invoice', 'multipage', focus='Identity on page 1, item schedule on page 2, totals on page 3.')
    add(16, 'mixed-text-and-scan', 'mixed', 'clarification', 'Native cover page with scanned item/totals page; per-page extraction.')
    add(17, 'low-contrast-scan', 'low_contrast', 'clarification', 'Faded grayscale scan intentionally tests OCR uncertainty.')
    add(18, 'sideways-scan', 'rotated', 'clarification', 'Image rotated 90 degrees; manual rotation/verification may be needed.')
    add(19, 'tax-inclusive-gross-po', 'table', focus='Gross PO and tax-inclusive line rate use the same comparison basis.',
        changes={'subtotal': '1000', 'tax_amount': '180', 'total': '1180', 'tax_inclusive': True,
                 'items': [{'description': 'Storage units', 'quantity': '1', 'unit_price': '1180', 'amount': '1180'}]},
        po_changes={'amount': '5900', 'amount_basis': 'gross', 'items': [{'description': 'Storage units', 'quantity': '5', 'unit_price': '1180', 'amount': '5900'}]})
    add(20, 'cgst-sgst-components', 'split_gst', focus='CGST 9% plus SGST 9% must sum to the explicit tax amount.', changes={'tax_amount': '180', 'total': '1180'})
    add(21, 'currency-mismatch', expected='procurement', focus='USD invoice against INR purchase order; no implicit conversion.', changes={'currency': 'USD'})
    add(22, 'ambiguous-numeric-date', expected='clarification', focus='01/02/2026 is ambiguous; date locale must be confirmed.', changes={'invoice_date': '01/02/2026'})
    add(23, 'different-item-description', expected='procurement', focus='Same amounts but different item wording; equivalence requires review.',
        changes={'items': [{'description': 'Managed archive capacity', 'quantity': '1', 'unit_price': '1000', 'amount': '1000'}]})
    cases.append({'filename': '24-identical-resubmission.pdf', 'copy_from': '14-positioned-table.pdf', 'expected': 'hold', 'style': 'identical copy', 'focus': 'Exact byte-for-byte duplicate of case 14, submitted under another filename.'})
    cases.append({'filename': '25-blank-document.pdf', 'expected': 'clarification', 'style': 'blank', 'focus': 'A valid empty PDF page; no fields may be invented.'})
    add(26, 'password-protected', 'password', 'upload_rejected', 'Encrypted PDF. Expected upload error; password is sample123.')
    add(27, 'missing-invoice-date', expected='clarification', focus='Invoice date deliberately omitted.', changes={'invoice_date': ''})
    add(28, 'credit-note', expected='clarification', focus='Negative credit-note amounts require a separate workflow.',
        changes={'subtotal': '-1000', 'tax_amount': '-180', 'total': '-1180', 'items': [{'description': 'Storage units', 'quantity': '-1', 'unit_price': '1000', 'amount': '-1000'}]})
    add(29, 'unregistered-vendor', expected='clarification', focus='Vendor absent from approved master and PO reference missing.',
        changes={'vendor_name': 'Unregistered Sample Services', 'vendor_id': 'V999', 'tax_id': 'SYNTHETIC-UNKNOWN', 'bank_account': '000000000001', 'po_number': ''})
    add(30, 'cancelled-po', expected='procurement', focus='PO exists but is cancelled; valid amounts are insufficient.', po_changes={'status': 'cancelled'})
    add(31, 'two-column-metadata', 'two_column', focus='Difficult two-column metadata layout; semantically valid invoice. Exposes local-parser limitations.')

    for kind, (name, records) in references.items():
        json_file(OUT / kind / name, records)
    generated = []
    for case in cases:
        target = OUT / 'invoices' / case['filename']
        if 'copy_from' in case:
            target.write_bytes((OUT / 'invoices' / case['copy_from']).read_bytes())
        elif case['style'] == 'blank':
            doc = fitz.open(); doc.new_page(); target.write_bytes(doc.tobytes()); doc.close()
        else:
            content = make_invoice(case['invoice'], case['style'])
            if case['style'] == 'password':
                with fitz.open(stream=content, filetype='pdf') as doc:
                    content = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw='owner-sample123', user_pw='sample123')
            target.write_bytes(content)
        generated.append(target)
    alternatives = OUT / 'po-pdf-alternatives'
    alternatives.mkdir(exist_ok=True)
    for ref in ('PO-F014', 'PO-F019'):
        po = next(p for p in pos if p['po_number'] == ref)
        path = alternatives / f'{ref}.pdf'
        path.write_bytes(make_po(po))
        generated.append(path)

    # Verify actual current behavior against independent, semantic expectations.
    # Reports record discrepancies rather than relabeling failures as successes.
    with tempfile.TemporaryDirectory(prefix='ledger-sample-verify-') as temp:
        original_data = store.DATA
        store.DATA = Path(temp)
        try:
            state = store.initial_state()
            for kind, (name, records) in references.items():
                ingest(state, kind, name, json.dumps(records).encode())
            rejected = {}
            for case in cases:
                path = OUT / 'invoices' / case['filename']
                try:
                    ingest(state, 'invoice', path.name, path.read_bytes())
                except ValueError as exc:
                    rejected[path.name] = str(exc)
            run_reviews(state)
            actual = {r['filename']: r for r in state['reviews']}
            manifest = []
            for case in cases:
                path = OUT / 'invoices' / case['filename']
                review = actual.get(case['filename'])
                observed = review['decision'] if review else 'upload_rejected'
                manifest.append({'file': str(path.relative_to(OUT)), 'synthetic': True, 'format': case['style'],
                                 'test_focus': case['focus'], 'expected_business_outcome': case['expected'],
                                 'observed_local_outcome': observed, 'matches_expectation': observed == case['expected'],
                                 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                 'unresolved_checks': [c['code'] for c in review['checks'] if c['route'] != 'ready'] if review else [],
                                 'upload_error': rejected.get(case['filename']),
                                 'invoice_truth': case.get('invoice')})
        finally:
            store.DATA = original_data
    json_file(OUT / 'expected-results.json', {'generated_on': DAY.isoformat(), 'mode': 'Local extraction and OCR; external LLM disabled', 'invoice_count': len(cases), 'pdf_count': len(generated), 'upload_order': 'Reference JSON files first, then invoices in ascending filename order.', 'cases': manifest})
    write_guide(manifest)
    archive_path = OUT / 'ledger-sample-test-cases.zip'
    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in [*generated, OUT / 'README.md', OUT / 'expected-results.json', *[OUT / k / n for k, (n, _) in references.items()]]:
            archive.write(path, path.relative_to(OUT))
    failures = [m for m in manifest if not m['matches_expectation']]
    print(json.dumps({'invoice_pdfs': len(cases), 'total_pdfs': len(generated), 'matches_expected': len(cases) - len(failures),
                      'known_limitations': [{'file': m['file'], 'expected': m['expected_business_outcome'], 'observed': m['observed_local_outcome']} for m in failures],
                      'archive': str(archive_path)}, indent=2))


def write_guide(manifest):
    lines = ['# Physical sample PDFs for invoice review', '',
             '**All identities, accounts, invoices, orders, and amounts are synthetic.**', '',
             f'Generated on **{DAY.isoformat()}**: **31 invoice PDFs + 2 alternative PO PDFs**.', '',
             '## Load the sample pack', '',
             '1. Start the app with `./run.sh` and use an empty workspace. Do not also load the built-in 13-example demo: its reference IDs overlap this pack.',
             '2. Upload `vendors/approved-vendors.json` under **Vendor master**.',
             '3. Upload `purchase_orders/purchase-orders.json` under **Purchase orders**.',
             '4. Upload `history/previous-invoices.json` under **Invoice history**.',
             '5. Upload `policy/ap-policy.json` under **Company policy**.',
             '6. Upload `invoices/01-...pdf` through `25-...pdf` in ascending filename order (25 files maximum per upload), then cases 26-31.',
             '7. Review fields, original PDFs, source evidence, checks, and recommendations.', '',
             'For isolated tests, use the same reference files and upload a selected invoice. Cases 11/12 depend on earlier ready invoices, and case 24 depends on case 14. The manifest records results for the complete ordered batch.', '',
             '**Protected-PDF test:** case 26 is intentionally encrypted with password `sample123`. The current app should reject the locked upload with an actionable message. The password is for manual inspection; do not unlock it before testing that behavior.', '',
             '**Alternative PO PDFs:** `po-pdf-alternatives/` contains native PDF versions of PO-F014 and PO-F019. They duplicate two entries in the JSON PO master. To test them, omit those two rows from a copy of the JSON master, or use the relevant PDF in a separate empty workspace. Uploading both representations should produce a duplicate-reference error.', '',
             '## Cases and verified local behavior', '',
             'Results below were obtained using local text extraction/OCR with the optional LLM disabled. OCR output can vary across runtime versions. A mismatch is a documented extraction limitation, not a corrected ground truth.', '',
             '| PDF | Format / test | Intended outcome | Observed local outcome |',
             '| --- | --- | --- | --- |']
    for item in manifest:
        name = Path(item['file']).name
        label = item['observed_local_outcome'] + (' **(limitation)**' if not item['matches_expectation'] else '')
        lines.append(f'| [{name}]({item["file"]}) | {item["test_focus"]} | {item["expected_business_outcome"]} | {label} |')
    lines += ['', '## Ground truth and evidence', '',
              '`expected-results.json` contains intended and observed outcomes, unresolved check codes, original field truth for authored invoices, file hashes, and upload errors. Case 24 is a byte-for-byte copy of case 14. Case 25 intentionally has no content.', '',
              'The low-contrast and sideways scans are intentionally degraded test inputs. They must not be silently treated as verified. The two-column example is deliberately difficult for the local parser; compare its extraction against the PDF before interpreting vendor-conflict alerts.', '',
              '## Regenerate', '',
              'From the project directory:', '', '```bash',
              'uv pip install --python .venv/bin/python -r scripts/requirements-samples.txt',
              '.venv/bin/python scripts/generate_sample_data.py', '```', '',
              'The generator refreshes dates, rewrites these named synthetic fixtures, recomputes observed outcomes in a temporary workspace, and rebuilds the ZIP. It does not read or change your live AP workspace.', '',
              'Regenerate after a year or whenever you want fresh invoice/PO dates. Use `ledger-sample-test-cases.zip` to move the complete pack to another machine.']
    (OUT / 'README.md').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
