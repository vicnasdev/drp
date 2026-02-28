"""
core/storage.py  —  Backblaze B2 via boto3 (S3-compatible).

All file I/O goes through here. Views never touch boto3 directly.
"""

import mimetypes
import uuid

import boto3
from botocore.exceptions import ClientError
from django.conf import settings

import logging
logger = logging.getLogger(__name__)


def _client():
    return boto3.client(
        "s3",
        endpoint_url=settings.B2_ENDPOINT_URL,
        aws_access_key_id=settings.B2_KEY_ID,
        aws_secret_access_key=settings.B2_APP_KEY,
    )


def b2_upload(file_obj, filename: str, content_type: str = "") -> tuple[str, int]:
    """
    Upload *file_obj* (Django InMemoryUploadedFile or similar) to B2.
    Returns (b2_name, size_bytes).
    """
    if not content_type:
        content_type, _ = mimetypes.guess_type(filename)
        content_type = content_type or "application/octet-stream"

    b2_name = f"{uuid.uuid4().hex}/{filename}"
    client  = _client()

    file_obj.seek(0)
    data = file_obj.read()
    size = len(data)

    client.put_object(
        Bucket=settings.B2_BUCKET_NAME,
        Key=b2_name,
        Body=data,
        ContentType=content_type,
        ContentDisposition=f'attachment; filename="{filename}"',
    )
    logger.info("b2_upload: %s (%d bytes)", b2_name, size)
    return b2_name, size


def b2_upload_text(content: str, key: str) -> tuple[str, int]:
    """Store plain-text drop content as a tiny object in B2."""
    encoded  = content.encode("utf-8")
    b2_name  = f"text/{key}.txt"
    client   = _client()

    client.put_object(
        Bucket=settings.B2_BUCKET_NAME,
        Key=b2_name,
        Body=encoded,
        ContentType="text/plain; charset=utf-8",
    )
    return b2_name, len(encoded)


def b2_download_url(b2_name: str, expires: int = 3600) -> str:
    """Return a presigned GET URL valid for *expires* seconds."""
    client = _client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.B2_BUCKET_NAME, "Key": b2_name},
        ExpiresIn=expires,
    )


def b2_read(b2_name: str) -> bytes:
    """Fetch object bytes directly (used for text raw view)."""
    client = _client()
    resp   = client.get_object(Bucket=settings.B2_BUCKET_NAME, Key=b2_name)
    return resp["Body"].read()


def b2_delete(b2_name: str) -> None:
    """Delete an object. Silently ignores NoSuchKey."""
    client = _client()
    try:
        client.delete_object(Bucket=settings.B2_BUCKET_NAME, Key=b2_name)
        logger.info("b2_delete: %s", b2_name)
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchKey":
            raise
