"""
Cloudflare R2 file storage service.

Required env vars (add to Railway when R2 is set up):
    R2_ACCOUNT_ID    — Cloudflare account ID
    R2_ACCESS_KEY    — R2 API token access key
    R2_SECRET_KEY    — R2 API token secret key
    R2_BUCKET        — bucket name (e.g. "zpay-driver-docs")
    R2_PUBLIC_URL    — optional public URL prefix for the bucket
"""

import os
import boto3
from botocore.client import Config
from pathlib import Path

def get_r2_client():
    """Returns boto3 S3 client configured for Cloudflare R2."""
    account_id = os.environ.get("R2_ACCOUNT_ID", "")
    access_key = os.environ.get("R2_ACCESS_KEY", "")
    secret_key = os.environ.get("R2_SECRET_KEY", "")

    if not all([account_id, access_key, secret_key]):
        raise ValueError("R2 credentials not configured. Set R2_ACCOUNT_ID, R2_ACCESS_KEY, R2_SECRET_KEY in env vars.")

    return boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )

def upload_file(file_bytes: bytes, key: str, content_type: str = "application/octet-stream") -> str:
    """Upload file bytes to R2. Returns the R2 key."""
    bucket = os.environ.get("R2_BUCKET", "zpay-driver-docs")
    client = get_r2_client()
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=file_bytes,
        ContentType=content_type,
    )
    return key

def get_presigned_url(key: str, expires_in: int = 3600) -> str:
    """Generate a presigned URL for downloading a file. Default 1 hour."""
    bucket = os.environ.get("R2_BUCKET", "zpay-driver-docs")
    client = get_r2_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires_in,
    )

def delete_file(key: str) -> bool:
    """Delete a file from R2. Returns True on success."""
    bucket = os.environ.get("R2_BUCKET", "zpay-driver-docs")
    client = get_r2_client()
    client.delete_object(Bucket=bucket, Key=key)
    return True

def r2_configured() -> bool:
    """Returns True if R2 env vars are set."""
    return all([
        os.environ.get("R2_ACCOUNT_ID"),
        os.environ.get("R2_ACCESS_KEY"),
        os.environ.get("R2_SECRET_KEY"),
    ])
