"""Global stop fields; route_id nullable (junction follows in 029).

Revision ID: 028_transport_stops_global
Revises: 027_transport_hardening
Create Date: 2026-04-10
"""

from alembic import op
import sqlalchemy as sa


revision = "028_transport_stops_global"
down_revision = "027_transport_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("transport_stops", sa.Column("area", sa.String(100), nullable=True))
    op.add_column("transport_stops", sa.Column("landmark", sa.String(300), nullable=True))
    op.add_column("transport_stops", sa.Column("latitude", sa.Numeric(10, 7), nullable=True))
    op.add_column("transport_stops", sa.Column("longitude", sa.Numeric(10, 7), nullable=True))
    op.create_index(
        "ix_transport_stops_tenant_area",
        "transport_stops",
        ["tenant_id", "area"],
    )
    op.alter_column(
        "transport_stops",
        "route_id",
        existing_type=sa.String(36),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "transport_stops",
        "route_id",
        existing_type=sa.String(36),
        nullable=False,
    )
    op.drop_index("ix_transport_stops_tenant_area", table_name="transport_stops")
    op.drop_column("transport_stops", "longitude")
    op.drop_column("transport_stops", "latitude")
    op.drop_column("transport_stops", "landmark")
    op.drop_column("transport_stops", "area")
