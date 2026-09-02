"""FacilityService — retiring the hostel → room → bed structure.

Hostels and rooms are soft-deleted (``deleted_at``); beds are retired with
``status='removed'`` *and* ``deleted_at``, because readers disagree about which
column means "gone": get_room filters beds on ``deleted_at`` while
ReportService._count_active_beds filters on ``status``. Setting both is what
makes a retired bed disappear from every reader rather than only some.

Retiring a container cascades downward. Without it a deleted room left its beds
behind, so bed counts kept including beds in rooms nobody could reach.

Callers check occupancy first (see AllocationService.count_active_residents);
these methods assume nobody is allocated and do not re-check.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from core.school_time import utc_now
from modules.hostel.models import Hostel, HostelBed, HostelRoom

BED_STATUS_REMOVED = "removed"


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
