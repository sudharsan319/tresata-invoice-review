import csv
import io
import json
import threading
import copy
import uuid
from pathlib import Path
from datetime import date, datetime
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from . import store, demo, progress
from .models import Correction, Resolution, Policy, Evidence, Invoice, PurchaseOrder, SemanticConfirmation
from .service import ingest, run_reviews, public_state, audit, validate_purchase_order, MAX_BYTES
from .extraction import ai_configured, extract_invoice, normalize
from . import ai
from .interpretation import review_brief

app = FastAPI(title='Invoices', version='1.0.0', description='Local, evidence-led two-way invoice review. Recommendations require human approval.')
app.add_middleware(CORSMiddleware, allow_origins=['http://127.0.0.1:5173', 'http://localhost:5173', 'http://127.0.0.1:8000', 'http://localhost:8000'], allow_methods=['GET', 'POST', 'PUT', 'DELETE'], allow_headers=['Content-Type'])
lock = threading.RLock()
jobs: dict[str, dict] = {}
upload_jobs: dict[str, dict] = {}
upload_lock = threading.RLock()


def upload_worker(job_id, kind, payloads):
    def event(document_id, item):
        with upload_lock:
            file = next((f for f in upload_jobs[job_id]['files'] if f['id'] == document_id), None)
            if file:
                file['events'].append(item)
                file['events'] = file['events'][-1000:]

    try:
        with lock, progress.capture(event):
            state = store.read_state()
            with upload_lock:
                upload_jobs[job_id]['status'] = 'running'
            for document_id, filename, data in payloads:
                with upload_lock:
                    file = next(f for f in upload_jobs[job_id]['files'] if f['id'] == document_id)
                    file['status'] = 'processing'
                with progress.document_scope(document_id, filename):
                    progress.emit('validation', 'running', 'Validating upload', 'Checking file size, category, and workspace limits.')
                    try:
                        document = ingest(state, kind, filename, data, document_id=document_id)
                        if kind == 'invoice':
                            progress.emit('verification', 'queued', 'Waiting for batch verification', 'Verification starts after every file in this upload has been interpreted.')
                        with upload_lock:
                            file['status'] = 'verifying'
                            upload_jobs[job_id]['accepted'].append({'id': document['id'], 'filename': document['filename'], 'pending_review': bool(document.get('pending_interpretation'))})
                    except (ValueError, ValidationError, UnicodeError) as exc:
                        message = str(exc)[:1500]
                        progress.emit('validation', 'failed', 'Document could not be accepted', message)
                        with upload_lock:
                            file['status'] = 'failed'
                            upload_jobs[job_id]['errors'].append({'filename': filename, 'message': message})
                    except Exception as exc:
                        message = f'Could not process this file ({type(exc).__name__}). Check its format and try again.'
                        progress.emit('validation', 'failed', 'Document processing failed', message)
                        with upload_lock:
                            file['status'] = 'failed'
                            upload_jobs[job_id]['errors'].append({'filename': filename, 'message': message})
            if upload_jobs[job_id]['accepted']:
                active_change = kind == 'invoice' or any(not item['pending_review'] for item in upload_jobs[job_id]['accepted'])
                if kind != 'invoice' and active_change:
                    for document_id, filename, _ in payloads:
                        if any(d['id'] == document_id and not d.get('pending_interpretation') for d in state['documents']):
                            with progress.document_scope(document_id, filename):
                                progress.emit('matching', 'running', 'Rechecking dependent invoices', f'Recomputing {sum(d["kind"] == "invoice" for d in state["documents"])} invoice review(s) with the updated references.')
                if active_change:
                    run_reviews(state)
                if kind != 'invoice' and active_change:
                    for document_id, filename, _ in payloads:
                        if any(d['id'] == document_id and not d.get('pending_interpretation') for d in state['documents']):
                            with progress.document_scope(document_id, filename):
                                progress.emit('matching', 'completed', 'Dependent reviews updated', f'{len(state["reviews"])} invoice review(s) recomputed. Check the invoice queue for individual results.')
                # Keep the actual upload-time trace, separate from later recomputed checks.
                with upload_lock:
                    for file in upload_jobs[job_id]['files']:
                        target = next((d for d in state['documents'] if d['id'] == file['id']), None)
                        if target:
                            target['processing_trace'] = copy.deepcopy(file['events'])
                audit(state, 'reviewed' if active_change else 'draft_created',
                      f'Recomputed {len(state["reviews"])} invoice recommendations after live upload.' if active_change else 'Saved document drafts for human review; active references unchanged.')
                store.save_state(state)
            with upload_lock:
                for file in upload_jobs[job_id]['files']:
                    if file['status'] != 'failed':
                        file['status'] = 'completed'
                        pending = next((item['pending_review'] for item in upload_jobs[job_id]['accepted'] if item['id'] == file['id']), False)
                        file['events'].append({'timestamp': datetime.now().astimezone().isoformat(), 'stage': 'saved', 'status': 'completed', 'title': 'Draft saved for review' if pending else 'Saved to workspace', 'detail': 'Confirm the extracted fields before this reference affects invoice matching.' if pending else 'Processing finished. Recommendations still require human review and approval.'})
                upload_jobs[job_id]['status'] = 'completed'
    except Exception:
        with upload_lock:
            upload_jobs[job_id]['status'] = 'failed'
            for file in upload_jobs[job_id]['files']:
                if file['status'] not in ('failed', 'completed'):
                    file['status'] = 'failed'
            upload_jobs[job_id]['errors'].append({'filename': 'Processing', 'message': 'Processing stopped unexpectedly. Refresh the workspace to check saved results before retrying.'})
    finally:
        payloads.clear()


