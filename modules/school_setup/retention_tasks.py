"""
Data retention Celery tasks.

Jobs run on beat schedule defined in celery_app.py.
Each job writes a DataPurgeLog row (counts only — no PII in logs).

Retention periods (fixed — not configurable per tenant):
  notification_logs      : 90 days
  audit_logs (finance)   : 1 academic term (~120 days)
  audit_logs (others)    : 365 days
  student PII            : 3 years after students.left_at
  financial records      : 7 years
  academic records       : 7 years after students.left_at
  teacher records        : 5 years after teachers.left_at
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from celery import shared_task
from core.database import db
from modules.school_setup.models import DataPurgeLog

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _log_purge(tenant_id: str, data_type: str, count: int) -> None:
    if count == 0:
        return
    entry = DataPurgeLog(
        tenant_id=tenant_id,
        data_type=data_type,
        records_deleted=count,
    )
    db.session.add(entry)


@shared_task(name="retention.purge_notification_logs")
def purge_notification_logs():
    """Delete notification log rows older than 90 days. Runs nightly."""
    from modules.notifications.models import Notification

    cutoff = _utcnow() - timedelta(days=90)
    try:
        deleted = (
            db.session.query(Notification)
            .filter(Notification.created_at < cutoff)
            .delete(synchronize_session=False)
        )
        if deleted:
            logger.info("retention.purge_notification_logs", extra={"deleted": deleted})
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("retention.purge_notification_logs.failed")


@shared_task(name="retention.purge_expired_sessions")
def purge_expired_sessions():
    """Delete login sessions whose refresh token has expired. Runs nightly.

    Nothing pruned these. A row is written per login and kept forever, so the
    table grows with every sign-in a school ever makes — the one table
    guaranteed to grow fastest, and the only one with no retention job.

    `auth/services.py` had a `cleanup_expired_sessions` for this, written with a
    docstring saying it "should be run periodically (e.g., via cron job)", and
    nothing ever ran it. Its body is here now, as a bulk delete rather than
    loading every expired row into memory to delete them one at a time.

    Not tenant-scoped and no DataPurgeLog row: a session is infrastructure, not
    a school's data, and the purge log records what was removed from a tenant.
    """
    from modules.auth.models import Session

    try:
        deleted = (
            db.session.query(Session)
            .filter(Session.refresh_token_expires_at < _utcnow())
            .delete(synchronize_session=False)
        )
        if deleted:
            logger.info("retention.purge_expired_sessions", extra={"deleted": deleted})
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("retention.purge_expired_sessions.failed")


@shared_task(name="retention.purge_audit_logs")
def purge_audit_logs():
    """
    Purge TenantAuditLog rows past their retention window. Runs weekly.

    Finance logs: kept 1 term (120 days).
    All other modules: kept 365 days.
    """
    from modules.audit.models import TenantAuditLog

    finance_cutoff = _utcnow() - timedelta(days=120)
    other_cutoff = _utcnow() - timedelta(days=365)

    try:
        finance_deleted = (
            db.session.query(TenantAuditLog)
            .filter(
                TenantAuditLog.module == "finance",
                TenantAuditLog.created_at < finance_cutoff,
            )
            .delete(synchronize_session=False)
        )
        other_deleted = (
            db.session.query(TenantAuditLog)
            .filter(
                TenantAuditLog.module != "finance",
                TenantAuditLog.created_at < other_cutoff,
            )
            .delete(synchronize_session=False)
        )
        db.session.commit()
        logger.info(
            "retention.purge_audit_logs",
            extra={"finance_deleted": finance_deleted, "other_deleted": other_deleted},
        )
    except Exception:
        db.session.rollback()
        logger.exception("retention.purge_audit_logs.failed")


@shared_task(name="retention.advance_offboarding_stage")
def advance_offboarding_stage():
    """
    Progress tenants through the offboarding lifecycle. Runs weekly.

    Active → Grace Period (30 days) → Export Window (60 days) → Staged Deletion
    """
    from core.models import Tenant, TENANT_STATUS_SUSPENDED, TENANT_STATUS_DELETED

    now = _utcnow()
    export_deadline = now - timedelta(days=90)  # 30 grace + 60 export

    try:
        past_export = (
            db.session.query(Tenant)
            .filter(
                Tenant.status == TENANT_STATUS_SUSPENDED,
                Tenant.offboarding_started_at.isnot(None),
                Tenant.offboarding_started_at < export_deadline,
                Tenant.purge_scheduled_at.is_(None),
            )
            .all()
        )
        for tenant in past_export:
            tenant.status = TENANT_STATUS_DELETED
            tenant.purge_scheduled_at = now + timedelta(days=30)
            logger.info(
                "retention.offboarding.moved_to_deletion",
                extra={"tenant_id": tenant.id},
            )

        db.session.commit()
        logger.info("retention.advance_offboarding_stage", extra={"processed": len(past_export)})
    except Exception:
        db.session.rollback()
        logger.exception("retention.advance_offboarding_stage.failed")
