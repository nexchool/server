"""payment idempotency_key + per-tenant partial unique index

Adds payments.idempotency_key (nullable) and a per-tenant partial unique index so
a retried / duplicate payment submission carrying the same key cannot create a
second payment. NULL keys (legacy rows and callers that don't pass one) are
unconstrained.

Revision ID: 066_payment_idempotency_key
Revises: 065_user_school_units
Create Date: 2026-06-11
"""

from alembic import op
import sqlalchemy as sa


revision = "066_payment_idempotency_key"
down_revision = "065_user_school_units"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "payments",
        sa.Column("idempotency_key", sa.String(64), nullable=True),
    )
    op.create_index(
        "uq_payments_tenant_idempotency_key",
        "payments",
        ["tenant_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )


def downgrade():
    op.drop_index("uq_payments_tenant_idempotency_key", table_name="payments")
    op.drop_column("payments", "idempotency_key")
