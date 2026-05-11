"""Hostel module Celery tasks (idempotent).

Tasks:
  - hostel.mark_overdue_gatepasses: runs every 5 min via beat schedule.
    Marks active gatepasses past their expected return + grace period as
    'overdue' and writes audit rows. Idempotent — only flips status when
    the transition is legal (active -> overdue).

  - hostel.rollover_academic_year: ad-hoc (admin-triggered) task to close
    every active allocation when the academic year changes. Idempotent —
    skips allocations that are not currently active.
"""

from __future__ import annotations

from celery_app import get_celery

celery_app = get_celery()


# Default grace period — gatepass is considered overdue this many minutes
# after its expected_return_datetime. Eventually configurable per-tenant
# via `hostel.gatepass_grace_period_minutes` tenant setting.
DEFAULT_GRACE_MINUTES = 30


@celery_app.task(bind=True, name="hostel.mark_overdue_gatepasses")
def mark_overdue_gatepasses_task(self, grace_period_minutes: int = DEFAULT_GRACE_MINUTES):
    """Mark active gatepasses past return time as overdue.

    Runs every 5 min via beat schedule. Idempotent — uses
    GatepassService.mark_overdue which validates the state transition
    (active -> overdue) so calling twice on the same gatepass is a no-op
    (raises a ValueError that we swallow per gatepass).
    """
    from core.database import db
    from modules.hostel.services import GatepassService

    service = GatepassService(db.session)

    candidates = service.find_overdue_gatepasses(
        grace_period_minutes=grace_period_minutes
    )

    marked = 0
    skipped = 0
    errors = 0

    for gp in candidates:
        try:
            service.mark_overdue(gp.id)
            marked += 1
        except ValueError:
            # Race / invalid transition (e.g., gatepass already closed
            # since query). Safe to skip.
            skipped += 1
        except Exception:  # noqa: BLE001
            # Don't kill the whole task for one bad row; log and continue.
            db.session.rollback()
            errors += 1
            continue

    db.session.commit()
    return {
        "marked_overdue": marked,
        "skipped_invalid_transition": skipped,
        "errors": errors,
        "grace_period_minutes": grace_period_minutes,
    }


@celery_app.task(bind=True, name="hostel.rollover_academic_year")
def rollover_academic_year_task(self, new_academic_year_id: str, tenant_id: str):
    """Close every active allocation in a tenant when the year changes.

    Called explicitly by admin action; not on a schedule. Idempotent —
    only operates on rows currently in status='active'.

    Args:
        new_academic_year_id: stamped on the closed allocations for
            historical association.
        tenant_id: scope the rollover to one tenant at a time.
    """
    from core.database import db
    from modules.hostel.models import HostelAllocation
    from modules.hostel.services import AllocationService

    service = AllocationService(db.session)

    active = service.list_allocations(tenant_id=tenant_id, status="active")
    closed = 0
    errors = 0

    for allocation in active:
        try:
            service.checkout_allocation(allocation.id)
            # Stamp the (now-closed) row with the new academic year so
            # we can group historical allocations by year.
            allocation.academic_year_id = new_academic_year_id
            closed += 1
        except ValueError:
            # Already non-active; skip.
            continue
        except Exception:  # noqa: BLE001
            db.session.rollback()
            errors += 1
            continue

    db.session.commit()
    return {
        "closed_allocations": closed,
        "errors": errors,
        "new_academic_year_id": new_academic_year_id,
        "tenant_id": tenant_id,
    }
