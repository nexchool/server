"""
Cloudinary utility functions for file upload and deletion.

Uses app config: CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET.
Import and use from any module that needs to upload or delete assets.
"""

import uuid

from flask import current_app


def _ensure_cloudinary_config():
    """Ensure Cloudinary is configured. Raises RuntimeError if not."""
    cloud_name = current_app.config.get("CLOUDINARY_CLOUD_NAME")
    api_key = current_app.config.get("CLOUDINARY_API_KEY")
    api_secret = current_app.config.get("CLOUDINARY_API_SECRET")
    if not all([cloud_name, api_key, api_secret]):
        raise RuntimeError("Cloudinary not configured")
    return cloud_name, api_key, api_secret


def upload_to_cloudinary(file_stream, folder: str, public_id: str | None = None) -> tuple[str, str]:
    """
    Upload a file to Cloudinary.

    Args:
        file_stream: File-like object (supports .read() or stream protocol)
        folder: Cloudinary folder path (e.g. school_erp/tenant_123/students/456/documents)
        public_id: Optional public ID. If None, generates one from uuid.

    Returns:
        Tuple of (secure_url, public_id)

    Raises:
        RuntimeError: If Cloudinary is not configured
        Exception: On upload failure (network, API errors)
    """
    import cloudinary
    import cloudinary.uploader

    cloud_name, api_key, api_secret = _ensure_cloudinary_config()
    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
    )

    if not public_id:
        public_id = f"doc_{uuid.uuid4().hex[:12]}"

    result = cloudinary.uploader.upload(
        file_stream,
        folder=folder,
        resource_type="auto",
        public_id=public_id,
    )
    return result["secure_url"], result["public_id"]


def destroy_cloudinary_asset(public_id: str, resource_type: str = "auto") -> None:
    """
    Delete an asset from Cloudinary. Suppresses errors (e.g. already deleted).

    Args:
        public_id: Cloudinary public_id of the asset
        resource_type: 'auto', 'image', 'raw', or 'video'
    """
    import cloudinary
    import cloudinary.uploader

    cloud_name, api_key, api_secret = _ensure_cloudinary_config()
    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
    )

    try:
        cloudinary.uploader.destroy(public_id, resource_type=resource_type)
    except Exception:
        pass
