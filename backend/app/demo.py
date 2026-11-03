"""Synthetic documents only. Fixtures exercise the real upload and review pipeline."""
import io
import json
import zipfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pymupdf as fitz


def invoice_pdf(invoice: dict, scan=False) -> bytes:
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    page.draw_rect(fitz.Rect(0, 0, 595, 105), color=None, fill=(.08, .15, .12))
    page.insert_text((38, 43), 'SYNTHETIC VENDOR INVOICE', fontsize=18, color=(.9, .95, .8))
    page.insert_text((38, 72), 'DEMONSTRATION DATA / NOT A REAL BILL', fontsize=9, color=(.8, .85, .8))
    rows = [f'Vendor Name: {invoice.get("vendor_name", "")}', f'Vendor ID: {invoice.get("vendor_id", "")}', f'Tax ID: {invoice.get("tax_id", "")}', f'Invoice Number: {invoice.get("invoice_number", "")}', f'Invoice Date: {invoice.get("invoice_date", "")}', f'PO Number: {invoice.get("po_number", "")}', f'Currency: {invoice.get("currency", "INR")}', f'Bank Account: {invoice.get("bank_account", "")}', '', 'Description | Quantity | Unit Price | Amount']
    for item in invoice.get('items', []):
        rows.append(f'{item["description"]} | {item["quantity"]} | {item["unit_price"]} | {item["amount"]}')
    rows += ['', f'Subtotal: {invoice.get("subtotal", "")}', f'Total Tax: {invoice.get("tax_amount", "")}', f'Invoice Total: {invoice.get("total", "")}', '', 'Terms: Due within 30 days. All amounts are synthetic.']
    for i, row in enumerate(rows):
        page.insert_text((38, 135 + i * 24), row, fontsize=10, fontname='helv', color=(.15, .2, .18))
    if scan:
        from PIL import Image, ImageFilter
        pix = page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8))
        im = Image.open(io.BytesIO(pix.tobytes('png'))).convert('L').filter(ImageFilter.GaussianBlur(.15))
        image_bytes = io.BytesIO()
        im.save(image_bytes, format='PNG')
        scanned = fitz.open()
        scanned.new_page(width=595, height=842).insert_image(fitz.Rect(0, 0, 595, 842), stream=image_bytes.getvalue())
        result = scanned.tobytes()
        scanned.close()
    else:
        result = pdf.tobytes()
    pdf.close()
    return result


