"""
Backblaze B2 storage helpers (S3-compatible via boto3).
"""

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

_client = None
_bucket = None


def _b2():
    global _client, _bucket
    if _client is None:
        from django.conf import settings
        _client = boto3.client(
            "s3",
            endpoint_url=settings.B2_ENDPOINT_URL,
            aws_access_key_id=settings.B2_KEY_ID,
            aws_secret_access_key=settings.B2_APP_KEY,
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )
        _bucket = settings.B2_BUCKET_NAME
    return _client, _bucket


def object_key(ns: str, drop_key: str) -> str:
    return f"drops/{ns}/{drop_key}"


def presigned_put(ns: str, drop_key: str, content_type: str = "application/octet-stream",
                  size: int = 0, expires_in: int = 3600) -> str:
    client, bucket = _b2()
    params = {
        "Bucket": bucket,
        "Key": object_key(ns, drop_key),
        "ContentType": content_type,
    }
    if size:
        params["ContentLength"] = size
    return client.generate_presigned_url(
        "put_object", Params=params, ExpiresIn=expires_in, HttpMethod="PUT",
    )


def presigned_get(ns: str, drop_key: str, filename: str = "",
                  expires_in: int = 3600, b2_key: str = "") -> str:
    """
    Return a presigned GET URL for a B2 object with proper filename encoding.
    """
    import urllib.parse
    
    client, bucket = _b2()
    b2_obj_key = b2_key if b2_key else object_key(ns, drop_key)
    params     = {"Bucket": bucket, "Key": b2_obj_key}
    
    if filename:
        # RFC 5987: Use RFC 2231 encoding for non-ASCII or special chars
        # For simplicity, encode all special chars to be safe
        safe_name = urllib.parse.quote(filename, safe='')
        # Use RFC 2231 syntax: filename*=UTF-8''<encoded_name>
        params["ResponseContentDisposition"] = f'attachment; filename*=UTF-8\'\'{safe_name}'
    return client.generate_presigned_url(
        "get_object", Params=params, ExpiresIn=expires_in,
    )


def invalidate_presigned(ns: str, drop_key: str, filename: str = "", b2_key: str = "") -> None:
    """No-op — kept so call sites in actions.py don't need updating."""
    pass


def copy_object(src_key: str, dst_key: str) -> bool:
    """
    Server-side copy within the same B2 bucket.
    Returns True on success.
    """
    import logging
    logger = logging.getLogger(__name__)
    client, bucket = _b2()
    try:
        client.copy_object(
            Bucket=bucket,
            CopySource={"Bucket": bucket, "Key": src_key},
            Key=dst_key,
        )
        return True
    except ClientError as e:
        logger.error("B2 copy failed %s → %s: %s", src_key, dst_key, e)
        return False


def upload_fileobj(file_obj, ns: str, drop_key: str,
                   content_type: str = "application/octet-stream") -> str:
    from boto3.s3.transfer import TransferConfig
    client, bucket = _b2()
    key = object_key(ns, drop_key)
    config = TransferConfig(
        multipart_threshold=100 * 1024 * 1024,
        multipart_chunksize=50 * 1024 * 1024,
        max_concurrency=4,
        use_threads=True,
    )
    client.upload_fileobj(
        file_obj, bucket, key,
        ExtraArgs={"ContentType": content_type},
        Config=config,
    )
    return key


def object_head(ns: str, drop_key: str) -> dict | None:
    """
    Single HEAD request. Returns {"exists": True, "size": int} or None if not found.
    Replaces separate object_exists() + object_size() calls.
    """
    client, bucket = _b2()
    try:
        resp = client.head_object(Bucket=bucket, Key=object_key(ns, drop_key))
        return {"exists": True, "size": resp.get("ContentLength", 0)}
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return None
        raise


def object_exists(ns: str, drop_key: str) -> bool:
    client, bucket = _b2()
    try:
        client.head_object(Bucket=bucket, Key=object_key(ns, drop_key))
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
            return False
        raise


def object_size(ns: str, drop_key: str) -> int:
    client, bucket = _b2()
    try:
        resp = client.head_object(Bucket=bucket, Key=object_key(ns, drop_key))
        return resp.get("ContentLength", 0)
    except ClientError:
        return 0


def delete_object(ns: str, drop_key: str, b2_key: str = "") -> bool:
    """Delete a B2 object. If b2_key is provided, use it directly instead of
    computing from ns/drop_key."""
    import logging
    logger = logging.getLogger(__name__)
    client, bucket = _b2()
    key = b2_key if b2_key else object_key(ns, drop_key)
    try:
        client.delete_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("404", "NoSuchKey"):
            return True
        logger.error("B2 delete failed for %s: %s", key, e)
        return False
    except Exception as e:
        logger.error("B2 delete error for %s: %s", key, e)
        return False