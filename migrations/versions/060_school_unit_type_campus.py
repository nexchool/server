"""school_unit_type_campus

Remove the categorised type enum (nursery/primary/secondary/higher_secondary/other)
from school_units. A unit is now always a campus/branch of the organisation.

Changes:
  - Drop check constraint ck_school_units_type (old enum values)
  - Migrate all existing rows to type = 'campus'
  - Add new check constraint allowing only 'campus'
  - Change column default to 'campus'

Revision ID: 060_school_unit_type_campus
Revises: 059_hostel_room_floor
Create Date: 2026-05-12

"""
from alembic import op
import sqlalchemy as sa


revision = "060_school_unit_type_campus"
down_revision = "059_hostel_room_floor"
branch_labels = None
depends_on = None


def upgrade():
    # Drop old check constraint that restricted to nursery/primary/secondary/etc.
    op.drop_constraint("ck_school_units_type", "school_units", type_="check")

    # Migrate all existing rows to the new uniform value.
    op.execute("UPDATE school_units SET type = 'campus'")

    # Add new constraint — units are always campus branches.
    op.create_check_constraint(
        "ck_school_units_type",
        "school_units",
        "type IN ('campus')",
    )

    # Update column default.
    op.alter_column(
        "school_units",
        "type",
        existing_type=sa.String(20),
        server_default="campus",
        existing_nullable=False,
    )


def downgrade():
    op.drop_constraint("ck_school_units_type", "school_units", type_="check")

    # Restore the old constraint — all migrated rows become 'other'.
    op.execute(
        "UPDATE school_units SET type = 'other' WHERE type = 'campus'"
    )

    op.create_check_constraint(
        "ck_school_units_type",
        "school_units",
        "type IN ('nursery','primary','secondary','higher_secondary','other')",
    )

    op.alter_column(
        "school_units",
        "type",
        existing_type=sa.String(20),
        server_default="other",
        existing_nullable=False,
    )
