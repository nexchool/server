"""
Centralized S3 storage: env-prefixed keys, upload/delete, presigned URLs.

Legacy references may be full HTTPS URLs, plain keys, or keys without env prefix;
helpers normalize for reads; delete uses the same key resolution as uploads.
"""

from __future__ import annotations

import os
import re
import uuid
from urllib.parse import unquote, urlparse

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from flask import current_app

# Filename: keep alphanumerics, dot, dash, underscore; collapse unsafe chars
_SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._\-]+")

_DEFAULT_PRESIGNED_EXPIRES = int(os.getenv("S3_PRESIGNED_URL_EXPIRES_SECONDS", "86400"))


def _resolve_aws_str(name: str) -> str | None:
    """
    Read AWS-related settings at call time.

    Prefer os.environ (Docker / compose env_file) over Flask config so values are not
    shadowed by empty strings from Config if .env load order differs.
    """
    v = os.environ.get(name)
    if v is not None and str(v).strip():
        return str(v).strip()
    try:
        cfg = current_app.config.get(name)
        if cfg is not None and str(cfg).strip():
            return str(cfg).strip()
    except RuntimeError:
        pass
    return None


def _get_s3_client():
    region = _resolve_aws_str("AWS_REGION")
    access_key = _resolve_aws_str("AWS_ACCESS_KEY_ID")
    secret_key = _resolve_aws_str("AWS_SECRET_ACCESS_KEY")
    session_token = _resolve_aws_str("AWS_SESSION_TOKEN")

    kwargs = {"region_name": region}
    if access_key and secret_key:
        kwargs["aws_access_key_id"] = access_key
        kwargs["aws_secret_access_key"] = secret_key
        if session_token:
            kwargs["aws_session_token"] = session_token

    return boto3.client("s3", **kwargs)


def _bucket_name() -> str | None:
    return _resolve_aws_str("AWS_S3_BUCKET_NAME") or _resolve_aws_str("S3_BUCKET_NAME")


def _ensure_s3_config() -> tuple[str, str]:
    bucket = _bucket_name()
    region = _resolve_aws_str("AWS_REGION")
    if not bucket or not region:
        raise RuntimeError("S3 not configured")
    return bucket, region


def get_env_prefix() -> str:
    """Return S3_ENV_PREFIX (e.g. local, prod)."""
    raw = _resolve_aws_str("S3_ENV_PREFIX")
    if raw is not None:
        return raw.strip("/")
    return "local"


def sanitize_filename(original: str | None) -> str:
    """Strip path components and unsafe characters; preserve extension when possible."""
    if not original:
        return f"file_{uuid.uuid4().hex[:12]}"
    base = original.rsplit("/", 1)[-1].replace("\\", "/").rsplit("/", 1)[-1]
    if not base or base in (".", ".."):
        return f"file_{uuid.uuid4().hex[:12]}"
    name = _SAFE_FILENAME_RE.sub("_", base).strip("._")
    if not name:
        return f"file_{uuid.uuid4().hex[:12]}"
    if len(name) > 180:
        stem, ext = _split_ext(name)
        name = stem[:160] + ext
    return name


def _split_ext(name: str) -> tuple[str, str]:
    if "." in name:
        return name.rsplit(".", 1)[0], "." + name.rsplit(".", 1)[1]
    return name, ""


def unique_filename(original: str | None) -> str:
    """uuid + sanitized base + extension."""
    safe = sanitize_filename(original)
    stem, ext = _split_ext(safe)
    return f"{uuid.uuid4().hex[:12]}_{stem}{ext}"


def sanitize_folder(folder: str) -> str:
    """Remove path traversal; collapse slashes; no leading/trailing slash."""
    if not folder:
        return ""
    parts = []
    for segment in folder.replace("\\", "/").split("/"):
        if not segment or segment in (".", ".."):
            continue
        seg = _SAFE_FILENAME_RE.sub("_", segment).strip("._")
        if seg:
            parts.append(seg)
    return "/".join(parts)


def build_s3_key(folder: str, filename: str) -> str:
    """
    Build `{S3_ENV_PREFIX}/{folder}/{unique_filename}`.

    folder: logical path (e.g. students/abc123/documents or tenants/t1/profile-pictures).
    """
    prefix = get_env_prefix()
    path = sanitize_folder(folder)
    safe_name = unique_filename(filename)
    if path:
        return f"{prefix}/{path}/{safe_name}"
    return f"{prefix}/{safe_name}"


def _extract_key_from_s3_url(url: str) -> str | None:
    """Virtual-hosted or path-style S3 URL -> object key."""
    bucket = _bucket_name()
    if not bucket:
        return None
    u = urlparse(url)
    path = unquote(u.path.lstrip("/"))
    host = (u.netloc or "").lower()

    # https://bucket.s3.region.amazonaws.com/key
    if host.startswith(f"{bucket.lower()}."):
        return path or None

    # https://bucket.s3.amazonaws.com/key
    if host == f"{bucket.lower()}.s3.amazonaws.com":
        return path or None

    # https://s3.region.amazonaws.com/bucket/key
    if host.startswith("s3.") and host.endswith(".amazonaws.com") and path.startswith(f"{bucket}/"):
        return path[len(bucket) + 1 :] or None

    return None


