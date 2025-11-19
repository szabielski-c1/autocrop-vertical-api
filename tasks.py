import os
import requests
from celery import Celery
from processor import process_video

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
def process_video_task(self, input_path: str, output_path: str, webhook_url: str = None):
    """
    Celery task to process video in background.

    Args:
        input_path: Path to uploaded input video
        output_path: Path for processed output video
        webhook_url: Optional URL to POST results when complete

    Returns:
        dict with processing results
    """
    job_id = self.request.id

    try:
        # Update task state
        self.update_state(state='PROCESSING', meta={'step': 1, 'message': 'Starting...'})

        # Process the video
        result = process_video(
            input_path,
            output_path,
            progress_callback=update_progress(job_id)
        )

        # Add job info to result
        result['job_id'] = job_id
        result['status'] = 'completed'

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
