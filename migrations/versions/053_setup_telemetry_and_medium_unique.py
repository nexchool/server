"""Setup telemetry on tenants + unique medium-per-tenant.

Revision ID: 053_setup_telemetry_and_medium_unique
Revises: 052_programme_medium_id_fk
Create Date: 2026-05-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "053_setup_telemetry_and_medium_unique"
down_revision = "052_programme_medium_id_fk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("setup_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("setup_completed_by", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column("setup_reconfirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_tenants_setup_completed_by_users",
        "tenants",
        "users",
        ["setup_completed_by"],
        ["id"],
        ondelete="SET NULL",
    )

    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_mediums_tenant_lower_name_active "
        "ON mediums (tenant_id, lower(name)) WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_mediums_tenant_lower_name_active")
    op.drop_constraint(
        "fk_tenants_setup_completed_by_users", "tenants", type_="foreignkey"
    )
    op.drop_column("tenants", "setup_reconfirmed_at")
    op.drop_column("tenants", "setup_completed_by")
    op.drop_column("tenants", "setup_completed_at")
