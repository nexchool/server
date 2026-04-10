"""Route fee fields, reverse flag, legacy approx_stops review flag.

Revision ID: 030_transport_route_fields
Revises: 029_transport_route_stops
Create Date: 2026-04-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision = "030_transport_route_fields"
down_revision = "029_transport_route_stops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "transport_routes",
        sa.Column("default_fee", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "transport_routes",
        sa.Column(
            "fee_cycle",
            sa.String(20),
            nullable=True,
            server_default="monthly",
        ),
    )
    op.add_column(
        "transport_routes",
        sa.Column(
            "is_reverse_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "transport_routes",
        sa.Column(
            "approx_stops_needs_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_check_constraint(
        "ck_transport_routes_fee_cycle",
        "transport_routes",
        "fee_cycle IS NULL OR fee_cycle IN ('monthly', 'quarterly', 'half_yearly', 'yearly')",
    )

    op.execute(
        text(
            """
            UPDATE transport_routes
            SET approx_stops_needs_review = true
            WHERE approx_stops IS NOT NULL
              AND trim(approx_stops::text) NOT IN ('null', '[]', '{}', '""')
            """
        )
    )


def downgrade() -> None:
    op.drop_constraint("ck_transport_routes_fee_cycle", "transport_routes", type_="check")
    op.drop_column("transport_routes", "approx_stops_needs_review")
    op.drop_column("transport_routes", "is_reverse_enabled")
    op.drop_column("transport_routes", "fee_cycle")
    op.drop_column("transport_routes", "default_fee")
