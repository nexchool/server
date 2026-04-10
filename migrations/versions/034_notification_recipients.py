"""Notification recipients for scalable bulk delivery; nullable notifications.user_id.

Revision ID: 034_notif_recipients
Revises: 033_sched_driver_fk
Create Date: 2026-04-10
"""

from alembic import op
import sqlalchemy as sa


revision = "034_notif_recipients"
down_revision = "033_sched_driver_fk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_recipients",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("notification_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["notification_id"], ["notifications.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_notification_recipients_notification_id"),
        "notification_recipients",
        ["notification_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notification_recipients_user_id"),
        "notification_recipients",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notification_recipients_status"),
        "notification_recipients",
        ["status"],
        unique=False,
    )
    op.create_index(
        "uq_notification_recipient_user",
        "notification_recipients",
        ["notification_id", "user_id"],
        unique=True,
    )

    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.alter_column(
            "user_id",
            existing_type=sa.String(length=36),
            nullable=True,
        )


def downgrade() -> None:
    op.drop_index("uq_notification_recipient_user", table_name="notification_recipients")
    op.drop_index(op.f("ix_notification_recipients_status"), table_name="notification_recipients")
    op.drop_index(op.f("ix_notification_recipients_user_id"), table_name="notification_recipients")
    op.drop_index(op.f("ix_notification_recipients_notification_id"), table_name="notification_recipients")
    op.drop_table("notification_recipients")

    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.alter_column(
            "user_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )
