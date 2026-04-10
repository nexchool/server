"""Transport module tables, student flag, transport-only fee structures.

Revision ID: 026_transport_module
Revises: 025_student_ext_profile
Create Date: 2026-04-08
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "026_transport_module"
down_revision = "025_student_ext_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "students",
        sa.Column(
            "is_transport_opted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "fee_structures",
        sa.Column(
            "is_transport_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.create_table(
        "transport_buses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bus_number", sa.String(50), nullable=False),
        sa.Column("vehicle_number", sa.String(50), nullable=True),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "bus_number", name="uq_transport_buses_tenant_bus_number"),
    )
    op.create_index("ix_transport_buses_tenant_id", "transport_buses", ["tenant_id"])

    op.create_table(
        "transport_drivers",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("alternate_phone", sa.String(20), nullable=True),
        sa.Column("license_number", sa.String(80), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_transport_drivers_tenant_id", "transport_drivers", ["tenant_id"])

    op.create_table(
        "transport_routes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("start_point", sa.String(255), nullable=True),
        sa.Column("end_point", sa.String(255), nullable=True),
        sa.Column("approx_stops", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("pickup_time", sa.Time(), nullable=True),
        sa.Column("drop_time", sa.Time(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_transport_routes_tenant_id", "transport_routes", ["tenant_id"])

    op.create_table(
        "transport_bus_assignments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bus_id", sa.String(36), sa.ForeignKey("transport_buses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("driver_id", sa.String(36), sa.ForeignKey("transport_drivers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("route_id", sa.String(36), sa.ForeignKey("transport_routes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_transport_bus_assignments_tenant_id", "transport_bus_assignments", ["tenant_id"])
    op.create_index("ix_transport_bus_assignments_bus_id", "transport_bus_assignments", ["bus_id"])
    op.create_index("ix_transport_bus_assignments_route_id", "transport_bus_assignments", ["route_id"])

    op.create_table(
        "transport_enrollments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("students.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bus_id", sa.String(36), sa.ForeignKey("transport_buses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("route_id", sa.String(36), sa.ForeignKey("transport_routes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pickup_point", sa.String(255), nullable=True),
        sa.Column("drop_point", sa.String(255), nullable=True),
        sa.Column("monthly_fee", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column(
            "student_fee_id",
            sa.String(36),
            sa.ForeignKey("student_fees.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_transport_enrollments_tenant_id", "transport_enrollments", ["tenant_id"])
    op.create_index("ix_transport_enrollments_student_id", "transport_enrollments", ["student_id"])
    op.create_index("ix_transport_enrollments_bus_id", "transport_enrollments", ["bus_id"])

    op.create_table(
        "transport_fee_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("route_id", sa.String(36), sa.ForeignKey("transport_routes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("tenant_id", "route_id", name="uq_transport_fee_plans_tenant_route"),
    )

    # Partial unique: one active enrollment per student per tenant
    op.execute(
        """
        CREATE UNIQUE INDEX uq_transport_enrollment_active_student
        ON transport_enrollments (tenant_id, student_id)
        WHERE status = 'active'
        """
    )
    # Partial unique: one active assignment per bus per tenant
    op.execute(
        """
        CREATE UNIQUE INDEX uq_transport_assignment_active_bus
        ON transport_bus_assignments (tenant_id, bus_id)
        WHERE status = 'active'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_transport_assignment_active_bus")
    op.execute("DROP INDEX IF EXISTS uq_transport_enrollment_active_student")

    op.drop_table("transport_fee_plans")
    op.drop_table("transport_enrollments")
    op.drop_table("transport_bus_assignments")
    op.drop_table("transport_routes")
    op.drop_table("transport_drivers")
    op.drop_table("transport_buses")

    op.drop_column("fee_structures", "is_transport_only")
    op.drop_column("students", "is_transport_opted")
