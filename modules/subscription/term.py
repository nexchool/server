"""The subscription term: where a school stands, and what it has paid.

A term is a start date and a due date on the tenant. Standing is derived from
the due date and the grace period, never stored, so there is one answer
whoever asks — the write gate, the nightly job, the panel, the school's own
screen. See ADR-023.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy import or_

from core.database import db
from core.models import TENANT_STATUS_ACTIVE, TENANT_STATUS_SUSPENDED, Tenant
from core.school_time import school_today, utc_now
from modules.auth.models import User
from modules.subscription.models import PAYMENT_METHODS, SubscriptionPayment

logger = logging.getLogger(__name__)

STANDING_NO_TERM = "no_term"
STANDING_CURRENT = "current"
STANDING_PAYMENT_DUE = "payment_due"
STANDING_GRACE_EXPIRED = "grace_expired"

DEFAULT_GRACE_DAYS = 7

#: How long before the due date the daily reminder starts. The same week its
#: own Subscription page turns into a countdown, so the email/push and the
#: screen begin speaking at the same moment. Two earlier, one-off warnings
#: land before this window opens — see EARLY_REMINDER_DAYS.
REMINDER_WINDOW_DAYS = 7

#: Two single-day warnings ahead of the daily window: a month out, then a
#: fortnight out. Exact-day matches, not thresholds — each fires once, not
#: "every day from here on," so a school hears from us three times before the
#: daily run at T-7 even starts, not three weeks of email.
EARLY_REMINDER_DAYS = (30, 15)


def grace_ends_on(due_on: Optional[date], grace_days: int) -> Optional[date]:
    """The last day the school keeps working after its due date."""
    if due_on is None:
        return None
    return due_on + timedelta(days=max(grace_days, 0))


def term_standing(*, due_on: Optional[date], grace_days: int, today: date) -> str:
    """Where a school is in its term on `today`.

    Current through the due date itself; payment due through the last day of
    grace; expired from the day after.
    """
    if due_on is None:
        return STANDING_NO_TERM
    if today <= due_on:
        return STANDING_CURRENT
    if today <= grace_ends_on(due_on, grace_days):
        return STANDING_PAYMENT_DUE
    return STANDING_GRACE_EXPIRED


def term_view(
    *,
    starts_on: Optional[date],
    due_on: Optional[date],
    grace_days: int,
    today: date,
) -> dict:
    """The term as every screen shows it."""
    ends = grace_ends_on(due_on, grace_days)
    return {
        "starts_on": starts_on.isoformat() if starts_on else None,
        "due_on": due_on.isoformat() if due_on else None,
        "grace_days": grace_days,
        "grace_ends_on": ends.isoformat() if ends else None,
        "days_until_due": (due_on - today).days if due_on else None,
        #: Days remaining in the grace period; negative once it has passed.
        "days_left_in_grace": (ends - today).days if ends else None,
        #: How close to the due date the school starts being told about it —
        #: the same number the daily reminder email uses, so the countdown on
        #: screen and the first email begin on the same day.
        "reminder_window_days": REMINDER_WINDOW_DAYS,
        "standing": term_standing(due_on=due_on, grace_days=grace_days, today=today),
    }


def suspend_schools_past_grace(*, today: Optional[date] = None) -> list[str]:
    """Suspend every active school whose grace period has run out.

    The write gate already refuses these schools on its own; this writes the
    suspension down so the panel, the banner and the audit trail agree with
    it. Schools that opted out of automatic suspension are left for the
    operator. Idempotent: a school already suspended is not a candidate.
    """
    today = today or school_today()
    candidates = (
        db.session.query(Tenant)
        .filter(
            Tenant.status == TENANT_STATUS_ACTIVE,
            Tenant.auto_suspend_after_grace.is_(True),
            Tenant.subscription_due_on.isnot(None),
        )
        .all()
    )
    suspended: list[str] = []
    for tenant in candidates:
        standing = term_standing(
            due_on=tenant.subscription_due_on, grace_days=tenant.grace_days, today=today
        )
        if standing != STANDING_GRACE_EXPIRED:
            continue
        tenant.status = TENANT_STATUS_SUSPENDED
        tenant.updated_at = utc_now()
        suspended.append(tenant.id)
        logger.info(
            "subscription suspended after grace",
            extra={"tenant_id": tenant.id, "due_on": tenant.subscription_due_on.isoformat()},
        )
    return suspended


def _dispatcher():
    """The notification dispatcher, looked up late so tests can stand in for it."""
    from modules.notifications.services import notification_dispatcher

    return notification_dispatcher


def _reminder_copy(tenant: Tenant, standing: str, today: date) -> tuple[str, str]:
    """What to say to a school about its outstanding payment."""
    due = tenant.subscription_due_on
    ends = grace_ends_on(due, tenant.grace_days or 0)
    if standing == STANDING_CURRENT:
        days = (due - today).days
        when = "today" if days == 0 else f"in {days} day{'' if days == 1 else 's'}"
        return (
            "Subscription payment due",
            f"Your Nexchool subscription payment for {tenant.name} is due "
            f"{when}, on {due.isoformat()}.",
        )
    if standing == STANDING_PAYMENT_DUE:
        left = (ends - today).days
        return (
            "Subscription payment overdue",
            f"Your Nexchool subscription payment for {tenant.name} was due on "
            f"{due.isoformat()}. Your school keeps working through the grace "
            f"period, which ends on {ends.isoformat()} "
            f"({left} day{'' if left == 1 else 's'} left).",
        )
    return (
        "Subscription suspended — payment overdue",
        f"Your Nexchool subscription payment for {tenant.name} was due on "
        f"{due.isoformat()} and the grace period ended on {ends.isoformat()}. "
        f"The school is suspended and changes cannot be saved until the "
        f"payment is recorded.",
    )


def schools_needing_payment_reminder(*, today: date) -> list[Tenant]:
    """Schools with an outstanding payment that have not heard from us today.

    From a week before the due date until the payment moves the term on —
    through the grace period and beyond it, because a suspended school is the
    one that most needs telling. A school with no term is never in this list.
    """
    candidates = (
        db.session.query(Tenant)
        .filter(
            Tenant.status.in_([TENANT_STATUS_ACTIVE, TENANT_STATUS_SUSPENDED]),
            Tenant.subscription_due_on.isnot(None),
            or_(
                Tenant.last_payment_reminder_on.is_(None),
                Tenant.last_payment_reminder_on != today,
            ),
        )
        .all()
    )
    due_soon = []
    for tenant in candidates:
        standing = term_standing(
            due_on=tenant.subscription_due_on,
            grace_days=tenant.grace_days or 0,
            today=today,
        )
        if standing == STANDING_NO_TERM:
            continue
        if standing == STANDING_CURRENT:
            days_until_due = (tenant.subscription_due_on - today).days
            if days_until_due > REMINDER_WINDOW_DAYS and days_until_due not in EARLY_REMINDER_DAYS:
                continue
        due_soon.append(tenant)
    return due_soon


def send_payment_reminders(*, today: Optional[date] = None) -> dict:
    """Tell every school with an outstanding payment, once for the day.

    One school's failure does not stop the rest: a school whose reminder
    could not be sent keeps its old stamp and is picked up on the next run.
    """
    from modules.notifications.enums import NotificationChannel, NotificationType
    from modules.rbac.authority_service import user_ids_holding_profiles

    today = today or school_today()
    reminded: list[str] = []
    failed: list[str] = []
    dispatcher = _dispatcher()

    for tenant in schools_needing_payment_reminder(today=today):
        standing = term_standing(
            due_on=tenant.subscription_due_on,
            grace_days=tenant.grace_days or 0,
            today=today,
        )
        title, body = _reminder_copy(tenant, standing, today)
        administrators = sorted(user_ids_holding_profiles(tenant.id, ("Admin",)))
        if not administrators:
            # Nobody to tell. Stamp it anyway: retrying every day would only
            # log the same nothing, and the operator can see the school in the
            # panel either way.
            logger.warning(
                "subscription reminder has no administrator to reach",
                extra={"tenant_id": tenant.id},
            )
            tenant.last_payment_reminder_on = today
            continue
        try:
            for user_id in administrators:
                dispatcher.dispatch(
                    user_id=user_id,
                    tenant_id=tenant.id,
                    notification_type=NotificationType.SUBSCRIPTION_PAYMENT_DUE.value,
                    channels=[
                        NotificationChannel.IN_APP.value,
                        NotificationChannel.EMAIL.value,
                        NotificationChannel.PUSH.value,
                    ],
                    title=title,
                    body=body,
                    extra_data={
                        "due_on": tenant.subscription_due_on.isoformat(),
                        "grace_ends_on": grace_ends_on(
                            tenant.subscription_due_on, tenant.grace_days or 0
                        ).isoformat(),
                        "standing": standing,
                    },
                )
        except Exception:  # noqa: BLE001
            logger.exception(
                "subscription reminder failed", extra={"tenant_id": tenant.id}
            )
            failed.append(tenant.id)
            continue
        tenant.last_payment_reminder_on = today
        reminded.append(tenant.id)

    return {"reminded": reminded, "failed": failed}


def record_payment(
    *,
    tenant: Tenant,
    recorded_by: User,
    amount: Decimal,
    paid_on: date,
    method: str,
    reference: Optional[str] = None,
    covers_from: Optional[date] = None,
    covers_to: Optional[date] = None,
    note: Optional[str] = None,
    next_due_on: Optional[date] = None,
) -> SubscriptionPayment:
    """Write a payment down, and optionally move the term on.

    Setting `next_due_on` is how a renewal is recorded: the due date moves,
    the start date is set if it never was, and a school suspended for
    non-payment is brought back. A payment without it is just a record — a
    part payment, say — and changes nothing about the term.
    """
    if amount is None or amount <= 0:
        raise ValueError("Payment amount must be greater than zero")
    if method not in PAYMENT_METHODS:
        raise ValueError(f"Payment method must be one of {', '.join(PAYMENT_METHODS)}")
    if covers_from and covers_to and covers_from > covers_to:
        raise ValueError("The period covered must start before it ends")

    payment = SubscriptionPayment(
        tenant_id=tenant.id,
        amount=amount,
        paid_on=paid_on,
        method=method,
        reference=(reference or "").strip() or None,
        covers_from=covers_from,
        covers_to=covers_to,
        note=(note or "").strip() or None,
        recorded_by_user_id=recorded_by.id,
    )
    db.session.add(payment)

    if next_due_on is not None:
        if tenant.subscription_starts_on is None:
            tenant.subscription_starts_on = covers_from or paid_on
        tenant.subscription_due_on = next_due_on
        if tenant.status == TENANT_STATUS_SUSPENDED:
            tenant.status = TENANT_STATUS_ACTIVE
        tenant.updated_at = utc_now()
    return payment


def void_payment(*, payment: SubscriptionPayment, voided_by: User, reason: str) -> None:
    """Strike a payment through. It stays on the list with the reason."""
    if payment.voided_at is not None:
        raise ValueError("This payment has already been voided")
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("A reason is required to void a payment")
    payment.voided_at = utc_now()
    payment.void_reason = reason
    payment.voided_by_user_id = voided_by.id


def list_payments(tenant_id: str) -> list[SubscriptionPayment]:
    """Every payment on record for the school, newest first, voided included."""
    return (
        db.session.query(SubscriptionPayment)
        .filter(SubscriptionPayment.tenant_id == tenant_id)
        .order_by(SubscriptionPayment.paid_on.desc(), SubscriptionPayment.created_at.desc())
        .all()
    )
