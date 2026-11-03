"""Generate a small, synthetic PO/invoice set for placement demonstrations.

Run from the project root: .venv/bin/python scripts/selection_demo.py
The script writes files only; loading them into the app is a separate step.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pymupdf as fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.demo import invoice_pdf  # noqa: E402

OUTPUT = ROOT / 'sample-data' / 'selection-demo'


def purchase_order_pdf(order: dict) -> bytes:
    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_text((40, 52), 'SYNTHETIC PURCHASE ORDER', fontsize=18)
    page.insert_text((40, 75), 'PLACEMENT DEMO / NOT A REAL ORDER', fontsize=9)
    item = order['items'][0]
    lines = [
        f'Purchase Order Number: {order["po_number"]}',
        f'Vendor Name: {order["vendor_name"]}',
        f'Vendor ID: {order["vendor_id"]}',
        f'Currency: {order["currency"]}',
        f'Amount Basis: {order["amount_basis"]}',
        f'Net Amount: {order["amount"]}',
        f'Status: {order["status"]}',
        f'Valid From: {order["valid_from"]}',
        f'Valid To: {order["valid_to"]}',
        '',
        'Description | Quantity | Unit Price | Amount',
        f'{item["description"]} | {item["quantity"]} | {item["unit_price"]} | {item["amount"]}',
    ]
    for index, line in enumerate(lines):
        page.insert_text((40, 118 + index * 27), line, fontsize=10)
    data = pdf.tobytes()
    pdf.close()
    return data


def generate() -> dict:
    today = datetime.now(ZoneInfo('Asia/Kolkata')).date()
    vendors = [
        {'vendor_id': 'SEL-ASTER', 'name': 'Aster Cloud Ltd', 'status': 'active',
         'tax_id': '29ABCDE1234F1Z5', 'bank_account': '100000000001'},
        {'vendor_id': 'SEL-BLUE', 'name': 'Blueleaf Office Supplies', 'status': 'active',
         'tax_id': '29FGHIJ5678K1Z2', 'bank_account': '200000000002'},
        {'vendor_id': 'SEL-CEDAR', 'name': 'Cedar Logistics Pvt Ltd', 'status': 'active',
         'tax_id': '29KLMNO9012P1Z9', 'bank_account': '300000000003'},
    ]
    specifications = [
        ('PO-SEL-001', vendors[0], 'Software seats', 10, 1000),
        ('PO-SEL-002', vendors[0], 'Support hours', 8, 500),
        ('PO-SEL-003', vendors[1], 'Office supply kits', 6, 300),
        ('PO-SEL-004', vendors[2], 'Delivery trips', 5, 2000),
    ]
    orders = []
    for number, vendor, description, quantity, unit_price in specifications:
        amount = quantity * unit_price
        orders.append({
            'po_number': number, 'vendor_id': vendor['vendor_id'], 'vendor_name': vendor['name'],
            'currency': 'INR', 'amount': str(amount), 'amount_basis': 'net', 'status': 'approved',
            'valid_from': (today - timedelta(days=90)).isoformat(),
            'valid_to': (today + timedelta(days=365)).isoformat(),
            'items': [{'description': description, 'quantity': quantity,
                       'unit_price': str(unit_price), 'amount': str(amount)}],
        })

    # The two additional invoices split PO-SEL-001 and PO-SEL-004 into pairs.
    scenarios = [
        ('01-aster-partial-first.pdf', 'INV-SEL-001', orders[0], vendors[0], 4, 1000, 720, False,
         'First instalment, leaving six software seats.'),
        ('02-aster-partial-final.pdf', 'INV-SEL-002', orders[0], vendors[0], 6, 1000, 1080, False,
         'Second instalment, using the remaining six seats.'),
        ('03-aster-taxed-service.pdf', 'INV-SEL-003', orders[1], vendors[0], 4, 500, 360, False,
         'A taxed service invoice from the same vendor on a different PO.'),
        ('04-blueleaf-scanned.pdf', 'INV-SEL-004', orders[2], vendors[1], 6, 300, 0, True,
         'A scanned invoice from another vendor; OCR needs visual review.'),
        ('05-cedar-partial-first.pdf', 'INV-SEL-005', orders[3], vendors[2], 3, 2000, 1080, False,
         'First delivery invoice, leaving two authorized trips.'),
        ('06-cedar-partial-over-limit.pdf', 'INV-SEL-006', orders[3], vendors[2], 3, 2000, 1080, False,
         'Second delivery invoice; combined quantity is six against five on the PO.'),
    ]
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / 'purchase-orders').mkdir(exist_ok=True)
    (OUTPUT / 'invoices').mkdir(exist_ok=True)
    (OUTPUT / 'approved-vendors.json').write_text(json.dumps(vendors, indent=2) + '\n')
    (OUTPUT / 'previous-invoices.json').write_text('[]\n')
    for order in orders:
        (OUTPUT / 'purchase-orders' / f'{order["po_number"]}.pdf').write_bytes(purchase_order_pdf(order))
    manifest = []
    for filename, number, order, vendor, quantity, unit_price, tax, scan, description in scenarios:
        subtotal = quantity * unit_price
        invoice = {
            'vendor_name': vendor['name'], 'vendor_id': vendor['vendor_id'],
            'tax_id': vendor['tax_id'], 'bank_account': vendor['bank_account'],
            'invoice_number': number, 'invoice_date': (today - timedelta(days=2)).isoformat(),
            'po_number': order['po_number'], 'currency': 'INR', 'subtotal': str(subtotal),
            'tax_amount': str(tax), 'total': str(subtotal + tax),
            'items': [{'description': order['items'][0]['description'], 'quantity': quantity,
                       'unit_price': str(unit_price), 'amount': str(subtotal)}],
        }
        (OUTPUT / 'invoices' / filename).write_bytes(invoice_pdf(invoice, scan=scan))
        manifest.append({'filename': filename, 'invoice_number': number,
                         'po_number': order['po_number'], 'vendor': vendor['name'],
                         'net_amount': str(subtotal), 'tax': str(tax), 'scenario': description})
    (OUTPUT / 'manifest.json').write_text(json.dumps({'synthetic': True, 'purchase_orders': orders,
                                                        'invoices': manifest}, indent=2) + '\n')
    return {'orders': len(orders), 'invoices': len(manifest), 'path': str(OUTPUT)}


if __name__ == '__main__':
    print(generate())