@app.post('/api/uploads', status_code=202)
def start_upload(kind: Literal['invoice', 'purchase_orders', 'vendors', 'history', 'policy'] = Form(...), files: list[UploadFile] = File(...)):
    try:
        if len(files) > 25:
            raise HTTPException(400, 'Upload at most 25 files at a time.')
        with upload_lock:
            if any(j['status'] in ('queued', 'running') for j in upload_jobs.values()):
                raise HTTPException(409, 'Another upload is processing. Wait for it to finish before uploading more files.')
            payloads = [(str(uuid.uuid4()), Path(f.filename or 'document').name[:180], f.file.read(MAX_BYTES + 1)) for f in files]
            job_id = str(uuid.uuid4())
            job = {'id': job_id, 'kind': kind, 'status': 'queued', 'started_at': datetime.now().astimezone().isoformat(),
                   'accepted': [], 'errors': [], 'files': [{'id': doc_id, 'filename': name, 'status': 'queued', 'events': []} for doc_id, name, _ in payloads]}
            finished = [key for key, value in upload_jobs.items() if value['status'] in ('completed', 'failed')]
            for key in finished[:-9]:
                upload_jobs.pop(key, None)
            upload_jobs[job_id] = job
            threading.Thread(target=upload_worker, args=(job_id, kind, payloads), daemon=True).start()
            return copy.deepcopy(job)
    finally:
        for file in files:
            file.file.close()


@app.get('/api/uploads/{job_id}')
def get_upload(job_id: str):
    # Independent of the workspace lock: progress remains readable during an AI call.
    with upload_lock:
        if job_id not in upload_jobs:
            raise HTTPException(404, 'Upload progress is unavailable; the server may have restarted. Check the workspace for saved results.')
        return copy.deepcopy(upload_jobs[job_id])


