"""Fee cycle on transport enrollments and fee plans.

Revision ID: 032_transport_fee_cycle
Revises: 031_transport_schedules
Create Date: 2026-04-10
"""

from alembic import op
import sqlalchemy as sa


revision = "032_transport_fee_cycle"
down_revision = "031_transport_schedules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transport_enrollments",
        sa.Column(
            "fee_cycle",
            sa.String(20),
            nullable=True,
            server_default="monthly",
        ),
    )
    op.create_check_constraint(
        "ck_transport_enrollments_fee_cycle",
        "transport_enrollments",
        "fee_cycle IS NULL OR fee_cycle IN ('monthly', 'quarterly', 'half_yearly', 'yearly')",
    )

    op.add_column(
        "transport_fee_plans",
        sa.Column(
            "fee_cycle",
            sa.String(20),
            nullable=True,
            server_default="monthly",
        ),
    )
    op.create_check_constraint(
        "ck_transport_fee_plans_fee_cycle",
        "transport_fee_plans",
        "fee_cycle IS NULL OR fee_cycle IN ('monthly', 'quarterly', 'half_yearly', 'yearly')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_transport_fee_plans_fee_cycle", "transport_fee_plans", type_="check")
    op.drop_column("transport_fee_plans", "fee_cycle")
    op.drop_constraint("ck_transport_enrollments_fee_cycle", "transport_enrollments", type_="check")
    op.drop_column("transport_enrollments", "fee_cycle")
