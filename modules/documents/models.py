"""The document store's tables.

One table serves every domain. A document names its owner as
`(owner_kind, owner_id)` rather than through a per-domain foreign key, which is
what lets the examination module store answer sheets without a migration
(ADR-015). `registry.resolve_tenant` stands in for the integrity the database
cannot enforce across a polymorphic reference.
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
    """A kind of document some owner kind collects, seeded from a catalogue.

    Not tenant-scoped: the vocabulary is the platform's, shared by every school.
    A school needing a type nobody has needed yet gets a catalogue line and a
    reseed rather than a migration.
    """

    __tablename__ = "document_types"

    code = db.Column(db.String(64), primary_key=True)
    # Which owner kind this type belongs to. 'aadhar_card' is a person's;
    # 'answer_sheet' will be an exam submission's. Scoping by kind is what stops
    # one vocabulary from becoming a junk drawer as domains are added.
    owner_kind = db.Column(db.String(40), nullable=False, index=True)
    label = db.Column(db.Text, nullable=False)
    # Sub-groups within the owner kind. JSON and filtered in Python: the
    # catalogue is dozens of rows, so an index costs more than the scan saves.
    contexts = db.Column(db.JSON, nullable=False)
    sequence = db.Column(db.Integer, nullable=False, default=100)
    description = db.Column(db.Text, nullable=False, default="")
    # Retiring a type must not orphan documents already filed under it, so a
    # withdrawn type stops being offered rather than being deleted.
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=_now, onupdate=_now
    )

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "owner_kind": self.owner_kind,
            "label": self.label,
            "contexts": list(self.contexts or []),
            "sequence": self.sequence,
            "description": self.description or "",
        }


class Document(TenantBaseModel):
    """A file a school holds. Bytes in S3, this row is the record."""

    __tablename__ = "documents"

    id = db.Column(db.String(36), primary_key=True, default=_new_id)
    owner_kind = db.Column(db.String(40), nullable=False)
    owner_id = db.Column(db.String(36), nullable=False)
    document_type_code = db.Column(
        db.String(64),
        db.ForeignKey("document_types.code", ondelete="RESTRICT"),
        nullable=False,
    )
    original_filename = db.Column(db.String(255), nullable=False)
    # The S3 object key, tenant-scoped by `storage.build_key`.
    storage_key = db.Column(db.String(500), nullable=False, unique=True)
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

    document_type = db.relationship("DocumentType", lazy="joined")
    uploaded_by = db.relationship("User", foreign_keys=[uploaded_by_user_id])

    __table_args__ = (
        # Every read is "what does this owner hold", and the completeness signal
        # counts distinct types within exactly that set.
        db.Index("idx_documents_owner", "owner_kind", "owner_id"),
        db.Index(
            "idx_documents_owner_type", "owner_kind", "owner_id", "document_type_code"
        ),
    )

    def to_dict(self) -> dict:
        """Serialize for a transport. Never exposes a direct S3 URL."""
        return {
            "id": self.id,
            "owner_kind": self.owner_kind,
            "owner_id": self.owner_id,
            "document_type": self.document_type_code,
            "document_type_label": (
                self.document_type.label
                if self.document_type
                else self.document_type_code
            ),
            "original_filename": self.original_filename,
            "view_url": f"/api/documents/{self.id}/file",
            "mime_type": self.mime_type,
            "file_size_bytes": self.file_size_bytes,
            "uploaded_by": (
                {"id": self.uploaded_by.id, "name": self.uploaded_by.name or ""}
                if self.uploaded_by
                else None
            ),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
