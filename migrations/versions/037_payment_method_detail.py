"""Add payments.method_detail for \"Other\" payment channel description.

Revision ID: 037_payment_method_detail
Revises: 036_drop_teacher_tt_override
Create Date: 2026-04-13
"""

from alembic import op
import sqlalchemy as sa


revision = "037_payment_method_detail"
down_revision = "036_drop_teacher_tt_override"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("method_detail", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("payments", "method_detail")
