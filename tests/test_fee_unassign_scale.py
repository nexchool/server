"""Removing a fee structure's classes deleted one student fee at a time.

`unassign_fees_for_removed_classes` runs when a school edits a fee structure to
exclude some classes. For each affected student fee it ran four statements — a
payment COUNT to decide whether it may be removed, then three DELETEs — so a
structure covering five hundred children meant two thousand round trips inside
one transaction.

That is slow, but the sharper problem is what slow means for a destructive
operation: the longer the transaction, the longer the rows are locked and the
more likely it is to hit a statement timeout partway through.

All four collapse into set operations: one grouped query to find which fees
have been paid against, and three bulk deletes over the rest.

The rule itself must not change — a fee with a successful payment against it is
never removed.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g
from sqlalchemy import event

from core.database import db
from modules.finance.services import student_fee_service as svc


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


@pytest.fixture
def year(db_session, tenant):
    from modules.academics.academic_year.models import AcademicYear

    ay = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id,
        name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 6, 1), end_date=date(2027, 3, 31),
    )
    db_session.add(ay)
    db_session.flush()
    return ay


@pytest.fixture
def klass(db_session, tenant, year):
    from modules.classes.models import Class

    cls = Class(id=_new_id("c-"), tenant_id=tenant.id, name="Grade 6",
                section="A", academic_year_id=year.id)
    db_session.add(cls)
    db_session.flush()
    return cls


@pytest.fixture
def structure(db_session, tenant, year):
    from modules.finance.models import FeeStructure

    fs = FeeStructure(
        id=_new_id("fs-"), tenant_id=tenant.id, academic_year_id=year.id,
        name="Term 1", due_date=date(2026, 7, 1),
    )
    db_session.add(fs)
    db_session.flush()
    return fs


def _student(db_session, tenant, klass):
    from modules.auth.models import User
    from modules.people.models import Person
    from modules.students.models import Student

    suffix = uuid.uuid4().hex[:10]
    person = Person(id=f"pe-{suffix}", tenant_id=tenant.id, full_name="Child")
    db_session.add(person)
    db_session.flush()
    user = User(id=f"u-{suffix}", tenant_id=tenant.id,
                email=f"{suffix}@t.test", password_hash="x" * 60,
                name="Child", person_id=person.id)
    db_session.add(user)
    db_session.flush()
    student = Student(id=f"s-{suffix}", tenant_id=tenant.id, user_id=user.id,
                      person_id=person.id, admission_number=f"A-{suffix[:8]}",
                      class_id=klass.id, academic_year_id=klass.academic_year_id)
    db_session.add(student)
    db_session.flush()
    return student


def _component(db_session, tenant, structure):
    from modules.finance.models import FeeComponent

    suffix = uuid.uuid4().hex[:10]
    component = FeeComponent(
        id=f"fc-{suffix}", tenant_id=tenant.id, name=f"Tuition {suffix[:4]}",
        fee_structure_id=structure.id, amount=1000,
    )
    db_session.add(component)
    db_session.flush()
    return component


def _fee(db_session, tenant, structure, student, *, paid=False, year=None):
    from modules.finance.models import (
        Payment, PaymentStatus, StudentFee, StudentFeeItem,
    )

    suffix = uuid.uuid4().hex[:10]
    fee = StudentFee(
        id=f"sf-{suffix}", tenant_id=tenant.id, student_id=student.id,
        fee_structure_id=structure.id,
        total_amount=1000, due_date=date(2026, 7, 1),
    )
    db_session.add(fee)
    db_session.flush()
    db_session.add(StudentFeeItem(
        id=f"sfi-{suffix}", tenant_id=tenant.id, student_fee_id=fee.id,
        fee_component_id=_component(db_session, tenant, structure).id, amount=1000,
    ))
    db_session.flush()
    if paid:
        db_session.add(Payment(
            id=f"pm-{suffix}", tenant_id=tenant.id, student_fee_id=fee.id,
            amount=1000, method="cash", status=PaymentStatus.success.value,
        ))
        db_session.flush()
    return fee


# ---------------------------------------------------------------------------
# The rule must not change
# ---------------------------------------------------------------------------

def test_an_unpaid_fee_is_removed(ctx, db_session, tenant, klass, structure):
    from modules.finance.models import StudentFee

    fee_id = _fee(db_session, tenant, structure,
                  _student(db_session, tenant, klass)).id

    result = svc.unassign_fees_for_removed_classes(structure.id, [klass.id])

    assert result["success"] is True
    assert result["removed_count"] == 1
    assert StudentFee.query.filter_by(id=fee_id).first() is None


def test_a_fee_that_has_been_paid_is_kept(ctx, db_session, tenant, klass, structure):
    """Deleting a paid fee would erase the record of money received."""
    from modules.finance.models import StudentFee

    fee = _fee(db_session, tenant, structure,
               _student(db_session, tenant, klass), paid=True)

    result = svc.unassign_fees_for_removed_classes(structure.id, [klass.id])

    assert result["removed_count"] == 0
    assert StudentFee.query.filter_by(id=fee.id).first() is not None


def test_a_mixed_class_removes_only_the_unpaid(
    ctx, db_session, tenant, klass, structure
):
    from modules.finance.models import StudentFee

    kept_id = _fee(db_session, tenant, structure,
                   _student(db_session, tenant, klass), paid=True).id
    gone_ids = [
        _fee(db_session, tenant, structure,
             _student(db_session, tenant, klass)).id
        for _ in range(3)
    ]

    result = svc.unassign_fees_for_removed_classes(structure.id, [klass.id])

    assert result["removed_count"] == 3
    assert StudentFee.query.filter_by(id=kept_id).first() is not None
    for fee_id in gone_ids:
        assert StudentFee.query.filter_by(id=fee_id).first() is None


def test_the_fee_items_go_with_the_fee(ctx, db_session, tenant, klass, structure):
    from modules.finance.models import StudentFeeItem

    fee_id = _fee(db_session, tenant, structure,
                  _student(db_session, tenant, klass)).id

    svc.unassign_fees_for_removed_classes(structure.id, [klass.id])

    assert StudentFeeItem.query.filter_by(student_fee_id=fee_id).first() is None


def test_no_classes_is_a_no_op(ctx, db_session, tenant, klass, structure):
    _fee(db_session, tenant, structure, _student(db_session, tenant, klass))

    result = svc.unassign_fees_for_removed_classes(structure.id, [])

    assert result["removed_count"] == 0


def test_a_class_with_nobody_in_it_removes_nothing(
    ctx, db_session, tenant, klass, structure, year
):
    from modules.classes.models import Class

    empty = Class(id=_new_id("c-"), tenant_id=tenant.id, name="Grade 9",
                  section="Z", academic_year_id=year.id)
    db_session.add(empty)
    db_session.flush()

    result = svc.unassign_fees_for_removed_classes(structure.id, [empty.id])

    assert result["removed_count"] == 0


# ---------------------------------------------------------------------------
# Cost, on a destructive operation where a timeout is a half-done delete
# ---------------------------------------------------------------------------

def test_the_cost_does_not_grow_with_the_number_of_children(
    ctx, db_session, tenant, klass, structure
):
    seen: list[str] = []

    def record(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    def measure():
        seen.clear()
        event.listen(db.engine, "before_cursor_execute", record)
        try:
            svc.unassign_fees_for_removed_classes(structure.id, [klass.id])
        finally:
            event.remove(db.engine, "before_cursor_execute", record)
        return len(seen)

    for _ in range(3):
        _fee(db_session, tenant, structure, _student(db_session, tenant, klass))
    small = measure()

    for _ in range(18):
        _fee(db_session, tenant, structure, _student(db_session, tenant, klass))
    large = measure()

    assert large == small, (
        f"{small} statements for 3 children, {large} for 18 — four per child"
    )
