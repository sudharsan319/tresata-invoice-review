import io
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest
import pymupdf as fitz
from fastapi.testclient import TestClient

from app import store, demo
from app.main import app
from app.service import ingest, run_reviews
from app.models import Invoice, Vendor, PurchaseOrder, HistoricalInvoice, Policy, LineItem
from app.engine import review_invoice
from app.extraction import extract_invoice, read_pdf, money, parse_date
import httpx


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    monkeypatch.delenv('AI_BASE_URL', raising=False)
    monkeypatch.delenv('AI_MODEL', raising=False)
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    monkeypatch.delenv('AI_API_KEY', raising=False)
    return TestClient(app)


def test_twelve_document_scenarios_end_to_end(client):
    manifest = None
    for kind, name, content in demo.files(include_scan=False):
        if kind == 'manifest':
            manifest = json.loads(content)
            continue
        response = client.post('/api/documents', data={'kind': kind}, files={'files': (name, content, 'application/pdf' if name.endswith('.pdf') else 'application/json')})
        assert response.status_code == 200, response.text
        assert response.json()['errors'] == [], response.text
    workspace = client.get('/api/workspace').json()
    actual = {r['filename']: r['decision'] for r in workspace['reviews']}
    assert actual == {m['filename']: m['expected_decision'] for m in manifest}
    ready = next(r for r in workspace['reviews'] if r['filename'] == '01-ready.pdf')
    assert ready['invoice']['total'] == '9440'
    assert ready['po_context']['historical_committed'] == '4000'
    capacity = next(r for r in workspace['reviews'] if r['filename'] == '12-batch-capacity.pdf')
    assert capacity['po_context']['batch_reserved'] == '12000'
    assert capacity['po_context']['remaining'] == '4000'
    assert all(c['evidence'] for c in ready['checks'] if c['code'] in ('tax_math', 'po_match', 'po_balance', 'vendor_identity'))
    exported = client.get('/api/export').json()
    assert len(exported['reviews']) == 12
    assert len(exported['source_documents']) == 16
    assert all(d['sha256'] for d in exported['source_documents'])
    assert next(d for d in exported['source_documents'] if d['kind']=='invoice')['extracted']
    assert exported['audit']
    assert client.get('/api/export?format=csv').status_code == 200


def fixtures(**overrides):
    today = date(2026, 10, 31)
    invoice = Invoice(invoice_number='INV-1', invoice_date=today.isoformat(), vendor_name='Acme', vendor_id='V1', po_number='PO-1', currency='INR', subtotal='100', tax_amount='18', total='118', items=[LineItem(description='Seats', quantity='1', unit_price='100', amount='100')], **overrides)
    vendor = Vendor(vendor_id='V1', name='Acme', status='approved', bank_account='12345')
    po = PurchaseOrder(po_number='PO-1', vendor_id='V1', currency='INR', amount='1000', amount_basis='net', status='approved', items=[LineItem(description='Seats', quantity='10', unit_price='100', amount='1000')])
    history = [HistoricalInvoice(invoice_number='OLD-1', vendor_id='V1', currency='INR', subtotal='10', total='10', status='paid')]
    document = {'id': 'd1', 'sha256': 'hash1', 'filename': 'invoice.pdf', 'pages': [{'method': 'text'}]}
    return invoice, vendor, po, history, document, today


def check(invoice, vendor, po, history, document, today, policy=None, earlier=None, reservations=None):
    return review_invoice(document, invoice, [vendor], [po], history, policy or Policy(), earlier or [], reservations or {}, today=today)


@pytest.mark.parametrize('change,expected_code,decision', [
    ({'currency':'USD'}, 'po_currency', 'procurement'),
    ({'invoice_date':'2027-01-01'}, 'invoice_date', 'clarification'),
    ({'invoice_date':'2025-01-01'}, 'invoice_date', 'clarification'),
    ({'invoice_date':'2026-02-31'}, 'invoice_date', 'clarification'),
    ({'total':Decimal('-118')}, 'positive_amount', 'clarification'),
    ({'tax_amount':None}, 'tax_math', 'clarification'),
    ({'total':Decimal('119')}, 'tax_math', 'clarification'),
    ({'invoice_number':''}, 'required_fields', 'clarification'),
    ({'items':[]}, 'line_math', 'clarification'),
    ({'bank_account':'99999'}, 'bank_match', 'hold'),
    ({'vendor_id':'OTHER'}, 'vendor_identity', 'hold'),
])
def test_financial_and_identity_controls(change, expected_code, decision):
    inv, v, po, history, document, today = fixtures()
    inv = inv.model_copy(update=change)
    result = check(inv,v,po,history,document,today)
    assert result.decision == decision
    assert any(c.code == expected_code and c.route != 'ready' for c in result.checks)


