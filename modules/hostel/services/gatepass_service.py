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
from typing import Optional, Sequence

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from core.branch_scope import filter_by_student_ids

from modules.hostel.models import (
    HostelGatepass,
    HostelGatepassAudit,
)
from core.school_time import utc_now

GATEPASS_PAGE_SIZE = 25
GATEPASS_MAX_PAGE_SIZE = 100


def _positive_int(value, *, default: int, maximum: Optional[int] = None) -> int:
    """Coerce a query-string number, falling back rather than raising."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    number = max(1, number)
    return min(number, maximum) if maximum else number


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
        gp.approved_at = utc_now()
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
        gp.actual_out_at = utc_now()

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
        gp.actual_in_at = utc_now()

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

    def get_gatepass(
        self, gatepass_id: str, *, tenant_id: str
    ) -> Optional[HostelGatepass]:
        """One gatepass, or None if it is not this caller's to read.

        Branch-filtered rather than refused: raising would confirm the gatepass
        exists, and for someone with no authority over the child it belongs to,
        "not found" is the honest answer. Reading one by id must not be the way
        around the list being scoped.
        """
        query = self.session.query(HostelGatepass).filter(
            HostelGatepass.id == gatepass_id,
            HostelGatepass.tenant_id == tenant_id,
            HostelGatepass.deleted_at.is_(None),
        )
        return filter_by_student_ids(query, HostelGatepass.student_id).first()

    def list_gatepasses(
        self,
        *,
        tenant_id: str,
        hostel_id: Optional[str] = None,
        student_id: Optional[str] = None,
        status: Optional[str | Sequence[str]] = None,
        gatepass_type: Optional[str] = None,
        search: Optional[str] = None,
        page=None,
        per_page=None,
        oldest_first: bool = False,
    ) -> dict:
        """One page of gatepasses, plus the total for the whole filtered set.

        Returns ``{items, total, page, per_page, total_pages}``.

        The admin board is five columns, and each asks for its own slice: its
        statuses (``status`` takes a list, because "closed" and "rejected" share
        a column), its own page, and its own sort — a warden works the pending
        queue oldest-first, while every other column reads newest-first.

        ``total`` is a COUNT over the filter, not ``len(items)``: it is what the
        column header shows, and the "closed" column holds every gatepass the
        school has ever issued.
        """
        query = self.session.query(HostelGatepass).filter(
            HostelGatepass.tenant_id == tenant_id,
            HostelGatepass.deleted_at.is_(None),
        )
        if hostel_id is not None:
            query = query.filter(HostelGatepass.hostel_id == hostel_id)
        if student_id is not None:
            query = query.filter(HostelGatepass.student_id == student_id)
        if status is not None:
            wanted = [status] if isinstance(status, str) else list(status)
            query = query.filter(HostelGatepass.status.in_(wanted))
        if gatepass_type is not None:
            query = query.filter(HostelGatepass.type == gatepass_type)

        # Whether a child may leave the hostel is a fact about the child, the
        # same as which bed they sleep in — so a campus-restricted warden sees
        # their own campus's gatepasses. Hostels carry no school_unit_id (they
        # are tenant-wide), which makes the student the only anchor.
        query = filter_by_student_ids(query, HostelGatepass.student_id)

        query = self._apply_search(query, search)

        total = query.count()

        page = _positive_int(page, default=1)
        per_page = _positive_int(
            per_page, default=GATEPASS_PAGE_SIZE, maximum=GATEPASS_MAX_PAGE_SIZE
        )

        # `requested_at` ties constantly — a warden approves a batch in one
        # sitting — so the id breaks the tie and makes the order total. Without
        # it LIMIT/OFFSET can serve a row twice and skip another.
        requested = HostelGatepass.requested_at
        order = (
            (requested.asc(), HostelGatepass.id.asc())
            if oldest_first
            else (requested.desc(), HostelGatepass.id.desc())
        )
        items = (
            query.order_by(*order)
            .limit(per_page)
            .offset((page - 1) * per_page)
            .all()
        )

        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": max(1, (total + per_page - 1) // per_page),
        }

    def _apply_search(self, query, search: Optional[str]):
        """Match what a warden would actually type into the box.

        The board used to filter in the browser, which meant it only ever
        searched the rows already downloaded — and it searched `student_id`, a
        UUID nobody can type. This searches the child's name and admission
        number, the parent's phone and the stated reason.

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
        # Escape LIKE metacharacters — an unescaped "%" matches every child.
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"

        return (
            query.outerjoin(Student, Student.id == HostelGatepass.student_id)
            .outerjoin(User, User.id == Student.user_id)
            .outerjoin(Person, Person.id == Student.person_id)
            .filter(
                or_(
                    Person.full_name.ilike(pattern, escape="\\"),
                    User.name.ilike(pattern, escape="\\"),
                    Student.admission_number.ilike(pattern, escape="\\"),
                    HostelGatepass.parent_phone.ilike(pattern, escape="\\"),
                    HostelGatepass.reason.ilike(pattern, escape="\\"),
                )
            )
        )

    def find_overdue_gatepasses(
        self, *, grace_period_minutes: int = DEFAULT_GRACE_PERIOD_MINUTES
    ) -> list[HostelGatepass]:
        """Return ACTIVE gatepasses whose expected return is past grace period.

        Two callers with deliberately different reach:

        * the Celery beat task, which finds candidates for mark_overdue and
          must see every campus — it runs outside a request, where branch scope
          resolves to UNRESTRICTED, so the sweep is unaffected;
        * the warden's alert screen, where a campus-restricted user must see
          only their own campus's children.
        """
        cutoff = utc_now() - timedelta(minutes=grace_period_minutes)
        query = self.session.query(HostelGatepass).filter(
            and_(
                HostelGatepass.status == HostelGatepass.STATUS_ACTIVE,
                HostelGatepass.expected_return_datetime < cutoff,
                HostelGatepass.deleted_at.is_(None),
            )
        )
        return filter_by_student_ids(query, HostelGatepass.student_id).all()

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
        gp.parent_consent_notified_at = utc_now()
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
