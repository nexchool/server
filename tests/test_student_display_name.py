"""A child with no login account still has a name, everywhere.

`students.user_id` is nullable — a child is always a person and only sometimes
someone who can sign in — while `students.person_id` is NOT NULL. The students
module has always resolved names from the person (`students/models.py`,
`students/services.py` search and sort on `people.full_name`).

Eight other modules did not. They read `student.user.name`, so a child without
an account rendered blank on the attendance register their teacher was marking,
on the bus roster, in the leave queue, and — worst — on their invoice PDF and
payment receipt.

This is the same defect I fixed three times in isolation before counting how
many there were. One property on the model, and everything reads through it.
"""

from __future__ import annotations

import uuid

import pytest
from flask import g


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


def _student(db_session, tenant, *, person_name="Ishaan Verma",
             login_name=None, with_login=True):
    from modules.auth.models import User
    from modules.people.models import Person
    from modules.students.models import Student

    suffix = uuid.uuid4().hex[:10]
    person = Person(id=f"pe-{suffix}", tenant_id=tenant.id,
                    full_name=person_name)
    db_session.add(person)
    db_session.flush()

    user_id = None
    if with_login:
        user = User(id=f"u-{suffix}", tenant_id=tenant.id,
                    email=f"{suffix}@test.school", password_hash="x" * 60,
                    name=login_name if login_name is not None else person_name,
                    person_id=person.id)
        db_session.add(user)
        db_session.flush()
        user_id = user.id

    student = Student(id=f"s-{suffix}", tenant_id=tenant.id, user_id=user_id,
                      person_id=person.id, admission_number=f"A-{suffix[:8]}")
    db_session.add(student)
    db_session.flush()
    return student


def test_a_child_with_no_login_is_named(ctx, db_session, tenant):
    child = _student(db_session, tenant, person_name="Ishaan Verma",
                     with_login=False)

    assert child.display_name == "Ishaan Verma"


def test_a_child_with_a_login_is_named(ctx, db_session, tenant):
    child = _student(db_session, tenant, person_name="Meera Pillai")

    assert child.display_name == "Meera Pillai"


def test_the_person_is_the_source_of_truth(ctx, db_session, tenant):
    """When the two disagree, the person wins.

    The person record is what the school administers; the login's `name` is a
    display field on an account that may never have been kept up to date.
    """
    child = _student(db_session, tenant, person_name="Anjali Rao",
                     login_name="anjali.rao@old-email")

    assert child.display_name == "Anjali Rao"


def test_a_blank_person_name_falls_back_to_the_login(ctx, db_session, tenant):
    child = _student(db_session, tenant, person_name="", login_name="Kabir Shah")

    assert child.display_name == "Kabir Shah"


def test_a_child_with_neither_has_no_name_rather_than_an_error(
    ctx, db_session, tenant
):
    """Callers render this straight into a cell; it must not raise."""
    child = _student(db_session, tenant, person_name="", with_login=False)

    assert child.display_name is None


# ---------------------------------------------------------------------------
# Nobody may go back to reading the login directly
# ---------------------------------------------------------------------------

def test_no_module_resolves_a_student_name_through_their_login():
    """The drift this fixes, pinned so it cannot come back quietly.

    Eight modules had their own `student.user.name`. Anything needing a child's
    name uses `Student.display_name`; a new `.user.name` on a student is the
    nameless-child bug again.
    """
    import pathlib
    import re

    # `users.name` is legitimate for staff and for whoever performed an
    # action — this is only about *reading* a child's name. Assigning to it is
    # correct and stays: `students/services.py` keeps the login's display name
    # in step when the child is renamed, for the children who have one.
    offender = re.compile(
        r"\b(student|st|sf\.student|leave\.student)\.user\.name\b(?!\s*=[^=])"
    )

    offenders = []
    for path in pathlib.Path("modules").rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        for i, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
            if offender.search(line):
                offenders.append(f"{path}:{i}")

    assert offenders == [], (
        "these resolve a child's name through an account they may not have:\n  "
        + "\n  ".join(offenders)
    )