def test_no_history_does_not_claim_duplicate_clearance():
    inv,v,po,_,document,today=fixtures()
    result=check(inv,v,po,[],document,today)
    assert result.decision=='clarification'
    assert next(c for c in result.checks if c.code=='duplicate').status=='warning'


def test_invoice_number_dedup_is_vendor_scoped():
    inv,v,po,history,document,today=fixtures()
    history.append(HistoricalInvoice(invoice_number='INV-1',vendor_id='ANOTHER',currency='INR',total='118',status='paid'))
    assert check(inv,v,po,history,document,today).decision=='ready'
    history.append(HistoricalInvoice(invoice_number='inv 1',vendor_id='V1',currency='INR',total='118',status='pending'))
    assert check(inv,v,po,history,document,today).decision=='hold'


def test_ocr_requires_human_verification(client):
    _, name, content = next(f for f in demo.files() if 'scanned' in f[1])
    document=read_pdf(content,'scan',name)
    invoice=extract_invoice(document,use_ai=False)
    assert document['pages'][0]['method']=='ocr'
    assert 'NS' in invoice.invoice_number, invoice.model_dump_json()
    assert invoice.total == Decimal('1000'), invoice.model_dump_json()
    assert invoice.items, invoice.model_dump_json()
    document.update(id='scan',sha256='scan')
    _,v,po,h,_,today=fixtures()
    result=check(invoice,v,po,h,document,today)
    assert any(c.code=='extraction_review' and c.route=='clarification' for c in result.checks)


def test_tax_inclusive_amounts_are_not_compared_to_net_rates():
    inv,v,po,h,d,today=fixtures()
    inv.tax_inclusive=True
    inv.items=[LineItem(description='Seats',quantity='1',unit_price='118',amount='118')]
    result=check(inv,v,po,h,d,today)
    assert result.decision=='procurement'
    assert any('include tax' in c.message for c in result.checks)


def test_historical_net_amount_missing_requires_procurement():
    inv,v,po,h,d,today=fixtures()
    h.append(HistoricalInvoice(invoice_number='OLD-2',vendor_id='V1',po_number='PO-1',currency='INR',total='118',status='paid'))
    result=check(inv,v,po,h,d,today)
    assert result.decision=='procurement'
    assert next(c for c in result.checks if c.code=='po_balance').status=='fail'


def test_normalized_po_identity_collision_is_rejected(client):
    data=[{'po_number':'PO-1','vendor_id':'V1','currency':'INR','amount':'100','amount_basis':'net','status':'approved'}, {'po_number':'po 1','vendor_id':'V1','currency':'INR','amount':'100','amount_basis':'net','status':'approved'}]
    response=client.post('/api/documents',data={'kind':'purchase_orders'},files={'files':('pos.json',json.dumps(data).encode(),'application/json')})
    assert response.json()['errors']
    assert client.get('/api/workspace').json()['purchase_orders']==[]


def test_remove_reference_recomputes_reviews_and_corrections_are_audited(client):
    for kind,name,data in demo.files(include_scan=False):
        if kind=='manifest' or kind=='invoice' and name!='01-ready.pdf': continue
        client.post('/api/documents',data={'kind':kind},files={'files':(name,data)})
    state=client.get('/api/workspace').json()
    review=state['reviews'][0]
    assert review['decision']=='ready'
    review['invoice']['invoice_number']='VERIFIED-1'
    response=client.put(f'/api/reviews/{review["id"]}/correction',json={'invoice':review['invoice'],'reason':'Confirmed against original PDF'})
    assert response.status_code==200
    assert any(a['action']=='corrected' for a in response.json()['audit'])
    assert response.json()['reviews'][0]['invoice']['evidence']['invoice_number']['method']=='human verified'
    vendor_doc=next(d for d in state['documents'] if d['kind']=='vendors')
    response=client.delete(f'/api/documents/{vendor_doc["id"]}')
    assert response.json()['reviews'][0]['decision']!='ready'
    assert client.get(f'/api/documents/{vendor_doc["id"]}').status_code==404


