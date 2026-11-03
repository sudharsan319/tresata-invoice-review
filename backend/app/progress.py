"""Request-local progress hooks. No prompts, credentials, or raw responses are logged."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone

_sink = ContextVar('progress_sink', default=None)
_document = ContextVar('progress_document', default=None)


@contextmanager
def capture(sink):
    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)


@contextmanager
def document_scope(document_id, filename):
    token = _document.set((document_id, filename))
    try:
        yield
    finally:
        _document.reset(token)


def emit(stage, status, title, detail='', **data):
    sink, document = _sink.get(), _document.get()
    if sink and document:
        sink(document[0], {'timestamp': datetime.now(timezone.utc).isoformat(),
                          'stage': stage, 'status': status, 'title': title,
                          'detail': detail, **data})
