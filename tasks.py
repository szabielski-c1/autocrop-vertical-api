import os
import tempfile
import requests
from pathlib import Path
from celery import Celery
from processor import process_video
import s3_storage

# Configure Celery
celery_app = Celery(
    'autocrop',
    broker=os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0'),
    backend=os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')
)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    result_extended=True,
)

# Storage for job progress
job_progress = {}

# Temp directory for processing
TEMP_DIR = Path(tempfile.gettempdir()) / "autocrop_worker"
TEMP_DIR.mkdir(exist_ok=True)


def update_progress(job_id):
    """Returns a progress callback for a specific job."""
    def callback(step, progress, message):
        job_progress[job_id] = {
            'step': step,
            'progress': progress,
            'message': message,
            'total_steps': 5
        }
    return callback


@celery_app.task(bind=True, name='process_video_task')
def process_video_task(self, input_s3_key: str, output_s3_key: str, webhook_url: str = None):
    """
    Celery task to process video in background.

    Args:
        input_s3_key: S3 key for input video
        output_s3_key: S3 key for output video
        webhook_url: Optional URL to POST results when complete

    Returns:
        dict with processing results
    """
    job_id = self.request.id

    # Local paths for processing
    ext = Path(input_s3_key).suffix
    local_input = TEMP_DIR / f"{job_id}_input{ext}"
    local_output = TEMP_DIR / f"{job_id}_output.mp4"

    try:
        # Update task state
        self.update_state(state='PROCESSING', meta={'step': 1, 'message': 'Downloading from S3...'})

        # Download input from S3
        if not s3_storage.download_file(input_s3_key, str(local_input)):
            raise Exception(f"Failed to download input from S3: {input_s3_key}")

        # Process the video
        result = process_video(
            str(local_input),
            str(local_output),
            progress_callback=update_progress(job_id)
        )

        # Upload output to S3
        self.update_state(state='PROCESSING', meta={'step': 5, 'message': 'Uploading to S3...'})
        if not s3_storage.upload_file(str(local_output), output_s3_key):
            raise Exception(f"Failed to upload output to S3: {output_s3_key}")

        # Clean up local files
        if local_input.exists():
            local_input.unlink()
        if local_output.exists():
            local_output.unlink()

        # Update result with S3 info
        result['job_id'] = job_id
        result['status'] = 'completed'
        result['output_s3_key'] = output_s3_key

        # Send webhook if provided
        if webhook_url:
            try:
                webhook_payload = {
                    'job_id': job_id,
                    'status': 'completed',
                    'result': result
                }
                response = requests.post(
                    webhook_url,
                    json=webhook_payload,
                    timeout=30
                )
                result['webhook_sent'] = True
                result['webhook_status'] = response.status_code
            except Exception as e:
                result['webhook_sent'] = False
                result['webhook_error'] = str(e)

        # Clean up progress
        if job_id in job_progress:
            del job_progress[job_id]

        return result

    except Exception as e:
        # Clean up local files on error
        if local_input.exists():
            local_input.unlink()
        if local_output.exists():
            local_output.unlink()

        error_result = {
            'job_id': job_id,
            'status': 'failed',
            'error': str(e)
        }

        # Send failure webhook if provided
        if webhook_url:
            try:
                requests.post(
                    webhook_url,
                    json=error_result,
                    timeout=30
                )
            except:
                pass

        # Clean up progress
        if job_id in job_progress:
            del job_progress[job_id]

        raise


def get_job_progress(job_id: str) -> dict:
    """Get the current progress of a job."""
    return job_progress.get(job_id, {})