@app.middleware('http')
async def local_workspace(request: Request, call_next):
    origin = request.headers.get('origin')
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and origin and origin not in {'http://127.0.0.1:5173', 'http://localhost:5173', 'http://127.0.0.1:8000', 'http://localhost:8000'}:
        return Response('Cross-origin writes are not allowed.', status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Cache-Control'] = 'no-store'
    return response


def workspace(state):
    config = ai.public_settings()
    return public_state(state) | {'extraction': {'mode': 'OpenRouter AI + verified rules' if ai_configured() else 'Local extraction + OCR', 'model': config['models']['extraction'], 'external_processing': ai_configured()}, 'ai_settings': config}


@app.get('/api/ai/settings')
def get_ai_settings():
    return ai.public_settings()


@app.put('/api/ai/settings')
def put_ai_settings(update: ai.AISettingsUpdate):
    try:
        with lock:
            config = ai.save_settings(update)
            state = store.read_state()
            audit(state, 'ai_settings_changed', f'AI {"enabled" if config["ready"] else "disabled"}; task models: ' + ', '.join(f'{task}={model}' for task, model in config['models'].items()))
            # Avoid making paid calls merely by saving settings.
            store.save_state(state)
        return config
    except ai.AIError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get('/api/ai/models')
def get_ai_models():
    try:
        return {'models': ai.catalog()}
    except ai.AIError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post('/api/ai/test')
def test_ai_connection():
    try:
        return ai.test_connection()
    except ai.AIError as exc:
        raise HTTPException(400, str(exc)) from exc


class ReprocessRequest(BaseModel):
    document_ids: list[str] | None = Field(default=None, max_length=120)


def reprocess_worker(job_id: str, document_ids: list[str]):
    job = jobs[job_id]
    try:
        for document_id in document_ids:
            with lock:
                state = store.read_state()
                original = next((d for d in state['documents'] if d['id'] == document_id), None)
                if not original or document_id in state['corrections']:
                    job['skipped'] += 1
                    job['completed'] += 1
                    continue
                document = copy.deepcopy(original)
                job['current_file'] = document['filename']
            try:
                raw = (store.DATA / 'documents' / document['stored_name']).read_bytes()
                invoice = Invoice.model_validate(extract_invoice(document, pdf_bytes=raw).model_dump())
                with lock:
                    state = store.read_state()
                    target = next((d for d in state['documents'] if d['id'] == document_id), None)
                    if target and document_id not in state['corrections']:
                        target.setdefault('original_extracted', target['extracted'])
                        target.setdefault('extraction_history', []).append({'timestamp': datetime.now().astimezone().isoformat(), 'snapshot': target['extracted']})
                        target['extraction_history'] = target['extraction_history'][-5:]
                        target['extracted'] = invoice.model_dump(mode='json')
                        target['pages'] = document['pages']
                        state['ai_matches'].pop(document_id, None)
                        state['ai_briefs'].pop(document_id, None)
                        audit(state, 'ai_reprocessed', f'Re-extracted {document["filename"]} using configured AI models; prior extraction retained.', document_id)
                        run_reviews(state)
                        store.save_state(state)
                if any(run.get('status') == 'failed' for run in invoice.ai_runs):
                    job['warnings'].append({'filename': document['filename'], 'message': 'One or more AI calls failed. Local extraction/checks remain available; inspect the AI trace.'})
            except Exception as exc:
                message = str(exc) if isinstance(exc, ai.AIError) else f'Reprocessing failed ({type(exc).__name__}); original extraction retained.'
                job['errors'].append({'filename': document['filename'], 'message': message})
            job['completed'] += 1
        job['status'] = 'completed'
    except Exception:
        job['status'] = 'failed'
        job['errors'].append({'filename': job.get('current_file', ''), 'message': 'Reprocessing stopped unexpectedly; completed extractions were saved.'})
    finally:
        job['current_file'] = ''


@app.post('/api/ai/reprocess')
def start_ai_reprocess(request: ReprocessRequest):
    if not ai.enabled():
        raise HTTPException(400, 'Enable AI and save your OpenRouter key in AI models first.')
    with lock:
        if any(job['status'] == 'running' for job in jobs.values()):
            raise HTTPException(409, 'An AI reprocessing job is already running.')
        state = store.read_state()
        available = {d['id'] for d in state['documents'] if d['kind'] == 'invoice'}
        ids = list(dict.fromkeys(request.document_ids)) if request.document_ids is not None else [d['id'] for d in state['documents'] if d['kind'] == 'invoice']
        if not ids or not set(ids) <= available:
            raise HTTPException(400, 'Select one or more invoices that exist in this workspace.')
        job_id = str(uuid.uuid4())
        jobs[job_id] = {'id': job_id, 'status': 'running', 'total': len(ids), 'completed': 0, 'skipped': 0, 'current_file': '', 'errors': [], 'warnings': []}
        # Only retain bounded non-sensitive job metadata in memory.
        finished = [key for key, job in jobs.items() if job['status'] != 'running']
        for key in finished[:-20]:
            jobs.pop(key, None)
        threading.Thread(target=reprocess_worker, args=(job_id, ids), daemon=True).start()
        return dict(jobs[job_id])


@app.get('/api/ai/jobs/{job_id}')
def get_ai_job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404, 'AI job not found; the server may have restarted. Saved extractions remain available.')
    return copy.deepcopy(jobs[job_id])