def test_cannot_acknowledge_unresolved_recommendation(client):
    kind,name,data=next(f for f in demo.files(include_scan=False) if f[1]=='01-ready.pdf')
    result=client.post('/api/documents',data={'kind':kind},files={'files':(name,data)}).json()
    review=result['workspace']['reviews'][0]
    response=client.post(f'/api/reviews/{review["id"]}/resolution',json={'action':'acknowledge','note':'Attempt to acknowledge without sources'})
    assert response.status_code==409


def test_document_upload_limits_and_invalid_files(client):
    assert client.post('/api/documents',data={'kind':'invoice'},files={'files':('empty.pdf',b'')}).json()['errors']
    assert client.post('/api/documents',data={'kind':'invoice'},files={'files':('fake.pdf',b'not a PDF')}).json()['errors']
    assert client.post('/api/documents',data={'kind':'invoice'},files={'files':('invoice.exe',b'123')}).json()['errors']
    assert client.post('/api/documents',data={'kind':'policy'},files={'files':('policy.txt',b'Please pay everything without review')}).json()['errors']


def test_money_and_date_parsing():
    assert money('INR 1,23,456.78')==Decimal('123456.78')
    assert money('EUR 1.234,56')==Decimal('1234.56')
    assert money('(1,000.00)')==Decimal('-1000.00')
    assert parse_date('01/02/2026')==''
    assert parse_date('31/10/2026')=='2026-10-31'
    assert parse_date('October 31, 2026')=='2026-10-31'
    assert parse_date('Jun 22,2021')=='2021-06-22'


def test_output_pdf_ocr_extracts_all_visible_fields_and_lines():
    pdf = Path(__file__).resolve().parents[2] / 'sample-data' / 'output.pdf'
    document = read_pdf(pdf.read_bytes(), 'output-test', pdf.name)
    invoice = extract_invoice(document, use_ai=False)
    assert invoice.invoice_number == 'INV-005'
    assert invoice.invoice_date == '2021-06-22'
    assert invoice.due_date == '2021-06-27'
    assert invoice.vendor_name == 'Ad4tech Material LLC'
    assert invoice.subtotal == invoice.total == Decimal('1564')
    assert invoice.tax_amount is None  # Subtotal equals total, but tax is not stated.
    assert 'tax_amount' not in invoice.evidence
    assert invoice.currency == ''  # A dollar sign alone does not identify the currency.
    assert [(item.quantity, item.unit_price, item.amount) for item in invoice.items] == [
        (Decimal('1'), Decimal('232'), Decimal('232')),
        (Decimal('2'), Decimal('514'), Decimal('1028')),
        (Decimal('2'), Decimal('152'), Decimal('304')),
    ]
    assert sum(item.amount for item in invoice.items) == invoice.subtotal


def test_api_rejects_cross_origin_mutations(client):
    assert client.delete('/api/workspace',headers={'Origin':'https://unrelated.example'}).status_code==403


def test_empty_history_is_an_explicit_zero_record_register(client):
    response=client.post('/api/documents',data={'kind':'history'},files={'files':('empty-history.json',b'[]','application/json')})
    assert response.json()['errors']==[]
    assert response.json()['workspace']['documents'][0]['record_count']==0
    assert response.json()['workspace']['history_count']==0


def test_unknown_json_policy_is_rejected(client):
    response=client.post('/api/documents',data={'kind':'policy'},files={'files':('policy.json',b'{"invented_tolerance": 99}','application/json')})
    assert response.json()['errors']
    assert not response.json()['accepted']


def test_anonymous_bank_and_vendor_names_are_not_fuzzy_approved():
    inv,v,po,h,d,today=fixtures()
    inv.vendor_name='Acme Services'
    result=check(inv,v,po,h,d,today)
    assert result.decision=='hold'


def test_historical_quantities_limit_partial_invoice():
    inv,v,po,h,d,today=fixtures()
    h.append(HistoricalInvoice(invoice_number='OLD-2',vendor_id='V1',po_number='PO-1',currency='INR',subtotal='900',total='900',status='paid',items=[LineItem(description='Seats',quantity='10',unit_price='90',amount='900')]))
    result=check(inv,v,po,h,d,today)
    assert result.decision=='procurement'
    assert next(c for c in result.checks if c.code=='po_balance').status=='pass'
    assert next(c for c in result.checks if c.code=='item_0').status=='fail'


