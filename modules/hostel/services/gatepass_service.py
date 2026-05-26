"""GatepassService — gatepass state machine + audit trail.

Encapsulates the lifecycle:

    pending → approved → active → closed
       │          │         │
       └─→ rejected         └─→ overdue (system) ─→ closed

Rules:
- A student can have only one in-flight gatepass at a time
  (pending / approved / active).
- Every transition writes an audit row.
- Parent notification is informational only (v1): security guard calls
  the parent before approving; this service does not send SMS / push,
  it only records `parent_consent_notified_at` and `parent_notification_type`
  if the API layer triggered a notification.
- Overdue detection is grace-period aware:
    overdue = active AND expected_return_datetime < now() - grace_minutes
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

from modules.hostel.models import (
    HostelGatepass,
    HostelGatepassAudit,
)


class GatepassService:
    """Service layer for HostelGatepass workflow."""

    DEFAULT_GRACE_PERIOD_MINUTES = 30

    # Statuses that count as "currently in flight" for the
    # one-gatepass-per-student rule.
    _IN_FLIGHT_STATUSES = (
        HostelGatepass.STATUS_PENDING,
        HostelGatepass.STATUS_APPROVED,
        HostelGatepass.STATUS_ACTIVE,
        HostelGatepass.STATUS_OVERDUE,
    )

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create_gatepass(
        self,
        *,
        tenant_id: str,
        student_id: str,
        hostel_id: str,
        gatepass_type: str,
        departure_datetime: datetime,
        expected_return_datetime: datetime,
        reason: Optional[str],
        parent_phone: str,
    ) -> HostelGatepass:
        """Create a pending gatepass request.

        Raises:
            ValueError: invalid type, return-before-departure, or the
                student already has an in-flight gatepass.
        """
        if gatepass_type not in HostelGatepass.TYPE_VALUES:
            raise ValueError(
                f"Invalid gatepass type {gatepass_type!r}; "
                f"must be one of {HostelGatepass.TYPE_VALUES}"
            )
        if expected_return_datetime <= departure_datetime:
            raise ValueError("Expected return must be after departure")

        if self._student_has_in_flight(tenant_id=tenant_id, student_id=student_id):
            raise ValueError("Student already has an active gatepass")

        gp = HostelGatepass(
            tenant_id=tenant_id,
            student_id=student_id,
            hostel_id=hostel_id,
            type=gatepass_type,
            departure_datetime=departure_datetime,
            expected_return_datetime=expected_return_datetime,
            reason=reason,
            parent_phone=parent_phone,
            status=HostelGatepass.STATUS_PENDING,
        )
        self.session.add(gp)
        self.session.flush()  # populate gp.id for audit row

        self._log_audit(
            gatepass_id=gp.id,
            action=HostelGatepassAudit.ACTION_CREATED,
            actor_type=HostelGatepassAudit.ACTOR_STUDENT,
            actor_id=student_id,
        )
        self.session.flush()
        return gp

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def approve_gatepass(
        self, gatepass_id: str, *, actor_user_id: str
    ) -> HostelGatepass:
        """Warden approves (after calling parent). pending → approved."""
        gp = self._get_or_raise(gatepass_id)
        self._require_transition(gp, HostelGatepass.STATUS_APPROVED)

        gp.status = HostelGatepass.STATUS_APPROVED
        gp.approved_at = datetime.utcnow()
        gp.approved_by_user_id = actor_user_id

        self._log_audit(
            gatepass_id=gp.id,
            action=HostelGatepassAudit.ACTION_APPROVED,
            actor_type=HostelGatepassAudit.ACTOR_WARDEN,
            actor_id=actor_user_id,
        )
        self.session.flush()
        return gp

    def reject_gatepass(
        self,
        gatepass_id: str,
        *,
        actor_user_id: str,
        reason: Optional[str] = None,
    ) -> HostelGatepass:
        """Warden rejects the request. pending → rejected."""
        gp = self._get_or_raise(gatepass_id)
        self._require_transition(gp, HostelGatepass.STATUS_REJECTED)

        gp.status = HostelGatepass.STATUS_REJECTED
        if reason:
            gp.notes = self._append_note(gp.notes, f"Rejected: {reason}")

        self._log_audit(
            gatepass_id=gp.id,
            action=HostelGatepassAudit.ACTION_REJECTED,
            actor_type=HostelGatepassAudit.ACTOR_WARDEN,
            actor_id=actor_user_id,
            notes=reason,
        )
        self.session.flush()
        return gp

    def mark_checkout(
        self, gatepass_id: str, *, actor_user_id: str
    ) -> HostelGatepass:
        """Gatekeeper records actual departure. approved → active."""
        gp = self._get_or_raise(gatepass_id)
        self._require_transition(gp, HostelGatepass.STATUS_ACTIVE)

        gp.status = HostelGatepass.STATUS_ACTIVE
        gp.actual_out_at = datetime.utcnow()

        self._log_audit(
            gatepass_id=gp.id,
            action=HostelGatepassAudit.ACTION_CHECKOUT,
            actor_type=HostelGatepassAudit.ACTOR_GATEKEEPER,
            actor_id=actor_user_id,
        )
        self.session.flush()
        return gp

    def mark_checkin(
        self, gatepass_id: str, *, actor_user_id: str
    ) -> HostelGatepass:
        """Gatekeeper records actual return. active|overdue → closed."""
        gp = self._get_or_raise(gatepass_id)
        self._require_transition(gp, HostelGatepass.STATUS_CLOSED)

        gp.status = HostelGatepass.STATUS_CLOSED
        gp.actual_in_at = datetime.utcnow()

        self._log_audit(
            gatepass_id=gp.id,
            action=HostelGatepassAudit.ACTION_CHECKIN,
            actor_type=HostelGatepassAudit.ACTOR_GATEKEEPER,
            actor_id=actor_user_id,
        )
        self.session.flush()
        return gp

    def mark_overdue(self, gatepass_id: str) -> HostelGatepass:
        """System action: active → overdue (called by Celery beat task)."""
        gp = self._get_or_raise(gatepass_id)
        self._require_transition(gp, HostelGatepass.STATUS_OVERDUE)

        gp.status = HostelGatepass.STATUS_OVERDUE

        self._log_audit(
            gatepass_id=gp.id,
            action=HostelGatepassAudit.ACTION_MARKED_OVERDUE,
            actor_type=HostelGatepassAudit.ACTOR_SYSTEM,
        )
        self.session.flush()
        return gp

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_gatepasses(
        self,
        *,
        tenant_id: str,
        hostel_id: Optional[str] = None,
        student_id: Optional[str] = None,
        status: Optional[str] = None,
        gatepass_type: Optional[str] = None,
    ) -> list[HostelGatepass]:
        """List gatepasses with optional filters, newest first."""
        query = self.session.query(HostelGatepass).filter(
            HostelGatepass.tenant_id == tenant_id,
            HostelGatepass.deleted_at.is_(None),
        )
        if hostel_id is not None:
            query = query.filter(HostelGatepass.hostel_id == hostel_id)
        if student_id is not None:
            query = query.filter(HostelGatepass.student_id == student_id)
        if status is not None:
            query = query.filter(HostelGatepass.status == status)
        if gatepass_type is not None:
            query = query.filter(HostelGatepass.type == gatepass_type)
        return query.order_by(HostelGatepass.requested_at.desc()).all()

    def find_overdue_gatepasses(
        self, *, grace_period_minutes: int = DEFAULT_GRACE_PERIOD_MINUTES
    ) -> list[HostelGatepass]:
        """Return ACTIVE gatepasses whose expected return is past grace period.

        The Celery beat task uses this to find candidates for mark_overdue.
        """
        cutoff = datetime.utcnow() - timedelta(minutes=grace_period_minutes)
        return (
            self.session.query(HostelGatepass)
            .filter(
                and_(
                    HostelGatepass.status == HostelGatepass.STATUS_ACTIVE,
                    HostelGatepass.expected_return_datetime < cutoff,
                    HostelGatepass.deleted_at.is_(None),
                )
            )
            .all()
        )

    # ------------------------------------------------------------------
    # Notifications recording (informational only in v1)
    # ------------------------------------------------------------------

    def record_parent_notified(
        self,
        gatepass_id: str,
        *,
        channels: list[str],
    ) -> HostelGatepass:
        """Record that the parent received an informational notification.

        Does NOT send anything; the actual SMS/push delivery is owned by
        the notifications module. This just stamps the gatepass so we
        have a record. `channels` is a list like ['in_app', 'push'].
        """
        gp = self._get_or_raise(gatepass_id)
        gp.parent_consent_notified_at = datetime.utcnow()
        gp.parent_notification_type = ",".join(channels)
        self.session.flush()
        return gp

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_or_raise(self, gatepass_id: str) -> HostelGatepass:
        gp = self.session.get(HostelGatepass, gatepass_id)
        if gp is None or gp.deleted_at is not None:
            raise ValueError(f"Gatepass {gatepass_id!r} not found")
        return gp

    def _require_transition(self, gp: HostelGatepass, new_status: str) -> None:
        if not gp.can_transition_to(new_status):
            raise ValueError(
                f"Gatepass {gp.id!r} cannot transition from "
                f"{gp.status!r} to {new_status!r}"
            )

    def _student_has_in_flight(self, *, tenant_id: str, student_id: str) -> bool:
        return (
            self.session.query(HostelGatepass.id)
            .filter(
                and_(
                    HostelGatepass.tenant_id == tenant_id,
                    HostelGatepass.student_id == student_id,
                    HostelGatepass.status.in_(self._IN_FLIGHT_STATUSES),
                    HostelGatepass.deleted_at.is_(None),
                )
            )
            .first()
            is not None
        )

    def _log_audit(
        self,
        *,
        gatepass_id: str,
        action: str,
        actor_type: str,
        actor_id: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> HostelGatepassAudit:
        audit = HostelGatepassAudit(
            gatepass_id=gatepass_id,
            action=action,
            actor_type=actor_type,
            actor_id=actor_id,
            notes=notes,
        )
        self.session.add(audit)
        return audit

    @staticmethod
    def _append_note(existing: Optional[str], new: str) -> str:
        if not existing:
            return new
        return f"{existing}\n{new}"
