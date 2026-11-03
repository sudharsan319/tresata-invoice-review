import json
import os
import sqlite3
from pathlib import Path
from .models import Policy

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.getenv('AP_DATA_DIR', str(ROOT / 'data')))


def initial_state():
    return {'documents': [], 'vendors': [], 'purchase_orders': [], 'po_drafts': {}, 'history': [], 'reviews': [], 'corrections': {}, 'resolutions': {}, 'audit': [], 'policy': Policy().model_dump(mode='json'), 'revision': 0, 'ai_matches': {}, 'semantic_confirmations': {}, 'ai_briefs': {}, 'reference_drafts': {}}


def connection():
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / 'documents').mkdir(exist_ok=True)
    db = sqlite3.connect(DATA / 'workspace.sqlite', timeout=30)
    db.execute('CREATE TABLE IF NOT EXISTS workspace (id INTEGER PRIMARY KEY, content TEXT NOT NULL)')
    return db


def read_state():
    with connection() as db:
        row = db.execute('SELECT content FROM workspace WHERE id=1').fetchone()
    state = json.loads(row[0]) if row else initial_state()
    for key in ('ai_matches', 'semantic_confirmations', 'ai_briefs', 'reference_drafts', 'po_drafts'):
        state.setdefault(key, {})
    return state


def save_state(state):
    state['revision'] = state.get('revision', 0) + 1
    with connection() as db:
        db.execute('INSERT INTO workspace (id, content) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET content=excluded.content', (json.dumps(state),))
