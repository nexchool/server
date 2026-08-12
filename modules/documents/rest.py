"""The two operations that carry bytes, shared by the profiles that expose them.

Metadata is GraphQL's (ADR-015). What is left on REST is a multipart upload and
an authenticated download — infrastructure, and awkward to do over GraphQL for
no gain.

Neither function decides authority. The route that calls them has already
answered "may this caller touch this profile", including branch scope; these
only enforce that the document really hangs off the person that route resolved.
"""

from __future__ import annotations

from flask import Response, g, request
from werkzeug.utils import secure_filename

from modules.documents import service
from modules.documents.errors import (
    DocumentNotFound,
    FileRejected,
    OwnerNotFound,
    UnknownDocumentType,
)
from modules.people.document_catalog import OWNER_KIND


def upload_for_person(person_id: str) -> tuple[dict, int]:
    """Take a multipart upload and file it against a person.

    Returns (body, status) in the platform's error shape rather than raising,
    because the callers are Flask routes and that is the contract they answer
    in.
    """
    uploaded = request.files.get("file") or request.files.get("document")
    document_type = (request.form.get("document_type") or "").strip().lower()

    if not uploaded or not uploaded.filename:
        return _error("ValidationError", "File is required"), 400
    if not document_type:
        return _error("ValidationError", "Document type is required"), 400

    try:
        document = service.upload(
            owner_kind=OWNER_KIND,
            owner_id=person_id,
            document_type_code=document_type,
            file_stream=uploaded.stream,
            original_filename=uploaded.filename or "document",
            mime_type=uploaded.content_type or "",
            uploaded_by_user_id=getattr(g.current_user, "id", None),
        )
    except UnknownDocumentType as exc:
        return _error("ValidationError", str(exc)), 400
    except FileRejected as exc:
        # Size and format are the client's mistake, so 400 and say which.
        code = "FileTooLarge" if "too large" in str(exc).lower() else "UnsupportedFileType"
        return _error(code, str(exc)), 400
    except OwnerNotFound as exc:
        return _error("NotFound", str(exc)), 404

    return {"data": document.to_dict()}, 201


def stream_document(person_id: str, document_id: str) -> Response | tuple[dict, int]:
    """Send a document's bytes back, if it is really this person's.

    The ownership check is not ceremony: the calling route established that the
    caller may read *this profile*, and a document id is guessable. Without it,
    any id would be readable by anyone holding one profile.
    """
    try:
        document = service.get(document_id)
    except DocumentNotFound:
        return _error("NotFound", "Document not found"), 404

    if document.owner_kind != OWNER_KIND or document.owner_id != person_id:
        # Deliberately the same answer as a missing document: telling a caller
        # that an id exists but belongs to someone else is itself a leak.
        return _error("NotFound", "Document not found"), 404

    payload, mime = service.read_bytes(document_id)
    safe_name = secure_filename(document.original_filename) or "document"

    return Response(
        payload,
        mimetype=mime,
        headers={
            "Content-Disposition": f'inline; filename="{safe_name}"',
            # Never cached: the response is one school's PII behind an
            # Authorization header, and a shared cache must not keep it.
            "Cache-Control": "private, no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _error(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}
