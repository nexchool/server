"""Hostel module tables: hostels, rooms, beds with soft deletes.

Creates three core tables:
- hostels: hostel metadata
- hostel_rooms: rooms within a hostel with capacity
- hostel_beds: individual beds with allocation status

All tables are tenant-scoped and support soft deletes (deleted_at).

Revision ID: 055_hostel_module
Revises: 054_add_medium_id_to_classes
Create Date: 2026-05-11

"""

from alembic import op
import sqlalchemy as sa


revision = "055_hostel_module"
down_revision = "054_add_medium_id_to_classes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Hostels table
    op.create_table(
        "hostels",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("warden_name", sa.String(200), nullable=True),
        sa.Column("warden_phone", sa.String(20), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("tenant_id", "name", name="uq_hostels_tenant_name"),
    )
    op.create_index("ix_hostels_tenant_id", "hostels", ["tenant_id"])

    # Hostel rooms table
    op.create_table(
        "hostel_rooms",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("hostel_id", sa.String(36), sa.ForeignKey("hostels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("room_number", sa.String(50), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("tenant_id", "hostel_id", "room_number", name="uq_hostel_rooms_tenant_hostel_room_number"),
    )
    op.create_index("ix_hostel_rooms_tenant_id", "hostel_rooms", ["tenant_id"])
    op.create_index("ix_hostel_rooms_hostel_id", "hostel_rooms", ["hostel_id"])

    # Hostel beds table
    op.create_table(
        "hostel_beds",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("room_id", sa.String(36), sa.ForeignKey("hostel_rooms.id", ondelete="CASCADE"), nullable=False),
        sa.Column("bed_number", sa.String(50), nullable=False),
        sa.Column("is_allocated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("allocated_to_student_id", sa.String(36), sa.ForeignKey("students.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("tenant_id", "room_id", "bed_number", name="uq_hostel_beds_tenant_room_bed_number"),
    )
    op.create_index("ix_hostel_beds_tenant_id", "hostel_beds", ["tenant_id"])
    op.create_index("ix_hostel_beds_room_id", "hostel_beds", ["room_id"])
    op.create_index("ix_hostel_beds_allocated_to_student_id", "hostel_beds", ["allocated_to_student_id"])


def downgrade() -> None:
    op.drop_table("hostel_beds")
    op.drop_table("hostel_rooms")
    op.drop_table("hostels")
