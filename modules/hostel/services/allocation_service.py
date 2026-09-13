"""AllocationService — business logic for student → bed assignments.

Encapsulates the rules:
- One active allocation per bed (also enforced at DB by partial unique index).
- One active allocation per student.
- Checkout marks status='completed', sets check_out_at, and frees the bed.
- A move closes the old allocation as status='moved' and opens the new one
  at the same instant, in one transaction.
- All queries are tenant-scoped.

The service operates on an injected SQLAlchemy session so callers can wrap
operations in transactions (e.g., API request scope, background job, test
fixture).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from core.branch_scope import filter_by_student_ids
from modules.hostel.services.paging import MAX_PAGE_SIZE as ALLOCATION_MAX_PAGE_SIZE
from modules.hostel.services.paging import paginate
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from modules.hostel.models import (
    HostelRoom,
    Hostel,
    HostelAllocation,
    HostelBed,
)
from core.school_time import utc_now
from modules.hostel.services.facility_service import BED_STATUS_ACTIVE


class AllocationService:
    """Service layer around HostelAllocation lifecycle."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_allocation(
        self,
        *,
        tenant_id: str,
        student_id: str,
        hostel_id: str,
        room_id: str,
        bed_id: str,
        check_in_at: datetime,
        academic_year_id: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> HostelAllocation:
        """Allocate a student to a bed.

        Raises:
            ValueError: bed not found / already occupied, or student already
                has an active allocation.
        """
        bed = self._get_bed(tenant_id=tenant_id, bed_id=bed_id)
        if bed is None:
            raise ValueError(f"Bed {bed_id!r} not found")

        # A retired bed or one under maintenance is not a place to put a
        # student, and the room and hostel named must be the bed's own:
        # residents are counted per room_id and hostel_id, so an allocation
        # filed under the wrong room lets that room carry more residents than
        # it has beds.
        if bed.deleted_at is not None or bed.status != BED_STATUS_ACTIVE:
            raise ValueError(f"Bed {bed.bed_number} is not available")
        if bed.room_id != room_id:
            raise ValueError(f"Bed {bed.bed_number} is not in room {room_id!r}")
        room = self.session.get(HostelRoom, room_id)
        if room is None or room.deleted_at is not None:
            raise ValueError(f"Room {room_id!r} not found")
        if room.hostel_id != hostel_id:
            raise ValueError(
                f"Room {room.room_number} is not in hostel {hostel_id!r}"
            )

        # Direct check on the number the warden cares about. It follows from
        # the room and bed budgets for rows written under them, but a hostel
        # set up before those guards must still not take one student more
        # than it holds.
        hostel = self.session.get(Hostel, hostel_id)
        if hostel is None or hostel.deleted_at is not None:
            raise ValueError(f"Hostel {hostel_id!r} not found")
        residents = self.count_active_residents(tenant_id=tenant_id, hostel_id=hostel_id)
        if residents >= hostel.capacity:
            raise ValueError(
                f"{hostel.name} is full: all {hostel.capacity} places are taken"
            )

        if self._is_bed_occupied(bed_id=bed_id):
            raise ValueError("Bed already occupied")

        if self._has_active_allocation(tenant_id=tenant_id, student_id=student_id):
            raise ValueError("Student already has active allocation")

        allocation = HostelAllocation(
            tenant_id=tenant_id,
            student_id=student_id,
            hostel_id=hostel_id,
            room_id=room_id,
            bed_id=bed_id,
            academic_year_id=academic_year_id,
            check_in_at=check_in_at,
            status=HostelAllocation.STATUS_ACTIVE,
            notes=notes,
        )
        self.session.add(allocation)

        # Keep the denormalized bed columns in sync.
        bed.is_allocated = True
        bed.allocated_to_student_id = student_id

        self.session.flush()
        return allocation

    # ------------------------------------------------------------------
    # Checkout
    # ------------------------------------------------------------------

    def checkout_allocation(
        self,
        allocation_id: str,
        *,
        check_out_at: Optional[datetime] = None,
    ) -> HostelAllocation:
        """Close an active allocation. Frees the bed.

        Raises:
            ValueError: allocation not found or not currently active.
        """
        allocation = self.session.get(HostelAllocation, allocation_id)
        if allocation is None or allocation.deleted_at is not None:
            raise ValueError(f"Allocation {allocation_id!r} not found")

        if allocation.status != HostelAllocation.STATUS_ACTIVE:
            raise ValueError(
                f"Allocation {allocation_id!r} is not active (status={allocation.status!r})"
            )

        allocation.status = HostelAllocation.STATUS_COMPLETED
        allocation.check_out_at = check_out_at or utc_now()

        # Free the bed.
        bed = self.session.get(HostelBed, allocation.bed_id)
        if bed is not None:
            bed.is_allocated = False
            bed.allocated_to_student_id = None

        self.session.flush()
        return allocation

    # ------------------------------------------------------------------
    # Move
    # ------------------------------------------------------------------

    def move_allocation(
        self,
        allocation_id: str,
        *,
        tenant_id: str,
        room_id: str,
        bed_id: str,
        moved_at: Optional[datetime] = None,
        notes: Optional[str] = None,
    ) -> tuple[HostelAllocation, HostelAllocation]:
        """Move a resident to another bed. Returns ``(closed, opened)``.

        A move is one event, recorded as one: the allocation being left is
        closed with ``status='moved'`` and the new one opens at the same
        instant, in the same transaction. Recording it as a checkout and a
        fresh admission — the only way a warden could do it before — said the
        child had left the hostel, which they had not, and lost the fact that
        the two rows were the same stay.

        The destination is validated exactly as a new allocation would be:
        the bed must exist, be active, and sit in the room named; the bed must
        be free. Moving *between* hostels also checks the destination is not
        full — the student does not yet hold a place there. Moving within a
        hostel does not: they already hold one.

        Raises:
            ValueError: allocation not found / not active, destination
                invalid, occupied, or the same bed; destination hostel full.
        """
        allocation = self.session.get(HostelAllocation, allocation_id)
        if (
            allocation is None
            or allocation.deleted_at is not None
            or allocation.tenant_id != tenant_id
        ):
            raise ValueError(f"Allocation {allocation_id!r} not found")
        if allocation.status != HostelAllocation.STATUS_ACTIVE:
            raise ValueError(
                f"Allocation {allocation_id!r} is not active (status={allocation.status!r})"
            )
        if bed_id == allocation.bed_id:
            raise ValueError("Student is already in that bed")

        bed = self._get_bed(tenant_id=tenant_id, bed_id=bed_id)
        if bed is None:
            raise ValueError(f"Bed {bed_id!r} not found")
        if bed.deleted_at is not None or bed.status != BED_STATUS_ACTIVE:
            raise ValueError(f"Bed {bed.bed_number} is not available")
        if bed.room_id != room_id:
            raise ValueError(f"Bed {bed.bed_number} is not in room {room_id!r}")
        room = self.session.get(HostelRoom, room_id)
        if room is None or room.deleted_at is not None:
            raise ValueError(f"Room {room_id!r} not found")
        hostel = self.session.get(Hostel, room.hostel_id)
        if hostel is None or hostel.deleted_at is not None:
            raise ValueError(f"Hostel {room.hostel_id!r} not found")
        # Same order as create_allocation: the building's capacity is checked
        # before the bed, so a full hostel says "full" rather than pointing at
        # whichever bed the warden happened to pick.
        if hostel.id != allocation.hostel_id:
            residents = self.count_active_residents(tenant_id=tenant_id, hostel_id=hostel.id)
            if residents >= hostel.capacity:
                raise ValueError(
                    f"{hostel.name} is full: all {hostel.capacity} places are taken"
                )

        if self._is_bed_occupied(bed_id=bed_id):
            raise ValueError("Bed already occupied")

        when = moved_at or utc_now()

        # Close first and flush, then open: the partial unique index that
        # allows one active allocation per student is checked at flush, and
        # the unit of work would otherwise INSERT the new row before it
        # UPDATEd the old one.
        allocation.status = HostelAllocation.STATUS_MOVED
        allocation.check_out_at = when
        old_bed = self.session.get(HostelBed, allocation.bed_id)
        if old_bed is not None:
            old_bed.is_allocated = False
            old_bed.allocated_to_student_id = None
        self.session.flush()

        opened = HostelAllocation(
            tenant_id=tenant_id,
            student_id=allocation.student_id,
            hostel_id=hostel.id,
            room_id=room_id,
            bed_id=bed_id,
            academic_year_id=allocation.academic_year_id,
            check_in_at=when,
            status=HostelAllocation.STATUS_ACTIVE,
            notes=notes,
        )
        self.session.add(opened)
        bed.is_allocated = True
        bed.allocated_to_student_id = allocation.student_id
        self.session.flush()
        return allocation, opened

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_allocation_by_student(
        self, *, tenant_id: str, student_id: str
    ) -> Optional[HostelAllocation]:
        """Return the student's current active allocation, or None."""
        return (
            self.session.query(HostelAllocation)
            .filter(
                and_(
                    HostelAllocation.tenant_id == tenant_id,
                    HostelAllocation.student_id == student_id,
                    HostelAllocation.status == HostelAllocation.STATUS_ACTIVE,
                    HostelAllocation.deleted_at.is_(None),
                )
            )
            .first()
        )

    def list_allocations(
        self,
        *,
        tenant_id: str,
        hostel_id: Optional[str] = None,
        room_id: Optional[str] = None,
        student_id: Optional[str] = None,
        status: Optional[str] = None,
        academic_year_id: Optional[str] = None,
        search: Optional[str] = None,
        page=None,
        per_page=None,
    ) -> dict:
        """Allocations for the tenant as ``{items, total, page, per_page,
        total_pages}``.

        Omit page/per_page and every matching row comes back — the year-end
        rollover task closes all of them and must not be handed a page. The
        route always pages.
        """
        query = self.session.query(HostelAllocation).filter(
            HostelAllocation.tenant_id == tenant_id,
            HostelAllocation.deleted_at.is_(None),
        )

        # Which bed a child sleeps in is a fact about the child, so a sub-admin
        # restricted to one campus sees their campus's boarders.
        query = filter_by_student_ids(query, HostelAllocation.student_id)

        if hostel_id is not None:
            query = query.filter(HostelAllocation.hostel_id == hostel_id)
        if room_id is not None:
            query = query.filter(HostelAllocation.room_id == room_id)
        if student_id is not None:
            query = query.filter(HostelAllocation.student_id == student_id)
        if status is not None:
            query = query.filter(HostelAllocation.status == status)
        if academic_year_id is not None:
            query = query.filter(HostelAllocation.academic_year_id == academic_year_id)

        query = self._apply_search(query, search)

        # The id breaks the tie: a warden admits a batch of boarders in one
        # sitting, so check_in_at alone is not a total order.
        return paginate(
            query,
            order_by=(
                HostelAllocation.check_in_at.desc(),
                HostelAllocation.id.desc(),
            ),
            page=page,
            per_page=per_page,
        )

    # ------------------------------------------------------------------
    # Occupancy
    # ------------------------------------------------------------------

    def _apply_search(self, query, search: Optional[str]):
        """Match the fields the residents list actually shows.

        The mobile screen filtered the rows it happened to be holding, which
        only searches the first page once the list is paged.

        The name is matched on the person *and* the account: `display_name`
        resolves from `people.full_name`, so matching only `users.name` would
        make a child with no login unfindable by the box meant to find them.
        Every student join is outer for the same reason.
        """
        if not search or not search.strip():
            return query

        from modules.auth.models import User
        from modules.people.models import Person
        from modules.students.models import Student

        term = search.strip()
        escaped = (
            term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        pattern = f"%{escaped}%"

        return (
            query.outerjoin(Student, Student.id == HostelAllocation.student_id)
            .outerjoin(User, User.id == Student.user_id)
            .outerjoin(Person, Person.id == Student.person_id)
            .outerjoin(Hostel, Hostel.id == HostelAllocation.hostel_id)
            .filter(
                or_(
                    Person.full_name.ilike(pattern, escape="\\"),
                    User.name.ilike(pattern, escape="\\"),
                    Student.admission_number.ilike(pattern, escape="\\"),
                    Hostel.name.ilike(pattern, escape="\\"),
                )
            )
        )

    def occupied_counts_by_room(
        self, *, tenant_id: str, hostel_id: str
    ) -> dict[str, int]:
        """How many beds are taken in each room of this hostel, keyed by room id.

        One grouped query, so it stays correct and cheap for a hostel of any
        size. The screen used to fetch every active allocation and count them
        in the browser, which sent hundreds of rows to render a handful of
        numbers — and would have counted only the first page once the
        allocations endpoint started paging.

        Rooms with nobody in them are absent; callers should default to 0.
        """
        rows = (
            self.session.query(
                HostelAllocation.room_id, func.count(HostelAllocation.id)
            )
            .filter(
                and_(
                    HostelAllocation.tenant_id == tenant_id,
                    HostelAllocation.hostel_id == hostel_id,
                    HostelAllocation.status == HostelAllocation.STATUS_ACTIVE,
                    HostelAllocation.deleted_at.is_(None),
                )
            )
            .group_by(HostelAllocation.room_id)
            .all()
        )
        return {room_id: count for room_id, count in rows}

    def count_active_residents(self, *, tenant_id: str, hostel_id: str) -> int:
        """How many students are currently allocated to a bed in this hostel.

        Used to decide whether the hostel can be deleted: nothing downstream
        filters allocations by their hostel's deleted_at, so removing an
        occupied hostel would strand its residents in a hostel that no longer
        exists.
        """
        return self._count_active_allocations(
            tenant_id=tenant_id,
            column=HostelAllocation.hostel_id,
            value=hostel_id,
        )

    def count_active_room_residents(self, *, tenant_id: str, room_id: str) -> int:
        """How many students are currently allocated to a bed in this room.

        The room-level twin of count_active_residents, for the same reason:
        rooms are soft-deleted and nothing filters allocations by their room's
        deleted_at.
        """
        return self._count_active_allocations(
            tenant_id=tenant_id,
            column=HostelAllocation.room_id,
            value=room_id,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _count_active_allocations(self, *, tenant_id: str, column, value: str) -> int:
        """Active, non-deleted allocations where ``column`` equals ``value``.

        "Active" matches _is_bed_occupied — status plus not soft-deleted — so
        the hostel, room and bed guards all agree on who counts as resident.
        """
        return (
            self.session.query(HostelAllocation.id)
            .filter(
                and_(
                    HostelAllocation.tenant_id == tenant_id,
                    column == value,
                    HostelAllocation.status == HostelAllocation.STATUS_ACTIVE,
                    HostelAllocation.deleted_at.is_(None),
                )
            )
            .count()
        )

    def _get_bed(self, *, tenant_id: str, bed_id: str) -> Optional[HostelBed]:
        return (
            self.session.query(HostelBed)
            .filter(HostelBed.tenant_id == tenant_id, HostelBed.id == bed_id)
            .first()
        )

    def _is_bed_occupied(self, *, bed_id: str) -> bool:
        """True iff there is an active, non-deleted allocation on this bed."""
        return (
            self.session.query(HostelAllocation.id)
            .filter(
                and_(
                    HostelAllocation.bed_id == bed_id,
                    HostelAllocation.status == HostelAllocation.STATUS_ACTIVE,
                    HostelAllocation.deleted_at.is_(None),
                )
            )
            .first()
            is not None
        )

    def _has_active_allocation(self, *, tenant_id: str, student_id: str) -> bool:
        """True iff the student has an active, non-deleted allocation."""
        return (
            self.session.query(HostelAllocation.id)
            .filter(
                and_(
                    HostelAllocation.tenant_id == tenant_id,
                    HostelAllocation.student_id == student_id,
                    HostelAllocation.status == HostelAllocation.STATUS_ACTIVE,
                    HostelAllocation.deleted_at.is_(None),
                )
            )
            .first()
            is not None
        )
