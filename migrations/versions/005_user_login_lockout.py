"""User login lockout fields for max_login_attempts (tenant logins only).

Revision ID: 005_user_login_lockout
Revises: 004_platform_settings
Create Date: 2025-02-21

"""
from alembic import op
import sqlalchemy as sa

revision = "005_user_login_lockout"
down_revision = "004_platform_settings"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("login_locked_until", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_column("users", "login_locked_until")
    op.drop_column("users", "failed_login_count")
