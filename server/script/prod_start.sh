#!/bin/bash
# Production startup script

set -e

echo "=================================="
echo "🚀 Starting AI Server (Production)"
echo "=================================="

# Check if models exist
if [ ! -d "models" ] || [ -z "$(ls -A models)" ]; then
    echo "📦 Models not found. Downloading..."
    python scripts/download_models.py
else
    echo "✅ Models already downloaded"
fi

echo "=================================="
echo "🔥 Starting server with Uvicorn"
echo "=================================="

# Start server with appropriate settings
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port ${PORT:-8000} \
    --workers ${WORKERS:-4} \
    --loop uvloop \
    --log-level info