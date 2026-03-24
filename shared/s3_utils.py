"""
S3 utility helpers for document upload and deletion.

This module keeps the same high-level behavior as the previous Cloudinary
utilities: upload returns (url, object_key), delete swallows missing-object
errors.
"""

from __future__ import annotations

import uuid
from urllib.parse import quote

import boto3
from botocore.exceptions import ClientError
from flask import current_app


def _get_s3_client():
    region = current_app.config.get("AWS_REGION")
    access_key = current_app.config.get("AWS_ACCESS_KEY_ID")
    secret_key = current_app.config.get("AWS_SECRET_ACCESS_KEY")
    session_token = current_app.config.get("AWS_SESSION_TOKEN")

    kwargs = {"region_name": region}
    if access_key and secret_key:
        kwargs["aws_access_key_id"] = access_key
        kwargs["aws_secret_access_key"] = secret_key
        if session_token:
            kwargs["aws_session_token"] = session_token

    return boto3.client("s3", **kwargs)


def _ensure_s3_config() -> tuple[str, str]:
    bucket = current_app.config.get("S3_BUCKET_NAME")
    region = current_app.config.get("AWS_REGION")
    if not bucket or not region:
        raise RuntimeError("S3 not configured")
    return bucket, region


def upload_to_s3(file_stream, folder: str, filename: str, content_type: str) -> tuple[str, str]:
    """
    Upload a file stream to S3.

    Returns:
        Tuple[str, str]: (public_url, object_key)
    """
    bucket, region = _ensure_s3_config()
    client = _get_s3_client()

    safe_name = (filename or f"file_{uuid.uuid4().hex[:12]}").replace(" ", "_")
    object_key = f"{folder}/{uuid.uuid4().hex[:12]}_{safe_name}"

    file_stream.seek(0)
    client.put_object(
        Bucket=bucket,
        Key=object_key,
        Body=file_stream,
        ContentType=content_type or "application/octet-stream",
    )

    encoded_key = quote(object_key, safe="/")
    public_url = f"https://{bucket}.s3.{region}.amazonaws.com/{encoded_key}"
    return public_url, object_key


def delete_s3_object(object_key: str) -> None:
    """Delete an object from S3; ignore not-found errors."""
    if not object_key:
        return

    bucket, _ = _ensure_s3_config()
    client = _get_s3_client()

    try:
        client.delete_object(Bucket=bucket, Key=object_key)
    except ClientError as exc:
        code = (exc.response.get("Error") or {}).get("Code")
        if code not in {"NoSuchKey", "404"}:
            raise
