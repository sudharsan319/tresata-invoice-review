"""Exercise live polling against blocked work, failures, and persisted evidence."""
import json
import io
import threading
import time

import httpx
import fitz
import pytest
from PIL import Image
from fastapi.testclient import TestClient

from app import ai, demo, progress, service, store
from app import main
from app.main import app, upload_jobs, upload_lock


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    for key in ('OPENROUTER_API_KEY', 'AI_API_KEY', 'AI_BASE_URL', 'AI_MODEL'):
        monkeypatch.delenv(key, raising=False)
    with upload_lock:
        upload_jobs.clear()
    return TestClient(app)


def invoice_pdf():
    return next((name, data) for kind, name, data in demo.files(include_scan=False) if kind == 'invoice')


def wait_finished(client, job_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = client.get(f'/api/uploads/{job_id}').json()
        if job['status'] in ('completed', 'failed'):
            return job
        time.sleep(.01)
    pytest.fail('Upload worker did not finish')


def test_live_checks_match_saved_review_and_trace(client):
    for kind, name, data in demo.files(include_scan=False):
        if kind not in ('invoice', 'manifest'):
            assert not client.post('/api/documents', data={'kind': kind}, files={'files': (name, data)}).json()['errors']
    name, data = invoice_pdf()
    response = client.post('/api/uploads', data={'kind': 'invoice'}, files={'files': (name, data)})
    assert response.status_code == 202
    job = wait_finished(client, response.json()['id'])
    assert job['status'] == 'completed' and not job['errors']
    file = job['files'][0]
    assert file['status'] == 'completed'
    events = file['events']
    workspace = client.get('/api/workspace').json()
    review = workspace['reviews'][0]
    assert review['decision'] == 'ready'
    assert [e['code'] for e in events if 'code' in e] == [c['code'] for c in review['checks']]
    assert [e['detail'] for e in events if 'code' in e] == [c['message'] for c in review['checks']]
    assert next(e for e in events if e['stage'] == 'recommendation')['decision'] == 'ready'
    assert next(e for e in events if e['stage'] == 'ai')['status'] == 'skipped'
    trace = workspace['documents'][-1]['processing_trace']
    assert trace == events[:-1]  # Final save event is emitted only after SQLite commits.
    assert all(e['timestamp'] for e in trace)


@pytest.mark.parametrize('image_format,filename,mime', [
    ('PNG', 'image-without-extension', 'image/png'),
    ('JPEG', 'invoice.jpeg', 'image/jpeg'),
    ('WEBP', 'invoice.webp', 'image/webp'),
])
def test_live_invoice_image_upload_runs_ocr_and_preserves_original(client, image_format, filename, mime):
    _, _, scanned_pdf = next(item for item in demo.files() if 'scanned-invoice' in item[1])
    with fitz.open(stream=scanned_pdf, filetype='pdf') as document:
        png = document[0].get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes('png')
    with Image.open(io.BytesIO(png)) as image:
        buffer = io.BytesIO()
        image.save(buffer, format=image_format)
    original = buffer.getvalue()
    response = client.post('/api/uploads', data={'kind': 'invoice'},
                           files={'files': (filename, original, mime)})
    assert response.status_code == 202
    job = wait_finished(client, response.json()['id'])
    assert job['status'] == 'completed' and not job['errors'], job
    uploaded = job['files'][0]
    assert uploaded['status'] == 'completed'
    assert any(event['stage'] == 'reading' and event['status'] == 'completed' for event in uploaded['events'])
    workspace = client.get('/api/workspace').json()
    source = next(item for item in workspace['documents'] if item['id'] == uploaded['id'])
    assert source['methods'] == ['ocr']
    assert source['filename'].endswith('.jpg' if image_format == 'JPEG' else '.' + image_format.lower())
    review = next(item for item in workspace['reviews'] if item['id'] == uploaded['id'])
    assert review['invoice']['invoice_number'].startswith('NS-')
    assert any(check['code'] == 'extraction_review' for check in review['checks'])
    saved = client.get(f'/api/documents/{uploaded["id"]}')
    assert saved.content == original
    assert saved.headers['content-type'].startswith(mime)


def test_image_invoice_can_be_reprocessed_without_losing_vision_input(client, monkeypatch):
    _, _, scanned_pdf = next(item for item in demo.files() if 'scanned-invoice' in item[1])
    with fitz.open(stream=scanned_pdf, filetype='pdf') as document:
        image = document[0].get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes('png')
    uploaded = client.post('/api/documents', data={'kind': 'invoice'},
                           files={'files': ('invoice-image', image, 'image/png')}).json()
    assert not uploaded['errors']
    document_id = uploaded['accepted'][0]['id']
    ai.save_settings(ai.AISettingsUpdate(enabled=True, api_key='synthetic-test-key'))
    seen = []
    original_extract = main.extract_invoice

    def local_extract(document, *, pdf_bytes):
        seen.append(pdf_bytes.startswith(b'%PDF-'))
        return original_extract(document, use_ai=False)

    monkeypatch.setattr(main, 'extract_invoice', local_extract)
    response = client.post('/api/ai/reprocess', json={'document_ids': [document_id]})
    assert response.status_code == 200, response.text
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        job = client.get(f'/api/ai/jobs/{response.json()["id"]}').json()
        if job['status'] != 'running':
            break
        time.sleep(.01)
    else:
        pytest.fail('Image reprocessing did not finish')
    assert job['status'] == 'completed' and not job['errors']
    assert seen == [True]
    assert client.get(f'/api/documents/{document_id}').content == image


def test_progress_available_during_slow_extraction_and_blocks_duplicate_job(client, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original = service.extract_invoice

    def slow(document, **kwargs):
        progress.emit('ai', 'running', 'AI extraction', 'Waiting for synthetic provider.', task='extraction', model='synthetic/model')
        entered.set()
        assert release.wait(5)
        progress.emit('ai', 'warning', 'AI unavailable', 'Synthetic timeout; using local fields.', task='extraction', model='synthetic/model')
        return original(document, use_ai=False)

    monkeypatch.setattr(service, 'extract_invoice', slow)
    name, data = invoice_pdf()
    response = client.post('/api/uploads', data={'kind': 'invoice'}, files={'files': (name, data)})
    job_id = response.json()['id']
    try:
        assert entered.wait(3)
        started = time.monotonic()
        running = client.get(f'/api/uploads/{job_id}').json()
        assert time.monotonic() - started < 1
        assert running['status'] == 'running'
        assert running['files'][0]['events'][-1]['model'] == 'synthetic/model'
        assert not any(e.get('code') for e in running['files'][0]['events'])
        second = client.post('/api/uploads', data={'kind': 'invoice'}, files={'files': (name, data)})
        assert second.status_code == 409
    finally:
        release.set()
        finished = wait_finished(client, job_id)
    assert finished['status'] == 'completed'
    assert any(e['status'] == 'warning' and e['stage'] == 'ai' for e in finished['files'][0]['events'])
    review = client.get('/api/workspace').json()['reviews'][0]
    assert review['decision'] == 'procurement'
    assert any(c['code'] == 'po_match' and c['status'] == 'fail' for c in review['checks'])


def test_batch_failure_does_not_fake_checks_or_block_other_files(client):
    name, data = invoice_pdf()
    result = client.post('/api/uploads', data={'kind': 'invoice'}, files=[('files', ('bad.txt', b'bad')), ('files', (name, data))])
    job = wait_finished(client, result.json()['id'])
    assert job['status'] == 'completed'
    assert len(job['accepted']) == len(job['errors']) == 1
    bad, good = job['files']
    assert bad['status'] == 'failed' and good['status'] == 'completed'
    assert not any(e.get('code') or e['stage'] == 'recommendation' for e in bad['events'])
    assert bad['events'][-1]['status'] == 'failed'
    assert len(client.get('/api/workspace').json()['documents']) == 1


def test_reference_upload_and_missing_job(client):
    response = client.post('/api/uploads', data={'kind': 'history'}, files={'files': ('empty-history.json', b'[]')})
    job = wait_finished(client, response.json()['id'])
    assert job['status'] == 'completed' and not job['errors']
    assert not any(e.get('code') for e in job['files'][0]['events'])
    assert client.get('/api/uploads/unknown-id').status_code == 404
    blocked = client.post('/api/uploads', headers={'Origin': 'https://untrusted.example'}, data={'kind': 'history'}, files={'files': ('history.json', b'[]')})
    assert blocked.status_code == 403


def test_live_po_pdf_upload_stays_pending_without_rechecking_invoices(client):
    pdf = fitz.open()
    page = pdf.new_page()
    for index, line in enumerate(('Purchase Order Number: PO-LIVE-1', 'Vendor Name: Acme',
                                  'Currency: INR', 'Amount Basis: net', 'Net Amount: 250',
                                  'Status: approved', 'Seats | 1 | 250 | 250')):
        page.insert_text((40, 40 + index * 24), line)
    response = client.post('/api/uploads', data={'kind': 'purchase_orders'},
                           files={'files': ('po-live.pdf', pdf.tobytes(), 'application/pdf')})
    assert response.status_code == 202
    job = wait_finished(client, response.json()['id'])
    assert job['status'] == 'completed' and not job['errors']
    assert job['accepted'][0]['pending_review'] is True
    events = job['files'][0]['events']
    assert events[-1]['title'] == 'Draft saved for review'
    assert not any(event['stage'] == 'matching' for event in events)
    workspace = client.get('/api/workspace').json()
    assert workspace['purchase_orders'] == []
    assert job['accepted'][0]['id'] in workspace['po_drafts']


def test_ai_events_exclude_prompts_secrets_and_raw_model_output(client, monkeypatch):
    ai.save_settings(ai.AISettingsUpdate(enabled=True, api_key='synthetic-secret'))

    def fake_post(url, **kwargs):
        return httpx.Response(200, json={'choices': [{'message': {'content': '{"private_result":"secret-model-output"}'}}], 'usage': {'prompt_tokens': 12, 'completion_tokens': 8}}, request=httpx.Request('POST', url))

    monkeypatch.setattr(httpx, 'post', fake_post)
    events = []
    with progress.capture(lambda doc_id, event: events.append(event)), progress.document_scope('doc', 'test.pdf'):
        result, record = ai.complete('extraction', 'private-system-prompt', 'private-invoice-text')
    assert result['private_result'] == 'secret-model-output'
    assert [e['status'] for e in events] == ['running', 'completed']
    serialized = json.dumps(events)
    assert all(secret not in serialized for secret in ('synthetic-secret', 'private-system-prompt', 'private-invoice-text', 'secret-model-output'))
    assert events[-1]['model'] == record['model']


def test_progress_context_is_restored():
    captured = []
    with progress.capture(lambda doc_id, event: captured.append(doc_id)):
        with progress.document_scope('outer', 'outer.pdf'):
            with progress.document_scope('inner', 'inner.pdf'):
                progress.emit('reading', 'running', 'Inner')
            progress.emit('reading', 'completed', 'Outer')
        progress.emit('reading', 'running', 'No document')
    assert captured == ['inner', 'outer']
