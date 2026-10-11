#!/bin/zsh
set -u
setopt NO_BG_NICE
cd "${0:A:h}"

pause_on_error() {
  echo
  read "?Press Return to close..."
  exit 1
}

python_is_supported() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1
}

PYTHON_BIN=""
if [[ -x ".venv/bin/python" ]] && python_is_supported ".venv/bin/python"; then
  PYTHON_BIN=".venv/bin/python"
else
  for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
    candidate_path="$(command -v "$candidate" 2>/dev/null || true)"
    if [[ -n "$candidate_path" ]] && python_is_supported "$candidate_path"; then
      PYTHON_BIN="$candidate_path"
      break
    fi
  done
fi

if [[ -z "$PYTHON_BIN" ]]; then
  echo "Python 3.11 or newer is required. Install it from python.org or with Homebrew, then try again."
  pause_on_error
fi
PYTHON_VERSION="$("$PYTHON_BIN" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "$PYTHON_BIN" != ".venv/bin/python" ]]; then
  if [[ -x ".venv/bin/python" ]]; then
    echo "Replacing the old private Python environment with Python $PYTHON_VERSION..."
    "$PYTHON_BIN" -m venv --clear .venv || pause_on_error
  else
    echo "First run: creating the private Python environment with Python $PYTHON_VERSION..."
    "$PYTHON_BIN" -m venv .venv || pause_on_error
  fi
fi
if [[ ! -f ".env" ]]; then cp .env.example .env; fi
if [[ -x ".venv/bin/researchos" ]] && .venv/bin/researchos --help >/dev/null 2>&1 && .venv/bin/python -m pip check >/dev/null 2>&1; then
  echo "ResearchOS and its dependencies are ready."
else
  echo "Preparing ResearchOS dependencies..."
  .venv/bin/python -m pip install -e . || pause_on_error
fi

if /usr/bin/curl --silent --fail --max-time 1 http://127.0.0.1:8000/health | /usr/bin/grep -Eq '"service"[[:space:]]*:[[:space:]]*"researchos"'; then
  echo "ResearchOS is already running at http://127.0.0.1:8000. Opening the existing app."
  if [[ "${RESEARCHOS_SKIP_BROWSER:-0}" != "1" ]]; then /usr/bin/open http://127.0.0.1:8000; fi
  exit 0
fi

OLLAMA_BIN="$(command -v ollama 2>/dev/null || true)"
if [[ -z "$OLLAMA_BIN" && -x "/opt/homebrew/bin/ollama" ]]; then
  OLLAMA_BIN="/opt/homebrew/bin/ollama"
fi
if [[ -n "$OLLAMA_BIN" ]] && ! /usr/bin/curl --silent --fail http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "Starting the Ollama service..."
  nohup "$OLLAMA_BIN" serve >/dev/null 2>&1 </dev/null &
  for attempt in {1..20}; do
    /usr/bin/curl --silent --fail http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
    sleep 1
  done
fi
if [[ -z "$OLLAMA_BIN" ]]; then
  echo "Ollama was not found. The app will still run; local model analysis will be unavailable until you connect a model server."
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
for attempt in {1..90}; do
  if /usr/bin/curl --silent --fail --max-time 1 http://127.0.0.1:8000/health | /usr/bin/grep -Eq '"service"[[:space:]]*:[[:space:]]*"researchos"'; then
    READY=1
    break
  fi
  if ! kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    wait "$SERVER_PID"
    pause_on_error
  fi
  sleep 1
done
if [[ "$READY" == "1" ]]; then
  echo "ResearchOS is ready. Press Control-C in this window to stop it."
  if [[ "${RESEARCHOS_SKIP_BROWSER:-0}" != "1" ]]; then
    /usr/bin/open http://127.0.0.1:8000
  fi
else
  echo "The app is taking longer to start. Keep this window open and visit http://127.0.0.1:8000 when it is ready."
fi
wait "$SERVER_PID"