def test_unresolved_invoice_prevents_later_po_invoice_being_ready():
    today=datetime.now(ZoneInfo('Asia/Kolkata')).date().isoformat()
    state=store.initial_state()
    state['vendors']=[Vendor(vendor_id='V1',name='Acme',status='active').model_dump(mode='json')]
    state['purchase_orders']=[PurchaseOrder(po_number='PO-1',vendor_id='V1',vendor_name='Acme',currency='INR',
        amount='1800',amount_basis='net',status='approved',items=[LineItem(description='Kits',quantity='6',unit_price='300',amount='1800')]).model_dump(mode='json')]

    def invoice(number,quantity,amount):
        return Invoice(invoice_number=number,invoice_date=today,vendor_name='Acme',vendor_id='V1',po_number='PO-1',
            currency='INR',subtotal=str(amount),tax_amount='0',total=str(amount),
            items=[LineItem(description='Kits',quantity=str(quantity),unit_price='300',amount=str(amount))]).model_dump(mode='json')

    first=invoice('SCAN-1',6,1800)
    second=invoice('NEXT-1',1,300)
    state['documents']=[{'kind':'history'},
        {'id':'scan','kind':'invoice','filename':'scan.pdf','sha256':'scan-hash','pages':[{'method':'ocr'}],'extracted':first},
        {'id':'next','kind':'invoice','filename':'next.pdf','sha256':'next-hash','pages':[{'method':'text'}],'extracted':second}]
    run_reviews(state)
    assert [r['decision'] for r in state['reviews']]==['clarification','clarification']
    later=state['reviews'][1]
    assert later['po_context']['pending_invoices']==['SCAN-1']
    assert later['po_context']['pending_amount']=='1800'
    assert later['po_context']['potential_remaining']=='0'
    assert any(c['code']=='po_pending' and c['status']=='warning' for c in later['checks'])

    # Once the scan is checked, its commitment becomes firm and the next invoice exceeds it.
    state['corrections']['scan']={'invoice':first,'reason':'Checked the original scan.'}
    run_reviews(state)
    assert [r['decision'] for r in state['reviews']]==['ready','procurement']
    assert state['reviews'][1]['po_context']['batch_reserved']=='1800'
    assert any(c['code']=='po_balance' and c['status']=='fail' for c in state['reviews'][1]['checks'])


def test_pdf_with_positioned_table_columns():
    pdf=fitz.open();page=pdf.new_page()
    labels=['Vendor Name: Acme','Invoice Number: INV-1','Invoice Date: 2026-10-31','Currency: INR','Subtotal: 200','Total Tax: 0','Invoice Total: 200']
    for index,line in enumerate(labels):page.insert_text((35,40+index*20),line)
    for x,text in [(35,'Seats'),(260,'2'),(360,'100'),(470,'200')]:page.insert_text((x,230),text)
    extracted=extract_invoice(read_pdf(pdf.tobytes(),'table','table.pdf'),use_ai=False)
    assert len(extracted.items)==1
    assert extracted.items[0].description=='Seats'
    assert extracted.items[0].amount==Decimal('200')


def test_ai_ungrounded_values_are_discarded(monkeypatch):
    monkeypatch.setenv('AI_BASE_URL','http://test-provider.invalid/v1')
    monkeypatch.setenv('AI_MODEL','test-model')
    def fake_post(*args,**kwargs):
        payload={'invoice_number':'INVENTED','total':'999999','sources':{'invoice_number':{'page':1,'quote':'not in the source'},'total':{'page':1,'quote':'Invoice Total: 118'}}}
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(payload)}}]},request=httpx.Request('POST','http://test-provider.invalid/v1/chat/completions'))
    monkeypatch.setattr(httpx,'post',fake_post)
    document={'document_id':'d','filename':'invoice.pdf','pages':[{'page':1,'text':'Invoice Number: REAL-1\nInvoice Total: 118\nCurrency: INR','method':'text'}],'notes':[]}
    result=extract_invoice(document)
    assert result.invoice_number=='REAL-1'
    assert result.total==Decimal('118')
    assert any('discarded' in note for note in result.extraction_notes)


def test_ai_failure_falls_back_without_inventing_missing_fields(monkeypatch):
    monkeypatch.setenv('AI_BASE_URL','http://test-provider.invalid/v1')
    monkeypatch.setenv('AI_MODEL','test-model')
    monkeypatch.setattr(httpx,'post',lambda *args,**kwargs: (_ for _ in ()).throw(httpx.ConnectError('offline')))
    document={'document_id':'d','filename':'invoice.pdf','pages':[{'page':1,'text':'Invoice Number: REAL-1\nInvoice Total: 118','method':'text'}],'notes':[]}
    result=extract_invoice(document)
    assert result.total==Decimal('118')
    assert result.currency==''
    assert result.tax_amount is None
    assert any('local extraction used' in note for note in result.extraction_notes)


def test_reference_pdf_and_csv_and_xlsx_uploads(client):
    pdf=fitz.open();page=pdf.new_page()
    for i,text in enumerate(['Purchase Order Number: PO-PDF','Vendor ID: V1','Currency: INR','Amount Basis: net','Net Amount: 1000','Status: approved','Seats | 10 | 100 | 1000']):page.insert_text((40,40+i*24),text)
    result=client.post('/api/documents',data={'kind':'purchase_orders'},files={'files':('po.pdf',pdf.tobytes())}).json()
    assert result['errors']==[], result
    assert result['workspace']['purchase_orders']==[]
    draft_id=result['accepted'][0]['id']
    draft=result['workspace']['po_drafts'][draft_id]
    assert draft['values']['po_number']=='PO-PDF'
    assert draft['values']['amount']=='1000'
    assert draft['values']['items'][0]['description']=='Seats'
    activation=client.post(f'/api/purchase-orders/drafts/{draft_id}/approve',json={
        'po': draft['values'] | {'vendor_name':'Acme'}, 'note':'Verified PO against the original PDF.', 'confirmed':True,
    })
    assert activation.status_code==200, activation.text
    assert activation.json()['purchase_orders'][0]['po_number']=='PO-PDF'
    assert activation.json()['po_drafts']=={}
    result=client.post('/api/documents',data={'kind':'vendors'},files={'files':('vendors.csv',b'vendor_id,name,status,bank_account\nV1,Acme,active,0012345')}).json()
    assert result['errors']==[]
    assert result['workspace']['vendors'][0]['bank_account']=='0012345'
    from openpyxl import Workbook
    book=Workbook();sheet=book.active
    sheet.append(['invoice_number','vendor_id','currency','subtotal','total','status'])
    sheet.append(['OLD-XLS','V1','INR',100,118,'paid'])
    buf=io.BytesIO();book.save(buf)
    result=client.post('/api/documents',data={'kind':'history'},files={'files':('history.xlsx',buf.getvalue())}).json()
    assert result['errors']==[],result
    assert result['workspace']['history_count']==1


def test_image_and_scanned_po_wait_for_review_then_recompute(client):
    from PIL import Image, ImageDraw
    invoice_pdf=fitz.open(); invoice_page=invoice_pdf.new_page()
    for index,text in enumerate(['Invoice Number: INV-IMG','Invoice Date: 2026-10-31','Vendor Name: Acme','Vendor ID: V1',
                                 'PO Number: PO-IMG','Currency: INR','Subtotal: 100','Tax Amount: 0','Total: 100',
                                 'Seats | 1 | 100 | 100']):
        invoice_page.insert_text((40,40+index*22),text)
    invoice_upload=client.post('/api/documents',data={'kind':'invoice'},files={'files':('invoice.pdf',invoice_pdf.tobytes())}).json()
    assert invoice_upload['errors']==[]
    assert invoice_upload['workspace']['reviews'][0]['matched_po'] is None
    image=Image.new('RGB',(900,350),'white')
    draw=ImageDraw.Draw(image)
    draw.text((35,35),'Purchase Order Number: PO-IMG',fill='black')
    draw.text((35,85),'Vendor Name: Acme',fill='black')
    draw.text((35,135),'Amount Basis: net',fill='black')
    draw.text((35,185),'Net Amount: 1000',fill='black')
    buffer=io.BytesIO();image.save(buffer,format='PNG')
    upload=client.post('/api/documents',data={'kind':'purchase_orders'},files={'files':('po.png',buffer.getvalue(),'image/png')})
    assert upload.status_code==200, upload.text
    result=upload.json()
    assert result['errors']==[], result
    draft_id=result['accepted'][0]['id']
    assert draft_id in result['workspace']['po_drafts']
    assert result['workspace']['purchase_orders']==[]
    assert next(d for d in result['workspace']['documents'] if d['id']==draft_id)['pending_interpretation'] is True
    assert result['workspace']['reviews'][0]['matched_po'] is None
    assert client.get(f'/api/documents/{draft_id}').headers['content-type'].startswith('image/png')
    po={'po_number':'PO-IMG','vendor_id':'V1','vendor_name':'Acme','currency':'INR','amount':'1000',
        'amount_basis':'net','status':'approved','valid_from':'','valid_to':'',
        'items':[{'description':'Seats','quantity':'10','unit_price':'100','amount':'1000'}]}
    rejected=client.post(f'/api/purchase-orders/drafts/{draft_id}/approve',json={'po':po,'note':'Checked original image.','confirmed':False})
    assert rejected.status_code==422
    accepted=client.post(f'/api/purchase-orders/drafts/{draft_id}/approve',json={'po':po,'note':'Checked original image.','confirmed':True})
    assert accepted.status_code==200, accepted.text
    assert accepted.json()['purchase_orders'][0]['evidence']['document_id']==draft_id
    assert next(d for d in accepted.json()['documents'] if d['id']==draft_id)['record_count']==1
    assert next(d for d in accepted.json()['documents'] if d['id']==draft_id)['pending_interpretation'] is False
    assert accepted.json()['reviews'][0]['matched_po']['po_number']=='PO-IMG'
    duplicate=client.post('/api/documents',data={'kind':'purchase_orders'},files={'files':('same.json',json.dumps([po]).encode())}).json()
    assert duplicate['errors'] and 'Duplicate' in duplicate['errors'][0]['message']


