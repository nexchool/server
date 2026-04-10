"""Device tokens for push notifications (FCM / Expo).

Revision ID: 035_device_tokens
Revises: 034_notif_recipients
Create Date: 2026-04-10
"""

from alembic import op
import sqlalchemy as sa


revision = "035_device_tokens"
down_revision = "034_notif_recipients"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_tokens",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("device_token", sa.String(length=512), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=20), nullable=False, server_default="expo"),
        sa.Column("app_version", sa.String(length=40), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_device_tokens_user_id"),
        "device_tokens",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_device_tokens_tenant_id"),
        "device_tokens",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_device_tokens_user_tenant",
        "device_tokens",
        ["user_id", "tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_device_tokens_is_active"),
        "device_tokens",
        ["is_active"],
        unique=False,
    )
    op.create_index(
        "uq_device_tokens_device_token",
        "device_tokens",
        ["device_token"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_device_tokens_device_token", table_name="device_tokens")
    op.drop_index(op.f("ix_device_tokens_is_active"), table_name="device_tokens")
    op.drop_index("ix_device_tokens_user_tenant", table_name="device_tokens")
    op.drop_index(op.f("ix_device_tokens_tenant_id"), table_name="device_tokens")
    op.drop_index(op.f("ix_device_tokens_user_id"), table_name="device_tokens")
    op.drop_table("device_tokens")
