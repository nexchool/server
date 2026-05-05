"""Subscription lifecycle (trial fields) + TenantUsage table.

Revision ID: 047_subscription_and_usage
Revises: 046_setup_softdelete_and_complete
Create Date: 2026-04-30

Adds:
  - tenants.trial_ends_at      (DateTime, nullable)
  - tenants.billing_cycle      (varchar(20), NOT NULL default 'yearly')
  - tenant_usage table         (one row per tenant; tenant_id unique)

Note on schema: the pricing columns required by Phase 5
(price_per_student_per_year, discount_percentage, discount_*_date) are
already present on `tenants` from migration 043, so we extend that table
rather than creating a parallel `tenant_subscriptions` row that would
duplicate them. `tenants.status` already exists; we just allow a new
'trial' value via the application layer (no DB constraint to relax).
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "047_subscription_and_usage"
down_revision = "046_setup_softdelete_and_complete"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── tenants.trial_ends_at, billing_cycle ────────────────────────
    op.add_column(
        "tenants",
        sa.Column("trial_ends_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "tenants",
        sa.Column(
            "billing_cycle",
            sa.String(length=20),
            nullable=False,
            server_default="yearly",
        ),
    )

    # ── tenant_usage ────────────────────────────────────────────────
    op.create_table(
        "tenant_usage",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(length=36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "active_students_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "last_updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_tenant_usage_tenant_id", "tenant_usage", ["tenant_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_tenant_usage_tenant_id", table_name="tenant_usage")
    op.drop_table("tenant_usage")
    op.drop_column("tenants", "billing_cycle")
    op.drop_column("tenants", "trial_ends_at")
