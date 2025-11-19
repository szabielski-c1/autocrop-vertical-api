import os
import boto3
from botocore.exceptions import ClientError

# Initialize S3 client
s3_client = boto3.client(
    's3',
    aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    region_name=os.getenv('AWS_REGION', 'us-east-1')
)

BUCKET_NAME = os.getenv('S3_BUCKET_NAME', 'c1-scott-scratchdisk')
S3_PREFIX = os.getenv('S3_PREFIX', 'Billboard/Reframe/')


def _full_key(s3_key: str) -> str:
    """Prepend the S3 prefix to the key."""
    return f"{S3_PREFIX}{s3_key}"


def upload_file(local_path: str, s3_key: str) -> bool:
    """Upload a file to S3."""
    try:
        s3_client.upload_file(local_path, BUCKET_NAME, _full_key(s3_key))
        return True
    except ClientError as e:
        print(f"Error uploading to S3: {e}")
        return False


def download_file(s3_key: str, local_path: str) -> bool:
    """Download a file from S3."""
    try:
        s3_client.download_file(BUCKET_NAME, _full_key(s3_key), local_path)
        return True
    except ClientError as e:
        print(f"Error downloading from S3: {e}")
        return False


def delete_file(s3_key: str) -> bool:
    """Delete a file from S3."""
    try:
        s3_client.delete_object(Bucket=BUCKET_NAME, Key=_full_key(s3_key))
        return True
    except ClientError as e:
        print(f"Error deleting from S3: {e}")
        return False


def file_exists(s3_key: str) -> bool:
    """Check if a file exists in S3."""
    try:
        s3_client.head_object(Bucket=BUCKET_NAME, Key=_full_key(s3_key))
        return True
    except ClientError:
        return False


def generate_presigned_url(s3_key: str, expiration: int = 3600) -> str:
    """Generate a presigned URL for downloading a file."""
    try:
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': BUCKET_NAME, 'Key': _full_key(s3_key)},
            ExpiresIn=expiration
        )
        return url
    except ClientError as e:
        print(f"Error generating presigned URL: {e}")
        return None
