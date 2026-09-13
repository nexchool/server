"""FacilityService — retiring the hostel → room → bed structure.

Hostels and rooms are soft-deleted (``deleted_at``); beds are retired with
``status='removed'`` *and* ``deleted_at``, because readers disagree about which
column means "gone": get_room filters beds on ``deleted_at`` while the
bed-capacity guard below filters on ``status``. Setting both is what
makes a retired bed disappear from every reader rather than only some.

Retiring a container cascades downward. Without it a deleted room left its beds
behind, so bed counts kept including beds in rooms nobody could reach.

Callers check occupancy first (see AllocationService.count_active_residents);
these methods assume nobody is allocated and do not re-check.

It also guards the capacity budget at both levels: the active rooms of a
hostel may never add up to more beds than the hostel itself holds, and a room
may never contain more beds than its own capacity. Retired rooms and beds have
handed their share back and do not count.
"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from core.school_time import utc_now
from modules.hostel.models import Hostel, HostelAllocation, HostelBed, HostelRoom

BED_STATUS_ACTIVE = "active"
BED_STATUS_MAINTENANCE = "maintenance"
BED_STATUS_REMOVED = "removed"
BED_STATUS_VALUES = (BED_STATUS_ACTIVE, BED_STATUS_MAINTENANCE, BED_STATUS_REMOVED)


class FacilityService:
    """Soft-delete of hostels and rooms, cascading to what they contain."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def retire_hostel(self, *, tenant_id: str, hostel: Hostel) -> None:
        """Soft-delete a hostel along with its rooms and their beds."""
        rooms = (
            self.session.query(HostelRoom)
            .filter(
                HostelRoom.tenant_id == tenant_id,
                HostelRoom.hostel_id == hostel.id,
                HostelRoom.deleted_at.is_(None),
            )
            .all()
        )
        for room in rooms:
            self.retire_room(tenant_id=tenant_id, room=room)

        hostel.deleted_at = utc_now()

    def retire_room(self, *, tenant_id: str, room: HostelRoom) -> None:
        """Soft-delete a room and retire every bed in it."""
        self._retire_beds_of(tenant_id=tenant_id, room_id=room.id)
        room.deleted_at = utc_now()

    def retire_bed(self, *, bed: HostelBed) -> None:
        """Retire a single bed, marking it in both columns readers check."""
        bed.status = BED_STATUS_REMOVED
        bed.deleted_at = utc_now()

    def set_bed_status(self, *, bed: HostelBed, status: str) -> None:
        """Move a bed between active, maintenance and removed.

        A bed with a student checked in stays in service until they are
        checked out; "removed" goes through retire_bed so both columns readers
        check are set.
        """
        if status not in BED_STATUS_VALUES:
            raise ValueError(
                f"Bed status must be one of {', '.join(BED_STATUS_VALUES)}"
            )
        if bed.is_allocated and status != BED_STATUS_ACTIVE:
            raise ValueError(
                f"Bed {bed.bed_number} has a student checked in. "
                f"Check them out before taking the bed out of service"
            )
        if status == BED_STATUS_REMOVED:
            self.retire_bed(bed=bed)
            return
        bed.status = status
        bed.deleted_at = None

    def _retire_beds_of(self, *, tenant_id: str, room_id: str) -> None:
        beds = (
            self.session.query(HostelBed)
            .filter(
                HostelBed.tenant_id == tenant_id,
                HostelBed.room_id == room_id,
                HostelBed.deleted_at.is_(None),
            )
            .all()
        )
        for bed in beds:
            self.retire_bed(bed=bed)

    # ------------------------------------------------------------------
    # Capacity budget
    # ------------------------------------------------------------------

    def beds_promised_by_rooms(
        self, *, tenant_id: str, hostel_id: str, exclude_room_id: str | None = None
    ) -> int:
        """Sum of the capacities of the hostel's active rooms.

        ``exclude_room_id`` leaves one room out, so a room being resized is
        measured against its neighbours rather than against its old self.
        """
        query = self.session.query(
            func.coalesce(func.sum(HostelRoom.capacity), 0)
        ).filter(
            HostelRoom.tenant_id == tenant_id,
            HostelRoom.hostel_id == hostel_id,
            HostelRoom.deleted_at.is_(None),
        )
        if exclude_room_id is not None:
            query = query.filter(HostelRoom.id != exclude_room_id)
        return int(query.scalar() or 0)

    def assert_room_capacity_fits(
        self,
        *,
        tenant_id: str,
        hostel: Hostel,
        room_capacity: int,
        exclude_room_id: str | None = None,
    ) -> None:
        """Refuse a room that would push the hostel's rooms past its capacity."""
        taken = self.beds_promised_by_rooms(
            tenant_id=tenant_id, hostel_id=hostel.id, exclude_room_id=exclude_room_id
        )
        remaining = hostel.capacity - taken
        if room_capacity > remaining:
            raise ValueError(
                f"Room capacity exceeds the hostel's remaining capacity: "
                f"{hostel.name} holds {hostel.capacity}, its other rooms already "
                f"take {taken}, so this room can hold at most {max(remaining, 0)}"
            )

    def assert_hostel_capacity_fits(
        self, *, tenant_id: str, hostel: Hostel, new_capacity: int
    ) -> None:
        """Refuse shrinking a hostel below the beds its rooms already hold."""
        taken = self.beds_promised_by_rooms(tenant_id=tenant_id, hostel_id=hostel.id)
        if new_capacity < taken:
            raise ValueError(
                f"Hostel capacity cannot be lower than the {taken} beds its rooms "
                f"already hold"
            )

    def assert_hostel_capacity_holds_residents(
        self, *, tenant_id: str, hostel: Hostel, new_capacity: int
    ) -> None:
        """Refuse shrinking a hostel below the students already living in it."""
        residents = int(
            self.session.query(func.count(HostelAllocation.id))
            .filter(
                HostelAllocation.tenant_id == tenant_id,
                HostelAllocation.hostel_id == hostel.id,
                HostelAllocation.status == HostelAllocation.STATUS_ACTIVE,
                HostelAllocation.deleted_at.is_(None),
            )
            .scalar()
            or 0
        )
        if new_capacity < residents:
            raise ValueError(
                f"Hostel capacity cannot be lower than the {residents} students "
                f"already living in it"
            )

    def provision_beds(self, *, tenant_id: str, room: HostelRoom) -> int:
        """Bring the room's standing beds up to its capacity. Returns how many were added.

        A room's capacity is a promise of places; an allocation needs an
        actual bed row to point at. Until now those rows were entered by hand,
        one at a time, after the room — so a hostel of seven rooms and 24
        places routinely had nowhere to put a student, and its cards said
        "3 free" over rooms nobody could be allocated to. A room now arrives
        with its beds, and grows them when its capacity grows.

        Idempotent: a room already holding its capacity gets nothing. Numbers
        run 1..n and skip any already used in the room — a retired bed keeps
        its number (the unique constraint does not care about ``deleted_at``),
        and a warden who named beds by hand keeps those names.
        """
        standing = self.beds_standing_in_room(tenant_id=tenant_id, room_id=room.id)
        missing = room.capacity - standing
        if missing <= 0:
            return 0
        taken = {
            number
            for (number,) in self.session.query(HostelBed.bed_number).filter(
                HostelBed.tenant_id == tenant_id, HostelBed.room_id == room.id
            )
        }
        added = 0
        candidate = 1
        while added < missing:
            label = str(candidate)
            candidate += 1
            if label in taken:
                continue
            self.session.add(
                HostelBed(tenant_id=tenant_id, room_id=room.id, bed_number=label, status="active")
            )
            added += 1
        self.session.flush()
        return added

    def beds_standing_in_room(self, *, tenant_id: str, room_id: str) -> int:
        """Number of active (non-retired) beds in the room."""
        return int(
            self.session.query(func.count(HostelBed.id))
            .filter(
                HostelBed.tenant_id == tenant_id,
                HostelBed.room_id == room_id,
                HostelBed.deleted_at.is_(None),
            )
            .scalar()
            or 0
        )

    def assert_bed_fits_room(self, *, tenant_id: str, room: HostelRoom) -> None:
        """Refuse a new bed once the room already holds its full capacity."""
        standing = self.beds_standing_in_room(tenant_id=tenant_id, room_id=room.id)
        if standing >= room.capacity:
            raise ValueError(
                f"Room {room.room_number} already holds its full capacity of "
                f"{room.capacity} beds. Raise the room's capacity to add more"
            )

    def assert_room_capacity_holds_beds(
        self, *, tenant_id: str, room: HostelRoom, new_capacity: int
    ) -> None:
        """Refuse shrinking a room below the beds already standing in it."""
        standing = self.beds_standing_in_room(tenant_id=tenant_id, room_id=room.id)
        if new_capacity < standing:
            raise ValueError(
                f"Room capacity cannot be lower than the {standing} beds already "
                f"standing in it. Remove beds first"
            )
