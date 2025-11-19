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

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Check if Celery is already running
if ! pgrep -f "celery.*tasks.*worker" > /dev/null; then
    echo "Starting Celery worker..."
    celery -A tasks worker --loglevel=info &
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
    uvicorn api:app --reload --port 8000
else
    echo "API already running on http://localhost:8000"
    echo "All services are running!"
fi
