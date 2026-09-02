"""A reminder nobody received is not a reminder that was sent.

`send_invoice_reminder` builds the in-app notification inside a
`try: ... except Exception: pass`. When that fails, `channels_sent` stays
empty, the commit that follows has nothing to write and therefore succeeds, and
the function returns

    {"success": True, "channels_sent": []}

So the office clicks "send reminder", the API answers 200, the screen says it
went — and the parent is never told. The one signal that anything went wrong is
an empty `channels_sent`, and nothing looks at it.

This is the failure mode the forbidden-patterns rule against empty catch blocks
exists to prevent: not a crash, but a quiet claim that something happened.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from flask import g


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


@pytest.fixture
def unpaid_invoice(db_session, tenant):
    from modules.auth.models import User
    from modules.fees.models import FeeInvoice
    from modules.people.models import Person
    from modules.students.models import Student

    suffix = uuid.uuid4().hex[:10]
    person = Person(id=f"pe-{suffix}", tenant_id=tenant.id, full_name="Payer")
    db_session.add(person)
    db_session.flush()
    user = User(id=f"u-{suffix}", tenant_id=tenant.id,
                email=f"{suffix}@t.test", password_hash="x" * 60,
                name="Payer", person_id=person.id)
    db_session.add(user)
    db_session.flush()
    student = Student(id=f"s-{suffix}", tenant_id=tenant.id, user_id=user.id,
                      person_id=person.id, admission_number=f"A-{suffix[:8]}")
    db_session.add(student)
    db_session.flush()

    invoice = FeeInvoice(
        id=f"fi-{suffix}", tenant_id=tenant.id, student_id=student.id,
        invoice_number=f"INV-{suffix[:8]}", academic_year="2026-27",
        issue_date=date(2026, 6, 1), due_date=date(2026, 7, 1),
        subtotal=Decimal("1000.00"), total_amount=Decimal("1000.00"),
        status="unpaid",
    )
    db_session.add(invoice)
    db_session.flush()
    return invoice


def test_a_reminder_that_reached_nobody_is_not_a_success(
    ctx, db_session, tenant, unpaid_invoice, monkeypatch
):
    """The office is told it was sent when it was not."""
    from modules.fees.services import reminder_service

    class _Explodes:
        def __init__(self, *a, **k):
            raise RuntimeError("notifications table is unhappy")

    monkeypatch.setattr(reminder_service, "Notification", _Explodes)

    result = reminder_service.send_invoice_reminder(unpaid_invoice.id)

    assert result["success"] is False, (
        "reported success for a reminder that reached no channel"
    )
    assert result.get("channels_sent", []) == []


def test_the_failure_is_logged_with_the_invoice(
    ctx, db_session, tenant, unpaid_invoice, monkeypatch, caplog
):
    """`except: pass` left no trace at all; the office cannot chase what it
    cannot see, and neither can anyone reading the logs afterwards."""
    import logging

    from modules.fees.services import reminder_service

    class _Explodes:
        def __init__(self, *a, **k):
            raise RuntimeError("notifications table is unhappy")

    monkeypatch.setattr(reminder_service, "Notification", _Explodes)

    with caplog.at_level(logging.ERROR):
        reminder_service.send_invoice_reminder(unpaid_invoice.id)

    assert any(unpaid_invoice.id in r.getMessage() for r in caplog.records), (
        "the failure was swallowed without naming the invoice"
    )


def test_an_ordinary_reminder_still_reports_the_channel(
    ctx, db_session, tenant, unpaid_invoice
):
    from modules.fees.services import reminder_service

    result = reminder_service.send_invoice_reminder(unpaid_invoice.id)

    assert result["success"] is True
    assert result["channels_sent"] == ["in_app"]


def test_a_paid_invoice_is_still_refused(ctx, db_session, tenant, unpaid_invoice):
    """The existing guards must keep working."""
    from modules.fees.services import reminder_service

    unpaid_invoice.status = "paid"
    db_session.flush()

    result = reminder_service.send_invoice_reminder(unpaid_invoice.id)

    assert result["success"] is False
    assert "paid" in result["error"].lower()
