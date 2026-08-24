"""The document store — one place the whole platform keeps files.

A domain that needs documents registers an owner kind and gets upload, listing,
deletion, completeness and tenant-scoped storage. It writes no storage code and
gets no table of its own (ADR-015).

    from modules.documents import OwnerKind, register, service

    register(
        OwnerKind(
            name="exam_paper",
            label="Exam paper",
            contexts=("question_paper", "answer_sheet"),
            resolve_tenant=exam_paper_tenant,
            max_file_size_bytes=50 * 1024 * 1024,
        )
    )

    service.upload("exam_paper", paper_id, "question_paper", stream, name, mime)
    service.list_for("exam_paper", paper_id)

Two obligations come with registering a kind, both because a polymorphic owner
reference is not something the database can police:

- `resolve_tenant` must return None for an owner that does not exist. It is the
  only thing standing between a typo and a document filed against nothing.
- Deleting an owner must call `service.delete_all_for`. Nothing cascades, and
  the leak is silent.

Types are declared in a catalogue and seeded into `document_types`; see
`modules/people/document_catalog.py` for the worked example.
"""

from modules.documents.errors import (
    DocumentError,
    DocumentNotFound,
    FileRejected,
    OwnerNotFound,
    UnknownDocumentType,
    UnknownOwnerKind,
)
from modules.documents.models import Document, DocumentType
from modules.documents.registry import (
    DEFAULT_MAX_FILE_SIZE_BYTES,
    DEFAULT_MIME_TYPES,
    OwnerKind,
    all_kinds,
    get,
    is_registered,
    register,
)

__all__ = [
    "Document",
    "DocumentType",
    "OwnerKind",
    "register",
    "get",
    "is_registered",
    "all_kinds",
    "DEFAULT_MIME_TYPES",
    "DEFAULT_MAX_FILE_SIZE_BYTES",
    "DocumentError",
    "UnknownOwnerKind",
    "OwnerNotFound",
    "UnknownDocumentType",
    "FileRejected",
    "DocumentNotFound",
]
