"""What a student studies, where it differs from what the class offers.

Grade 11 Science offers Biology and Computer Science; each student takes one.
Nothing in the schema could say which, so "who sits the Physics paper" could
only ever be answered "everyone in the class" — including the four who dropped
it.

Elections are deviations. A section with no electives writes no rows, which is
what keeps the ordinary school unchanged.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g
from sqlalchemy.exc import IntegrityError

from modules.academics.academic_year.models import AcademicYear
from modules.classes.models import Class, ClassSubject
from modules.students.election_service import (
    class_has_electives,
    effective_class_subjects,
    record_election,
    withdraw_election,
)
from modules.students.elections import (
    ELECTION_DROPPED,
    ELECTION_EXEMPTED,
    ELECTION_TAKING,
    StudentSubjectElection,
)
from modules.students.class_enrollment_service import (
    assign_student_to_class,
    enroll_additional,
)
from modules.students.models import Student
from modules.subjects.models import Subject


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


@pytest.fixture
def academic_year(db_session, tenant):
    row = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 6, 1), end_date=date(2027, 3, 31),
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def science(db_session, tenant, academic_year):
    row = Class(
        id=_new_id("cl-"), tenant_id=tenant.id, section="A",
        name="Grade 11 Science", academic_year_id=academic_year.id,
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def other_class(db_session, tenant, academic_year):
    row = Class(
        id=_new_id("cl-"), tenant_id=tenant.id, section="B",
        name="Grade 11 Commerce", academic_year_id=academic_year.id,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _subject(db_session, tenant, label):
    row = Subject(
        id=_new_id("sb-"), tenant_id=tenant.id,
        name=f"{label}-{uuid.uuid4().hex[:6]}",
        code=f"{label[:3].upper()}{uuid.uuid4().hex[:4]}",
    )
    db_session.add(row)
    db_session.flush()
    return row


def _offer(db_session, tenant, cls, subject, *, mandatory=True):
    row = ClassSubject(
        id=_new_id("cs-"), tenant_id=tenant.id, class_id=cls.id,
        subject_id=subject.id, weekly_periods=5,
        is_mandatory=mandatory, is_elective_bucket=not mandatory,
        status="active",
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def curriculum(db_session, tenant, science):
    """Three mandatory subjects and two electives — the Grade 11 shape."""
    return {
        "physics": _offer(db_session, tenant, science, _subject(db_session, tenant, "Physics")),
        "chemistry": _offer(db_session, tenant, science, _subject(db_session, tenant, "Chemistry")),
        "maths": _offer(db_session, tenant, science, _subject(db_session, tenant, "Maths")),
        "biology": _offer(
            db_session, tenant, science, _subject(db_session, tenant, "Biology"),
            mandatory=False,
        ),
        "computer": _offer(
            db_session, tenant, science, _subject(db_session, tenant, "ComputerSci"),
            mandatory=False,
        ),
    }


def _student(db_session, tenant, academic_year, name):
    from modules.people.models import Person

    person = Person(id=_new_id("p-"), tenant_id=tenant.id, full_name=name)
    db_session.add(person)
    db_session.flush()
    row = Student(
        id=_new_id("s-"), tenant_id=tenant.id, person_id=person.id,
        admission_number=f"ADM{uuid.uuid4().hex[:8]}",
        academic_year_id=academic_year.id,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _placed(db_session, tenant, academic_year, cls, name):
    from modules.academics.backbone.models import (
        ENROLLMENT_TYPE_PRIMARY,
        StudentClassEnrollment,
    )

    student = _student(db_session, tenant, academic_year, name)
    assign_student_to_class(student.id, cls.id, commit=False)
    db_session.flush()
    enrollment = StudentClassEnrollment.query.filter_by(
        student_id=student.id, tenant_id=tenant.id,
        is_current=True, enrollment_type=ENROLLMENT_TYPE_PRIMARY,
    ).first()
    return student, enrollment


def _names(rows):
    return {r.id for r in rows}


# ---------------------------------------------------------------------------
# The simple school pays nothing
# ---------------------------------------------------------------------------

def test_mandatory_subjects_need_no_election_rows(
    ctx, db_session, tenant, academic_year, science, curriculum
):
    _student_, enrollment = _placed(db_session, tenant, academic_year, science, "Asha")

    effective = effective_class_subjects(enrollment.id, tenant.id)

    assert curriculum["physics"].id in _names(effective)
    assert curriculum["chemistry"].id in _names(effective)
    assert curriculum["maths"].id in _names(effective)
    assert StudentSubjectElection.query.count() == 0, (
        "a student taking only mandatory subjects must not need rows"
    )


def test_an_unelected_elective_is_not_studied(
    ctx, db_session, tenant, academic_year, science, curriculum
):
    """This is what separates an elective from a mandatory subject."""
    _student_, enrollment = _placed(db_session, tenant, academic_year, science, "Asha")

    effective = _names(effective_class_subjects(enrollment.id, tenant.id))
    assert curriculum["biology"].id not in effective
    assert curriculum["computer"].id not in effective


# ---------------------------------------------------------------------------
# Different students, different subjects
# ---------------------------------------------------------------------------

def test_two_students_in_one_section_study_different_subjects(
    ctx, db_session, tenant, academic_year, science, curriculum
):
    _a, first = _placed(db_session, tenant, academic_year, science, "Student A")
    _b, second = _placed(db_session, tenant, academic_year, science, "Student B")

    record_election(
        tenant_id=tenant.id, enrollment_id=first.id,
        class_subject_id=curriculum["biology"].id, status=ELECTION_TAKING,
    )
    record_election(
        tenant_id=tenant.id, enrollment_id=second.id,
        class_subject_id=curriculum["computer"].id, status=ELECTION_TAKING,
    )
    db_session.flush()

    a_subjects = _names(effective_class_subjects(first.id, tenant.id))
    b_subjects = _names(effective_class_subjects(second.id, tenant.id))

    assert curriculum["biology"].id in a_subjects
    assert curriculum["computer"].id not in a_subjects
    assert curriculum["computer"].id in b_subjects
    assert curriculum["biology"].id not in b_subjects
    # Both still take everything mandatory.
    assert curriculum["physics"].id in a_subjects and curriculum["physics"].id in b_subjects


def test_a_mandatory_subject_can_be_dropped_or_excused(
    ctx, db_session, tenant, academic_year, science, curriculum
):
    _a, first = _placed(db_session, tenant, academic_year, science, "Dropper")
    _b, second = _placed(db_session, tenant, academic_year, science, "Excused")

    record_election(
        tenant_id=tenant.id, enrollment_id=first.id,
        class_subject_id=curriculum["physics"].id, status=ELECTION_DROPPED,
    )
    record_election(
        tenant_id=tenant.id, enrollment_id=second.id,
        class_subject_id=curriculum["chemistry"].id, status=ELECTION_EXEMPTED,
        note="Medical exemption from practicals",
    )
    db_session.flush()

    assert curriculum["physics"].id not in _names(
        effective_class_subjects(first.id, tenant.id)
    )
    assert curriculum["chemistry"].id not in _names(
        effective_class_subjects(second.id, tenant.id)
    )


def test_withdrawing_an_election_returns_the_class_default(
    ctx, db_session, tenant, academic_year, science, curriculum
):
    _a, enrollment = _placed(db_session, tenant, academic_year, science, "Asha")
    record_election(
        tenant_id=tenant.id, enrollment_id=enrollment.id,
        class_subject_id=curriculum["physics"].id, status=ELECTION_DROPPED,
    )
    db_session.flush()
    assert curriculum["physics"].id not in _names(
        effective_class_subjects(enrollment.id, tenant.id)
    )

    withdraw_election(enrollment.id, curriculum["physics"].id, tenant.id)
    db_session.flush()

    assert curriculum["physics"].id in _names(
        effective_class_subjects(enrollment.id, tenant.id)
    )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_recording_twice_updates_rather_than_duplicating(
    ctx, db_session, tenant, academic_year, science, curriculum
):
    _a, enrollment = _placed(db_session, tenant, academic_year, science, "Asha")

    first = record_election(
        tenant_id=tenant.id, enrollment_id=enrollment.id,
        class_subject_id=curriculum["biology"].id, status=ELECTION_TAKING,
    )
    second = record_election(
        tenant_id=tenant.id, enrollment_id=enrollment.id,
        class_subject_id=curriculum["biology"].id, status=ELECTION_DROPPED,
    )
    db_session.flush()

    assert first["created"] is True
    assert second["created"] is False
    assert first["election_id"] == second["election_id"]
    assert curriculum["biology"].id not in _names(
        effective_class_subjects(enrollment.id, tenant.id)
    )


def test_a_duplicate_row_is_refused_by_the_database(
    ctx, db_session, tenant, academic_year, science, curriculum
):
    _a, enrollment = _placed(db_session, tenant, academic_year, science, "Asha")
    record_election(
        tenant_id=tenant.id, enrollment_id=enrollment.id,
        class_subject_id=curriculum["biology"].id, status=ELECTION_TAKING,
    )
    db_session.flush()

    db_session.begin_nested()
    db_session.add(
        StudentSubjectElection(
            tenant_id=tenant.id,
            student_class_enrollment_id=enrollment.id,
            class_subject_id=curriculum["biology"].id,
            status=ELECTION_TAKING,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_a_subject_from_another_class_is_refused(
    ctx, db_session, tenant, academic_year, science, other_class, curriculum
):
    """Electing another section's subject is how a student ends up sitting a
    paper nobody scheduled for them."""
    _a, enrollment = _placed(db_session, tenant, academic_year, science, "Asha")
    theirs = _offer(
        db_session, tenant, other_class, _subject(db_session, tenant, "Accountancy"),
        mandatory=False,
    )

    result = record_election(
        tenant_id=tenant.id, enrollment_id=enrollment.id,
        class_subject_id=theirs.id, status=ELECTION_TAKING,
    )
    assert result["success"] is False
    assert "different class" in result["error"]


def test_an_inactive_subject_cannot_be_elected(
    ctx, db_session, tenant, academic_year, science, curriculum
):
    _a, enrollment = _placed(db_session, tenant, academic_year, science, "Asha")
    curriculum["biology"].status = "inactive"
    db_session.flush()

    result = record_election(
        tenant_id=tenant.id, enrollment_id=enrollment.id,
        class_subject_id=curriculum["biology"].id, status=ELECTION_TAKING,
    )
    assert result["success"] is False


def test_an_unknown_status_is_refused(
    ctx, db_session, tenant, academic_year, science, curriculum
):
    _a, enrollment = _placed(db_session, tenant, academic_year, science, "Asha")
    result = record_election(
        tenant_id=tenant.id, enrollment_id=enrollment.id,
        class_subject_id=curriculum["biology"].id, status="maybe",
    )
    assert result["success"] is False


# ---------------------------------------------------------------------------
# Tenancy — declared in the database, not trusted to a service
# ---------------------------------------------------------------------------

def test_an_election_cannot_cross_tenants(
    ctx, db_session, tenant, academic_year, science, curriculum
):
    from core.models import Tenant, TENANT_STATUS_ACTIVE, BILLING_CYCLE_YEARLY

    _a, enrollment = _placed(db_session, tenant, academic_year, science, "Asha")

    other = Tenant(
        id=_new_id("t-"), name="Other School",
        subdomain=f"test-{uuid.uuid4().hex}",
        status=TENANT_STATUS_ACTIVE, billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(other)
    db_session.flush()

    # Their tenant id against our enrollment: the composite FK must refuse it.
    db_session.begin_nested()
    db_session.add(
        StudentSubjectElection(
            tenant_id=other.id,
            student_class_enrollment_id=enrollment.id,
            class_subject_id=curriculum["biology"].id,
            status=ELECTION_TAKING,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_another_schools_enrollment_is_refused_by_the_service(
    ctx, db_session, tenant, academic_year, science, curriculum
):
    result = record_election(
        tenant_id=tenant.id, enrollment_id="does-not-exist",
        class_subject_id=curriculum["biology"].id, status=ELECTION_TAKING,
    )
    assert result["success"] is False
    assert "Enrollment not found" in result["error"]


# ---------------------------------------------------------------------------
# Enrollment context
# ---------------------------------------------------------------------------

def test_elections_belong_to_the_enrollment_not_the_student(
    ctx, db_session, tenant, academic_year, science, other_class, curriculum
):
    """A coaching batch has its own subjects; choosing there must not change
    what the student studies in their class."""
    student, placement = _placed(db_session, tenant, academic_year, science, "Riya")

    extra_subject = _offer(
        db_session, tenant, other_class, _subject(db_session, tenant, "JEEPhysics"),
        mandatory=False,
    )
    joined = enroll_additional(
        tenant_id=tenant.id, student_id=student.id, class_id=other_class.id
    )
    db_session.flush()

    record_election(
        tenant_id=tenant.id, enrollment_id=joined["enrollment_id"],
        class_subject_id=extra_subject.id, status=ELECTION_TAKING,
    )
    db_session.flush()

    in_class = _names(effective_class_subjects(placement.id, tenant.id))
    in_batch = _names(effective_class_subjects(joined["enrollment_id"], tenant.id))

    assert extra_subject.id not in in_class
    assert extra_subject.id in in_batch
    assert curriculum["physics"].id in in_class


def test_a_class_reports_whether_it_asks_students_to_choose(
    ctx, db_session, tenant, academic_year, science, other_class, curriculum
):
    """The admin screens use this to stay out of the way for ordinary classes."""
    assert class_has_electives(tenant.id, science.id) is True

    _offer(
        db_session, tenant, other_class, _subject(db_session, tenant, "OnlyMandatory")
    )
    assert class_has_electives(tenant.id, other_class.id) is False
