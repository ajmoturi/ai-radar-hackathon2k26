#!/usr/bin/env bash
# Start Frontier AI Radar (backend + frontend)
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

# Load .env if present
if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

echo "====================================="
echo "  Frontier AI Radar — Starting up"
echo "====================================="

# 1. Install system libraries required by WeasyPrint (PDF rendering)
if [[ "$OSTYPE" == "darwin"* ]]; then
  if ! brew list pango &>/dev/null; then
    echo "Installing WeasyPrint system dependencies via Homebrew..."
    brew install pango cairo libffi gdk-pixbuf
  fi
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
  if ! dpkg -s libpango-1.0-0 &>/dev/null 2>&1; then
    echo "Installing WeasyPrint system dependencies via apt..."
    sudo apt-get install -y libpango-1.0-0 libpangocairo-1.0-0 \
      libcairo2 libgdk-pixbuf2.0-0 libffi-dev shared-mime-info
  fi
fi

# 2. Install Python deps (if needed)
if ! python3 -c "import fastapi" 2>/dev/null; then
  echo "Installing Python dependencies..."
  cd "$ROOT"
  pip install -e ".[dev]"
fi

# 3. Start FastAPI backend
echo "Starting FastAPI backend on :8000..."
cd "$ROOT"
# WeasyPrint needs Homebrew libs on macOS (libgobject, libpango, etc.)
export DYLD_LIBRARY_PATH="/opt/homebrew/lib:${DYLD_LIBRARY_PATH:-}"
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

# 4. Start Next.js frontend
echo "Starting Next.js frontend on :3000..."
cd "$ROOT/frontend"
npm run dev &
FRONTEND_PID=$!

echo ""
echo "Backend:   http://localhost:8000"
echo "Frontend:  http://localhost:3000"
echo "API docs:  http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop."

cleanup() {
  echo "Shutting down..."
  kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
}
trap cleanup EXIT INT TERM
wait
