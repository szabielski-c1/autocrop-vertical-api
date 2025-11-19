# AutoCrop-Vertical API Documentation

Convert horizontal videos to vertical (9:16) format optimized for social media.

## Base URL

```
https://your-api-domain.com
```

## Authentication

No authentication required (CORS enabled for all origins).

---

## Endpoints

### 1. Process Video

Upload a video for processing.

**POST** `/process`

**Request:**
- Content-Type: `multipart/form-data`
- Body:
  - `file` (required): Video file (mp4, mov, avi, mkv, webm)
  - `webhook_url` (optional): URL to receive completion notification

**Example:**
```bash
curl -X POST "https://api.example.com/process" \
  -F "file=@video.mp4" \
  -F "webhook_url=https://your-app.com/webhook"
```

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "message": "Video queued for processing"
}
```

---

### 2. Process Video from URL

Process a video from a URL (e.g., S3, cloud storage).

**POST** `/process-url`

**Request:**
- Content-Type: `application/json`
- Body:
  - `url` (required): URL to video file
  - `webhook_url` (optional): URL to receive completion notification

**Example:**
```bash
curl -X POST "https://api.example.com/process-url" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://s3.amazonaws.com/bucket/video.mp4",
    "webhook_url": "https://your-app.com/webhook"
  }'
```

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "message": "Video downloaded and queued for processing"
}
```

---

### 3. Check Status

Get the current status of a processing job.

**GET** `/status/{job_id}`

**Example:**
```bash
curl "https://api.example.com/status/550e8400-e29b-41d4-a716-446655440000"
```

**Response (pending):**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "progress": {
    "message": "Waiting in queue..."
  }
}
```

**Response (processing):**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "processing",
  "progress": {
    "step": 3,
    "progress": 45,
    "message": "Processing video frames...",
    "total_steps": 5
  }
}
```

**Response (completed):**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "result": {
    "output_file": "/outputs/550e8400-e29b-41d4-a716-446655440000_output.mp4",
    "scenes_detected": 12,
    "total_frames": 3600,
    "processing_time": 45.2,
    "output_resolution": "608x1080"
  }
}
```

**Response (failed):**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "failed",
  "error": "Error message describing what went wrong"
}
```

---

### 3. Download Result

Download the processed vertical video.

**GET** `/download/{job_id}`

**Example:**
```bash
curl -O "https://api.example.com/download/550e8400-e29b-41d4-a716-446655440000"
```

**Response:**
- Content-Type: `video/mp4`
- Filename: `vertical_{job_id}.mp4`

**Error (job not complete):**
```json
{
  "detail": "Job not complete. Current status: PROCESSING"
}
```

---

### 4. Retry Failed Job

Re-queue a failed job using the original input file.

**POST** `/retry/{job_id}`

**Query Parameters:**
- `webhook_url` (optional): URL to receive completion notification

**Example:**
```bash
curl -X POST "https://api.example.com/retry/550e8400-e29b-41d4-a716-446655440000?webhook_url=https://your-app.com/webhook"
```

**Response:**
```json
{
  "job_id": "661f9511-f30c-52e5-b827-557766551111",
  "status": "queued",
  "message": "Job re-queued for processing"
}
```

Note: Returns a **new job_id** for the retried job.

---

### 5. Delete Job

Delete a job and its associated files.

**DELETE** `/job/{job_id}`

**Example:**
```bash
curl -X DELETE "https://api.example.com/job/550e8400-e29b-41d4-a716-446655440000"
```

**Response:**
```json
{
  "message": "Job 550e8400-e29b-41d4-a716-446655440000 deleted"
}
```

---

### 6. Health Check

Check if the API is running.

**GET** `/health`

**Response:**
```json
{
  "status": "healthy"
}
```

---

## Webhooks

When you provide a `webhook_url`, the API will POST to that URL when processing completes (success or failure).

### Webhook Payload (Success)

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "result": {
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "completed",
    "output_file": "/outputs/550e8400-e29b-41d4-a716-446655440000_output.mp4",
    "scenes_detected": 12,
    "total_frames": 3600,
    "processing_time": 45.2,
    "output_resolution": "608x1080",
    "webhook_sent": true,
    "webhook_status": 200
  }
}
```

### Webhook Payload (Failure)

```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "failed",
  "error": "Error message describing what went wrong"
}
```

### Webhook Implementation Example

Your webhook endpoint should:
1. Accept POST requests with JSON body
2. Return a 2xx status code to acknowledge receipt
3. Handle both success and failure payloads

**Node.js/Express Example:**
```javascript
app.post('/webhook', (req, res) => {
  const { job_id, status, result, error } = req.body;

  if (status === 'completed') {
    // Download the processed video
    const downloadUrl = `https://api.example.com/download/${job_id}`;
    // Process the result...
  } else if (status === 'failed') {
    // Handle the error
    console.error(`Job ${job_id} failed: ${error}`);
  }

  res.status(200).send('OK');
});
```

**Python/Flask Example:**
```python
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    job_id = data['job_id']
    status = data['status']

    if status == 'completed':
        # Download the processed video
        download_url = f"https://api.example.com/download/{job_id}"
        # Process the result...
    elif status == 'failed':
        # Handle the error
        error = data.get('error')
        print(f"Job {job_id} failed: {error}")

    return 'OK', 200
```

---

## Typical Workflow

### Without Webhook (Polling)

1. **Upload video:**
   ```bash
   POST /process
   # Returns job_id
   ```

2. **Poll for status:**
   ```bash
   GET /status/{job_id}
   # Repeat every 2-5 seconds until status is "completed" or "failed"
   ```

3. **Download result:**
   ```bash
   GET /download/{job_id}
   ```

### With Webhook (Recommended)

1. **Upload video with webhook URL:**
   ```bash
   POST /process
   # Include webhook_url parameter
   ```

2. **Wait for webhook callback**
   - Your endpoint receives POST when complete

3. **Download result:**
   ```bash
   GET /download/{job_id}
   ```

---

## Processing Steps

The API processes videos in 5 steps:

1. **Scene Detection** - Analyzes video for scene changes
2. **Content Analysis** - Detects people and faces in each scene
3. **Frame Processing** - Crops/letterboxes each frame to 9:16
4. **Audio Extraction** - Extracts audio from original video
5. **Final Merge** - Combines processed video with audio

---

## Error Codes

| Status Code | Description |
|-------------|-------------|
| 200 | Success |
| 400 | Bad request (invalid file type, job not complete) |
| 404 | Job or file not found |
| 500 | Server error |

---

## File Size Limits

- Maximum file size depends on server configuration
- Recommended: Keep videos under 500MB for optimal processing

## Supported Formats

**Input:** mp4, mov, avi, mkv, webm

**Output:** mp4 (H.264)
