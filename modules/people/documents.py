"""Documents a school holds about a person.

A document belongs to the human, not to the studentship or the employment that
prompted collecting it (ADR-015). The student profile and the teacher profile
are two views of one person's papers, so someone who is both a parent and a
teacher hands over their Aadhar once.

The type vocabulary lives in `document_catalog.py` and is seeded into
`document_types`; rows here reference it by code.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from core.database import db
from core.models import TenantBaseModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


class DocumentType(db.Model):
    """A kind of document a school collects, seeded from the catalogue.

    Not tenant-scoped: the vocabulary is the platform's, shared by every school.
    A school that needs a type nobody has needed yet gets a catalogue line and a
    reseed rather than a migration (ADR-015).
    """

    __tablename__ = "document_types"

    code = db.Column(db.String(64), primary_key=True)
    label = db.Column(db.Text, nullable=False)
    # Which kinds of profile offer this type. Held as JSON and filtered in
    # Python: the catalogue is a dozen rows, so an index would cost more to
    # maintain than the scan it saves.
    contexts = db.Column(db.JSON, nullable=False)
    sequence = db.Column(db.Integer, nullable=False, default=100)
    description = db.Column(db.Text, nullable=False, default="")
    # Retiring a type must not orphan the documents already filed under it, so
    # a withdrawn type stops being offered rather than being deleted.
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "label": self.label,
            "contexts": list(self.contexts or []),
            "sequence": self.sequence,
            "description": self.description or "",
        }


class PersonDocument(TenantBaseModel):
    """A file a school holds about a person. Bytes in S3, this row is the record."""

    __tablename__ = "person_documents"

    id = db.Column(db.String(36), primary_key=True, default=_new_id)
    person_id = db.Column(
        db.String(36),
        db.ForeignKey("persons.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_type_code = db.Column(
        db.String(64),
        db.ForeignKey("document_types.code", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    original_filename = db.Column(db.String(255), nullable=False)
    # The S3 object key. v1 carried a second `file_url` column beside it that
    # every serializer returned as None; it is not reproduced here.
    s3_object_key = db.Column(db.String(500), nullable=False, unique=True)
    mime_type = db.Column(db.String(100), nullable=False)
    file_size_bytes = db.Column(db.Integer, nullable=False)
    # The acting account, as `PersonMerge.merged_by_user_id` records it. An
    # actor signed in by definition; only subjects were freed from needing a
    # login (migration 094).
    uploaded_by_user_id = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    person = db.relationship(
        "Person",
        backref=db.backref("documents", lazy="selectin"),
        passive_deletes=True,
    )
    document_type = db.relationship("DocumentType", lazy="joined")
    uploaded_by = db.relationship("User", foreign_keys=[uploaded_by_user_id])

    def to_dict(self) -> dict:
        """Serialize for a transport. Never exposes a direct S3 URL."""
        return {
            "id": self.id,
            "person_id": self.person_id,
            "document_type": self.document_type_code,
            "document_type_label": (
                self.document_type.label if self.document_type else self.document_type_code
            ),
            "original_filename": self.original_filename,
            "view_url": f"/api/people/{self.person_id}/documents/{self.id}/file",
            "mime_type": self.mime_type,
            "file_size_bytes": self.file_size_bytes,
            "uploaded_by": (
                {"id": self.uploaded_by.id, "name": self.uploaded_by.name or ""}
                if self.uploaded_by
                else None
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
