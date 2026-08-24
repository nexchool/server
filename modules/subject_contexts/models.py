"""Subject context: how a (programme, grade) offers a subject."""

from __future__ import annotations

import uuid

from sqlalchemy import text

from core.database import db
from core.models import TenantBaseModel


CONTEXT_TYPES = ("mandatory", "elective")
CONTEXT_ROLES = (
    "first_language",
    "second_language",
    "third_language",
    "core",
    "co_curricular",
)


class SubjectContext(TenantBaseModel):
    """One offering: how a (programme, grade) uses a subject."""

    __tablename__ = "subject_contexts"

    id = db.Column(
        db.String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    programme_id = db.Column(
        db.String(36),
        db.ForeignKey("academic_programmes.id", ondelete="CASCADE"),
        nullable=False,
    )
    grade_id = db.Column(
        db.String(36),
        db.ForeignKey("grades.id", ondelete="CASCADE"),
        nullable=False,
    )
    subject_id = db.Column(
        db.String(36),
        db.ForeignKey("subjects.id", ondelete="RESTRICT"),
        nullable=False,
    )
    display_name = db.Column(db.String(160), nullable=True)
    short_code = db.Column(db.String(32), nullable=True)
    exam_code = db.Column(
        db.String(20),
        nullable=True,
        comment="Board paper number for this (programme, grade, subject).",
    )
    type = db.Column(db.String(16), nullable=False, default="mandatory")
    role = db.Column(db.String(32), nullable=True)
    medium_id = db.Column(
        db.String(36),
        db.ForeignKey("mediums.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Which track this offering belongs to. NULL means it applies to every
    # stream at this (programme, grade) — which is every context that existed
    # before migration 108, and every context in a school with no streams.
    #
    # This is what lets Grade 11 Science offer Physics and Grade 11 Commerce
    # offer Accountancy. Without it both resolve to the same subject set, and
    # so would their examinations.
    stream_id = db.Column(
        db.String(36),
        db.ForeignKey("streams.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    variant_of_context_id = db.Column(
        db.String(36),
        db.ForeignKey("subject_contexts.id", ondelete="SET NULL"),
        nullable=True,
    )
    elective_group_key = db.Column(db.String(80), nullable=True)
    default_weekly_periods = db.Column(
        db.SmallInteger, nullable=False, default=5
    )
    sort_order = db.Column(db.SmallInteger, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    created_by = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by = db.Column(
        db.String(36),
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    subject = db.relationship(
        "Subject", lazy="joined", foreign_keys=[subject_id]
    )

    def to_dict(self):
        subject = self.subject
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "programme_id": self.programme_id,
            "grade_id": self.grade_id,
            "subject_id": self.subject_id,
            "subject_name": subject.name if subject else None,
            "subject_code": subject.code if subject else None,
            "display_name": self.display_name or (subject.name if subject else None),
            "short_code": self.short_code,
            "exam_code": self.exam_code,
            "type": self.type,
            "role": self.role,
            "medium_id": self.medium_id,
            "stream_id": self.stream_id,
            "variant_of_context_id": self.variant_of_context_id,
            "elective_group_key": self.elective_group_key,
            "default_weekly_periods": self.default_weekly_periods,
            "sort_order": self.sort_order,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
