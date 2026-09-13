"""Nightly: write down the suspension of schools whose grace period ran out.

The write gate already refuses them (core/decorators/subscription.py); this
makes the panel, the school's banner and the audit trail say the same thing.
"""

from __future__ import annotations

from celery_app import get_celery

celery_app = get_celery()


@celery_app.task(bind=True, name="subscription.suspend_after_grace")
def suspend_after_grace_task(self):
    from core.database import db
    from modules.subscription.term import suspend_schools_past_grace

    try:
        suspended = suspend_schools_past_grace()
        db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()
        raise
    return {"suspended": suspended}


@celery_app.task(bind=True, name="subscription.send_payment_reminders")
def send_payment_reminders_task(self):
    """Daily: remind schools with an outstanding subscription payment.

    Starts a week before the due date and continues through grace and
    suspension. Once a day per school, so re-running is harmless.
    """
    from core.database import db
    from modules.subscription.term import send_payment_reminders

    try:
        result = send_payment_reminders()
        db.session.commit()
    except Exception:  # noqa: BLE001
        db.session.rollback()
        raise
    return result
