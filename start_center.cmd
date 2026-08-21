@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".env" (
  echo Missing .env. Copy central.env.example to .env and configure MySQL.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Missing virtual environment. Install Python, then run:
  echo python -m venv .venv
  echo .venv\Scripts\python -m pip install -r requirements-center.txt
  pause
  exit /b 1
)

".venv\Scripts\python.exe" tools\case_editor_server.py --host 0.0.0.0 --port 8765 --no-open