@app.post('/api/reviews/{document_id}/semantic-confirmation')
def confirm_semantics(document_id: str, confirmation: SemanticConfirmation):
    with lock:
        state = store.read_state()
        cached = state['ai_matches'].get(document_id)
        current = next((r for r in state['reviews'] if r['id'] == document_id), None)
        current_match = (current or {}).get('ai_analysis', {}).get('matching') or {}
        if not cached or cached.get('analysis_key') != confirmation.analysis_key or current_match.get('analysis_key') != confirmation.analysis_key:
            raise HTTPException(409, 'The item proposal is stale. Rerun the review before confirming.')
        proposal = next((m for m in cached['matches'] if m['invoice_line'] == confirmation.invoice_line and m['po_line'] == confirmation.po_line and m['equivalence'] == 'equivalent'), None)
        if not proposal:
            raise HTTPException(400, 'There is no supported equivalence proposal for these lines.')
        state['semantic_confirmations'].setdefault(document_id, {})[f'{confirmation.analysis_key}:{confirmation.invoice_line}'] = confirmation.po_line
        audit(state, 'semantic_match_confirmed', f'Human confirmed invoice line {confirmation.invoice_line + 1} ↔ PO line {confirmation.po_line + 1}. {confirmation.note}', document_id)
        run_reviews(state)
        store.save_state(state)
    return workspace(state)


@app.post('/api/reviews/{document_id}/ai-brief')
def generate_ai_brief(document_id: str):
    with lock:
        state = store.read_state()
        review = next((r for r in state['reviews'] if r['id'] == document_id), None)
        if not review:
            raise HTTPException(404, 'Invoice review not found.')
        try:
            state['ai_briefs'][document_id] = review_brief(review)
        except ai.AIError as exc:
            raise HTTPException(502, str(exc)) from exc
        audit(state, 'ai_brief_generated', 'Generated an AI reviewer brief grounded in existing check IDs. Recommendation unchanged.', document_id)
        run_reviews(state)
        store.save_state(state)
    return workspace(state)


class DraftApproval(BaseModel):
    policy: Policy
    note: str = Field(min_length=5, max_length=1000)


class PurchaseOrderApproval(BaseModel):
    po: PurchaseOrder
    note: str = Field(min_length=5, max_length=1000)
    confirmed: Literal[True]


