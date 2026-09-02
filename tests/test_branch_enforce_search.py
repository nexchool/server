"""Global search must not be the way around campus scoping.

Every other read a campus-restricted sub-admin makes is filtered through
`core/branch_scope`. Search reached none of it: each of its four sub-queries
stopped at `tenant_id`. And its gates — `student.read.all`, `class.read`,
`fees.invoice.read`/`finance.read` — are all keys a branch-restricted sub-admin
can actually be granted, so this was live rather than latent.

Two characters in the search box returned, across every campus: children with
their admission numbers and class, staff with their employee numbers, section
names, and **fee invoices with a student's name and the amount owed**.

The four searches anchor differently, and each uses the helper for its own
domain: students and fees by the child, classes by the unit they belong to,
teachers by where they teach.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g

from modules.academics.backbone.models import ClassSubjectTeacher
from modules.auth.models import User
from modules.classes.models import Class, ClassSubject
from modules.people.employment import Staff
from modules.people.models import Person
from modules.search import services as search_services
from modules.students.models import Student
from modules.subjects.models import Subject
from modules.sub_admins.models import UserSchoolUnit
from modules.teachers.models import Teacher

#: Every seeded name and number contains this, so one query matches everything.
NEEDLE = "Zarq"


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def units(db_session, tenant):
    from modules.school_units.models import SchoolUnit

    made = []
    for label in ("A", "B"):
        unit = SchoolUnit(
            id=_new_id("su-"), tenant_id=tenant.id, name=f"{NEEDLE} Campus {label}",
            code=f"{label}-{uuid.uuid4().hex[:6]}",
        )
        db_session.add(unit)
        made.append(unit)
    db_session.flush()
    return made


@pytest.fixture
def year(db_session, tenant):
    from modules.academics.academic_year.models import AcademicYear

    row = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name=f"AY-{uuid.uuid4().hex[:5]}",
        start_date=date(2026, 4, 1), end_date=date(2027, 3, 31),
    )
    db_session.add(row)
    db_session.flush()
    return row


def _person(db_session, tenant, name):
    row = Person(id=_new_id("pe-"), tenant_id=tenant.id, full_name=name)
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def school(db_session, tenant, units, year):
    """A section, a child, a teacher and an invoice on each of two campuses."""
    from modules.fees.models import FeeInvoice

    made = {}
    for label, unit in zip(("A", "B"), units):
        section = Class(
            id=_new_id("cl-"), tenant_id=tenant.id,
            name=f"{NEEDLE} Grade", section=label,
            academic_year_id=year.id, school_unit_id=unit.id,
        )
        db_session.add(section)
        db_session.flush()

        child = Student(
            id=_new_id("st-"), tenant_id=tenant.id,
            person_id=_person(db_session, tenant, f"{NEEDLE} Child {label}").id,
            admission_number=f"{NEEDLE}-{label}-{uuid.uuid4().hex[:5]}",
            academic_year_id=year.id, class_id=section.id,
        )
        db_session.add(child)
        db_session.flush()

        # A teacher who teaches in this section, so branch scope can see them.
        staff = Staff(
            id=_new_id("sf-"), tenant_id=tenant.id,
            person_id=_person(db_session, tenant, f"{NEEDLE} Teacher {label}").id,
            employee_number=f"{NEEDLE}{label}{uuid.uuid4().hex[:4]}",
        )
        db_session.add(staff)
        db_session.flush()
        teacher = Teacher(id=_new_id("te-"), tenant_id=tenant.id, staff_id=staff.id)
        db_session.add(teacher)
        db_session.flush()

        subject = Subject(
            id=_new_id("sb-"), tenant_id=tenant.id,
            name=f"{NEEDLE} Subject {label}", code=f"{label}{uuid.uuid4().hex[:4]}",
        )
        db_session.add(subject)
        db_session.flush()
        offering = ClassSubject(
            id=_new_id("cs-"), tenant_id=tenant.id, class_id=section.id,
            subject_id=subject.id, weekly_periods=5, status="active",
        )
        db_session.add(offering)
        db_session.flush()
        db_session.add(ClassSubjectTeacher(
            id=_new_id("ct-"), tenant_id=tenant.id,
            class_subject_id=offering.id, teacher_id=teacher.id,
            role="primary", is_active=True,
        ))

        invoice = FeeInvoice(
            id=_new_id("fi-"), tenant_id=tenant.id, student_id=child.id,
            invoice_number=f"{NEEDLE}-INV-{label}-{uuid.uuid4().hex[:5]}",
            academic_year=year.name,
            issue_date=date(2026, 4, 15), due_date=date(2026, 5, 15),
            subtotal=25000, total_amount=25000, status="pending",
        )
        db_session.add(invoice)
        db_session.flush()

        made[label] = {
            "class": section, "student": child,
            "teacher": teacher, "invoice": invoice,
        }
    return made


def _searcher(db_session, tenant, *, branches=()):
    """Somebody who may search everything the search surface offers."""
    from modules.rbac.models import Permission, Role, RolePermission
    from tests.conftest import grant_profile_to

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}", tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name="Searcher",
    )
    db_session.add(user)
    db_session.flush()

    role = Role(id=f"r-{suffix}", tenant_id=tenant.id, name=f"Role-{suffix}")
    db_session.add(role)
    db_session.flush()
    for key in ("student.read.all", "teacher.read", "class.read", "finance.read"):
        permission = Permission.query.filter_by(name=key).first()
        if permission is None:
            permission = Permission(id=_new_id("perm-"), name=key)
            db_session.add(permission)
            db_session.flush()
        db_session.add(RolePermission(
            tenant_id=tenant.id, role_id=role.id, permission_id=permission.id
        ))
    for branch in branches:
        db_session.add(UserSchoolUnit(
            id=_new_id("usu-"), tenant_id=tenant.id,
            user_id=user.id, school_unit_id=branch.id,
        ))
    db_session.flush()
    grant_profile_to(user, role.id, employee_number=f"EMP-{suffix}")
    return user


@pytest.fixture
def as_user(flask_app, tenant):
    from contextlib import contextmanager

    @contextmanager
    def _run(user):
        with flask_app.test_request_context("/"):
            # `g` lives on the app context, which test_request_context reuses.
            g.pop("_branch_scope_allowed_unit_ids", None)
            g.pop("_branch_scope_allowed_class_ids", None)
            g.tenant_id = tenant.id
            g.current_user = user
            yield

    return _run


def test_a_campus_head_searches_only_their_own_campus(
    as_user, db_session, tenant, units, school
):
    head = _searcher(db_session, tenant, branches=(units[0],))

    with as_user(head):
        found = search_services.global_search(head, NEEDLE, limit=10)

    assert [s["id"] for s in found["students"]] == [school["A"]["student"].id]
    assert [c["id"] for c in found["classes"]] == [school["A"]["class"].id]
    assert [t["id"] for t in found["teachers"]] == [school["A"]["teacher"].id]
    assert [f["id"] for f in found["fees"]] == [school["A"]["invoice"].id], (
        "a fee invoice carries a child's name and what they owe"
    )


def test_a_matching_fee_invoice_does_not_crash_the_search(
    as_user, db_session, tenant, school
):
    """`_search_fees` raised NameError on its first matching row.

    Its comprehension unpacked `for inv, u in rows` and then read `person`,
    which is not a name in that scope — so global search 500'd for anyone
    holding a finance key the moment a search matched an invoice number or a
    child's name. It survived because no test had ever put a matching invoice
    in front of it.
    """
    admin = _searcher(db_session, tenant)

    with as_user(admin):
        found = search_services.global_search(admin, NEEDLE, limit=10)

    assert found["fees"], "the seeded invoices match the query"
    for invoice in found["fees"]:
        assert invoice["student_name"], "the child's name is what makes it useful"


def test_an_unrestricted_admin_still_searches_the_whole_trust(
    as_user, db_session, tenant, school
):
    """Regression guard: the helpers are a strict no-op without a restriction."""
    admin = _searcher(db_session, tenant)

    with as_user(admin):
        found = search_services.global_search(admin, NEEDLE, limit=10)

    assert len(found["students"]) == 2
    assert len(found["classes"]) == 2
    assert len(found["teachers"]) == 2
    assert len(found["fees"]) == 2
