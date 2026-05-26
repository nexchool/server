"""Add `floor` column to hostel_rooms.

Used by the rooms grid UI to group rooms by floor (Ground Floor,
First Floor, etc.). Nullable for backfill; new rows default to
'Ground Floor'.

Revision ID: 059_hostel_room_floor
Revises: 058_hostel_gatepasses
Create Date: 2026-05-11

"""

from alembic import op
import sqlalchemy as sa


revision = "059_hostel_room_floor"
down_revision = "058_hostel_gatepasses"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "hostel_rooms",
        sa.Column(
            "floor",
            sa.String(50),
            nullable=False,
            server_default="Ground Floor",
        ),
    )
    op.create_index(
        "ix_hostel_rooms_floor",
        "hostel_rooms",
        ["hostel_id", "floor"],
    )


def downgrade() -> None:
    op.drop_index("ix_hostel_rooms_floor", table_name="hostel_rooms")
    op.drop_column("hostel_rooms", "floor")
