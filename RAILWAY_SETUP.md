# Railway Deployment Setup

## Quick Setup

### 1. Create a New Project on Railway

1. Go to [railway.app](https://railway.app) and create a new project
2. Connect your GitHub repository

### 2. Add Redis Service

1. Click **"+ New"** → **"Database"** → **"Add Redis"**
2. Railway will provision a Redis instance

### 3. Create Web Service

1. Click **"+ New"** → **"GitHub Repo"** → Select this repo
2. In service settings:
   - **Start Command**: `uvicorn api:app --host 0.0.0.0 --port $PORT`
3. Add environment variables:
   ```
   CELERY_BROKER_URL=${{Redis.REDIS_URL}}
   CELERY_RESULT_BACKEND=${{Redis.REDIS_URL}}
   UPLOAD_DIR=/tmp/uploads
   OUTPUT_DIR=/tmp/outputs
   ```

### 4. Create Worker Service

1. Click **"+ New"** → **"GitHub Repo"** → Select this repo again
2. In service settings:
   - **Start Command**: `celery -A tasks worker --loglevel=info --concurrency=1`
3. Add the same environment variables:
   ```
   CELERY_BROKER_URL=${{Redis.REDIS_URL}}
   CELERY_RESULT_BACKEND=${{Redis.REDIS_URL}}
   UPLOAD_DIR=/tmp/uploads
   OUTPUT_DIR=/tmp/outputs
   ```

### 5. Deploy

Both services will automatically deploy when you push to your repository.

---

## API Usage

### Upload a Video

```bash
curl -X POST "https://your-app.railway.app/process" \
  -F "file=@video.mp4" \
  -F "webhook_url=https://your-webhook.com/callback"
```

Response:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "message": "Video queued for processing"
}
```

### Check Status

```bash
curl "https://your-app.railway.app/status/{job_id}"
```

Response:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "processing",
  "progress": {
    "step": 3,
    "progress": 45,
    "message": "Processed 450/1000 frames",
    "total_steps": 5
  }
}
```

### Download Result

```bash
curl "https://your-app.railway.app/download/{job_id}" -o output.mp4
```

### Webhook Payload

When processing completes, your webhook will receive:

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "result": {
    "output_file": "/tmp/outputs/550e8400_output.mp4",
    "scenes_detected": 5,
    "total_frames": 1500,
    "processing_time": 12.5,
    "output_resolution": "360x640"
  }
}
```

On failure:
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "failed",
  "error": "Error message"
}
```

---

## Important Notes

- **Storage**: Railway uses ephemeral storage. Processed videos are stored temporarily. Download or use webhook to save results promptly.
- **Memory**: Video processing is memory-intensive. Consider Railway's Pro plan for larger videos.
- **Concurrency**: Worker is set to 1 concurrent task to manage memory. Scale by adding more worker instances.
- **FFmpeg**: Installed automatically via nixpacks.toml configuration.
