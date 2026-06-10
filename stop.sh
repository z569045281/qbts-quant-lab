#!/usr/bin/env bash
echo "Stopping backend (port 8000) and frontend (port 3000)..."
kill -9 $(lsof -ti :8000) 2>/dev/null && echo "  ✓ Backend stopped" || echo "  – Backend not running"
kill -9 $(lsof -ti :3000) 2>/dev/null && echo "  ✓ Frontend stopped" || echo "  – Frontend not running"
