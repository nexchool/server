"""The document store's operations — the whole surface a domain needs.

Business logic lives here; transports call in and stay thin. Tenant scoping is
the ORM's (`core.database`), so nothing below filters by tenant by hand.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func

from core.database import db
from modules.documents import registry, storage
from modules.documents.errors import (
    DocumentNotFound,
    FileRejected,
    OwnerNotFound,
    UnknownDocumentType,
)
from modules.documents.models import Document, DocumentType
from shared.s3_utils import delete_file, fetch_s3_object_bytes, upload_file


@dataclass(frozen=True)
class Completeness:
    """How far along an owner's paperwork is."""

    distinct_type_count: int
    minimum_required: int
    is_satisfied: bool
    # False when the owner kind has no rule, so a caller can tell "complete"
    # apart from "never asked for anything".
    is_tracked: bool


def types_for(owner_kind: str, contexts: tuple[str, ...] | None = None) -> list[DocumentType]:
    """Active types this owner kind offers, narrowed to `contexts` when given.

    Ordered by context group in the order asked for, then sequence, with a type
    belonging to every context — a catch-all like "Other" — last, so a picker
    reads sensibly instead of interleaving groups whose sequences collide.
    """
    kind = registry.get(owner_kind)
    wanted = tuple(contexts) if contexts else kind.contexts

    rows = (
        DocumentType.query.filter(
            DocumentType.owner_kind == owner_kind,
            DocumentType.is_active.is_(True),
        )
        .all()
    )

    ranked = []
    for row in rows:
        row_contexts = list(row.contexts or [])
        position = next((i for i, c in enumerate(wanted) if c in row_contexts), None)
        if position is None:
            continue
        is_catch_all = int(len(row_contexts) >= len(kind.contexts))
        ranked.append((is_catch_all, position, row.sequence, row.label, row))
    return [row for *_, row in sorted(ranked, key=lambda r: r[:4])]


def list_for(owner_kind: str, owner_id: str) -> list[Document]:
    """Everything this owner holds, newest first."""
    return (
        Document.query.filter(
            Document.owner_kind == owner_kind, Document.owner_id == owner_id
        )
        .order_by(Document.created_at.desc())
        .all()
    )


def get(document_id: str) -> Document:
    document = Document.query.filter(Document.id == document_id).first()
    if document is None:
        raise DocumentNotFound(f"No document '{document_id}'")
    return document


def completeness(owner_kind: str, owner_id: str) -> Completeness:
    kind = registry.get(owner_kind)
    count = (
        db.session.query(func.count(func.distinct(Document.document_type_code)))
        .filter(Document.owner_kind == owner_kind, Document.owner_id == owner_id)
        .scalar()
        or 0
    )
    return _completeness(kind.minimum_distinct_types, count)


def completeness_for_many(
    owner_kind: str, owner_ids: list[str]
) -> dict[str, Completeness]:
    """The same signal for many owners in one query.

    A list screen showing this for every row must not ask per row — at fifteen
    thousand students that is fifteen thousand queries. One grouped count
    answers all of them.
    """
    kind = registry.get(owner_kind)
    if not owner_ids:
        return {}

    counted = dict(
        db.session.query(
            Document.owner_id,
            func.count(func.distinct(Document.document_type_code)),
        )
        .filter(Document.owner_kind == owner_kind, Document.owner_id.in_(owner_ids))
        .group_by(Document.owner_id)
        .all()
    )
    # Owners with nothing filed do not appear in the grouped result and are the
    # ones the signal exists for, so they are filled in rather than omitted.
    return {
        owner_id: _completeness(kind.minimum_distinct_types, counted.get(owner_id, 0))
        for owner_id in owner_ids
    }


def _completeness(minimum: int, count: int) -> Completeness:
    return Completeness(
        distinct_type_count=count,
        minimum_required=minimum,
        is_satisfied=minimum == 0 or count >= minimum,
        is_tracked=minimum > 0,
    )


def upload(
    owner_kind: str,
    owner_id: str,
    document_type_code: str,
    file_stream,
    original_filename: str,
    mime_type: str,
    uploaded_by_user_id: str | None = None,
) -> Document:
    """Store a file against an owner. Raises rather than half-succeeding."""
    kind = registry.get(owner_kind)

    tenant_id = kind.resolve_tenant(owner_id)
    if not tenant_id:
        raise OwnerNotFound(
            f"No {kind.label.lower()} '{owner_id}' in this school."
        )

    if not _type_is_offered(owner_kind, document_type_code):
        raise UnknownDocumentType(
            f"'{document_type_code}' is not a document type a "
            f"{kind.label.lower()} collects."
        )

    normalized_mime = (mime_type or "").strip().lower()
    if normalized_mime not in kind.allowed_mime_types:
        raise FileRejected(
            f"Unsupported file type. Allowed: "
            f"{', '.join(sorted(kind.allowed_mime_types))}."
        )

    size = _measure(file_stream)
    if size == 0:
        raise FileRejected("The file is empty.")
    if size > kind.max_file_size_bytes:
        limit_mb = kind.max_file_size_bytes // (1024 * 1024)
        raise FileRejected(f"File too large. Maximum allowed size is {limit_mb} MB.")

    _, storage_key = upload_file(
        file_stream,
        folder=storage.owner_folder(tenant_id, owner_kind, owner_id),
        original_filename=original_filename,
        content_type=normalized_mime,
    )

    document = Document(
        tenant_id=tenant_id,
        owner_kind=owner_kind,
        owner_id=owner_id,
        document_type_code=document_type_code,
        original_filename=original_filename,
        storage_key=storage_key,
        mime_type=normalized_mime,
        file_size_bytes=size,
        uploaded_by_user_id=uploaded_by_user_id,
    )
    db.session.add(document)
    db.session.commit()
    return document


def delete(document_id: str) -> None:
    """Remove a document and its bytes.

    The row goes first. A stored object with no row is invisible waste; a row
    with no object is a broken download every time anyone opens the profile.
    """
    document = get(document_id)
    key = document.storage_key
    db.session.delete(document)
    db.session.commit()
    delete_file(key)


def delete_all_for(owner_kind: str, owner_id: str) -> int:
    """Remove everything an owner holds. Returns how many went.

    A polymorphic owner reference cannot cascade, so a domain deleting an owner
    calls this. Not calling it leaks files, and the leak is silent.
    """
    documents = list_for(owner_kind, owner_id)
    keys = [d.storage_key for d in documents]
    for document in documents:
        db.session.delete(document)
    db.session.commit()
    for key in keys:
        delete_file(key)
    return len(keys)


def read_bytes(document_id: str) -> tuple[bytes, str]:
    """The file itself, for a transport that is streaming it back."""
    document = get(document_id)
    payload, _ = fetch_s3_object_bytes(document.storage_key)
    return payload, document.mime_type


def _type_is_offered(owner_kind: str, code: str) -> bool:
    return bool(
        DocumentType.query.filter(
            DocumentType.code == code,
            DocumentType.owner_kind == owner_kind,
            DocumentType.is_active.is_(True),
        ).first()
    )


def _measure(file_stream) -> int:
    """Size in bytes, by seeking rather than trusting a declared length.

    `content_length` is absent on a chunked upload and is client-supplied when
    it is there, so neither reason is good enough to accept a file on.
    """
    file_stream.seek(0, 2)
    size = file_stream.tell()
    file_stream.seek(0)
    return size