def files(include_scan=True):
    today = datetime.now(ZoneInfo('Asia/Kolkata')).date()
    vendors = [
        {'vendor_id': 'V001', 'name': 'Northstar Cloud Services', 'status': 'active', 'tax_id': '29ABCDE1234F1Z5', 'bank_account': '123456789012'},
        {'vendor_id': 'V002', 'name': 'Oakline Office Supplies', 'status': 'approved', 'tax_id': '29FGHIJ5678K1Z2', 'bank_account': '234567890123'},
        {'vendor_id': 'V003', 'name': 'Summit Consulting', 'status': 'blocked', 'tax_id': '29KLMNO9012P1Z9', 'bank_account': '345678901234'},
    ]
    pos = []
    specs = [('PO-1001', 'V001', 'Northstar Cloud Services', 20000, 'Cloud service seats', 20, 1000), ('PO-1002', 'V002', 'Oakline Office Supplies', 5000, 'Office supply kits', 5, 1000), ('PO-1003', 'V003', 'Summit Consulting', 20000, 'Consulting hours', 20, 1000), ('PO-1004', 'V001', 'Northstar Cloud Services', 3000, 'Support visits', 3, 1000), ('PO-1005', 'V001', 'Northstar Cloud Services', 10000, 'Platform licenses', 10, 1000), ('PO-1006', 'V001', 'Northstar Cloud Services', 5000, 'Storage units', 5, 1000)]
    for ref, vid, name, amount, desc, qty, rate in specs:
        pos.append({'po_number': ref, 'vendor_id': vid, 'vendor_name': name, 'currency': 'INR', 'amount': str(amount), 'amount_basis': 'net', 'status': 'approved', 'valid_from': (today - timedelta(days=180)).isoformat(), 'valid_to': (today + timedelta(days=180)).isoformat(), 'items': [{'description': desc, 'quantity': qty, 'unit_price': str(rate), 'amount': str(qty * rate)}]})
    history = [{'invoice_number': 'NS-0998', 'vendor_id': 'V001', 'po_number': 'PO-1001', 'currency': 'INR', 'subtotal': '4000', 'total': '4720', 'status': 'paid', 'items': [{'description': 'Cloud service seats', 'quantity': 4, 'unit_price': '1000', 'amount': '4000'}]}]
    policy = {'name': 'Demo · controlled purchasing', 'amount_tolerance_percent': '2', 'amount_tolerance_absolute': '0', 'unit_price_tolerance_percent': '1', 'require_line_items': True, 'check_bank_details': True, 'max_invoice_age_days': 365}
    result = [('vendors', 'approved-vendors.json', json.dumps(vendors, indent=2).encode()), ('purchase_orders', 'purchase-orders.json', json.dumps(pos, indent=2).encode()), ('history', 'previous-invoices.json', json.dumps(history, indent=2).encode()), ('policy', 'ap-policy.json', json.dumps(policy, indent=2).encode())]

    def inv(number, po='PO-1001', qty=2, rate=1000, desc='Cloud service seats', vendor=0, **changes):
        v = vendors[vendor]
        base = {'vendor_name': v['name'], 'vendor_id': v['vendor_id'], 'tax_id': v['tax_id'], 'bank_account': v['bank_account'], 'invoice_number': number, 'invoice_date': (today - timedelta(days=3)).isoformat(), 'po_number': po, 'currency': 'INR', 'subtotal': str(qty * rate), 'tax_amount': '0', 'total': str(qty * rate), 'items': [{'description': desc, 'quantity': qty, 'unit_price': str(rate), 'amount': str(qty * rate)}]}
        base.update(changes)
        return base

    scenarios = [
        ('01-ready.pdf', inv('NS-1042', qty=8, tax_amount='1440', total='9440'), 'ready'),
        ('02-within-tolerance.pdf', inv('OAK-204', po='PO-1002', qty=5, rate=1010, desc='Office supply kits', vendor=1), 'ready'),
        ('03-duplicate.pdf', inv('NS-0998', qty=4, tax_amount='720', total='4720'), 'hold'),
        ('04-blocked-vendor.pdf', inv('SUM-301', po='PO-1003', desc='Consulting hours', vendor=2), 'hold'),
        ('05-bank-changed.pdf', inv('NS-1043', bank_account='999999999999'), 'hold'),
        ('06-missing-po.pdf', inv('NS-1044', po=''), 'clarification'),
        ('07-over-po-balance.pdf', inv('NS-1045', po='PO-1004', qty=4, desc='Support visits'), 'procurement'),
        ('08-rate-mismatch.pdf', inv('NS-1046', po='PO-1005', rate=1400, desc='Platform licenses'), 'procurement'),
        ('09-missing-number.pdf', inv('', qty=1), 'clarification'),
        ('10-tax-discrepancy.pdf', inv('NS-1047', qty=1, tax_amount='180', total='1300'), 'clarification'),
        ('11-partial-invoice.pdf', inv('NS-1048', qty=4), 'ready'),
        ('12-batch-capacity.pdf', inv('NS-1049', qty=6), 'procurement'),
    ]
    if include_scan:
        scenarios.append(('13-scanned-invoice.pdf', inv('NS-1050', po='PO-1006', qty=1, desc='Storage units'), 'clarification'))
    manifest = []
    for filename, invoice, expected in scenarios:
        result.append(('invoice', filename, invoice_pdf(invoice, scan='scanned' in filename)))
        manifest.append({'filename': filename, 'expected_decision': expected, 'synthetic': True})
    result.append(('manifest', 'expected-results.json', json.dumps(manifest, indent=2).encode()))
    return result


def archive():
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for kind, filename, data in files():
            archive.writestr(f'{kind}/{filename}', data)
        archive.writestr('README.txt', 'All documents are synthetic. Upload files into the category matching their folder. expected-results.json documents the expected routing. Dates are generated when the archive is downloaded. No financial actions are performed.')
    return output.getvalue()
