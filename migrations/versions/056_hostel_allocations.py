"""Hostel allocations table.

Tracks student → bed assignments with check-in/check-out times.
Soft-delete + tenant-scoped. Enforces single active allocation per bed.

Revision ID: 056_hostel_allocations
Revises: 055_hostel_module
Create Date: 2026-05-11

"""

from alembic import op
import sqlalchemy as sa


revision = "056_hostel_allocations"
down_revision = "055_hostel_module"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hostel_allocations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "student_id",
            sa.String(36),
            sa.ForeignKey("students.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "hostel_id",
            sa.String(36),
            sa.ForeignKey("hostels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "room_id",
            sa.String(36),
            sa.ForeignKey("hostel_rooms.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "bed_id",
            sa.String(36),
            sa.ForeignKey("hostel_beds.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "academic_year_id",
            sa.String(36),
            sa.ForeignKey("academic_years.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("check_in_at", sa.DateTime(), nullable=False),
        sa.Column("check_out_at", sa.DateTime(), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="active",
        ),  # active, completed, moved
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_hostel_allocations_tenant_id",
        "hostel_allocations",
        ["tenant_id"],
    )
    op.create_index(
        "ix_hostel_allocations_student_id",
        "hostel_allocations",
        ["student_id"],
    )
    op.create_index(
        "ix_hostel_allocations_hostel_id",
        "hostel_allocations",
        ["hostel_id"],
    )
    op.create_index(
        "ix_hostel_allocations_bed_id",
        "hostel_allocations",
        ["bed_id"],
    )
    op.create_index(
        "ix_hostel_allocations_status_check_out_at",
        "hostel_allocations",
        ["status", "check_out_at"],
    )
    # Enforce one active allocation per bed (partial unique index).
    # Active = status='active' AND deleted_at IS NULL.
    op.create_index(
        "uq_hostel_allocations_bed_active",
        "hostel_allocations",
        ["bed_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_hostel_allocations_bed_active", table_name="hostel_allocations")
    op.drop_index("ix_hostel_allocations_status_check_out_at", table_name="hostel_allocations")
    op.drop_index("ix_hostel_allocations_bed_id", table_name="hostel_allocations")
    op.drop_index("ix_hostel_allocations_hostel_id", table_name="hostel_allocations")
    op.drop_index("ix_hostel_allocations_student_id", table_name="hostel_allocations")
    op.drop_index("ix_hostel_allocations_tenant_id", table_name="hostel_allocations")
    op.drop_table("hostel_allocations")
