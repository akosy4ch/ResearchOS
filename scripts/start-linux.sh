#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$APP_ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.11 or newer is required. Install Python 3 and run this launcher again." >&2
  exit 1
fi
if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "ResearchOS needs Python 3.11 or newer." >&2
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  echo "First run: creating the local Python environment..."
  python3 -m venv .venv
fi
if [[ ! -f .env ]]; then cp .env.example .env; fi
echo "Preparing ResearchOS dependencies..."
.venv/bin/python -m pip install -e .

if curl --silent --fail --max-time 1 http://127.0.0.1:8000/health | grep -Eq '"service"[[:space:]]*:[[:space:]]*"researchos"'; then
  echo "ResearchOS is already running at http://127.0.0.1:8000. Opening the existing app."
  if [[ "${RESEARCHOS_SKIP_BROWSER:-0}" != "1" ]] && command -v xdg-open >/dev/null 2>&1; then
    xdg-open http://127.0.0.1:8000 >/dev/null 2>&1 || true
  fi
  exit 0
fi

if command -v ollama >/dev/null 2>&1 && ! curl --silent --fail http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "Starting the Ollama service..."
  nohup ollama serve >/dev/null 2>&1 </dev/null &
  for _ in {1..20}; do
    curl --silent --fail http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
    sleep 1
  done
fi
if ! command -v ollama >/dev/null 2>&1; then
  echo "Ollama was not found. The app will run, but local model analysis needs a connected model server."
fi

echo "Starting ResearchOS at http://127.0.0.1:8000"
.venv/bin/researchos serve --host 127.0.0.1 --port 8000 &
SERVER_PID=$!
cleanup() {
  kill "$SERVER_PID" >/dev/null 2>&1 || true
  wait "$SERVER_PID" >/dev/null 2>&1 || true
}
trap cleanup INT TERM EXIT
READY=0
for _ in {1..90}; do
  if curl --silent --fail --max-time 1 http://127.0.0.1:8000/health | grep -Eq '"service"[[:space:]]*:[[:space:]]*"researchos"'; then READY=1; break; fi
  if ! kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    wait "$SERVER_PID" || true
    echo "Could not start ResearchOS. Port 8000 may be in use by another application." >&2
    exit 1
  fi
  sleep 1
done
if [[ "$READY" == "1" ]]; then
  echo "ResearchOS is ready. Press Control-C to stop it."
  if [[ "${RESEARCHOS_SKIP_BROWSER:-0}" != "1" ]] && command -v xdg-open >/dev/null 2>&1; then
    xdg-open http://127.0.0.1:8000 >/dev/null 2>&1 || true
  fi
else
  echo "The app is taking longer to start. Keep this window open and visit http://127.0.0.1:8000 when ready."
fi
wait "$SERVER_PID"
