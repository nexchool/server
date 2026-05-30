"""announcements + announcement_revisions + announcement_attachments

Revision ID: 062_announcements
Revises: 061_student_leaves
Create Date: 2026-05-28
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "062_announcements"
down_revision = "061_student_leaves"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "announcements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("body_markdown", sa.Text, nullable=False),
        sa.Column("audience_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recalled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("recalled_reason", sa.Text, nullable=True),
        sa.Column(
            "author_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("revision_count", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'scheduled', 'published', 'recalled')",
            name="ck_announcements_status",
        ),
    )
    op.create_index(
        "ix_announcements_tenant_status", "announcements", ["tenant_id", "status"]
    )
    op.create_index(
        "ix_announcements_scheduled_due", "announcements", ["status", "scheduled_at"]
    )

    op.create_table(
        "announcement_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "announcement_id",
            sa.String(36),
            sa.ForeignKey("announcements.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("revision_number", sa.Integer, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("body_markdown", sa.Text, nullable=False),
        sa.Column(
            "edited_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "edited_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("edit_note", sa.Text, nullable=True),
        sa.UniqueConstraint(
            "announcement_id",
            "revision_number",
            name="uq_announcement_revision_number",
        ),
    )

    op.create_table(
        "announcement_attachments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "announcement_id",
            sa.String(36),
            sa.ForeignKey("announcements.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("s3_key", sa.Text, nullable=False),
        sa.Column("original_filename", sa.Text, nullable=True),
        sa.Column("content_type", sa.String(128), nullable=True),
        sa.Column("size_bytes", sa.Integer, nullable=True),
        sa.Column(
            "uploaded_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_announcement_attachments_orphans",
        "announcement_attachments",
        ["announcement_id", "created_at"],
    )


def downgrade():
    op.drop_index(
        "ix_announcement_attachments_orphans", table_name="announcement_attachments"
    )
    op.drop_table("announcement_attachments")
    op.drop_table("announcement_revisions")
    op.drop_index("ix_announcements_scheduled_due", table_name="announcements")
    op.drop_index("ix_announcements_tenant_status", table_name="announcements")
    op.drop_table("announcements")
