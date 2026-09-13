"""Rooms come with their beds.

A hostel room's ``capacity`` is a promise of places; an allocation needs an
actual ``hostel_beds`` row to point at (``bed_id`` is NOT NULL). Until now the
rows were entered by hand after the room, one at a time — so a hostel of seven
rooms and 24 places routinely had no bed to allocate anyone to, while its room
cards read "3 free" and its listing card read "0 vacant".

``FacilityService.provision_beds`` now creates the beds when a room is created
or enlarged. This migration is the same top-up for every room that already
exists: each live room with fewer standing beds than its capacity receives the
difference, numbered ``1..n`` and skipping any number the room already uses —
a retired bed keeps its number (the unique constraint ignores ``deleted_at``),
and beds a warden named by hand keep their names.

The work is in ``backfill_beds(conn)`` rather than inline in ``upgrade`` so a
test can run it against a transactional connection.

The downgrade is deliberately a no-op. The beds this adds are indistinguishable
from ones a warden would have entered, and by the time anyone downgrades some
may hold students; deleting them would be destructive, and leaving them is
harmless — they are exactly the beds the room's capacity always claimed.
"""

import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "138_rooms_come_with_their_beds"
down_revision = "137_tenant_seat_limits"
branch_labels = None
depends_on = None


def backfill_beds(conn) -> int:
    """Top every live room up to its capacity. Returns the number of beds added."""
    rooms = conn.execute(
        sa.text(
            """
            SELECT r.id, r.tenant_id, r.capacity,
                   COUNT(b.id) FILTER (WHERE b.deleted_at IS NULL) AS standing,
                   COALESCE(ARRAY_AGG(b.bed_number) FILTER (WHERE b.id IS NOT NULL), '{}') AS taken
            FROM hostel_rooms r
            LEFT JOIN hostel_beds b ON b.room_id = r.id AND b.tenant_id = r.tenant_id
            WHERE r.deleted_at IS NULL
            GROUP BY r.id, r.tenant_id, r.capacity
            HAVING r.capacity > COUNT(b.id) FILTER (WHERE b.deleted_at IS NULL)
            """
        )
    ).all()

    # `id` and `created_at` are NOT NULL and their defaults live in Python, so
    # a raw INSERT has to supply them.
    now = datetime.now(timezone.utc)
    added = 0
    for room_id, tenant_id, capacity, standing, taken in rooms:
        taken = set(taken or [])
        missing = capacity - standing
        candidate = 1
        while missing > 0:
            label = str(candidate)
            candidate += 1
            if label in taken:
                continue
            conn.execute(
                sa.text(
                    """
                    INSERT INTO hostel_beds
                        (id, tenant_id, room_id, bed_number, is_allocated, status, created_at, updated_at)
                    VALUES
                        (:id, :tenant_id, :room_id, :bed_number, false, 'active', :now, :now)
                    """
                ),
                {"id": str(uuid.uuid4()), "tenant_id": tenant_id, "room_id": room_id,
                 "bed_number": label, "now": now},
            )
            missing -= 1
            added += 1
    return added


def upgrade():
    backfill_beds(op.get_bind())


def downgrade():
    # See the module docstring: the added beds cannot be told apart from
    # hand-entered ones, and removing beds that may now hold students would be
    # destructive. Nothing to undo that is safe to undo.
    pass
