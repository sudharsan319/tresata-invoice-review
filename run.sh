#!/usr/bin/env bash
set -euo pipefail
AP_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$AP_ROOT"

if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo 'Node.js 20.19+ (or 22.12+) and npm are required.' >&2
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo 'Python 3.11+ is required.' >&2
  exit 1
fi
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
AP_REQUIREMENTS_HASH="$(sha256sum backend/requirements.lock.txt | cut -d' ' -f1)"
if [[ ! -f .venv/.requirements-hash ]] || [[ "$(cat .venv/.requirements-hash)" != "$AP_REQUIREMENTS_HASH" ]]; then
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python .venv/bin/python -r backend/requirements.lock.txt
  else
    .venv/bin/python -m pip install -r backend/requirements.lock.txt
  fi
  echo "$AP_REQUIREMENTS_HASH" > .venv/.requirements-hash
fi
AP_FRONTEND_HASH="$(sha256sum frontend/package-lock.json | cut -d' ' -f1)"
if [[ ! -d frontend/node_modules ]] || [[ ! -f frontend/node_modules/.dependencies-hash ]] || [[ "$(cat frontend/node_modules/.dependencies-hash)" != "$AP_FRONTEND_HASH" ]]; then
  (cd frontend && npm ci --no-audit --no-fund)
  echo "$AP_FRONTEND_HASH" > frontend/node_modules/.dependencies-hash
fi

# Optional AI configuration stays outside source control.
if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi
export PYTHONPATH="$AP_ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"
if [[ "${1:-}" == '--dev' ]]; then
  echo 'Invoices: http://127.0.0.1:5173  |  API docs: http://127.0.0.1:8000/docs'
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload &
  AP_BACKEND_PID=$!
  (cd frontend && exec node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort) &
  AP_FRONTEND_PID=$!
  trap 'kill "$AP_BACKEND_PID" "$AP_FRONTEND_PID" 2>/dev/null || true; wait 2>/dev/null || true' EXIT INT TERM
  wait -n "$AP_BACKEND_PID" "$AP_FRONTEND_PID"
else
  (cd frontend && npm run build)
  echo 'Invoices is starting at http://127.0.0.1:8000'
  echo 'Press Ctrl+C to stop. Uploaded data is saved in ap-review/data/.'
  exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
fi