@app.post('/api/purchase-orders/drafts/{document_id}/approve')
def approve_po_draft(document_id: str, approval: PurchaseOrderApproval):
    with lock:
        state = store.read_state()
        draft = state['po_drafts'].get(document_id)
        source = next((d for d in state['documents'] if d['id'] == document_id and d['kind'] == 'purchase_orders'), None)
        if not draft or not source or not source.get('pending_interpretation'):
            raise HTTPException(404, 'Purchase-order draft not found.')
        try:
            po = validate_purchase_order(approval.po)
            if not po.status.strip():
                raise ValueError('Confirm the PO status, or enter unknown.')
            start = date.fromisoformat(po.valid_from) if po.valid_from else None
            end = date.fromisoformat(po.valid_to) if po.valid_to else None
            if start and end and start > end:
                raise ValueError('PO validity start must be on or before the end date.')
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if any(normalize(item['po_number']) == normalize(po.po_number) for item in state['purchase_orders']):
            raise HTTPException(409, f'Purchase order {po.po_number} already exists. Remove the earlier source before replacing it.')
        po.evidence = Evidence(document_id=document_id, filename=source['filename'],
                               excerpt=f'Human confirmed extracted PO. {approval.note}', method='human reviewed extraction')
        for line in po.items:
            line.evidence = Evidence(document_id=document_id, filename=source['filename'],
                                     excerpt=f'Human confirmed PO line: {line.description}; quantity {line.quantity}; unit price {line.unit_price}. {approval.note}',
                                     method='human reviewed extraction')
        record = po.model_dump(mode='json')
        state['purchase_orders'].append(record)
        state['po_drafts'].pop(document_id)
        source['pending_interpretation'] = False
        source['record_count'] = 1
        source['extracted'] = record
        audit(state, 'po_approved', f'Human confirmed purchase order {po.po_number} from {source["filename"]}. {approval.note}', document_id)
        run_reviews(state)
        store.save_state(state)
    return workspace(state)


@app.post('/api/ai/policy-drafts/{document_id}/approve')
def approve_policy_draft(document_id: str, approval: DraftApproval):
    with lock:
        state = store.read_state()
        draft = state['reference_drafts'].get(document_id)
        source = next((d for d in state['documents'] if d['id'] == document_id), None)
        if not draft or not source or draft['kind'] != 'policy':
            raise HTTPException(404, 'Policy draft not found.')
        policy = approval.policy
        policy.evidence = Evidence(document_id=document_id, filename=source['filename'], excerpt=f'Human approved AI policy interpretation. {approval.note}', method='AI proposal + human approved')
        state['policy'] = policy.model_dump(mode='json')
        state['reference_drafts'].pop(document_id)
        source['pending_interpretation'] = False
        source['record_count'] = 1
        audit(state, 'ai_policy_approved', f'Human reviewed and activated {policy.name}. {approval.note}', document_id)
        run_reviews(state)
        store.save_state(state)
    return workspace(state)


@app.get('/api/health')
def health():
    return {'status': 'ok', 'ai_configured': ai_configured()}


@app.get('/api/workspace')
def get_workspace():
    return workspace(store.read_state())


@app.post('/api/documents')
def upload_documents(kind: Literal['invoice', 'purchase_orders', 'vendors', 'history', 'policy'] = Form(...), files: list[UploadFile] = File(...)):
    if len(files) > 25:
        raise HTTPException(400, 'Upload at most 25 files at a time.')
    errors, accepted = [], []
    with lock:
        state = store.read_state()
        for file in files:
            try:
                data = file.file.read(MAX_BYTES + 1)
                document = ingest(state, kind, file.filename or 'document', data)
                accepted.append({'id': document['id'], 'filename': document['filename']})
            except (ValueError, ValidationError, UnicodeError, json.JSONDecodeError) as exc:
                errors.append({'filename': file.filename, 'message': str(exc)[:1500]})
            except Exception as exc:
                errors.append({'filename': file.filename, 'message': f'Could not parse this file ({type(exc).__name__}). Check its format and use a supplied template if needed.'})
            finally:
                file.file.close()
        if accepted:
            active_change = kind == 'invoice' or any(not next(d for d in state['documents'] if d['id'] == item['id']).get('pending_interpretation') for item in accepted)
            if active_change:
                run_reviews(state)
            audit(state, 'reviewed' if active_change else 'draft_created',
                  f'Recomputed {len(state["reviews"])} invoice recommendations after upload.' if active_change else 'Saved document drafts for human review; active references unchanged.')
            store.save_state(state)
    return {'accepted': accepted, 'errors': errors, 'workspace': workspace(state)}


@app.post('/api/review')
def review_all():
    with lock:
        state = store.read_state()
        run_reviews(state)
        audit(state, 'reviewed', f'Recomputed {len(state["reviews"])} invoice recommendations.')
        store.save_state(state)
    return workspace(state)


