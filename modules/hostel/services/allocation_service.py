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

from sqlalchemy import and_
from sqlalchemy.orm import Session

from modules.hostel.models import (
    HostelAllocation,
    HostelBed,
)


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
        allocation.check_out_at = check_out_at or datetime.utcnow()

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
    ) -> list[HostelAllocation]:
        """List allocations with optional filters."""
        query = self.session.query(HostelAllocation).filter(
            HostelAllocation.tenant_id == tenant_id,
            HostelAllocation.deleted_at.is_(None),
        )

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

        return query.order_by(HostelAllocation.check_in_at.desc()).all()

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
