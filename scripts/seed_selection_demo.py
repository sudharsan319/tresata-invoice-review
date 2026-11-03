"""Populate a new workspace with the four-PO, six-invoice synthetic case set.

The files are generated with fresh dates, processed through the application's
upload routes, and verified before the staged workspace is made available.
This command does not start the web server or overwrite existing data.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))

# The synthetic seed should be repeatable and should not make provider calls.
for name in ('OPENROUTER_API_KEY', 'AI_API_KEY', 'AI_BASE_URL', 'AI_MODEL'):
    os.environ.pop(name, None)

from app import store  # noqa: E402
from app.main import app  # noqa: E402
import selection_demo  # noqa: E402

EXPECTED = {
    'INV-SEL-001': 'ready',
    'INV-SEL-002': 'ready',
    'INV-SEL-003': 'ready',
    'INV-SEL-004': 'clarification',
    'INV-SEL-005': 'ready',
    'INV-SEL-006': 'procurement',
}


def upload(client: TestClient, kind: str, source: Path) -> tuple[str, dict]:
    mime = 'application/pdf' if source.suffix == '.pdf' else 'application/json'
    response = client.post('/api/documents', data={'kind': kind},
                           files={'files': (source.name, source.read_bytes(), mime)})
    response.raise_for_status()
    result = response.json()
    if result['errors'] or len(result['accepted']) != 1:
        raise RuntimeError(f'Could not load {source.name}: {result["errors"]}')
    return result['accepted'][0]['id'], result['workspace']


def seed(client: TestClient, sources: Path) -> None:
    manifest = json.loads((sources / 'manifest.json').read_text())
    upload(client, 'vendors', sources / 'approved-vendors.json')
    upload(client, 'history', sources / 'previous-invoices.json')

    for order in manifest['purchase_orders']:
        source = sources / 'purchase-orders' / f'{order["po_number"]}.pdf'
        document_id, workspace = upload(client, 'purchase_orders', source)
        draft = workspace['po_drafts'].get(document_id)
        if not draft:
            raise RuntimeError(f'{source.name} did not produce a reviewable PO draft.')
        values = draft['values']
        for field in ('po_number', 'vendor_name', 'vendor_id', 'currency', 'amount_basis', 'status', 'valid_from', 'valid_to'):
            if values.get(field) != order[field]:
                raise RuntimeError(f'{source.name}: extracted {field} does not match the synthetic source.')
        if Decimal(str(values['amount'])) != Decimal(order['amount']):
            raise RuntimeError(f'{source.name}: extracted amount does not match the synthetic source.')
        if len(values['items']) != len(order['items']):
            raise RuntimeError(f'{source.name}: extracted PO lines do not match the synthetic source.')
        for actual, expected in zip(values['items'], order['items']):
            if actual['description'] != expected['description'] or any(
                Decimal(str(actual[field])) != Decimal(str(expected[field]))
                for field in ('quantity', 'unit_price', 'amount')
            ):
                raise RuntimeError(f'{source.name}: extracted PO line does not match the synthetic source.')
        approval = client.post(f'/api/purchase-orders/drafts/{document_id}/approve', json={
            'po': order,
            'note': 'Synthetic PO checked against the generated source and manifest.',
            'confirmed': True,
        })
        approval.raise_for_status()
        print(f'Activated {order["po_number"]} from {source.name}')

    for invoice in manifest['invoices']:
        source = sources / 'invoices' / invoice['filename']
        upload(client, 'invoice', source)
        print(f'Processed {invoice["invoice_number"]} from {source.name}')

    workspace = client.get('/api/workspace').json()
    decisions = {review['invoice']['invoice_number']: review['decision'] for review in workspace['reviews']}
    if decisions != EXPECTED or len(workspace['purchase_orders']) != 4:
        raise RuntimeError(f'Synthetic case results differ from the expected set: {decisions}')
    print('Verified: 4 purchase orders, 6 invoices, all expected recommendations.')


def main() -> None:
    target = store.DATA.resolve()
    if target.is_symlink() or (target.exists() and (not target.is_dir() or any(target.iterdir()))):
        raise SystemExit(f'Workspace already contains data: {target}\nChoose an empty AP_DATA_DIR to keep existing records.')
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.selection-demo-', dir=target.parent))
    try:
        sources = staging / 'source'
        selection_demo.OUTPUT = sources
        selection_demo.generate()
        store.DATA = staging / 'workspace'
        with TestClient(app) as client:
            seed(client, sources)
        if target.exists():
            target.rmdir()
        store.DATA.rename(target)
        print(f'Ready to start the app with AP_DATA_DIR={target}')
    finally:
        if staging.exists():
            shutil.rmtree(staging)


if __name__ == '__main__':
    main()
