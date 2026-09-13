"""A school is reminded, once a day, while a payment is outstanding.

The reminder starts a week before the due date — the same week the school's
own screen turns into a countdown — and keeps going every day through the
grace period and after it, because a suspended school is exactly the one that
most needs telling. It stops the moment the term moves on.

Once a day, not once a run: the job is safe to re-run, and a school never
gets two reminders for the same day.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from core.models import BILLING_CYCLE_YEARLY, TENANT_STATUS_ACTIVE, Tenant
from modules.subscription.term import (
    REMINDER_WINDOW_DAYS,
    send_payment_reminders,
)

TODAY = date(2026, 9, 13)


@pytest.fixture
def sent(monkeypatch):
    """Capture what would have been emailed, instead of emailing it."""
    import modules.subscription.term as term_module

    calls = []

    class _Recorder:
        def dispatch(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(term_module, "_dispatcher", lambda: _Recorder())
    return calls


def _school(db_session, *, due_on, status=TENANT_STATUS_ACTIVE, grace_days=7,
            last_reminded=None):
    tenant = Tenant(
        id=f"t-{uuid.uuid4().hex[:12]}",
        name="Reminder School",
        subdomain=f"rem-{uuid.uuid4().hex}",
        status=status,
        billing_cycle=BILLING_CYCLE_YEARLY,
        subscription_due_on=due_on,
        grace_days=grace_days,
        last_payment_reminder_on=last_reminded,
    )
    db_session.add(tenant)
    db_session.flush()
    return tenant


def _admin_of(db_session, tenant):
    """An account holding the school's Admin profile, the way a real one does.

    Authority is held by the employment, not the login (ADR-013), so the
    person is employed into the Admin role — the same profile
    `list_tenant_admins` reads when the panel asks who runs this school.
    """
    import uuid as _uuid

    from modules.rbac.models import Permission, Role, RolePermission
    from tests.auth._characterization import make_user
    from tests.conftest import grant_profile_to

    role = Role.query.filter_by(name="Admin", tenant_id=tenant.id).first()
    if role is None:
        role = Role(id=f"r-{_uuid.uuid4().hex[:12]}", tenant_id=tenant.id, name="Admin")
        db_session.add(role)
        db_session.flush()
        permission = Permission.query.filter_by(name="subscription.read").first()
        if permission is None:
            permission = Permission(id=f"perm-{_uuid.uuid4().hex[:8]}", name="subscription.read")
            db_session.add(permission)
            db_session.flush()
        db_session.add(
            RolePermission(tenant_id=tenant.id, role_id=role.id, permission_id=permission.id)
        )
        db_session.flush()

    user = make_user(db_session, tenant, password="Member12345")
    grant_profile_to(user, role.id, employee_number=f"EMP-{_uuid.uuid4().hex[:8]}")
    return user


def test_a_school_a_week_out_is_reminded(db_session, sent):
    tenant = _school(db_session, due_on=TODAY + timedelta(days=REMINDER_WINDOW_DAYS))
    _admin_of(db_session, tenant)

    result = send_payment_reminders(today=TODAY)

    assert tenant.id in result["reminded"]
    assert len(sent) == 1
    assert "due" in sent[0]["body"].lower()


def test_a_school_further_out_than_the_window_is_left_alone(db_session, sent):
    tenant = _school(db_session, due_on=TODAY + timedelta(days=REMINDER_WINDOW_DAYS + 1))
    _admin_of(db_session, tenant)

    assert send_payment_reminders(today=TODAY)["reminded"] == []
    assert sent == []


def test_a_school_in_its_grace_period_is_reminded(db_session, sent):
    tenant = _school(db_session, due_on=TODAY - timedelta(days=3))
    _admin_of(db_session, tenant)

    assert tenant.id in send_payment_reminders(today=TODAY)["reminded"]
    assert "grace" in sent[0]["body"].lower()


def test_a_suspended_school_is_reminded_too(db_session, sent):
    tenant = _school(db_session, due_on=TODAY - timedelta(days=30), status="suspended")
    _admin_of(db_session, tenant)

    assert tenant.id in send_payment_reminders(today=TODAY)["reminded"]
    assert "suspended" in sent[0]["body"].lower()


def test_a_school_with_no_term_is_never_reminded(db_session, sent):
    tenant = _school(db_session, due_on=None)
    _admin_of(db_session, tenant)

    assert send_payment_reminders(today=TODAY)["reminded"] == []


def test_a_school_already_reminded_today_is_not_reminded_twice(db_session, sent):
    tenant = _school(db_session, due_on=TODAY + timedelta(days=2), last_reminded=TODAY)
    _admin_of(db_session, tenant)

    assert send_payment_reminders(today=TODAY)["reminded"] == []
    assert sent == []


def test_running_the_job_twice_in_a_day_sends_one_reminder(db_session, sent):
    tenant = _school(db_session, due_on=TODAY + timedelta(days=2))
    _admin_of(db_session, tenant)

    send_payment_reminders(today=TODAY)
    send_payment_reminders(today=TODAY)

    assert len(sent) == 1
    assert tenant.last_payment_reminder_on == TODAY


def test_the_next_day_brings_another_reminder(db_session, sent):
    tenant = _school(db_session, due_on=TODAY + timedelta(days=2))
    _admin_of(db_session, tenant)

    send_payment_reminders(today=TODAY)
    send_payment_reminders(today=TODAY + timedelta(days=1))

    assert len(sent) == 2


def test_every_administrator_is_told_and_nobody_else(db_session, sent):
    tenant = _school(db_session, due_on=TODAY + timedelta(days=1))
    first, second = _admin_of(db_session, tenant), _admin_of(db_session, tenant)
    from tests.auth._characterization import grant_permissions, make_user

    # A teacher runs no billing and hears nothing about it.
    teacher = make_user(db_session, tenant, password="Member12345")
    grant_permissions(db_session, tenant, teacher, ("student.read.all",))

    send_payment_reminders(today=TODAY)

    told = {call["user_id"] for call in sent}
    assert told == {first.id, second.id}


def test_the_reminder_goes_out_by_email_as_well_as_in_the_app(db_session, sent):
    tenant = _school(db_session, due_on=TODAY + timedelta(days=1))
    _admin_of(db_session, tenant)

    send_payment_reminders(today=TODAY)

    assert "EMAIL" in sent[0]["channels"]
    assert "IN_APP" in sent[0]["channels"]
