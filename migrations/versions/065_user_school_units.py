"""user_school_units association table for per-sub-admin branch scoping

Creates the user_school_units join table. No rows for a user means the user is
unrestricted (all units); one or more rows restrict the user to those units.

Revision ID: 065_user_school_units
Revises: 064_remove_school_setup_from_admin
Create Date: 2026-05-29
"""

from alembic import op
import sqlalchemy as sa


revision = "065_user_school_units"
down_revision = "064_remove_school_setup_from_admin"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_school_units",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "school_unit_id",
            sa.String(36),
            sa.ForeignKey("school_units.id", ondelete="CASCADE"),
            nullable=False,
        ),
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
        sa.UniqueConstraint(
            "user_id", "school_unit_id", "tenant_id",
            name="uq_user_school_unit",
        ),
    )
    op.create_index(
        "ix_user_school_units_user_id",
        "user_school_units",
        ["user_id"],
    )
    op.create_index(
        "ix_user_school_units_school_unit_id",
        "user_school_units",
        ["school_unit_id"],
    )


def downgrade():
    op.drop_index("ix_user_school_units_school_unit_id", table_name="user_school_units")
    op.drop_index("ix_user_school_units_user_id", table_name="user_school_units")
    op.drop_table("user_school_units")
