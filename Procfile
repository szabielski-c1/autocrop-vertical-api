web: uvicorn api:app --host 0.0.0.0 --port $PORT
worker: celery -A tasks worker --loglevel=info --concurrency=1
