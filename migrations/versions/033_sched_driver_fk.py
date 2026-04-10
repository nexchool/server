"""Schedule driver_id references transport_drivers (same as bus assignments).

Revision ID: 033_sched_driver_fk
Revises: 032_transport_fee_cycle
Create Date: 2026-04-10

Existing schedule rows used transport_staff IDs in driver_id; those cannot be
reinterpreted as transport_drivers IDs. Clears schedule tables before retargeting FKs.

Note: revision id must stay <= 32 chars (alembic_version.version_num).
"""

from alembic import op


revision = "033_sched_driver_fk"
down_revision = "032_transport_fee_cycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM transport_schedule_exceptions")
    op.execute("DELETE FROM transport_route_schedules")
    op.drop_constraint(
        "transport_route_schedules_driver_id_fkey",
        "transport_route_schedules",
        type_="foreignkey",
    )
    op.drop_constraint(
        "transport_schedule_exceptions_driver_id_fkey",
        "transport_schedule_exceptions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "transport_route_schedules_driver_id_fkey",
        "transport_route_schedules",
        "transport_drivers",
        ["driver_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "transport_schedule_exceptions_driver_id_fkey",
        "transport_schedule_exceptions",
        "transport_drivers",
        ["driver_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "transport_route_schedules_driver_id_fkey",
        "transport_route_schedules",
        type_="foreignkey",
    )
    op.drop_constraint(
        "transport_schedule_exceptions_driver_id_fkey",
        "transport_schedule_exceptions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "transport_route_schedules_driver_id_fkey",
        "transport_route_schedules",
        "transport_staff",
        ["driver_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "transport_schedule_exceptions_driver_id_fkey",
        "transport_schedule_exceptions",
        "transport_staff",
        ["driver_id"],
        ["id"],
        ondelete="SET NULL",
    )
