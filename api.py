import os
import uuid
import shutil
import tempfile
import requests
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from typing import Optional
from celery.result import AsyncResult

from tasks import celery_app, process_video_task, get_job_progress
import s3_storage

app = FastAPI(
    title="AutoCrop-Vertical API",
    description="Convert horizontal videos to vertical format for social media",
    version="1.0.0"
)

# Enable CORS for frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Local temp directory for processing
TEMP_DIR = Path(tempfile.gettempdir()) / "autocrop"
TEMP_DIR.mkdir(exist_ok=True)


class ProcessRequest(BaseModel):
    webhook_url: Optional[HttpUrl] = None


class JobResponse(BaseModel):
    job_id: str
    status: str
    message: str


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    progress: Optional[dict] = None
    result: Optional[dict] = None
    error: Optional[str] = None


class ProcessUrlRequest(BaseModel):
    url: HttpUrl
    webhook_url: Optional[HttpUrl] = None


@app.post("/process", response_model=JobResponse)
async def process_video_endpoint(
    file: UploadFile = File(...),
    webhook_url: Optional[str] = None
):
    """
    Upload a video for processing.

    Returns a job_id that can be used to check status and download the result.
    Optionally provide a webhook_url to receive results when processing completes.
    """
    # Validate file type
    if not file.filename.lower().endswith(('.mp4', '.mov', '.avi', '.mkv', '.webm')):
        raise HTTPException(status_code=400, detail="Invalid file type. Supported: mp4, mov, avi, mkv, webm")

    # Generate unique job ID
    job_id = str(uuid.uuid4())

    # Define S3 keys
    ext = Path(file.filename).suffix
    input_s3_key = f"inputs/{job_id}_input{ext}"
    output_s3_key = f"outputs/{job_id}_output.mp4"

    # Save to temp file first
    temp_input = TEMP_DIR / f"{job_id}_input{ext}"

    try:
        with open(temp_input, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Upload to S3
        if not s3_storage.upload_file(str(temp_input), input_s3_key):
            raise HTTPException(status_code=500, detail="Failed to upload file to S3")

        # Clean up temp file
        temp_input.unlink()

    except Exception as e:
        if temp_input.exists():
            temp_input.unlink()
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    # Queue the processing task with S3 keys
    task = process_video_task.apply_async(
        args=[input_s3_key, output_s3_key, webhook_url],
        task_id=job_id
    )

    return JobResponse(
        job_id=job_id,
        status="queued",
        message="Video queued for processing"
    )


@app.post("/process-url", response_model=JobResponse)
async def process_video_from_url(request: ProcessUrlRequest):
    """
    Process a video from a URL (e.g., S3, cloud storage).

    Downloads the video from the provided URL and queues it for processing.
    Optionally provide a webhook_url to receive results when processing completes.
    """
    # Parse URL to get filename and extension
    parsed_url = urlparse(str(request.url))
    url_path = parsed_url.path

    # Try to get extension from URL path
    ext = Path(url_path).suffix.lower()
    if ext not in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
        # Default to .mp4 if we can't determine extension
        ext = '.mp4'

    # Generate unique job ID
    job_id = str(uuid.uuid4())

    # Define S3 keys
    input_s3_key = f"inputs/{job_id}_input{ext}"
    output_s3_key = f"outputs/{job_id}_output.mp4"

    # Download file from URL to temp
    temp_input = TEMP_DIR / f"{job_id}_input{ext}"

    try:
        response = requests.get(str(request.url), stream=True, timeout=300)
        response.raise_for_status()

        with open(temp_input, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        # Upload to S3
        if not s3_storage.upload_file(str(temp_input), input_s3_key):
            raise HTTPException(status_code=500, detail="Failed to upload file to S3")

        # Clean up temp file
        temp_input.unlink()

    except requests.exceptions.RequestException as e:
        if temp_input.exists():
            temp_input.unlink()
        raise HTTPException(status_code=400, detail=f"Failed to download video: {str(e)}")

    # Queue the processing task
    webhook_url = str(request.webhook_url) if request.webhook_url else None
    task = process_video_task.apply_async(
        args=[input_s3_key, output_s3_key, webhook_url],
        task_id=job_id
    )

    return JobResponse(
        job_id=job_id,
        status="queued",
        message="Video downloaded and queued for processing"
    )


@app.get("/status/{job_id}", response_model=JobStatusResponse)
async def get_status(job_id: str):
    """
    Get the status of a processing job.
    """
    task_result = AsyncResult(job_id, app=celery_app)

    if task_result.state == 'PENDING':
        # Task hasn't started yet
        return JobStatusResponse(
            job_id=job_id,
            status="pending",
            progress={"message": "Waiting in queue..."}
        )

    elif task_result.state == 'PROCESSING':
        # Task is running
        progress = get_job_progress(job_id)
        return JobStatusResponse(
            job_id=job_id,
            status="processing",
            progress=progress or task_result.info
        )

    elif task_result.state == 'SUCCESS':
        # Task completed
        return JobStatusResponse(
            job_id=job_id,
            status="completed",
            result=task_result.result
        )

    elif task_result.state == 'FAILURE':
        # Task failed
        return JobStatusResponse(
            job_id=job_id,
            status="failed",
            error=str(task_result.info)
        )

    else:
        return JobStatusResponse(
            job_id=job_id,
            status=task_result.state.lower()
        )


@app.get("/download/{job_id}")
async def download_result(job_id: str):
    """
    Download the processed video via presigned S3 URL.
    """
    # Check if job is complete
    task_result = AsyncResult(job_id, app=celery_app)

    if task_result.state != 'SUCCESS':
        raise HTTPException(
            status_code=400,
            detail=f"Job not complete. Current status: {task_result.state}"
        )

    # Generate presigned URL for output
    output_s3_key = f"outputs/{job_id}_output.mp4"

    if not s3_storage.file_exists(output_s3_key):
        raise HTTPException(status_code=404, detail="Output file not found")

    # Redirect to presigned URL (1 hour expiry)
    presigned_url = s3_storage.generate_presigned_url(output_s3_key, expiration=3600)

    if not presigned_url:
        raise HTTPException(status_code=500, detail="Failed to generate download URL")

    return RedirectResponse(url=presigned_url)


@app.post("/retry/{job_id}")
async def retry_job(job_id: str, webhook_url: Optional[str] = None):
    """
    Retry a failed job by re-queuing it with the same input file.
    """
    # Find the input file in S3
    input_s3_key = None
    for ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
        potential_key = f"inputs/{job_id}_input{ext}"
        if s3_storage.file_exists(potential_key):
            input_s3_key = potential_key
            break

    if not input_s3_key:
        raise HTTPException(status_code=404, detail="Input file not found. Cannot retry.")

    # Generate new job ID
    new_job_id = str(uuid.uuid4())

    # Copy input to new key in S3
    ext = Path(input_s3_key).suffix
    new_input_s3_key = f"inputs/{new_job_id}_input{ext}"
    output_s3_key = f"outputs/{new_job_id}_output.mp4"

    # Download old input and re-upload with new key
    temp_file = TEMP_DIR / f"{new_job_id}_temp{ext}"
    try:
        s3_storage.download_file(input_s3_key, str(temp_file))
        s3_storage.upload_file(str(temp_file), new_input_s3_key)
        temp_file.unlink()
    except Exception as e:
        if temp_file.exists():
            temp_file.unlink()
        raise HTTPException(status_code=500, detail=f"Failed to copy input file: {str(e)}")

    # Queue the processing task
    task = process_video_task.apply_async(
        args=[new_input_s3_key, output_s3_key, webhook_url],
        task_id=new_job_id
    )

    return JobResponse(
        job_id=new_job_id,
        status="queued",
        message="Job re-queued for processing"
    )


@app.delete("/job/{job_id}")
async def delete_job(job_id: str):
    """
    Delete a job and its associated files.
    """
    # Remove input file from S3
    for ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
        input_key = f"inputs/{job_id}_input{ext}"
        s3_storage.delete_file(input_key)

    # Remove output file from S3
    output_key = f"outputs/{job_id}_output.mp4"
    s3_storage.delete_file(output_key)

    # Revoke task if still pending
    celery_app.control.revoke(job_id, terminate=True)

    return {"message": f"Job {job_id} deleted"}


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
