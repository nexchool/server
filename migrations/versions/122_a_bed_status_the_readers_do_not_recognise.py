"""A bed's status must be one the readers recognise.

`hostel_beds.status` is the bed's own lifecycle — `active` / `maintenance` /
`removed` — and that is the vocabulary the model defaults to and the vocabulary
admin-web's `BedStatus` declares. The demo seeder wrote `available` and
`occupied` instead, conflating lifecycle with whether the bed is taken. Whether
a bed is taken is `is_allocated`; it always was.

Nothing in the application ever wrote those two values, so this repairs seeded
data rather than a shipped feature — but it repairs it wherever the seeder ran,
which is why it is a migration and not a local UPDATE.

The damage was silent and total: every reader that filters on status stopped
seeing the beds.

  - `ReportService._count_active_beds` filters `status == "active"`, so
    `total_beds` came back 0 for every hostel. The hostels screen rendered
    "12/0 (0%)" — twelve residents in zero beds.
  - admin-web's room detail sorts beds by `status === "active"` and flags
    `maintenance`, so no seeded bed was ever treated as active.

`occupied` maps to `active`: those beds exist and are usable, they simply have
someone in them, which `is_allocated` already records. `available` maps to
`active` for the same reason.

The downgrade reconstructs the old values from `is_allocated` — the one bit
that distinguished them — so it round-trips faithfully. Only rows still holding
the two bad values are touched, so re-running is a no-op and a bed legitimately
set to `maintenance` or `removed` is left alone.
"""

from alembic import op

revision = "122_a_bed_status_the_readers_do_not_recognise"
down_revision = "121_a_scoped_list_should_not_scan_the_school"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        UPDATE hostel_beds
           SET status = 'active'
         WHERE status IN ('available', 'occupied')
        """
    )


def downgrade():
    op.execute(
        """
        UPDATE hostel_beds
           SET status = CASE WHEN is_allocated THEN 'occupied' ELSE 'available' END
         WHERE status = 'active'
        """
    )
