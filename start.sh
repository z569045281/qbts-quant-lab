#!/usr/bin/env bash
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"

# Backend
echo "Starting FastAPI backend on :8000..."
cd "$ROOT"
.venv/bin/uvicorn backend.api:app --reload --port 8000 &
BACKEND_PID=$!

# Frontend
echo "Starting Next.js frontend on :3000..."
cd "$ROOT/frontend"
npm run dev &
FRONTEND_PID=$!

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT INT TERM
echo ""
echo "  Backend : http://localhost:8000"
echo "  Frontend: http://localhost:3000"
echo ""
wait
