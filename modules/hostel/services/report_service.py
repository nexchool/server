"""ReportService — dashboard + CSV export queries for hostel module.

Read-only aggregations:
  - occupancy_stats(): per-hostel summary (active allocations, vacant beds, %).
  - overdue_alerts(): currently-overdue gatepasses.
  - residents_csv_rows(): rows for the residents.csv export.

Heavy lifting (joins, count aggregates) is delegated to SQL; the service
just shapes the result into a JSON-friendly list of dicts.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from modules.hostel.models import (
    Hostel,
    HostelAllocation,
    HostelBed,
    HostelGatepass,
    HostelRoom,
)


class ReportService:
    """Read-only aggregate queries for the hostel dashboard / reports."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Occupancy
    # ------------------------------------------------------------------

    def occupancy_stats(self, *, tenant_id: str) -> list[dict]:
        """Per-hostel occupancy summary.

        Returns:
            List of dicts with keys: hostel_id, hostel_name, total_beds,
            active_allocations, vacant_beds, occupancy_pct, status.
        """
        hostels = (
            self.session.query(Hostel)
            .filter(Hostel.tenant_id == tenant_id, Hostel.deleted_at.is_(None))
            .order_by(Hostel.name)
            .all()
        )

        results: list[dict] = []
        for hostel in hostels:
            total_beds = self._count_active_beds(hostel.id)
            active_allocs = self._count_active_allocations(hostel.id)
            vacant = max(total_beds - active_allocs, 0)
            pct = round((active_allocs / total_beds) * 100, 1) if total_beds else 0.0

            results.append(
                {
                    "hostel_id": hostel.id,
                    "hostel_name": hostel.name,
                    "status": hostel.status,
                    "total_beds": total_beds,
                    "active_allocations": active_allocs,
                    "vacant_beds": vacant,
                    "occupancy_pct": pct,
                }
            )
        return results

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------

    def overdue_alerts(
        self,
        *,
        tenant_id: str,
        hostel_id: Optional[str] = None,
    ) -> list[HostelGatepass]:
        """Currently overdue gatepasses for the warden's dashboard."""
        query = self.session.query(HostelGatepass).filter(
            and_(
                HostelGatepass.tenant_id == tenant_id,
                HostelGatepass.status == HostelGatepass.STATUS_OVERDUE,
                HostelGatepass.deleted_at.is_(None),
            )
        )
        if hostel_id is not None:
            query = query.filter(HostelGatepass.hostel_id == hostel_id)
        return query.order_by(HostelGatepass.expected_return_datetime).all()

    # ------------------------------------------------------------------
    # CSV export
    # ------------------------------------------------------------------

    def residents_csv_rows(
        self,
        *,
        tenant_id: str,
        hostel_id: Optional[str] = None,
    ) -> list[dict]:
        """One row per active allocation for the residents.csv download."""
        query = (
            self.session.query(HostelAllocation, HostelRoom, HostelBed, Hostel)
            .join(HostelRoom, HostelAllocation.room_id == HostelRoom.id)
            .join(HostelBed, HostelAllocation.bed_id == HostelBed.id)
            .join(Hostel, HostelAllocation.hostel_id == Hostel.id)
            .filter(
                and_(
                    HostelAllocation.tenant_id == tenant_id,
                    HostelAllocation.status == HostelAllocation.STATUS_ACTIVE,
                    HostelAllocation.deleted_at.is_(None),
                )
            )
        )
        if hostel_id is not None:
            query = query.filter(Hostel.id == hostel_id)

        rows: list[dict] = []
        for allocation, room, bed, hostel in query.order_by(Hostel.name, HostelRoom.room_number, HostelBed.bed_number).all():
            rows.append(
                {
                    "hostel_name": hostel.name,
                    "room_number": room.room_number,
                    "bed_number": bed.bed_number,
                    "student_id": allocation.student_id,
                    "check_in_date": allocation.check_in_at.strftime("%Y-%m-%d")
                    if allocation.check_in_at
                    else "",
                }
            )
        return rows

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _count_active_beds(self, hostel_id: str) -> int:
        """Number of active beds across all active rooms in the hostel."""
        return (
            self.session.query(func.count(HostelBed.id))
            .join(HostelRoom, HostelBed.room_id == HostelRoom.id)
            .filter(
                HostelRoom.hostel_id == hostel_id,
                HostelRoom.deleted_at.is_(None),
                HostelBed.status == "active",
            )
            .scalar()
            or 0
        )

    def _count_active_allocations(self, hostel_id: str) -> int:
        return (
            self.session.query(func.count(HostelAllocation.id))
            .filter(
                HostelAllocation.hostel_id == hostel_id,
                HostelAllocation.status == HostelAllocation.STATUS_ACTIVE,
                HostelAllocation.deleted_at.is_(None),
            )
            .scalar()
            or 0
        )
