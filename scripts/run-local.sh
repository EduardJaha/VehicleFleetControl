#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

osascript -e "tell application \"Terminal\" to do script \"cd '$ROOT_DIR/backend' && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000\"" 2>/dev/null || \
  (cd "$ROOT_DIR/backend" && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000) &

osascript -e "tell application \"Terminal\" to do script \"cd '$ROOT_DIR/frontend' && npm install && npm run dev\"" 2>/dev/null || \
  (cd "$ROOT_DIR/frontend" && npm install && npm run dev) &
