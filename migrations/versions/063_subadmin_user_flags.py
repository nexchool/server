"""users.is_suspended + users.deleted_at + roles.is_subadmin

Revision ID: 063_subadmin_user_flags
Revises: 062_announcements
Create Date: 2026-05-29
"""

from alembic import op
import sqlalchemy as sa


revision = "063_subadmin_user_flags"
down_revision = "062_announcements"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column(
            "is_suspended",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "deleted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "roles",
        sa.Column(
            "is_subadmin",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade():
    op.drop_column("roles", "is_subadmin")
    op.drop_column("users", "deleted_at")
    op.drop_column("users", "is_suspended")
