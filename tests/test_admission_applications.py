"""Applying to a school, and the school's answer.

The point of these is the applicant who never became a student. Before this,
admission was `create_student`, so the only way to record that a child had
applied was to admit them — and the family that withdrew, or the offer that
went elsewhere, left no trace at all.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g

from modules.students.models import (
    EVENT_ADMITTED,
    AdmissionApplication,
    Student,
)


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


@pytest.fixture
def klass(db_session, tenant, academic_year):
    from modules.classes.models import Class

    cls = Class(
        id=_new_id("c-"), tenant_id=tenant.id, name="Grade 1", section="A",
        academic_year_id=academic_year.id,
    )
    db_session.add(cls)
    db_session.flush()
    return cls


def _apply(academic_year, **overrides):
    from modules.students.admission_service import submit_application

    payload = {
        "applicant_name": "Ananya Desai",
        "guardian_name": "Nikhil Desai",
        "guardian_relationship": "father",
        "guardian_phone": "9800000123",
        "academic_year_id": academic_year.id,
        "date_of_birth": "2020-03-14",
        "gender": "female",
    }
    payload.update(overrides)
    return submit_application(payload)


def _students_named(name):
    from modules.people.models import Person

    return (
        Student.query.join(Person, Student.person_id == Person.id)
        .filter(Person.full_name == name)
        .count()
    )


# ---------------------------------------------------------------------------
# Applying
# ---------------------------------------------------------------------------

def test_an_application_creates_no_student(ctx, tenant, db_session, academic_year):
    """An applicant is not half a student."""
    result = _apply(academic_year)
    assert result["success"], result
    assert result["application"]["status"] == "submitted"
    assert result["application"]["student_id"] is None
    assert _students_named("Ananya Desai") == 0


def test_an_application_needs_someone_to_contact(ctx, tenant, db_session, academic_year):
    """Required now, not at approval — finding out then is too late."""
    result = _apply(academic_year, guardian_phone="")
    assert result["success"] is False
    assert "guardian_phone" in result["error"]


# ---------------------------------------------------------------------------
# The school says no
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "action,expected", [("reject", "rejected"), ("withdraw", "withdrawn")]
)
def test_a_declined_application_is_kept_and_admits_nobody(
    ctx, tenant, db_session, academic_year, action, expected
):
    """The canon's requirement: visible in history, no Student created."""
    from modules.students import admission_service

    submitted = _apply(academic_year)["application"]

    closed = getattr(admission_service, action)(
        submitted["id"], reason="Joined another school"
    )
    assert closed["success"], closed
    assert closed["application"]["status"] == expected
    assert closed["application"]["decision_reason"] == "Joined another school"
    assert closed["application"]["student_id"] is None

    # Still there to be found, and still nobody admitted.
    assert AdmissionApplication.query.filter_by(id=submitted["id"]).first() is not None
    assert _students_named("Ananya Desai") == 0


def test_a_decided_application_cannot_be_decided_again(
    ctx, tenant, db_session, academic_year
):
    from modules.students import admission_service

    submitted = _apply(academic_year)["application"]
    admission_service.reject(submitted["id"])

    again = admission_service.approve(submitted["id"])
    assert again["success"] is False
    assert "already" in again["error"].lower()


# ---------------------------------------------------------------------------
# The school says yes
# ---------------------------------------------------------------------------

def test_approval_admits_the_applicant(ctx, tenant, db_session, academic_year, klass):
    from modules.students import admission_service

    submitted = _apply(academic_year, desired_class_id=klass.id)["application"]

    approved = admission_service.approve(submitted["id"])
    assert approved["success"], approved

    student_id = approved["student"]["id"]
    assert approved["application"]["status"] == "approved"
    # The link back: this application became that student.
    assert approved["application"]["student_id"] == student_id
    assert approved["application"]["decided_on"] is not None

    student = Student.query.filter_by(id=student_id).first()
    assert student is not None
    # An ordinary admission: a person, an admission number, a place.
    assert student.person.full_name == "Ananya Desai"
    assert student.admission_number
    assert student.class_id == klass.id


def test_approval_is_recorded_on_the_student_timeline(
    ctx, tenant, db_session, academic_year, klass
):
    from modules.students import admission_service
    from modules.students.lifecycle_service import timeline_for

    submitted = _apply(academic_year, desired_class_id=klass.id)["application"]
    approved = admission_service.approve(submitted["id"])

    events = [event.event for event in timeline_for(approved["student"]["id"])]
    assert EVENT_ADMITTED in events


def test_the_same_applicant_is_not_admitted_twice(
    ctx, tenant, db_session, academic_year, klass
):
    from modules.students import admission_service

    submitted = _apply(academic_year, desired_class_id=klass.id)["application"]
    assert admission_service.approve(submitted["id"])["success"]

    again = admission_service.approve(submitted["id"])
    assert again["success"] is False
    assert _students_named("Ananya Desai") == 1


def test_review_precedes_a_decision(ctx, tenant, db_session, academic_year):
    from modules.students import admission_service

    submitted = _apply(academic_year)["application"]

    reviewing = admission_service.start_review(submitted["id"])
    assert reviewing["success"]
    assert reviewing["application"]["status"] == "under_review"
    # Still open, still nobody admitted.
    assert reviewing["application"]["is_open"] is True

    approved = admission_service.approve(submitted["id"])
    assert approved["success"], approved


# ---------------------------------------------------------------------------
# Finding them again
# ---------------------------------------------------------------------------

def test_the_list_keeps_the_ones_who_did_not_join(
    ctx, tenant, db_session, academic_year
):
    from modules.students import admission_service

    joined = _apply(academic_year, applicant_name="Riya Shah")["application"]
    did_not = _apply(academic_year, applicant_name="Kabir Rao")["application"]
    admission_service.reject(did_not["id"], reason="Places full")

    everyone = admission_service.list_applications()
    names = {item["applicant_name"] for item in everyone["items"]}
    assert {"Riya Shah", "Kabir Rao"} <= names

    only_rejected = admission_service.list_applications(status="rejected")
    assert [item["applicant_name"] for item in only_rejected["items"]] == ["Kabir Rao"]

    by_family = admission_service.list_applications(search="Kabir")
    assert by_family["total"] == 1
    assert joined["id"] != did_not["id"]
