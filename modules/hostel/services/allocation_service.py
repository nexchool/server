"""AllocationService — business logic for student → bed assignments.

Encapsulates the rules:
- One active allocation per bed (also enforced at DB by partial unique index).
- One active allocation per student.
- Checkout marks status='completed', sets check_out_at, and frees the bed.
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
from sqlalchemy import and_
from sqlalchemy.orm import Session

from modules.hostel.models import (
    HostelAllocation,
    HostelBed,
)
from core.school_time import utc_now


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

    def count_active_residents(self, *, tenant_id: str, hostel_id: str) -> int:
        """How many students are currently allocated to a bed in this hostel.

        Used to decide whether the hostel can be deleted: nothing downstream
        filters allocations by their hostel's deleted_at, so removing an
        occupied hostel would strand its residents in a hostel that no longer
        exists. "Active" here matches _is_bed_occupied — status plus not
        soft-deleted.
        """
        return (
            self.session.query(HostelAllocation.id)
            .filter(
                and_(
                    HostelAllocation.tenant_id == tenant_id,
                    HostelAllocation.hostel_id == hostel_id,
                    HostelAllocation.status == HostelAllocation.STATUS_ACTIVE,
                    HostelAllocation.deleted_at.is_(None),
                )
            )
            .count()
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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
