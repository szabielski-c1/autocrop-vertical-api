#!/bin/bash

# Cleanup function to kill background processes on exit
cleanup() {
    echo ""
    echo "Shutting down..."
    if [ ! -z "$CELERY_PID" ]; then
        kill $CELERY_PID 2>/dev/null
    fi
    if [ ! -z "$REDIS_PID" ]; then
        kill $REDIS_PID 2>/dev/null
    fi
    exit 0
}

trap cleanup SIGINT SIGTERM

# Check if Redis is already running
if ! pgrep -x "redis-server" > /dev/null; then
    echo "Starting Redis..."
    redis-server &
    REDIS_PID=$!
    sleep 1
else
    echo "Redis already running"
fi

# Set up virtual environment paths
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

if [ -d "$VENV_DIR" ]; then
    CELERY_CMD="$VENV_DIR/bin/celery"
    UVICORN_CMD="$VENV_DIR/bin/uvicorn"
else
    CELERY_CMD="celery"
    UVICORN_CMD="uvicorn"
fi

# Check if Celery is already running
if ! pgrep -f "celery.*tasks.*worker" > /dev/null; then
    echo "Starting Celery worker..."
    $CELERY_CMD -A tasks worker --loglevel=info --pool=solo &
    CELERY_PID=$!
    sleep 2
else
    echo "Celery worker already running"
fi

# Check if API is already running
if ! pgrep -f "uvicorn.*api:app" > /dev/null; then
    echo "Starting API on http://localhost:8000"
    echo "Press Ctrl+C to stop all services"
    echo ""
    $UVICORN_CMD api:app --reload --port 8000 --reload-exclude '.venv'
else
    echo "API already running on http://localhost:8000"
    echo "All services are running!"
fi
