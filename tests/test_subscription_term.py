"""A school's subscription has a term, a grace period, and a paper trail.

The term is a start date and a due date on the tenant. Until the due date
the school is current. For `grace_days` after it (a week by default) the
school keeps working while Nexchool waits for the payment. After that the
school is suspended — the write gate fails closed on its own, and a nightly
job records the suspension so it is visible and audited. A school with no
due date set has no term and is never suspended by it.

Payments are records the operator enters. One may also set the next due
date, and doing so brings a suspended school back. A wrong payment is voided
with a reason, never deleted.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from flask import g

from core.models import (
    BILLING_CYCLE_YEARLY,
    TENANT_STATUS_ACTIVE,
    TENANT_STATUS_SUSPENDED,
    Tenant,
)
from modules.auth.models import User
from modules.subscription.term import (
    STANDING_CURRENT,
    STANDING_GRACE_EXPIRED,
    STANDING_NO_TERM,
    STANDING_PAYMENT_DUE,
    list_payments,
    record_payment,
    suspend_schools_past_grace,
    term_standing,
    void_payment,
)

TODAY = date(2026, 9, 13)


@pytest.fixture
def operator(db_session):
    home = Tenant(id=f"t-{uuid.uuid4().hex[:12]}", name="Platform HQ",
                  subdomain=f"hq-{uuid.uuid4().hex}", status=TENANT_STATUS_ACTIVE,
                  billing_cycle=BILLING_CYCLE_YEARLY)
    db_session.add(home)
    db_session.flush()
    u = User(id=f"pa-{uuid.uuid4().hex[:12]}", tenant_id=home.id,
             email=f"super-{uuid.uuid4().hex[:6]}@platform.test", name="Super Admin",
             is_platform_admin=True, email_verified=True)
    u.set_password("Sup3r-secret!")
    db_session.add(u)
    db_session.flush()
    return u


# ---------------------------------------------------------------------------
# Standing: where a school is in its term
# ---------------------------------------------------------------------------

def test_no_due_date_means_no_term():
    assert term_standing(due_on=None, grace_days=7, today=TODAY) == STANDING_NO_TERM


def test_current_until_and_including_the_due_date():
    assert term_standing(due_on=TODAY, grace_days=7, today=TODAY) == STANDING_CURRENT
    assert term_standing(due_on=TODAY + timedelta(days=200), grace_days=7, today=TODAY) == STANDING_CURRENT


def test_payment_due_through_the_last_day_of_grace():
    due = TODAY - timedelta(days=1)
    assert term_standing(due_on=due, grace_days=7, today=TODAY) == STANDING_PAYMENT_DUE
    assert term_standing(due_on=TODAY - timedelta(days=7), grace_days=7, today=TODAY) == STANDING_PAYMENT_DUE


def test_grace_expired_the_day_after_grace_ends():
    assert term_standing(due_on=TODAY - timedelta(days=8), grace_days=7, today=TODAY) == STANDING_GRACE_EXPIRED


def test_zero_grace_expires_the_day_after_the_due_date():
    assert term_standing(due_on=TODAY - timedelta(days=1), grace_days=0, today=TODAY) == STANDING_GRACE_EXPIRED


# ---------------------------------------------------------------------------
# The write gate follows the term
# ---------------------------------------------------------------------------

def _state(flask_app, tenant_id):
    from core.decorators.subscription import _subscription_state

    with flask_app.test_request_context("/"):
        g._subscription_state = None
        return _subscription_state(tenant_id)


def test_a_school_in_grace_keeps_writing_but_is_told_payment_is_due(flask_app, db_session, tenant):
    tenant.subscription_due_on = date.today() - timedelta(days=2)
    tenant.grace_days = 7
    db_session.flush()

    state = _state(flask_app, tenant.id)
    assert state["allow_writes"] is True
    assert state["reason"] == "PaymentDue"
    assert state["term"]["grace_ends_on"] == (date.today() + timedelta(days=5)).isoformat()


def test_a_school_past_grace_is_locked_even_before_the_nightly_job_runs(flask_app, db_session, tenant):
    tenant.subscription_due_on = date.today() - timedelta(days=30)
    tenant.grace_days = 7
    db_session.flush()

    state = _state(flask_app, tenant.id)
    assert state["allow_writes"] is False
    assert state["reason"] == "GracePeriodExpired"


def test_a_school_with_no_term_is_simply_active(flask_app, db_session, tenant):
    state = _state(flask_app, tenant.id)
    assert state["allow_writes"] is True
    assert state["reason"] == "Active"
    assert state["term"]["standing"] == STANDING_NO_TERM


# ---------------------------------------------------------------------------
# The nightly job writes the suspension down
# ---------------------------------------------------------------------------

def test_the_job_suspends_a_school_past_grace_and_leaves_the_rest(db_session, tenant):
    late = tenant
    late.subscription_due_on = TODAY - timedelta(days=8)
    in_grace = Tenant(id=f"t-{uuid.uuid4().hex[:12]}", name="In grace",
                      subdomain=f"g-{uuid.uuid4().hex}", status=TENANT_STATUS_ACTIVE,
                      billing_cycle=BILLING_CYCLE_YEARLY,
                      subscription_due_on=TODAY - timedelta(days=3))
    opted_out = Tenant(id=f"t-{uuid.uuid4().hex[:12]}", name="Manual only",
                       subdomain=f"m-{uuid.uuid4().hex}", status=TENANT_STATUS_ACTIVE,
                       billing_cycle=BILLING_CYCLE_YEARLY,
                       subscription_due_on=TODAY - timedelta(days=30),
                       auto_suspend_after_grace=False)
    db_session.add_all([in_grace, opted_out])
    db_session.flush()

    suspended = suspend_schools_past_grace(today=TODAY)

    assert suspended == [late.id]
    assert late.status == TENANT_STATUS_SUSPENDED
    assert in_grace.status == TENANT_STATUS_ACTIVE
    assert opted_out.status == TENANT_STATUS_ACTIVE
    # Running again finds nothing new to do.
    assert suspend_schools_past_grace(today=TODAY) == []


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------

def test_recording_a_payment_keeps_the_record_and_can_set_the_next_due_date(
    db_session, tenant, operator
):
    tenant.subscription_starts_on = date(2025, 6, 1)
    tenant.subscription_due_on = date(2026, 6, 1)
    tenant.status = TENANT_STATUS_SUSPENDED
    db_session.flush()

    payment = record_payment(
        tenant=tenant,
        recorded_by=operator,
        amount=Decimal("190600"),
        paid_on=date(2026, 6, 10),
        method="bank_transfer",
        reference="NEFT-8812",
        covers_from=date(2026, 6, 1),
        covers_to=date(2027, 5, 31),
        note="Annual renewal",
        next_due_on=date(2027, 6, 1),
    )
    db_session.flush()

    assert payment.amount == Decimal("190600")
    assert tenant.subscription_due_on == date(2027, 6, 1)
    assert tenant.status == TENANT_STATUS_ACTIVE
    assert [p.id for p in list_payments(tenant.id)] == [payment.id]


def test_a_payment_without_a_next_due_date_changes_nothing_about_the_term(
    db_session, tenant, operator
):
    tenant.subscription_due_on = date(2026, 6, 1)
    db_session.flush()

    record_payment(tenant=tenant, recorded_by=operator, amount=Decimal("5000"),
                   paid_on=date(2026, 3, 1), method="upi")
    assert tenant.subscription_due_on == date(2026, 6, 1)


@pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-1")])
def test_a_payment_must_be_for_a_positive_amount(db_session, tenant, operator, bad):
    with pytest.raises(ValueError, match="greater than zero"):
        record_payment(tenant=tenant, recorded_by=operator, amount=bad,
                       paid_on=date(2026, 3, 1), method="cash")


def test_an_unknown_method_is_refused(db_session, tenant, operator):
    with pytest.raises(ValueError, match="method"):
        record_payment(tenant=tenant, recorded_by=operator, amount=Decimal("1"),
                       paid_on=date(2026, 3, 1), method="barter")


def test_a_wrong_payment_is_voided_with_a_reason_and_stays_on_record(
    db_session, tenant, operator
):
    payment = record_payment(tenant=tenant, recorded_by=operator, amount=Decimal("100"),
                             paid_on=date(2026, 3, 1), method="cash")
    db_session.flush()

    void_payment(payment=payment, voided_by=operator, reason="Entered against the wrong school")
    db_session.flush()

    assert payment.voided_at is not None
    assert payment.void_reason == "Entered against the wrong school"
    assert [p.id for p in list_payments(tenant.id)] == [payment.id]
    with pytest.raises(ValueError, match="already"):
        void_payment(payment=payment, voided_by=operator, reason="twice")
