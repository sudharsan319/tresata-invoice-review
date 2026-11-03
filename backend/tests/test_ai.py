"""OpenRouter integration tests never use a real key or make paid calls."""
import json
import stat
import time
from datetime import date
from decimal import Decimal

import httpx
import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import ai, store, demo
from app.main import app
from app.extraction import extract_invoice, _vision_transcribe
from app.interpretation import propose_item_matches, review_brief, policy_proposal
from app.models import Invoice, LineItem, PurchaseOrder, Vendor, HistoricalInvoice, Policy
from app.engine import review_invoice
from app.service import ingest, run_reviews


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    for name in ('OPENROUTER_API_KEY', 'AI_BASE_URL', 'AI_MODEL', 'AI_API_KEY'):
        monkeypatch.delenv(name, raising=False)
    return TestClient(app)


def configure(client, **changes):
    data = {'enabled': True, 'api_key': 'sk-test-never-a-real-credential', 'models': dict(ai.DEFAULT_MODELS), **changes}
    response = client.put('/api/ai/settings', json=data)
    assert response.status_code == 200, response.text
    return response.json()


def run_record(task):
    return {'task': task, 'model': ai.DEFAULT_MODELS[task], 'status': 'completed', 'timestamp': '2026-10-31T12:00:00Z',
            'prompt_tokens': 100, 'completion_tokens': 50, 'cost_usd': .00001}


def facts():
    invoice = Invoice(invoice_number='A-1', invoice_date='2026-10-31', vendor_id='V1', vendor_name='Acme',
                      po_number='PO-1', currency='INR', subtotal='100', tax_amount='0', total='100',
                      items=[LineItem(description='Managed cloud hosting', quantity='1', unit_price='100', amount='100')])
    po = PurchaseOrder(po_number='PO-1', vendor_id='V1', currency='INR', amount='1000', amount_basis='net', status='approved',
                       items=[LineItem(description='Cloud infrastructure service', quantity='10', unit_price='100', amount='1000')])
    return invoice, po


def equivalent(invoice_quote='Managed cloud hosting', po_quote='Cloud infrastructure service', **changes):
    return {'invoice_line': 0, 'po_line': 0, 'equivalence': 'equivalent', 'reason': 'Both describe managed cloud hosting services.',
            'invoice_quote': invoice_quote, 'po_quote': po_quote, **changes}


def test_budget_defaults_and_private_key_storage(client):
    config = configure(client)
    assert config['models']['extraction'] == 'mistralai/mistral-nemo'
    assert config['models']['vision'] == 'google/gemma-3-12b-it'
    assert config['models']['matching'] == 'mistralai/mistral-small-24b-instruct-2501'
    assert config['key_configured'] and config['ready']
    assert 'sk-test' not in json.dumps(config)
    assert stat.S_IMODE(ai.settings_path().stat().st_mode) == 0o600
    assert 'sk-test' not in client.get('/api/workspace').text
    assert 'sk-test' not in client.get('/api/export').text
    assert 'sk-test' not in client.get('/api/ai/settings').text


def test_settings_save_never_makes_a_paid_call(client, monkeypatch):
    monkeypatch.setattr(httpx, 'post', lambda *args, **kwargs: pytest.fail('Saving settings must not call a model'))
    configure(client)


def test_key_can_be_retained_disabled_and_removed(client):
    configure(client)
    config = configure(client, api_key=None, enabled=False)
    assert config['key_configured'] and not config['ready']
    config = configure(client, api_key=None, enabled=False, remove_api_key=True)
    assert not config['key_configured']


def test_enable_without_key_is_rejected(client):
    result = client.put('/api/ai/settings', json={'enabled': True, 'models': ai.DEFAULT_MODELS})
    assert result.status_code == 400
    assert not ai.settings_path().exists()


def test_connection_test_uses_key_endpoint_not_inference(client, monkeypatch):
    configure(client)
    seen = []
    def fake_get(url, **kwargs):
        seen.append(url)
        return httpx.Response(200, json={'data': {'limit_remaining': 2.5}}, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx, 'get', fake_get)
    monkeypatch.setattr(httpx, 'post', lambda *a, **kw: pytest.fail('Connection check must not call a paid model'))
    result = client.post('/api/ai/test')
    assert result.status_code == 200
    assert seen == [ai.BASE_URL + '/key']