@app.get('/api/documents/{document_id}')
def get_document(document_id: str):
    document = next((d for d in store.read_state()['documents'] if d['id'] == document_id), None)
    if not document:
        raise HTTPException(404, 'Document not found.')
    return FileResponse(store.DATA / 'documents' / document['stored_name'], filename=document['filename'], content_disposition_type='inline')


@app.get('/api/documents/{document_id}/text')
def document_text(document_id: str):
    document = next((d for d in store.read_state()['documents'] if d['id'] == document_id), None)
    if not document:
        raise HTTPException(404, 'Document not found.')
    return {'filename': document['filename'], 'pages': document['pages'], 'notes': document['notes']}


@app.delete('/api/documents/{document_id}')
def remove_document(document_id: str):
    with lock:
        state = store.read_state()
        document = next((d for d in state['documents'] if d['id'] == document_id), None)
        if not document:
            raise HTTPException(404, 'Document not found.')
        state['documents'] = [d for d in state['documents'] if d['id'] != document_id]
        for kind in ('vendors', 'purchase_orders', 'history'):
            state[kind] = [r for r in state[kind] if r['evidence']['document_id'] != document_id]
        if state['policy']['evidence']['document_id'] == document_id:
            state['policy'] = Policy().model_dump(mode='json')
        state['corrections'].pop(document_id, None)
        state['resolutions'].pop(document_id, None)
        for key in ('ai_matches', 'semantic_confirmations', 'ai_briefs', 'reference_drafts', 'po_drafts'):
            state[key].pop(document_id, None)
        run_reviews(state)
        audit(state, 'removed', f'Removed {document["filename"]} and recomputed dependent recommendations.', document_id)
        store.save_state(state)
        (store.DATA / 'documents' / document['stored_name']).unlink(missing_ok=True)
    return workspace(state)


@app.put('/api/reviews/{document_id}/correction')
def correct_invoice(document_id: str, correction: Correction):
    with lock:
        state = store.read_state()
        document = next((d for d in state['documents'] if d['id'] == document_id and d['kind'] == 'invoice'), None)
        if not document:
            raise HTTPException(404, 'Invoice not found.')
        previous = state['corrections'].get(document_id, {}).get('invoice', document['extracted'])
        invoice = correction.invoice
        changed = [key for key, value in invoice.model_dump(mode='json').items() if key not in ('evidence', 'extraction_notes', 'extraction_method') and previous.get(key) != value]
        for key in changed:
            invoice.evidence[key] = Evidence(document_id=document_id, filename=document['filename'], excerpt=f'Human correction: {getattr(invoice, key)}. Reason: {correction.reason}', method='human verified')
        if 'items' in changed:
            for line in invoice.items:
                line.evidence = Evidence(document_id=document_id, filename=document['filename'], excerpt=f'Human-corrected line: {line.description}; quantity {line.quantity}, rate {line.unit_price}, amount {line.amount}. Reason: {correction.reason}', method='human verified')
        state['corrections'][document_id] = {'invoice': invoice.model_dump(mode='json'), 'reason': correction.reason, 'timestamp': datetime.now().astimezone().isoformat()}
        state['resolutions'].pop(document_id, None)
        audit(state, 'corrected', f'Human verified fields ({", ".join(changed) or "no changes"}). Reason: {correction.reason}', document_id)
        run_reviews(state)
        store.save_state(state)
    return workspace(state)


@app.post('/api/reviews/{document_id}/resolution')
def resolve_review(document_id: str, resolution: Resolution):
    with lock:
        state = store.read_state()
        review = next((r for r in state['reviews'] if r['id'] == document_id), None)
        if not review:
            raise HTTPException(404, 'Review not found.')
        if resolution.action == 'acknowledge' and review['decision'] != 'ready':
            raise HTTPException(409, 'Resolve the outstanding checks before acknowledging a ready recommendation.')
        item = resolution.model_dump() | {'timestamp': datetime.now().astimezone().isoformat(), 'decision_at_time': review['decision']}
        state['resolutions'][document_id] = item
        audit(state, 'reviewer_note', f'{resolution.action}: {resolution.note}', document_id)
        run_reviews(state)
        store.save_state(state)
    return workspace(state)


