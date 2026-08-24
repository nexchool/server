"""Stream Model

The academic track a senior section follows — Science, Commerce, Arts, and
whatever else a school actually offers.

Tenant-owned on purpose. The four common tracks are seeded per tenant, but a
school running "Integrated Science" or "Vocational — IT" must be able to say so
without a deploy: the vocabulary used to be a Python frozenset *and* a database
CHECK constraint, which made every new track a code change. That is the
"configuration, not forks" rule, and it is why this is a table.

A stream is a dimension of a `Class`, not of a Grade — Grades 1-10 have no
stream at all, and it is the section that is "Grade 11 Science A".
"""

import uuid

from sqlalchemy import Index, text

from core.database import db
from core.models import TenantBaseModel
from core.school_time import utc_now


class Stream(TenantBaseModel):
    """An academic track offered by a tenant (Science, Commerce, …)."""

    __tablename__ = "streams"
    __table_args__ = (
        Index(
            "uq_streams_tenant_name_active",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_streams_tenant_code_active",
            "tenant_id",
            "code",
            unique=True,
            postgresql_where=text("code IS NOT NULL AND deleted_at IS NULL"),
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    name = db.Column(db.String(80), nullable=False)
    # Short label for compact displays and imports ("SCI"). Optional: a school
    # that never abbreviates should not be made to invent one.
    code = db.Column(db.String(32), nullable=True)
    sequence = db.Column(db.Integer, nullable=False, default=0, index=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
    # Retiring a stream must not orphan the sections that named it, so a
    # withdrawn stream stops being offered rather than being deleted — the same
    # rule `document_types` and `mediums` follow.
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "code": self.code,
            "sequence": self.sequence,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f"<Stream {self.name}>"
