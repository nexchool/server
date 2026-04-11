"""
Document request/response validation for student documents.

Used for multipart/form-data upload validation.
"""

from modules.students.models import DocumentType, DOCUMENT_TYPE_LABELS

# Allowed MIME types for upload
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/jpg",
    "image/png",
}

# Max file size: 10 MB
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024

# Valid document_type values (enum values)
VALID_DOCUMENT_TYPES = {dt.value for dt in DocumentType}


def validate_document_type(value: str) -> str | None:
    """
    Validate document_type form field.
    Returns None when valid, error message when invalid.
    """
    if not value or not value.strip():
        return "Document type is required."
    val = value.strip().lower()
    if val not in VALID_DOCUMENT_TYPES:
        return "Invalid document type."
    return None


def validate_file(file) -> tuple[bool, str | None]:
    """
    Validate uploaded file: presence, size, MIME type.
    Returns (is_valid, error_message).
    """
    if not file or not file.filename:
        return False, "File is required."
    if file.content_length is not None and file.content_length > MAX_FILE_SIZE_BYTES:
        return False, "File too large. Maximum allowed size is 10 MB."
    # content_length may be None for chunked uploads; we'll check after read if needed
    mime = (file.content_type or "").strip().lower()
    if mime not in ALLOWED_MIME_TYPES:
        return False, "Unsupported file type. Allowed: PDF, JPG, PNG."
    return True, None