@app.put('/api/policy')
def update_policy(policy: Policy):
    with lock:
        state = store.read_state()
        policy.evidence = Evidence(filename='Workspace policy', excerpt=f'Human-configured policy: {policy.model_dump_json(exclude={"evidence"})}', method='human configured')
        state['policy'] = policy.model_dump(mode='json')
        audit(state, 'policy_changed', f'Updated {policy.name}; all recommendations recomputed.')
        run_reviews(state)
        store.save_state(state)
    return workspace(state)


@app.post('/api/demo')
def load_demo():
    with lock:
        state = store.read_state()
        if state['documents']:
            raise HTTPException(409, 'Load examples into an empty workspace. Clear this workspace first or download the sample documents to upload individually.')
        for kind, filename, data in demo.files():
            if kind != 'manifest':
                ingest(state, kind, filename, data)
        run_reviews(state)
        audit(state, 'demo_loaded', 'Loaded 13 synthetic invoices and supporting reference records.')
        store.save_state(state)
    return workspace(state)


@app.get('/api/samples')
def download_samples():
    return Response(demo.archive(), media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="invoices-synthetic-samples.zip"'})


@app.delete('/api/workspace')
def clear_workspace():
    with lock:
        state = store.read_state()
        for document in state['documents']:
            (store.DATA / 'documents' / document['stored_name']).unlink(missing_ok=True)
        state = store.initial_state()
        audit(state, 'workspace_cleared', 'Started an empty workspace.')
        store.save_state(state)
    return workspace(state)


@app.get('/api/export')
def export(format: Literal['json', 'csv'] = 'json'):
    state = store.read_state()
    if format == 'json':
        sources = [{k: v for k, v in document.items() if k != 'stored_name'} for document in state['documents']]
        payload = {'exported_at': datetime.now().astimezone().isoformat(), 'policy': state['policy'], 'purchase_orders': state['purchase_orders'], 'pending_po_drafts': state.get('po_drafts', {}), 'reviews': state['reviews'], 'source_documents': sources, 'human_corrections': state['corrections'], 'audit': state['audit'], 'note': 'Recommendations only. No approval, payment, or external communication was performed.'}
        return Response(json.dumps(payload, indent=2), media_type='application/json', headers={'Content-Disposition': 'attachment; filename="invoices-review-evidence.json"'})
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['invoice_number', 'vendor', 'currency', 'subtotal', 'tax', 'total', 'po_number', 'recommendation', 'issues', 'reviewed_at'])
    def safe_cell(value):
        value = str(value or '')
        return "'" + value if value.startswith(('=', '+', '-', '@', '\t', '\r')) else value
    for review in state['reviews']:
        inv = review['invoice']
        writer.writerow([safe_cell(v) for v in [inv['invoice_number'], inv['vendor_name'], inv['currency'], inv['subtotal'], inv['tax_amount'], inv['total'], inv['po_number'], review['decision'], ' | '.join(c['message'] for c in review['checks'] if c['route'] != 'ready'), review['reviewed_at']]])
    return Response(output.getvalue(), media_type='text/csv', headers={'Content-Disposition': 'attachment; filename="invoices-review-summary.csv"'})


@app.get('/api/templates/{kind}')
def template(kind: str):
    if kind not in ('vendors', 'purchase_orders', 'history', 'policy'):
        raise HTTPException(404, 'Template not found.')
    sample = next(data for category, _, data in demo.files(include_scan=False) if category == kind)
    return Response(sample, media_type='application/json', headers={'Content-Disposition': f'attachment; filename="{kind}-template.json"'})


DIST = Path(__file__).resolve().parents[2] / 'frontend' / 'dist'
if DIST.is_dir():
    app.mount('/', StaticFiles(directory=DIST, html=True), name='frontend')
