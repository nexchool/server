"""Platform settings table for super admin config.

Revision ID: 004_platform_settings
Revises: 003_platform_admin
Create Date: 2025-02-21

"""
from alembic import op
import sqlalchemy as sa

revision = "004_platform_settings"
down_revision = "003_platform_admin"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "platform_settings",
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade():
    op.drop_table("platform_settings")
