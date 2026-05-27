"""Announcement, AnnouncementRevision, AnnouncementAttachment models."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB

from core.database import db
from core.models import TenantBaseModel


ANNOUNCEMENT_STATUSES = ("draft", "scheduled", "published", "recalled")
AUDIENCE_SCOPES = ("all", "roles", "classes", "students")
KNOWN_AUDIENCE_ROLES = ("admin", "teacher", "student", "parent")


class Announcement(TenantBaseModel):
    """Owner record (latest state). Append-only revision rows in AnnouncementRevision."""

    __tablename__ = "announcements"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title = db.Column(db.Text, nullable=False)
    body_markdown = db.Column(db.Text, nullable=False)
    audience_json = db.Column(JSONB, nullable=False)
    status = db.Column(db.String(16), nullable=False)
    scheduled_at = db.Column(db.DateTime(timezone=True), nullable=True)
    published_at = db.Column(db.DateTime(timezone=True), nullable=True)
    recalled_at = db.Column(db.DateTime(timezone=True), nullable=True)
    recalled_reason = db.Column(db.Text, nullable=True)
    author_user_id = db.Column(db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    revision_count = db.Column(db.Integer, nullable=False, default=1, server_default=text("1"))
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, server_default=text("now()"), onupdate=datetime.utcnow
    )

    author = db.relationship("User", foreign_keys=[author_user_id])
    revisions = db.relationship(
        "AnnouncementRevision",
        cascade="all, delete-orphan",
        order_by="AnnouncementRevision.revision_number",
        back_populates="announcement",
    )
    attachments = db.relationship(
        "AnnouncementAttachment",
        cascade="all, delete-orphan",
        back_populates="announcement",
    )

    def to_dict(self, *, include_attachments: bool = False):
        data = {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "title": self.title,
            "body_markdown": self.body_markdown,
            "audience_json": self.audience_json,
            "status": self.status,
            "scheduled_at": self.scheduled_at.isoformat() if self.scheduled_at else None,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "recalled_at": self.recalled_at.isoformat() if self.recalled_at else None,
            "recalled_reason": self.recalled_reason,
            "author_user_id": self.author_user_id,
            "author_name": self.author.name if self.author else None,
            "revision_count": self.revision_count,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_attachments:
            data["attachments"] = [a.to_dict() for a in (self.attachments or [])]
        return data

    def __repr__(self):
        return f"<Announcement id={self.id} status={self.status}>"


class AnnouncementRevision(TenantBaseModel):
    """Append-only snapshot of state at each publish/edit."""

    __tablename__ = "announcement_revisions"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    announcement_id = db.Column(
        db.String(36),
        db.ForeignKey("announcements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_number = db.Column(db.Integer, nullable=False)
    title = db.Column(db.Text, nullable=False)
    body_markdown = db.Column(db.Text, nullable=False)
    edited_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    edited_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=text("now()"))
    edit_note = db.Column(db.Text, nullable=True)

    announcement = db.relationship("Announcement", back_populates="revisions")
    edited_by = db.relationship("User", foreign_keys=[edited_by_user_id])

    def to_dict(self):
        return {
            "id": self.id,
            "announcement_id": self.announcement_id,
            "revision_number": self.revision_number,
            "title": self.title,
            "body_markdown": self.body_markdown,
            "edited_by_user_id": self.edited_by_user_id,
            "edited_by_name": self.edited_by.name if self.edited_by else None,
            "edited_at": self.edited_at.isoformat() if self.edited_at else None,
            "edit_note": self.edit_note,
        }


class AnnouncementAttachment(TenantBaseModel):
    """File ref. announcement_id may be NULL for pre-publish drafts; orphan-swept after 24h."""

    __tablename__ = "announcement_attachments"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    announcement_id = db.Column(
        db.String(36),
        db.ForeignKey("announcements.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    s3_key = db.Column(db.Text, nullable=False)
    original_filename = db.Column(db.Text, nullable=True)
    content_type = db.Column(db.String(128), nullable=True)
    size_bytes = db.Column(db.Integer, nullable=True)
    uploaded_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=text("now()"))

    announcement = db.relationship("Announcement", back_populates="attachments")
    uploaded_by = db.relationship("User", foreign_keys=[uploaded_by_user_id])

    def to_dict(self):
        return {
            "id": self.id,
            "announcement_id": self.announcement_id,
            "tenant_id": self.tenant_id,
            "s3_key": self.s3_key,
            "original_filename": self.original_filename,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "uploaded_by_user_id": self.uploaded_by_user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
