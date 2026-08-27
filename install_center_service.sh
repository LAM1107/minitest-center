#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="minitest-center"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_USER="${MINITEST_CENTER_USER:-${SUDO_USER:-root}}"
HOST="${MINITEST_CENTER_HOST:-127.0.0.1}"
PORT="${MINITEST_CENTER_PORT:-8765}"

usage() {
  cat <<'EOF'
Usage:
  sudo ./install_center_service.sh [--host 127.0.0.1|0.0.0.0] [--port 8765] [--user username]

Examples:
  # Nginx/Caddy reverse proxy (recommended)
  sudo ./install_center_service.sh

  # Direct access through http://server-ip:8765
  sudo ./install_center_service.sh --host 0.0.0.0
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --host)
      if [ "$#" -lt 2 ]; then
        echo "Missing value for --host." >&2
        exit 1
      fi
      HOST="$2"
      shift 2
      ;;
    --port)
      if [ "$#" -lt 2 ]; then
        echo "Missing value for --port." >&2
        exit 1
      fi
      PORT="$2"
      shift 2
      ;;
    --user)
      if [ "$#" -lt 2 ]; then
        echo "Missing value for --user." >&2
        exit 1
      fi
      SERVICE_USER="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this installer with sudo." >&2
  exit 1
fi

if [ "$HOST" != "127.0.0.1" ] && [ "$HOST" != "0.0.0.0" ]; then
  echo "--host must be 127.0.0.1 or 0.0.0.0." >&2
  exit 1
fi

if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
  echo "--port must be an integer between 1 and 65535." >&2
  exit 1
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  echo "Linux user does not exist: $SERVICE_USER" >&2
  exit 1
fi

if [[ "$PROJECT_DIR" =~ [[:space:]] ]]; then
  echo "The project path cannot contain spaces: $PROJECT_DIR" >&2
  exit 1
fi

if [ ! -f "$PROJECT_DIR/.env" ]; then
  echo "Missing $PROJECT_DIR/.env. Run ./install_center.sh and configure .env first." >&2
  exit 1
fi

if [ ! -x "$PROJECT_DIR/.venv/bin/python" ]; then
  echo "Missing $PROJECT_DIR/.venv/bin/python. Run ./install_center.sh first." >&2
  exit 1
fi

cat >"$SERVICE_FILE" <<EOF
[Unit]
Description=Minitest Center Service
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$PROJECT_DIR/.venv/bin/python $PROJECT_DIR/tools/case_editor_server.py --host $HOST --port $PORT --no-open
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo
echo "Installed and started: $SERVICE_FILE"
echo "Service user: $SERVICE_USER"
echo "Listening on: $HOST:$PORT"
echo
echo "Status: sudo systemctl status $SERVICE_NAME"
echo "Logs:   journalctl -u $SERVICE_NAME -f"
