"""Transport hardening: stops, staff (helpers), academic years, route status, soft-delete friendly.

Revision ID: 027_transport_hardening
Revises: 026_transport_module
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "027_transport_hardening"
down_revision = "026_transport_module"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Routes: status + updated_at
    op.add_column(
        "transport_routes",
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
    )
    op.add_column(
        "transport_routes",
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )

    # Staff table (helpers/attendants; drivers remain on transport_drivers)
    op.create_table(
        "transport_staff",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("alternate_phone", sa.String(20), nullable=True),
        sa.Column("role", sa.String(30), nullable=False, server_default="helper"),
        sa.Column("license_number", sa.String(80), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_transport_staff_tenant_id", "transport_staff", ["tenant_id"])
    op.create_index("ix_transport_staff_tenant_role", "transport_staff", ["tenant_id", "role"])

    # Assignment: optional helper
    op.add_column(
        "transport_bus_assignments",
        sa.Column(
            "helper_staff_id",
            sa.String(36),
            sa.ForeignKey("transport_staff.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_transport_bus_assignments_helper_staff_id",
        "transport_bus_assignments",
        ["helper_staff_id"],
    )

    # Stops master
    op.create_table(
        "transport_stops",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("route_id", sa.String(36), sa.ForeignKey("transport_routes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("sequence_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pickup_time", sa.Time(), nullable=True),
        sa.Column("drop_time", sa.Time(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_transport_stops_tenant_route", "transport_stops", ["tenant_id", "route_id"])

    # Enrollments: academic year + stop FKs
    op.add_column(
        "transport_enrollments",
        sa.Column(
            "academic_year_id",
            sa.String(36),
            sa.ForeignKey("academic_years.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column(
        "transport_enrollments",
        sa.Column(
            "pickup_stop_id",
            sa.String(36),
            sa.ForeignKey("transport_stops.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "transport_enrollments",
        sa.Column(
            "drop_stop_id",
            sa.String(36),
            sa.ForeignKey("transport_stops.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_transport_enrollments_academic_year_id", "transport_enrollments", ["academic_year_id"])

    # Backfill academic_year_id from students, then active year, then latest year per tenant
    op.execute(
        """
        UPDATE transport_enrollments te
        SET academic_year_id = s.academic_year_id
        FROM students s
        WHERE te.student_id = s.id AND te.academic_year_id IS NULL AND s.academic_year_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE transport_enrollments te
        SET academic_year_id = (
            SELECT ay.id FROM academic_years ay
            WHERE ay.tenant_id = te.tenant_id AND ay.is_active = true
            ORDER BY ay.start_date DESC NULLS LAST
            LIMIT 1
        )
        WHERE te.academic_year_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE transport_enrollments te
        SET academic_year_id = (
            SELECT ay.id FROM academic_years ay
            WHERE ay.tenant_id = te.tenant_id
            ORDER BY ay.start_date DESC NULLS LAST
            LIMIT 1
        )
        WHERE te.academic_year_id IS NULL
        """
    )
    op.alter_column("transport_enrollments", "academic_year_id", nullable=False)

    # Fee plans: academic year (drop old unique, add new)
    op.add_column(
        "transport_fee_plans",
        sa.Column(
            "academic_year_id",
            sa.String(36),
            sa.ForeignKey("academic_years.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.drop_constraint("uq_transport_fee_plans_tenant_route", "transport_fee_plans", type_="unique")
    op.execute(
        """
        UPDATE transport_fee_plans tfp
        SET academic_year_id = (
            SELECT ay.id FROM academic_years ay
            WHERE ay.tenant_id = tfp.tenant_id AND ay.is_active = true
            ORDER BY ay.start_date DESC NULLS LAST
            LIMIT 1
        )
        WHERE tfp.academic_year_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE transport_fee_plans tfp
        SET academic_year_id = (
            SELECT ay.id FROM academic_years ay
            WHERE ay.tenant_id = tfp.tenant_id
            ORDER BY ay.start_date DESC NULLS LAST
            LIMIT 1
        )
        WHERE tfp.academic_year_id IS NULL
        """
    )
    op.alter_column("transport_fee_plans", "academic_year_id", nullable=False)
    op.create_unique_constraint(
        "uq_transport_fee_plans_tenant_route_year",
        "transport_fee_plans",
        ["tenant_id", "route_id", "academic_year_id"],
    )

    # Buses: updated_at for operational tracking
    op.add_column(
        "transport_buses",
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_column("transport_buses", "updated_at")
    op.drop_constraint("uq_transport_fee_plans_tenant_route_year", "transport_fee_plans", type_="unique")
    op.create_unique_constraint(
        "uq_transport_fee_plans_tenant_route",
        "transport_fee_plans",
        ["tenant_id", "route_id"],
    )
    op.drop_column("transport_fee_plans", "academic_year_id")
    op.drop_index("ix_transport_enrollments_academic_year_id", table_name="transport_enrollments")
    op.drop_column("transport_enrollments", "drop_stop_id")
    op.drop_column("transport_enrollments", "pickup_stop_id")
    op.drop_column("transport_enrollments", "academic_year_id")
    op.drop_table("transport_stops")
    op.drop_index("ix_transport_bus_assignments_helper_staff_id", table_name="transport_bus_assignments")
    op.drop_column("transport_bus_assignments", "helper_staff_id")
    op.drop_table("transport_staff")
    op.drop_column("transport_routes", "updated_at")
    op.drop_column("transport_routes", "status")
