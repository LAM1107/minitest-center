#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "Missing .env. Copy central.env.example to .env and configure MySQL." >&2
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "Missing virtual environment. Run ./install_center.sh first." >&2
  exit 1
fi

exec .venv/bin/python tools/case_editor_server.py --host 127.0.0.1 --port 8765 --no-open
