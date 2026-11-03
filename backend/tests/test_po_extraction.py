from app import ai
from app.po_extraction import extract_po_draft


def test_ai_po_fields_require_matching_source_quotes(monkeypatch):
    lines = [
        'Order Ref: PO-AI-7', 'Supplier: Example Services', 'Currency: INR',
        'Approved budget: 1250', 'Basis: net', 'Status: approved',
    ]
    document = {'id': 'po-doc', 'document_id': 'po-doc', 'filename': 'po.pdf',
                'pages': [{'page': 1, 'text': '\n'.join(lines), 'method': 'text', 'table_rows': []}], 'notes': []}
    proposed = {
        'po_number': 'PO-AI-7', 'vendor_id': 'V-FAKE', 'vendor_name': 'Example Services',
        'currency': 'INR', 'amount': '1250', 'amount_basis': 'net', 'status': 'approved',
        'valid_from': '', 'valid_to': '', 'items': [], 'uncertainties': [],
        'sources': [
            {'field': 'po_number', 'page': 1, 'quote': lines[0]},
            {'field': 'vendor_id', 'page': 1, 'quote': lines[1]},
            {'field': 'vendor_name', 'page': 1, 'quote': lines[1]},
            {'field': 'currency', 'page': 1, 'quote': lines[2]},
            {'field': 'amount', 'page': 1, 'quote': lines[3]},
            {'field': 'amount_basis', 'page': 1, 'quote': lines[4]},
            {'field': 'status', 'page': 1, 'quote': lines[5]},
        ],
    }
    monkeypatch.setattr(ai, 'enabled', lambda: True)
    monkeypatch.setattr(ai, 'complete', lambda task, system, content, schema: (proposed, {'task': task, 'status': 'completed', 'model': 'mock'}))
    draft = extract_po_draft(document, b'')
    assert draft['values']['po_number'] == 'PO-AI-7'
    assert draft['values']['amount'] == '1250'
    assert draft['values']['amount_basis'] == 'net'
    assert draft['values']['status'] == 'approved'
    assert draft['values']['vendor_id'] == ''
    assert any('vendor id' in note for note in draft['uncertainties'])
    assert draft['method'] == 'AI assisted'