def test_scanned_po_pdf_is_saved_as_draft(client):
    from PIL import Image
    image=Image.new('RGB',(900,300),'white')
    buffer=io.BytesIO();image.save(buffer,format='PNG')
    pdf=fitz.open();page=pdf.new_page();page.insert_image(page.rect,stream=buffer.getvalue())
    result=client.post('/api/documents',data={'kind':'purchase_orders'},files={'files':('scan.pdf',pdf.tobytes())}).json()
    assert result['errors']==[], result
    assert result['workspace']['purchase_orders']==[]
    assert result['accepted'][0]['id'] in result['workspace']['po_drafts']


def test_locked_pdf_returns_actionable_error(client):
    pdf=fitz.open();pdf.new_page().insert_text((40,40),'Locked invoice')
    data=pdf.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256,owner_pw='owner',user_pw='secret')
    result=client.post('/api/documents',data={'kind':'invoice'},files={'files':('locked.pdf',data)}).json()
    assert 'Password-protected' in result['errors'][0]['message']


def test_duplicate_pdf_in_same_batch_is_held(client):
    kind,name,data=next(f for f in demo.files(include_scan=False) if f[1]=='01-ready.pdf')
    result=client.post('/api/documents',data={'kind':kind},files=[('files',(name,data)),('files',('same.pdf',data))]).json()
    assert result['errors']==[]
    assert result['workspace']['reviews'][1]['decision']=='hold'


def test_changed_bank_cannot_be_hidden_by_claiming_verification(client):
    for kind,name,data in demo.files(include_scan=False):
        if kind=='manifest' or kind=='invoice' and name!='05-bank-changed.pdf':continue
        client.post('/api/documents',data={'kind':kind},files={'files':(name,data)})
    review=client.get('/api/workspace').json()['reviews'][0]
    result=client.put(f'/api/reviews/{review["id"]}/correction',json={'invoice':review['invoice'],'reason':'Reviewed all fields, no changes'}).json()
    assert result['reviews'][0]['decision']=='hold'


def test_sample_zip_contains_expected_manifest(client):
    import zipfile
    response=client.get('/api/samples')
    assert response.status_code==200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        cases=json.loads(archive.read('manifest/expected-results.json'))
        assert len(cases)==13
        assert 'invoice/13-scanned-invoice.pdf' in archive.namelist()


def test_missing_po_reference_shows_exact_vendor_name_candidate_without_matching():
    invoice, vendor, po, history, document, today = fixtures()
    invoice.po_number = ''
    invoice.vendor_id = ''
    po.vendor_id = ''
    po.vendor_name = 'Acme'
    result = review_invoice(document, invoice, [], [po], history, Policy(), [], {}, today=today)
    po_check = next(item for item in result.checks if item.code == 'po_match')
    assert result.matched_po is None
    assert result.po_candidates == ['PO-1']
    assert 'Confirm the intended PO' in po_check.message
