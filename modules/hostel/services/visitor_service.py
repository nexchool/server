"""VisitorService — hostel visitor check-in / check-out and search.

Visitors are de-duplicated by (tenant_id, phone). Each check-in / out
pair becomes one HostelVisitorLog row. The 'currently inside' view is
just `WHERE check_out_at IS NULL AND deleted_at IS NULL`.

Soft-delete is supported on visitor_logs (audit trail preserved). The
visitor profile itself is never deleted automatically; only via admin
purge.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

from modules.hostel.models import (
    HostelVisitor,
    HostelVisitorLog,
)


class VisitorService:
    """Service layer for visitor profiles and visit logs."""

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Check-in / out
    # ------------------------------------------------------------------

    def check_in(
        self,
        *,
        tenant_id: str,
        phone: str,
        name: str,
        relation_type: Optional[str],
        student_id: str,
        hostel_id: str,
        room_id: Optional[str],
        purpose: Optional[str],
    ) -> HostelVisitorLog:
        """Register a visitor entering the hostel.

        Upserts the HostelVisitor profile keyed by (tenant_id, phone)
        and creates a new HostelVisitorLog row.
        """
        visitor = self._upsert_visitor(
            tenant_id=tenant_id,
            phone=phone,
            name=name,
            relation_type=relation_type,
        )

        log = HostelVisitorLog(
            tenant_id=tenant_id,
            visitor_id=visitor.id,
            student_id=student_id,
            hostel_id=hostel_id,
            room_id=room_id,
            check_in_at=datetime.utcnow(),
            purpose=purpose,
        )
        self.session.add(log)
        self.session.flush()
        return log

    def check_out(
        self,
        log_id: str,
        *,
        check_out_at: Optional[datetime] = None,
    ) -> HostelVisitorLog:
        """Close an open visitor log row.

        Raises:
            ValueError: log not found, already checked out, or soft-deleted.
        """
        log = self.session.get(HostelVisitorLog, log_id)
        if log is None or log.deleted_at is not None:
            raise ValueError(f"Visitor log {log_id!r} not found")
        if log.check_out_at is not None:
            raise ValueError(f"Visitor log {log_id!r} already checked out")

        log.check_out_at = check_out_at or datetime.utcnow()
        self.session.flush()
        return log

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_currently_inside(
        self,
        *,
        tenant_id: str,
        hostel_id: Optional[str] = None,
    ) -> list[HostelVisitorLog]:
        """List visitor logs with no check_out_at yet (i.e. inside)."""
        query = self.session.query(HostelVisitorLog).filter(
            HostelVisitorLog.tenant_id == tenant_id,
            HostelVisitorLog.check_out_at.is_(None),
            HostelVisitorLog.deleted_at.is_(None),
        )
        if hostel_id is not None:
            query = query.filter(HostelVisitorLog.hostel_id == hostel_id)
        return query.order_by(HostelVisitorLog.check_in_at.desc()).all()

    def list_visitor_logs(
        self,
        *,
        tenant_id: str,
        hostel_id: Optional[str] = None,
        student_id: Optional[str] = None,
        visitor_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        only_open: bool = False,
    ) -> list[HostelVisitorLog]:
        """Historical search with optional filters; newest first."""
        query = self.session.query(HostelVisitorLog).filter(
            HostelVisitorLog.tenant_id == tenant_id,
            HostelVisitorLog.deleted_at.is_(None),
        )
        if hostel_id is not None:
            query = query.filter(HostelVisitorLog.hostel_id == hostel_id)
        if student_id is not None:
            query = query.filter(HostelVisitorLog.student_id == student_id)
        if visitor_id is not None:
            query = query.filter(HostelVisitorLog.visitor_id == visitor_id)
        if start_date is not None:
            query = query.filter(HostelVisitorLog.check_in_at >= start_date)
        if end_date is not None:
            query = query.filter(HostelVisitorLog.check_in_at <= end_date)
        if only_open:
            query = query.filter(HostelVisitorLog.check_out_at.is_(None))
        return query.order_by(HostelVisitorLog.check_in_at.desc()).all()

    def search_visitors(
        self,
        *,
        tenant_id: str,
        phone_prefix: str,
        limit: int = 10,
    ) -> list[HostelVisitor]:
        """Auto-suggest repeat visitors by phone prefix."""
        if not phone_prefix:
            return []
        return (
            self.session.query(HostelVisitor)
            .filter(
                and_(
                    HostelVisitor.tenant_id == tenant_id,
                    HostelVisitor.phone.like(f"{phone_prefix}%"),
                )
            )
            .order_by(HostelVisitor.name)
            .limit(limit)
            .all()
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _upsert_visitor(
        self,
        *,
        tenant_id: str,
        phone: str,
        name: str,
        relation_type: Optional[str],
    ) -> HostelVisitor:
        visitor = (
            self.session.query(HostelVisitor)
            .filter(
                and_(
                    HostelVisitor.tenant_id == tenant_id,
                    HostelVisitor.phone == phone,
                )
            )
            .first()
        )
        if visitor is None:
            visitor = HostelVisitor(
                tenant_id=tenant_id,
                phone=phone,
                name=name,
                relation_type=relation_type,
            )
            self.session.add(visitor)
            self.session.flush()
        else:
            # Keep the profile updated with the latest name / relation.
            visitor.name = name
            if relation_type is not None:
                visitor.relation_type = relation_type
        return visitor
