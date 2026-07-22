#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 is required." >&2
  exit 1
fi

if [ ! -f .env ]; then
  cp central.env.example .env
  echo "Created .env. Fill in the MySQL connection before starting the service."
fi

if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-center.txt
echo "Installed. Configure .env, then start with ./start_center.sh."