def key_for_s3_operation(stored: str | None) -> str | None:
    """
    Resolve DB/API value to an object key for delete/get_object.

    Accepts full S3 URL (this bucket), or plain key (including legacy paths).
    """
    if not stored:
        return None
    s = str(stored).strip()
    if not s:
        return None
    if s.startswith("http://") or s.startswith("https://"):
        extracted = _extract_key_from_s3_url(s)
        return extracted if extracted else None
    return s


def key_for_download_url(stored: str | None) -> str | None:
    """Same as key_for_s3_operation; name clarifies response-layer use."""
    return key_for_s3_operation(stored)


def normalize_stored_file_value_for_db(value: str | None) -> str | None:
    """
    For PATCH/body updates: store object key when value is our S3 URL; keep external URLs as-is.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if s.startswith("http://") or s.startswith("https://"):
        key = key_for_s3_operation(s)
        if key:
            return key
        return s
    return s


def is_external_url(stored: str | None) -> bool:
    """True if value is not a resolvable key in our bucket (e.g. Cloudinary or other host)."""
    if not stored:
        return False
    s = str(stored).strip()
    if not s.startswith("http://") and not s.startswith("https://"):
        return False
    return _extract_key_from_s3_url(s) is None


def get_object_url(
    stored_key_or_url: str | None,
    *,
    expires_in: int | None = None,
) -> str | None:
    """
    Presigned GET URL for a stored object key or S3 URL from this bucket.

    External URLs (e.g. legacy Cloudinary) are returned unchanged.
    """
    if not stored_key_or_url:
        return None
    if is_external_url(stored_key_or_url):
        return str(stored_key_or_url).strip()

    key = key_for_download_url(stored_key_or_url)
    if not key:
        return None

    try:
        bucket, _ = _ensure_s3_config()
    except RuntimeError:
        # Local dev without bucket: allow legacy full HTTPS URLs still in DB
        s = str(stored_key_or_url).strip()
        if s.startswith("http://") or s.startswith("https://"):
            return s
        return None

    exp = expires_in if expires_in is not None else _DEFAULT_PRESIGNED_EXPIRES
    client = _get_s3_client()
    try:
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=exp,
        )
    except ClientError:
        return None


def upload_file(
    file_stream,
    folder: str,
    original_filename: str,
    content_type: str,
) -> tuple[str, str]:
    """
    Upload stream to S3 using env-prefixed key.

    Returns:
        Tuple[str, str]: (presigned_url_for_immediate_use, object_key)
    """
    object_key = build_s3_key(folder, original_filename)
    bucket, _ = _ensure_s3_config()
    client = _get_s3_client()

    file_stream.seek(0)
    try:
        client.put_object(
            Bucket=bucket,
            Key=object_key,
            Body=file_stream,
            ContentType=content_type or "application/octet-stream",
            ServerSideEncryption="AES256",
        )
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": object_key},
            ExpiresIn=_DEFAULT_PRESIGNED_EXPIRES,
        )
    except NoCredentialsError as e:
        raise RuntimeError(
            "S3 upload failed: no AWS credentials. Set AWS_ACCESS_KEY_ID and "
            "AWS_SECRET_ACCESS_KEY in the env file used by Docker Compose "
            "(e.g. school-erp-infra/env/.env.local). On EC2, use an IAM instance profile instead."
        ) from e
    return url, object_key


def fetch_s3_object_bytes(stored_key_or_url: str) -> tuple[bytes, str]:
    """
    Download full object body from S3 (for authenticated proxy responses).

    Returns:
        (body_bytes, content_type)

    Raises:
        ValueError: invalid reference
        FileNotFoundError: object missing in bucket
        ClientError: other S3 errors
    """
    key = key_for_s3_operation(stored_key_or_url)
    if not key:
        raise ValueError("Invalid object reference")

    bucket, _ = _ensure_s3_config()
    client = _get_s3_client()
    try:
        resp = client.get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = (exc.response.get("Error") or {}).get("Code")
        if code in {"NoSuchKey", "404"}:
            raise FileNotFoundError("Object not found in storage") from exc
        raise
    body = resp["Body"].read()
    ct = resp.get("ContentType") or "application/octet-stream"
    return body, ct


def delete_file(stored_key_or_url: str | None) -> None:
    """Delete object; key may be URL or plain key; ignore not-found."""
    key = key_for_s3_operation(stored_key_or_url)
    if not key:
        return

    bucket, _ = _ensure_s3_config()
    client = _get_s3_client()

    try:
        client.delete_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        code = (exc.response.get("Error") or {}).get("Code")
        if code not in {"NoSuchKey", "404"}:
            raise


# Backwards-compatible names
def upload_to_s3(file_stream, folder: str, filename: str, content_type: str) -> tuple[str, str]:
    return upload_file(file_stream, folder, filename, content_type)


def delete_s3_object(object_key: str) -> None:
    delete_file(object_key)


def profile_picture_public_url(stored: str | None) -> str | None:
    """Resolve user.profile_picture_url for JSON responses."""
    return get_object_url(stored)


def document_download_url(stored_key_or_url: str | None) -> str | None:
    """Resolve student document field (cloudinary_url or key) for API."""
    return get_object_url(stored_key_or_url)
