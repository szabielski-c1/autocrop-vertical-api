import os
import uuid
import shutil
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from typing import Optional
from celery.result import AsyncResult

from tasks import celery_app, process_video_task, get_job_progress

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

# Configure upload/output directories
UPLOAD_DIR = Path(os.getenv('UPLOAD_DIR', './uploads'))
OUTPUT_DIR = Path(os.getenv('OUTPUT_DIR', './outputs'))
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)


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

    # Save uploaded file
    input_path = UPLOAD_DIR / f"{job_id}_input{Path(file.filename).suffix}"
    output_path = OUTPUT_DIR / f"{job_id}_output.mp4"

    try:
        with open(input_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    # Queue the processing task
    task = process_video_task.apply_async(
        args=[str(input_path), str(output_path), webhook_url],
        task_id=job_id
    )

    return JobResponse(
        job_id=job_id,
        status="queued",
        message="Video queued for processing"
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
    Download the processed video.
    """
    # Check if job is complete
    task_result = AsyncResult(job_id, app=celery_app)

    if task_result.state != 'SUCCESS':
        raise HTTPException(
            status_code=400,
            detail=f"Job not complete. Current status: {task_result.state}"
        )

    # Find the output file
    output_path = OUTPUT_DIR / f"{job_id}_output.mp4"

    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Output file not found")

    return FileResponse(
        path=str(output_path),
        media_type="video/mp4",
        filename=f"vertical_{job_id}.mp4"
    )


@app.delete("/job/{job_id}")
async def delete_job(job_id: str):
    """
    Delete a job and its associated files.
    """
    # Remove input file
    for ext in ['.mp4', '.mov', '.avi', '.mkv', '.webm']:
        input_path = UPLOAD_DIR / f"{job_id}_input{ext}"
        if input_path.exists():
            input_path.unlink()

    # Remove output file
    output_path = OUTPUT_DIR / f"{job_id}_output.mp4"
    if output_path.exists():
        output_path.unlink()

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
