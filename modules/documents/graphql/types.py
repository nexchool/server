"""What the document store looks like over GraphQL.

Metadata is business and lives here; the bytes are infrastructure and stay on
REST (ADR-015). Nothing in this file exposes a storage key — a client is given
a path to ask the API for the file, never a way to reach the bucket.
"""

from __future__ import annotations

from typing import List, Optional

import strawberry

from modules.documents.models import Document as DocumentModel
from modules.documents.models import DocumentType as DocumentTypeModel
from modules.documents.service import Completeness


@strawberry.type(description="A kind of document this sort of owner collects.")
class DocumentTypeOption:
    code: str
    label: str
    description: str
    contexts: List[str]


@strawberry.type(description="Who filed a document.")
class DocumentUploader:
    id: str
    name: str


@strawberry.type(description="A file the school holds.")
class Document:
    id: str
    document_type: str
    document_type_label: str
    original_filename: str
    mime_type: str
    file_size_bytes: int
    # The path to ask the API for the bytes. Not a storage URL: the file is
    # served by an authenticated route, so a link that leaves the app is dead.
    view_url: str
    created_at: Optional[str]
    uploaded_by: Optional[DocumentUploader]


@strawberry.type(
    description=(
        "How far along an owner's paperwork is. `isTracked` is false when this "
        "kind of owner has no requirement, so a client can tell 'complete' "
        "apart from 'nothing was ever asked for'."
    )
)
class DocumentCompleteness:
    distinct_type_count: int
    minimum_required: int
    is_satisfied: bool
    is_tracked: bool


@strawberry.type(description="An owner's documents and how complete they are.")
class DocumentSet:
    documents: List[Document]
    completeness: DocumentCompleteness
    # What this particular profile may file, already narrowed to its contexts,
    # so a client never has to know which types belong to whom.
    available_types: List[DocumentTypeOption]


def type_option_to_graphql(row: DocumentTypeModel) -> DocumentTypeOption:
    return DocumentTypeOption(
        code=row.code,
        label=row.label,
        description=row.description or "",
        contexts=list(row.contexts or []),
    )


def document_to_graphql(row: DocumentModel, view_url_base: str) -> Document:
    """`view_url_base` is the profile route serving the bytes.

    Domain-scoped rather than a single /api/documents/<id>/file, because who
    may read a file is decided by the profile it hangs off — a generic byte
    route would have to re-derive that from the person, and get it right for
    every relationship they hold.
    """
    return Document(
        id=row.id,
        document_type=row.document_type_code,
        document_type_label=(
            row.document_type.label if row.document_type else row.document_type_code
        ),
        original_filename=row.original_filename,
        mime_type=row.mime_type,
        file_size_bytes=row.file_size_bytes,
        view_url=f"{view_url_base}/{row.id}/file",
        created_at=row.created_at.isoformat() if row.created_at else None,
        uploaded_by=(
            DocumentUploader(id=row.uploaded_by.id, name=row.uploaded_by.name or "")
            if row.uploaded_by
            else None
        ),
    )


def completeness_to_graphql(value: Completeness) -> DocumentCompleteness:
    return DocumentCompleteness(
        distinct_type_count=value.distinct_type_count,
        minimum_required=value.minimum_required,
        is_satisfied=value.is_satisfied,
        is_tracked=value.is_tracked,
    )
