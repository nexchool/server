"""Which day a fee was collected on is the school's question, not the server's.

The dashboard's seven-day collection series labelled its days with the
school's calendar and filled them from a `cast(created_at, Date)`, which
Postgres evaluates in the session zone — UTC. The two disagreed for the five
and a half hours after midnight in India: a fee taken at 02:30 on a Saturday
was 21:00 Friday in UTC, so it was summed into Friday's bar while Saturday's
tile read zero. The money was not lost; it had been filed under yesterday.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from flask import g

from modules.dashboard import service as dashboard_service

UTC = timezone.utc


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


@pytest.fixture
def unpaid_fee(db_session, tenant):
    """One student with one fee and nothing paid on it yet."""
    from modules.academics.academic_year.models import AcademicYear
    from modules.auth.models import User
    from modules.classes.models import Class
    from modules.finance.models import FeeComponent, FeeStructure, StudentFee, StudentFeeItem
    from modules.people.models import Person
    from modules.students.models import Student

    suffix = uuid.uuid4().hex[:10]
    year = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name=f"AY-{suffix[:6]}",
        start_date=date(2026, 6, 1), end_date=date(2027, 3, 31),
    )
    db_session.add(year); db_session.flush()
    klass = Class(id=_new_id("c-"), tenant_id=tenant.id, name="Grade 6", section="A", academic_year_id=year.id)
    db_session.add(klass); db_session.flush()
    person = Person(id=f"pe-{suffix}", tenant_id=tenant.id, full_name="Child")
    db_session.add(person); db_session.flush()
    user = User(id=f"u-{suffix}", tenant_id=tenant.id, email=f"{suffix}@t.test",
                password_hash="x" * 60, name="Child", person_id=person.id)
    db_session.add(user); db_session.flush()
    student = Student(id=f"s-{suffix}", tenant_id=tenant.id, user_id=user.id, person_id=person.id,
                      admission_number=f"A-{suffix[:8]}", class_id=klass.id, academic_year_id=year.id)
    db_session.add(student); db_session.flush()
    structure = FeeStructure(id=_new_id("fs-"), tenant_id=tenant.id, academic_year_id=year.id,
                             name="Term 1", due_date=date(2026, 7, 1))
    db_session.add(structure); db_session.flush()
    component = FeeComponent(id=f"fc-{suffix}", tenant_id=tenant.id, name="Tuition",
                             fee_structure_id=structure.id, amount=1000)
    db_session.add(component); db_session.flush()
    fee = StudentFee(id=f"sf-{suffix}", tenant_id=tenant.id, student_id=student.id,
                     fee_structure_id=structure.id, total_amount=1000, due_date=date(2026, 7, 1))
    db_session.add(fee); db_session.flush()
    db_session.add(StudentFeeItem(id=f"sfi-{suffix}", tenant_id=tenant.id, student_fee_id=fee.id,
                                  fee_component_id=component.id, amount=1000))
    db_session.flush()
    return fee


def _pay(db_session, tenant, fee, amount, at: datetime):
    from modules.finance.models import Payment, PaymentStatus

    db_session.add(Payment(
        id=_new_id("pm-"), tenant_id=tenant.id, student_fee_id=fee.id,
        amount=amount, method="cash", status=PaymentStatus.success.value, created_at=at,
    ))
    db_session.flush()


def test_a_payment_after_midnight_counts_for_the_school_s_day(ctx, tenant, db_session, unpaid_fee, monkeypatch):
    # Saturday 12 Sept 2026 at the school, in the small hours.
    monkeypatch.setattr(dashboard_service, "school_today", lambda tenant_id=None: date(2026, 9, 12))

    # 02:30 IST Saturday == 21:00 UTC Friday.
    _pay(db_session, tenant, unpaid_fee, 1000, datetime(2026, 9, 11, 21, 0, tzinfo=UTC))

    series = dashboard_service._finance(tenant.id)["last_7_days_collection"]
    by_day = {point["date"]: point["amount"] for point in series}

    assert series[-1]["date"] == "2026-09-12", "the series ends on the school's today"
    assert by_day["2026-09-12"] == 1000.0, "collected on Saturday, where the school stands"
    assert by_day["2026-09-11"] == 0.0, "and not filed under Friday"


def test_the_window_starts_at_the_school_s_midnight(ctx, tenant, db_session, unpaid_fee, monkeypatch):
    """Six days back means from 00:00 at the school that day — a payment at
    00:30 IST on the first day of the window is inside it; one at 23:30 IST
    the evening before is not, even though in UTC both are on the same day."""
    monkeypatch.setattr(dashboard_service, "school_today", lambda tenant_id=None: date(2026, 9, 12))
    first_day = date(2026, 9, 6)

    _pay(db_session, tenant, unpaid_fee, 300, datetime(2026, 9, 5, 19, 0, tzinfo=UTC))   # 00:30 IST 6 Sept — in
    _pay(db_session, tenant, unpaid_fee, 700, datetime(2026, 9, 5, 18, 0, tzinfo=UTC))   # 23:30 IST 5 Sept — out

    series = dashboard_service._finance(tenant.id)["last_7_days_collection"]
    by_day = {point["date"]: point["amount"] for point in series}

    assert series[0]["date"] == first_day.isoformat()
    assert by_day[first_day.isoformat()] == 300.0
    assert sum(by_day.values()) == 300.0


def test_the_receipt_carries_the_school_s_date(ctx, tenant):
    """The same 02:30 Saturday payment used to print Friday on the receipt,
    because the date was the first ten characters of a UTC stamp."""
    from modules.finance.services.pdf_service import _receipt_day

    assert _receipt_day("2026-09-11T21:00:00+00:00") == "2026-09-12"
    assert _receipt_day("2026-09-11T21:00:00Z") == "2026-09-12"
    assert _receipt_day(None) == "—"
    assert _receipt_day("not a date") == "—"
