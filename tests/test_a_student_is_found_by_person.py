"""Recognising the signed-in child.

Every "my …" screen has to answer one question: given this account, whose
record is this? It was answered by reading `students.user_id`, a column that
predates the person-centric cutover. That works only while every student has
a login and the column happens to be filled in.

The account is optional (ADR-003) and the Person is the identity (ADR-001),
so the question is really "which studentship belongs to this account's
Person". Asked the old way, a child whose login was added after admission —
or whose row simply never had the column set — is told they have no record
here, which is a wrong answer that looks like an empty screen.

Unambiguous under either family-access mode: the Student relationship is what
carries the Account (ADR-011), so one account resolves to one child.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


@pytest.fixture
def academic_year(db_session, tenant):
    from modules.academics.academic_year.models import AcademicYear

    year = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 6, 1), end_date=date(2027, 3, 31), is_active=True,
    )
    db_session.add(year)
    db_session.flush()
    return year


def _child_with_login(db_session, tenant, *, fill_legacy_column: bool):
    """One child, one account, sharing a Person.

    `fill_legacy_column` decides whether `students.user_id` is set — which is
    the whole point: the answer must not depend on it.
    """
    from modules.auth.models import User
    from modules.people.models import Person
    from modules.students.models import Student

    suffix = uuid.uuid4().hex[:8]
    person = Person(id=_new_id("p-"), tenant_id=tenant.id, full_name="Aanya Rao")
    db_session.add(person)
    db_session.flush()

    account = User(
        id=f"u-{suffix}", tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name="Aanya Rao", person_id=person.id,
    )
    db_session.add(account)
    db_session.flush()

    student = Student(
        id=_new_id("s-"), tenant_id=tenant.id, person_id=person.id,
        admission_number=f"ADM-{suffix}",
        user_id=account.id if fill_legacy_column else None,
    )
    db_session.add(student)
    db_session.flush()
    return student, account


def test_a_child_is_found_through_their_person(ctx, db_session, tenant):
    from modules.students.services import student_for_user

    student, account = _child_with_login(
        db_session, tenant, fill_legacy_column=True
    )

    assert student_for_user(account.id, tenant.id) is student


def test_a_child_whose_legacy_column_was_never_set_is_still_found(
    ctx, db_session, tenant
):
    """The bug. Reading `students.user_id` answers "you have no record here"
    to a child who plainly does — their account and their studentship name the
    same human."""
    from modules.students.services import student_for_user

    student, account = _child_with_login(
        db_session, tenant, fill_legacy_column=False
    )

    assert student.user_id is None
    assert student_for_user(account.id, tenant.id) is student


def test_an_account_that_is_nobodys_studentship_finds_nothing(
    ctx, db_session, tenant
):
    """A teacher signing in is not a student, and must not become one."""
    from modules.auth.models import User
    from modules.people.models import Person
    from modules.students.services import student_for_user

    person = Person(id=_new_id("p-"), tenant_id=tenant.id, full_name="Ramesh Patel")
    db_session.add(person)
    db_session.flush()
    suffix = uuid.uuid4().hex[:8]
    account = User(
        id=f"u-{suffix}", tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name="Ramesh Patel", person_id=person.id,
    )
    db_session.add(account)
    db_session.flush()

    assert student_for_user(account.id, tenant.id) is None


def test_one_school_cannot_answer_with_anothers_child(ctx, db_session, tenant):
    from modules.students.services import student_for_user

    student, account = _child_with_login(
        db_session, tenant, fill_legacy_column=True
    )

    assert student_for_user(account.id, "some-other-tenant") is None
    assert student_for_user(account.id, tenant.id) is student


# ---------------------------------------------------------------------------
# The same question, asked of a record rather than of an account
# ---------------------------------------------------------------------------

def test_a_child_recognises_their_own_record(ctx, db_session, tenant):
    from modules.students.services import is_own_studentship

    student, account = _child_with_login(
        db_session, tenant, fill_legacy_column=False
    )

    assert is_own_studentship(student, account) is True


def test_a_child_does_not_recognise_somebody_elses(ctx, db_session, tenant):
    from modules.students.services import is_own_studentship

    _mine, account = _child_with_login(db_session, tenant, fill_legacy_column=True)
    theirs, _their_account = _child_with_login(
        db_session, tenant, fill_legacy_column=True
    )

    assert is_own_studentship(theirs, account) is False


def test_a_missing_record_is_not_anybodys(ctx, db_session, tenant):
    """Guards the shape the old check had: `not student or student.user_id !=
    user_id` read as a permission decision, so a null student had to be
    handled by every caller separately."""
    from modules.students.services import is_own_studentship

    _student, account = _child_with_login(
        db_session, tenant, fill_legacy_column=True
    )

    assert is_own_studentship(None, account) is False
