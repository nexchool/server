"""Recurring route schedules and one-off schedule exceptions.

Revision ID: 031_transport_schedules
Revises: 030_transport_route_fields
Create Date: 2026-04-10
"""

from alembic import op
import sqlalchemy as sa


revision = "031_transport_schedules"
down_revision = "030_transport_route_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transport_route_schedules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "route_id",
            sa.String(36),
            sa.ForeignKey("transport_routes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "bus_id",
            sa.String(36),
            sa.ForeignKey("transport_buses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "driver_id",
            sa.String(36),
            sa.ForeignKey("transport_staff.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "helper_id",
            sa.String(36),
            sa.ForeignKey("transport_staff.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("shift_type", sa.String(10), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column(
            "academic_year_id",
            sa.String(36),
            sa.ForeignKey("academic_years.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "is_reverse_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "reverse_of_schedule_id",
            sa.String(36),
            sa.ForeignKey("transport_route_schedules.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("end_time > start_time", name="ck_transport_route_schedules_time_order"),
        sa.CheckConstraint("shift_type IN ('pickup', 'drop')", name="ck_transport_route_schedules_shift"),
    )
    op.create_index(
        "ix_trs_tenant_driver_year",
        "transport_route_schedules",
        ["tenant_id", "driver_id", "academic_year_id"],
    )
    op.create_index(
        "ix_trs_tenant_bus_year",
        "transport_route_schedules",
        ["tenant_id", "bus_id", "academic_year_id"],
    )
    op.create_index(
        "ix_trs_tenant_route_year",
        "transport_route_schedules",
        ["tenant_id", "route_id", "academic_year_id"],
    )

    op.create_table(
        "transport_schedule_exceptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "academic_year_id",
            sa.String(36),
            sa.ForeignKey("academic_years.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("exception_date", sa.Date(), nullable=False),
        sa.Column("exception_type", sa.String(20), nullable=False),
        sa.Column(
            "route_id",
            sa.String(36),
            sa.ForeignKey("transport_routes.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "bus_id",
            sa.String(36),
            sa.ForeignKey("transport_buses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "driver_id",
            sa.String(36),
            sa.ForeignKey("transport_staff.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "helper_id",
            sa.String(36),
            sa.ForeignKey("transport_staff.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("shift_type", sa.String(10), nullable=True),
        sa.Column("start_time", sa.Time(), nullable=True),
        sa.Column("end_time", sa.Time(), nullable=True),
        sa.Column(
            "schedule_id",
            sa.String(36),
            sa.ForeignKey("transport_route_schedules.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "exception_type IN ('override', 'cancellation')",
            name="ck_transport_schedule_exceptions_type",
        ),
    )
    op.create_index(
        "ix_tse_tenant_year_date",
        "transport_schedule_exceptions",
        ["tenant_id", "academic_year_id", "exception_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_tse_tenant_year_date", table_name="transport_schedule_exceptions")
    op.drop_table("transport_schedule_exceptions")
    op.drop_index("ix_trs_tenant_route_year", table_name="transport_route_schedules")
    op.drop_index("ix_trs_tenant_bus_year", table_name="transport_route_schedules")
    op.drop_index("ix_trs_tenant_driver_year", table_name="transport_route_schedules")
    op.drop_table("transport_route_schedules")