@pytest.mark.parametrize('task', ai.TASKS)
def test_each_task_uses_its_selected_model_and_json_schema(client, monkeypatch, task):
    configure(client)
    calls = []
    def fake_post(url, **kwargs):
        calls.append(kwargs['json'])
        return httpx.Response(200, json={'model': kwargs['json']['model'], 'choices': [{'message': {'content': '{"ok":true}'}, 'finish_reason': 'stop'}],
                                     'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'cost': .00002}}, request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx, 'post', fake_post)
    data, record = ai.complete(task, 'Extract facts.', 'Synthetic source.', ai.object_schema({'ok': {'type': 'boolean'}}))
    assert data['ok']
    assert calls[0]['model'] == ai.DEFAULT_MODELS[task]
    assert calls[0]['response_format']['json_schema']['strict'] is True
    assert record['cost_usd'] == .00002
    assert 'sk-test' not in json.dumps(record)


@pytest.mark.parametrize('status', [401, 402, 429, 500])
def test_provider_errors_are_sanitized(client, monkeypatch, status):
    configure(client)
    def failed(url, **kwargs):
        return httpx.Response(status, text='provider echo sk-test-never-a-real-credential', request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx, 'post', failed)
    with pytest.raises(ai.AIError) as error:
        ai.complete('extraction', 'Facts', 'Source')
    assert 'sk-test' not in str(error.value)
    assert str(status) in str(error.value)


def test_truncated_json_is_not_used(client, monkeypatch):
    configure(client)
    monkeypatch.setattr(httpx, 'post', lambda url, **kw: httpx.Response(200, json={'choices': [{'finish_reason': 'length', 'message': {'content': '{"partial":'}}]}, request=httpx.Request('POST', url)))
    with pytest.raises(ai.AIError, match='token limit'):
        ai.complete('extraction', 'Facts', 'Source')


def test_semantic_proposal_is_grounded_in_both_descriptions(client, monkeypatch):
    configure(client)
    invoice, po = facts()
    monkeypatch.setattr(ai, 'complete', lambda *args, **kwargs: ({'matches': [equivalent()]}, run_record('matching')))
    result = propose_item_matches(invoice, po)
    assert not result['matches'][0]['confirmed']
    assert result['matches'][0]['equivalence'] == 'equivalent'
    monkeypatch.setattr(ai, 'complete', lambda *args, **kwargs: ({'matches': [equivalent(po_quote='invented item')]}, run_record('matching')))
    with pytest.raises(ai.AIError, match='unsupported'):
        propose_item_matches(invoice, po)


def test_conflicting_product_numbers_block_model_equivalence(client, monkeypatch):
    configure(client)
    invoice, po = facts()
    invoice.items[0].description = 'Storage 100 GB'
    po.items[0].description = 'Storage 500 GB'
    monkeypatch.setattr(ai, 'complete', lambda *args, **kwargs: ({'matches': [equivalent(invoice_quote='Storage 100 GB', po_quote='Storage 500 GB')]}, run_record('matching')))
    assert propose_item_matches(invoice, po)['matches'][0]['equivalence'] == 'uncertain'


def test_semantic_match_needs_confirmation_and_cannot_override_rate(client):
    invoice, po = facts()
    vendor = Vendor(vendor_id='V1', name='Acme', status='active')
    history = [HistoricalInvoice(invoice_number='OLD', vendor_id='V1', currency='INR', total='1', status='paid')]
    document = {'id':'d', 'sha256':'hash', 'filename':'invoice.pdf', 'pages':[{'method':'text'}]}
    semantic = {'matches': [{**equivalent(), 'confirmed': False}]}
    def review():
        return review_invoice(document, invoice, [vendor], [po], history, Policy(), [], {}, today=date(2026,10,31), semantic=semantic)
    assert review().decision == 'clarification'
    semantic['matches'][0]['confirmed'] = True
    assert review().decision == 'ready'
    invoice.items[0].unit_price = Decimal('200')
    invoice.items[0].amount = Decimal('200')
    invoice.subtotal = invoice.total = Decimal('200')
    assert review().decision == 'procurement'


def test_semantic_cache_and_confirmation_endpoint(client, monkeypatch):
    state = store.initial_state()
    invoice, po = facts()
    invoice.invoice_date = date.today().isoformat()
    with monkeypatch.context() as context:
        context.setattr(ai, 'enabled', lambda: False)
        ingest(state, 'vendors', 'vendors.json', json.dumps([{'vendor_id':'V1','name':'Acme','status':'active'}]).encode())
        ingest(state, 'purchase_orders', 'po.json', json.dumps([po.model_dump(mode='json')]).encode())
        ingest(state, 'history', 'history.json', b'[]')
        ingest(state, 'invoice', 'invoice.pdf', demo.invoice_pdf(invoice.model_dump(mode='json')))
    calls = []
    def match(*args, **kwargs):
        calls.append(1)
        return {'matches':[equivalent()]},run_record('matching')
    configure(client)
    monkeypatch.setattr(ai, 'complete', match)
    run_reviews(state)
    run_reviews(state)
    assert len(calls)==1
    store.save_state(state)
    review = state['reviews'][0]
    assert review['decision']=='clarification'
    key = review['ai_analysis']['matching']['analysis_key']
    response=client.post(f'/api/reviews/{review["id"]}/semantic-confirmation',json={'analysis_key':key,'invoice_line':0,'po_line':0,'note':'Confirmed scope and units against both sources'})
    assert response.status_code==200,response.text
    assert response.json()['reviews'][0]['decision']=='ready'
    assert len(calls)==1
    assert any(a['action']=='semantic_match_confirmed' for a in response.json()['audit'])


def test_stale_semantic_confirmation_is_rejected(client):
    response=client.post('/api/reviews/unknown/semantic-confirmation',json={'analysis_key':'old','invoice_line':0,'po_line':0,'note':'Human verification'})
    assert response.status_code==409


def test_semantic_batch_quantities_cannot_be_lost_after_paraphrasing(client):
    invoice, po = facts()
    invoice.items[0].description = po.items[0].description
    invoice.items[0].quantity = Decimal('8')
    invoice.items[0].amount = invoice.subtotal = invoice.total = Decimal('800')
    previous_alias = LineItem(description='Managed cloud hosting', quantity='3', unit_price='100', amount='300')
    reservations={'po1':[{'amount':Decimal('300'),'invoice_number':'PREV','items':[previous_alias],'line_assignments':{'0':0}}]}
    document={'id':'d','sha256':'hash','filename':'invoice.pdf','pages':[{'method':'text'}]}
    history=[HistoricalInvoice(invoice_number='OTHER',vendor_id='V1',currency='INR',total='1',status='paid')]
    result=review_invoice(document,invoice,[Vendor(vendor_id='V1',name='Acme',status='active')],[po],history,Policy(),[],reservations,today=date(2026,10,31))
    assert result.decision=='procurement'
    assert any(c.code=='item_0' and '8 + 3' in c.message for c in result.checks)


def test_confirmed_semantics_survive_disabling_paid_calls(client, monkeypatch):
    invoice,po=facts()
    # The content fingerprint must not depend on keys, enabled state, or model selection.
    from app.interpretation import matching_key
    configure(client)
    before=matching_key(invoice,po)
    configure(client,enabled=False,api_key=None)
    assert matching_key(invoice,po)==before


def test_prose_policy_is_draft_until_reviewed(client, monkeypatch):
    configure(client)
    def proposed(task,*args,**kwargs):
        assert task=='policy'
        return {'rules':{'amount_tolerance_percent':'3'},'sources':{'amount_tolerance_percent':{'page':1,'quote':'Allow a 3% PO amount tolerance.'}},'uncertainties':[]},run_record('policy')
    monkeypatch.setattr(ai,'complete',proposed)
    response=client.post('/api/documents',data={'kind':'policy'},files={'files':('policy.txt',b'Allow a 3% PO amount tolerance.')})
    assert response.status_code==200,response.text
    data=response.json();assert not data['errors'],data
    state=data['workspace']
    assert state['policy']['amount_tolerance_percent']=='2'
    draft_id=next(iter(state['reference_drafts']))
    draft=state['reference_drafts'][draft_id]
    assert draft['values']['amount_tolerance_percent']=='3'
    result=client.post(f'/api/ai/policy-drafts/{draft_id}/approve',json={'policy':draft['values'],'note':'Verified the percentage and scope against the source'})
    assert result.status_code==200,result.text
    assert result.json()['policy']['amount_tolerance_percent']=='3'
    assert not result.json()['reference_drafts']


def test_unsupported_policy_quote_cannot_change_rules(client, monkeypatch):
    configure(client)
    monkeypatch.setattr(ai,'complete',lambda *a,**kw:({'rules':{'amount_tolerance_percent':'3'},'sources':{'amount_tolerance_percent':{'page':1,'quote':'Invented rule.'}},'uncertainties':[]},run_record('policy')))
    result=client.post('/api/documents',data={'kind':'policy'},files={'files':('policy.txt',b'Please review invoices carefully.')} ).json()
    assert result['errors']
    assert result['workspace']['policy']['amount_tolerance_percent']=='2'


def test_policy_preserves_title_and_normalizes_percentage_suffix(client, monkeypatch):
    configure(client)
    proposal={'rules':{'name':'AP Review','amount_tolerance_percent':'2%','unit_price_tolerance_percent':'0'},
              'sources':{'name':{'page':1,'quote':'AP Review'},'amount_tolerance_percent':{'page':1,'quote':'Allow a 2% PO amount tolerance.'},'unit_price_tolerance_percent':{'page':1,'quote':'No unit-price tolerance is permitted.'}},'uncertainties':[]}
    monkeypatch.setattr(ai,'complete',lambda *a,**kw:(proposal,run_record('policy')))
    document={'id':'policy','filename':'policy.txt','pages':[{'page':1,'text':'Allow a 2% PO amount tolerance. No unit-price tolerance is permitted.'}]}
    result=policy_proposal(document,Policy().model_dump(mode='json'))
    assert result['values']['amount_tolerance_percent']=='2'
    assert result['values']['unit_price_tolerance_percent']=='0'
    assert result['values']['name']=='Standard AP review policy'
    assert any('title' in note for note in result['uncertainties'])


def test_policy_numeric_value_must_appear_in_its_source(client, monkeypatch):
    configure(client)
    proposal={'rules':{'amount_tolerance_percent':'3%'},'sources':{'amount_tolerance_percent':{'page':1,'quote':'Allow a 2% PO amount tolerance.'}},'uncertainties':[]}
    monkeypatch.setattr(ai,'complete',lambda *a,**kw:(proposal,run_record('policy')))
    document={'id':'policy','filename':'policy.txt','pages':[{'page':1,'text':'Allow a 2% PO amount tolerance.'}]}
    with pytest.raises(ai.AIError,match='numeric source support'):
        policy_proposal(document,Policy().model_dump(mode='json'))


def test_missing_ai_cells_can_use_one_identical_source_backed_local_row(client, monkeypatch):
    configure(client)
    row='Cloud service seats | 8 | 1000 | 8000'
    proposal={'items':[{'description':'Cloud service seats','quantity':None,'unit_price':None,'amount':'8000','page':1,'quote':row}]}
    monkeypatch.setattr(ai,'complete',lambda *a,**kw:(proposal,run_record('extraction')))
    document={'id':'invoice','document_id':'invoice','filename':'invoice.pdf','pages':[{'page':1,'text':row,'method':'text'}],'notes':[]}
    result=extract_invoice(document)
    assert result.items[0].quantity==Decimal('8')
    assert result.items[0].unit_price==Decimal('1000')
    assert 'verified local table cells' in result.items[0].evidence.method
    assert not any('could not be grounded' in note for note in result.extraction_notes)
    assert result.extraction_method=='AI assisted'


def test_ai_cells_are_not_recovered_from_a_different_row_quote(client, monkeypatch):
    configure(client)
    row='Cloud service seats | 8 | 1000 | 8000'
    proposal={'items':[{'description':'Cloud service seats','quantity':None,'unit_price':None,'amount':'8000','page':1,'quote':'Cloud service seats'}]}
    monkeypatch.setattr(ai,'complete',lambda *a,**kw:(proposal,run_record('extraction')))
    document={'id':'invoice','document_id':'invoice','filename':'invoice.pdf','pages':[{'page':1,'text':row,'method':'text'}],'notes':[]}
    result=extract_invoice(document)
    assert any('could not be grounded' in note for note in result.extraction_notes)


def test_ai_omission_keeps_locally_extracted_rows(client, monkeypatch):
    configure(client)
    rows = ['Desk | 1 | 200 | 200', 'Chair | 2 | 50 | 100', 'Lamp | 3 | 10 | 30']
    proposal = {'items': [{'description': 'Desk', 'quantity': '1', 'unit_price': '200',
                           'amount': '200', 'page': 1, 'quote': rows[0]}]}
    monkeypatch.setattr(ai, 'complete', lambda *a, **kw: (proposal, run_record('extraction')))
    document = {'document_id': 'invoice', 'filename': 'invoice.pdf',
                'pages': [{'page': 1, 'text': '\n'.join(rows), 'method': 'text'}], 'notes': []}
    result = extract_invoice(document)
    assert [item.description for item in result.items] == ['Desk', 'Chair', 'Lamp']
    assert sum(item.amount for item in result.items) == Decimal('330')
    assert any('omitted locally extracted line items' in note for note in result.extraction_notes)


def test_ai_can_add_a_source_backed_row_missing_from_local_layout(client, monkeypatch):
    configure(client)
    row = 'Repair service 3 units at 4 each: 12'
    proposal = {'items': [{'description': 'Repair service', 'quantity': '3', 'unit_price': '4',
                           'amount': '12', 'page': 1, 'quote': row}]}
    monkeypatch.setattr(ai, 'complete', lambda *a, **kw: (proposal, run_record('extraction')))
    document = {'document_id': 'invoice', 'filename': 'invoice.pdf',
                'pages': [{'page': 1, 'text': 'Desk | 1 | 200 | 200\n' + row, 'method': 'text'}], 'notes': []}
    result = extract_invoice(document)
    assert [item.description for item in result.items] == ['Desk', 'Repair service']


def test_ai_date_evidence_accepts_missing_space_after_comma(client, monkeypatch):
    configure(client)
    line = 'Invoice Date: Jun 22,2021'
    proposal = {'invoice_date': '2021-06-22', 'sources': {'invoice_date': {'page': 1, 'quote': line}}}
    monkeypatch.setattr(ai, 'complete', lambda *a, **kw: (proposal, run_record('extraction')))
    document = {'document_id': 'invoice', 'filename': 'invoice.pdf',
                'pages': [{'page': 1, 'text': line, 'method': 'text'}], 'notes': []}
    result = extract_invoice(document)
    assert result.invoice_date == '2021-06-22'
    assert result.evidence['invoice_date'].method.startswith('AI + source validation')


def test_ai_cannot_replace_supplier_with_bill_to_customer(client, monkeypatch):
    configure(client)
    source = 'Ad4tech Material LLC\n67 Martin street\n\nBill To\nGreen1 Materials LLC\nInvoice No: INV-005'
    proposal = {'vendor_name': 'Green1 Materials LLC',
                'sources': {'vendor_name': {'page': 1, 'quote': 'Green1 Materials LLC'}}}
    monkeypatch.setattr(ai, 'complete', lambda *a, **kw: (proposal, run_record('extraction')))
    document = {'document_id': 'invoice', 'filename': 'invoice.pdf',
                'pages': [{'page': 1, 'text': source, 'method': 'text'}], 'notes': []}
    result = extract_invoice(document)
    assert result.vendor_name == 'Ad4tech Material LLC'
    assert result.evidence['vendor_name'].excerpt == 'Ad4tech Material LLC'
    assert any('unsupported vendor name' in note for note in result.extraction_notes)


def test_ai_does_not_treat_address_or_payee_as_identifiers(client, monkeypatch):
    configure(client)
    source = 'Ad4tech Material LLC\nAlexander road\n576832\nPayment Instructions\nPay Cheque to\nJohn Doe'
    proposal = {'vendor_id': '576832', 'bank_account': 'Pay Cheque to\nJohn Doe',
                'sources': {'vendor_id': {'page': 1, 'quote': '576832'},
                            'bank_account': {'page': 1, 'quote': 'Pay Cheque to\nJohn Doe'}}}
    monkeypatch.setattr(ai, 'complete', lambda *a, **kw: (proposal, run_record('extraction')))
    document = {'document_id': 'invoice', 'filename': 'invoice.pdf',
                'pages': [{'page': 1, 'text': source, 'method': 'text'}], 'notes': []}
    result = extract_invoice(document)
    assert result.vendor_id == ''
    assert result.bank_account == ''
    assert any('unsupported vendor id' in note for note in result.extraction_notes)
    assert any('unsupported bank account' in note for note in result.extraction_notes)


def test_ai_accepts_explicitly_labeled_vendor_and_bank_ids(client, monkeypatch):
    configure(client)
    source = 'Vendor ID: V-12345\nBank Account: 0012345678'
    proposal = {'vendor_id': 'V-12345', 'bank_account': '0012345678',
                'sources': {'vendor_id': {'page': 1, 'quote': 'Vendor ID: V-12345'},
                            'bank_account': {'page': 1, 'quote': 'Bank Account: 0012345678'}}}
    monkeypatch.setattr(ai, 'complete', lambda *a, **kw: (proposal, run_record('extraction')))
    document = {'document_id': 'invoice', 'filename': 'invoice.pdf',
                'pages': [{'page': 1, 'text': source, 'method': 'text'}], 'notes': []}
    result = extract_invoice(document)
    assert result.vendor_id == 'V-12345'
    assert result.bank_account == '0012345678'


def test_openrouter_vision_rows_replace_noisy_ocr_rows(client, monkeypatch):
    configure(client)
    ocr = 'Invoice No: INV-005\nSubtotal: 1564\nDesktopfurniture | 1 | 232 | 232\nPlumbing andelectrical services | 2 | 514 | 1028\nWatertankrepairworks | 2 | 152 | 304'
    vision = 'Invoice No: INV-005\nSubtotal: 1564\nDesktop furniture | 1 | 232 | 232\nPlumbing and electrical services | 2 | 514 | 1028\nWater tank repair works | 2 | 152 | 304'
    document = {'document_id': 'invoice', 'filename': 'invoice.pdf',
                'pages': [{'page': 1, 'text': ocr, 'method': 'ocr'}], 'notes': []}
    def fake_vision(doc, pdf_bytes):
        doc['pages'][0]['vision_text'] = vision
        return run_record('vision')
    monkeypatch.setattr('app.extraction._vision_transcribe', fake_vision)
    monkeypatch.setattr(ai, 'complete', lambda *a, **kw: ({'items': []}, run_record('extraction')))
    result = extract_invoice(document, pdf_bytes=b'%PDF-synthetic')
    assert [line.description for line in result.items] == ['Desktop furniture', 'Plumbing and electrical services', 'Water tank repair works']
    assert all('OpenRouter vision transcription' in line.evidence.method for line in result.items)
    assert [run['task'] for run in result.ai_runs] == ['vision', 'extraction']


def test_vision_accepts_omitted_page_only_when_rendered_blank(client, monkeypatch):
    configure(client)
    pdf = pymupdf.open()
    pdf.new_page().insert_text((50, 50), 'Invoice No: INV-005')
    pdf.new_page()
    document = {'document_id': 'invoice', 'filename': 'invoice.pdf',
                'pages': [{'page': 1, 'text': 'Invoice No: INV-005', 'method': 'ocr'},
                          {'page': 2, 'text': '', 'method': 'ocr'}]}
    proposal = {'pages': [{'page': 1, 'text': 'Invoice No: INV-005'}], 'uncertainties': []}
    monkeypatch.setattr(ai, 'complete', lambda *a, **kw: (proposal, run_record('vision')))
    _vision_transcribe(document, pdf.tobytes())
    assert document['pages'][0]['vision_text'] == 'Invoice No: INV-005'
    assert 'vision_text' not in document['pages'][1]
    assert any('Page 2 was visually blank' in note for note in document['vision_uncertainties'])


def test_ai_brief_requires_real_check_references(client, monkeypatch):
    configure(client)
    review={'decision':'clarification','checks':[{'code':'required_fields','title':'Fields','status':'fail','message':'Missing invoice number.','route':'clarification'}]}
    monkeypatch.setattr(ai,'complete',lambda *a,**kw:({'observations':[{'text':'Invoice number is missing.','check_codes':['required_fields']}],'next_steps':[]},run_record('review')))
    assert review_brief(review)['observations']
    monkeypatch.setattr(ai,'complete',lambda *a,**kw:({'observations':[{'text':'Invoice approved.','check_codes':['invented_approval']}],'next_steps':[]},run_record('review')))
    with pytest.raises(ai.AIError,match='unsupported'):
        review_brief(review)


def test_vision_sends_images_only_to_vision_task_and_retains_original(client, monkeypatch):
    configure(client)
    invoice,_=facts()
    original='Noisy OCR 123'
    document={'id':'d','document_id':'d','filename':'scan.pdf','pages':[{'page':1,'text':original,'method':'ocr'}]}
    def fake(task,system,content,schema):
        assert task=='vision'
        assert any(item.get('type')=='image_url' and item['image_url']['url'].startswith('data:image/png;base64,') for item in content)
        return {'pages':[{'page':1,'text':'Invoice Number: A-1\nInvoice Total: 100'}],'uncertainties':[]},run_record('vision')
    monkeypatch.setattr(ai,'complete',fake)
    _vision_transcribe(document,demo.invoice_pdf(invoice.model_dump(mode='json')))
    assert document['pages'][0]['text']==original
    assert 'A-1' in document['pages'][0]['vision_text']


def test_vision_page_omission_is_rejected(client, monkeypatch):
    configure(client)
    invoice,_=facts()
    document={'pages':[{'page':1,'text':'Noisy','method':'ocr'}]}
    monkeypatch.setattr(ai,'complete',lambda *a,**kw:({'pages':[],'uncertainties':[]},run_record('vision')))
    with pytest.raises(ai.AIError,match='every requested page'):
        _vision_transcribe(document,demo.invoice_pdf(invoice.model_dump(mode='json')))


def test_reprocess_requires_configuration(client):
    assert client.post('/api/ai/reprocess',json={}).status_code==400


def test_background_reprocess_preserves_original_snapshot(client, monkeypatch):
    state=store.initial_state()
    invoice,_=facts()
    with monkeypatch.context() as context:
        context.setattr(ai,'enabled',lambda:False)
        document=ingest(state,'invoice','invoice.pdf',demo.invoice_pdf(invoice.model_dump(mode='json')))
    run_reviews(state);store.save_state(state)
    configure(client)
    monkeypatch.setattr('app.main.extract_invoice',lambda *a,**kw:invoice.model_copy(update={'ai_runs':[run_record('extraction')],'extraction_method':'AI assisted'}))
    response=client.post('/api/ai/reprocess',json={'document_ids':[document['id']]})
    assert response.status_code==200,response.text
    job=response.json()
    for _ in range(100):
        job=client.get('/api/ai/jobs/'+job['id']).json()
        if job['status']!='running':break
        time.sleep(.01)
    assert job['status']=='completed' and not job['errors'],job
    saved=store.read_state()['documents'][0]
    assert saved['original_extracted']['invoice_number']==invoice.invoice_number
    assert saved['extraction_history']
    assert saved['extracted']['extraction_method']=='AI assisted'
