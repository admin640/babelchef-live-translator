#!/bin/bash
set -e

# Disable python output buffering so logs show up in Cloud Run
export PYTHONUNBUFFERED=1

echo "Starting BabelChef (ADK Bidi Streaming)..."

# Single process — ADK runs inside FastAPI (no worker subprocess needed)
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
