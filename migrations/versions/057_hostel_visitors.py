"""Hostel visitors and visitor logs tables.

- hostel_visitors: repeat-visitor profile (phone-based identity).
- hostel_visitor_logs: each check-in/check-out event.

Both tenant-scoped. Logs are soft-deleted only (audit trail preserved).

Revision ID: 057_hostel_visitors
Revises: 056_hostel_allocations
Create Date: 2026-05-11

"""

from alembic import op
import sqlalchemy as sa


revision = "057_hostel_visitors"
down_revision = "056_hostel_allocations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # hostel_visitors: repeat-visitor profile
    op.create_table(
        "hostel_visitors",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("relation_type", sa.String(50), nullable=True),  # father, mother, sibling, other
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
        sa.UniqueConstraint("tenant_id", "phone", name="uq_hostel_visitors_tenant_phone"),
    )
    op.create_index(
        "ix_hostel_visitors_tenant_id", "hostel_visitors", ["tenant_id"]
    )

    # hostel_visitor_logs: each check-in/check-out event
    op.create_table(
        "hostel_visitor_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "visitor_id",
            sa.String(36),
            sa.ForeignKey("hostel_visitors.id", ondelete="CASCADE"),
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
            sa.ForeignKey("hostel_rooms.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("check_in_at", sa.DateTime(), nullable=False),
        sa.Column("check_out_at", sa.DateTime(), nullable=True),
        sa.Column("purpose", sa.String(200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_hostel_visitor_logs_tenant_id",
        "hostel_visitor_logs",
        ["tenant_id"],
    )
    op.create_index(
        "ix_hostel_visitor_logs_visitor_id",
        "hostel_visitor_logs",
        ["visitor_id"],
    )
    op.create_index(
        "ix_hostel_visitor_logs_student_id",
        "hostel_visitor_logs",
        ["student_id"],
    )
    # Index for "currently inside" query (check_out_at IS NULL)
    op.create_index(
        "ix_hostel_visitor_logs_check_out_at",
        "hostel_visitor_logs",
        ["check_out_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_hostel_visitor_logs_check_out_at",
        table_name="hostel_visitor_logs",
    )
    op.drop_index(
        "ix_hostel_visitor_logs_student_id",
        table_name="hostel_visitor_logs",
    )
    op.drop_index(
        "ix_hostel_visitor_logs_visitor_id",
        table_name="hostel_visitor_logs",
    )
    op.drop_index(
        "ix_hostel_visitor_logs_tenant_id",
        table_name="hostel_visitor_logs",
    )
    op.drop_table("hostel_visitor_logs")
    op.drop_index("ix_hostel_visitors_tenant_id", table_name="hostel_visitors")
    op.drop_table("hostel_visitors")
