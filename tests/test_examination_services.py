"""Creating, scheduling and cancelling examinations.

The fixture is the shape the product has to serve, not a convenient minimum:
one reporting year holding GSEB, CBSE and a 40-day vacation batch, with Grade
10 sections on two boards and Grade 11 split across three streams.

Everything below is proved through data. There is no branch anywhere on
"unit test" or "board" or "JEE" — those are rows in `exam_types`.
"""

from __future__ import annotations

import uuid
from datetime import date, time

import pytest
from flask import g
from sqlalchemy.exc import IntegrityError

from core.database import db
from modules.academics.academic_year.models import AcademicYear
from modules.academics.backbone.models import AcademicTerm
from modules.academics.calendar.models import ExamWindow
from modules.academics.cycles.models import (
    CYCLE_KIND_MAIN,
    CYCLE_KIND_SHORT_COURSE,
    AcademicCycle,
)
from modules.academics.cycles.services import default_cycle_for_year
from modules.classes.models import Class, ClassSubject
from modules.examinations import publication_service, services as exam_services
from modules.examinations.models import (
    EXAM_CANCELLED,
    EXAM_DRAFT,
    EXAM_MARKS_ENTRY,
    EXAM_PUBLISHED,
    EXAM_SCHEDULED,
    ExamMark,
    ExamPaper,
    ExamType,
    Examination,
    ExaminationLifecycleEvent,
    GradingScheme,
)
from modules.streams.models import Stream
from modules.subjects.models import Subject


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


@pytest.fixture
def year(db_session, tenant):
    row = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name=f"2026-27-{uuid.uuid4().hex[:5]}",
        start_date=date(2026, 4, 1), end_date=date(2027, 3, 31),
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def cycles(db_session, tenant, year):
    """GSEB Main, CBSE Main and a 40-day vacation batch under one 2026-27."""
    gseb = default_cycle_for_year(year.id, tenant.id)
    gseb.name = f"GSEB Main-{uuid.uuid4().hex[:5]}"
    gseb.start_date, gseb.end_date = date(2026, 6, 1), date(2027, 4, 30)

    cbse = AcademicCycle(
        id=_new_id("cy-"), tenant_id=tenant.id, academic_year_id=year.id,
        name=f"CBSE Main-{uuid.uuid4().hex[:5]}",
        start_date=date(2026, 4, 1), end_date=date(2027, 3, 31),
        cycle_kind=CYCLE_KIND_MAIN,
    )
    batch = AcademicCycle(
        id=_new_id("cy-"), tenant_id=tenant.id, academic_year_id=year.id,
        name=f"JEE Batch-{uuid.uuid4().hex[:5]}",
        start_date=date(2026, 5, 1), end_date=date(2026, 6, 9),
        cycle_kind=CYCLE_KIND_SHORT_COURSE,
    )
    db_session.add_all([cbse, batch])
    db_session.flush()
    return {"gseb": gseb, "cbse": cbse, "batch": batch}


@pytest.fixture
def exam_types(db_session, tenant):
    """Whatever a school calls its examinations — all of it data."""
    made = {}
    for label in ("Unit Test", "Semester", "Half Yearly", "Preliminary", "Board", "Mock"):
        row = ExamType(
            id=_new_id("et-"), tenant_id=tenant.id,
            name=f"{label}-{uuid.uuid4().hex[:5]}", sequence=10,
        )
        db_session.add(row)
        made[label] = row
    db_session.flush()
    return made


def _section(db_session, tenant, year, cycle, label, *, stream=None):
    row = Class(
        id=_new_id("cl-"), tenant_id=tenant.id, section=label,
        name=f"Section {label}", academic_year_id=year.id,
        academic_cycle_id=cycle.id, stream_id=stream.id if stream else None,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _offering(db_session, tenant, cls, label):
    subject = Subject(
        id=_new_id("sb-"), tenant_id=tenant.id,
        name=f"{label}-{uuid.uuid4().hex[:6]}",
        code=f"{label[:3].upper()}{uuid.uuid4().hex[:4]}",
    )
    db_session.add(subject)
    db_session.flush()
    offering = ClassSubject(
        id=_new_id("cs-"), tenant_id=tenant.id, class_id=cls.id,
        subject_id=subject.id, weekly_periods=5, status="active",
    )
    db_session.add(offering)
    db_session.flush()
    return offering


@pytest.fixture
def school(db_session, tenant, year, cycles):
    """Sections across both boards, three Grade 11 streams and the batch."""
    streams = {}
    for name in ("Science", "Commerce", "Arts"):
        row = Stream(
            id=_new_id("st-"), tenant_id=tenant.id,
            name=f"{name}-{uuid.uuid4().hex[:5]}", sequence=1,
        )
        db_session.add(row)
        streams[name] = row
    db_session.flush()

    made = {
        "gseb_10a": _section(db_session, tenant, year, cycles["gseb"], "10A"),
        "gseb_10b": _section(db_session, tenant, year, cycles["gseb"], "10B"),
        "cbse_10a": _section(db_session, tenant, year, cycles["cbse"], "10A"),
        "sci_11": _section(db_session, tenant, year, cycles["gseb"], "11S",
                           stream=streams["Science"]),
        "com_11": _section(db_session, tenant, year, cycles["gseb"], "11C",
                           stream=streams["Commerce"]),
        "arts_11": _section(db_session, tenant, year, cycles["gseb"], "11A",
                            stream=streams["Arts"]),
        "jee": _section(db_session, tenant, year, cycles["batch"], "JEE1"),
    }
    offerings = {
        "gseb_10a_maths": _offering(db_session, tenant, made["gseb_10a"], "Maths"),
        "gseb_10a_science": _offering(db_session, tenant, made["gseb_10a"], "Science"),
        "gseb_10b_maths": _offering(db_session, tenant, made["gseb_10b"], "Maths"),
        "cbse_10a_maths": _offering(db_session, tenant, made["cbse_10a"], "Maths"),
        "sci_physics": _offering(db_session, tenant, made["sci_11"], "Physics"),
        "com_accounts": _offering(db_session, tenant, made["com_11"], "Accountancy"),
        "jee_physics": _offering(db_session, tenant, made["jee"], "JEEPhysics"),
    }
    return {"classes": made, "offerings": offerings, "streams": streams}


# Publication moved out of `services.py` in EX-03B: it is no longer a bare
# transition, so reaching `published` goes through the real door. These
# examinations have no enrolled students, so their cohort is empty and there is
# nothing to refuse — which is exactly what makes them useful for testing the
# lifecycle itself. Authorization and cohort rules are covered in
# `test_examination_publication.py`.


@pytest.fixture(autouse=True)
def _may_publish(monkeypatch):
    """This file tests lifecycle and services, neither of which checks
    permissions; publication does, so it is granted here."""
    import modules.rbac.services as rbac

    monkeypatch.setattr(rbac, "has_permission", lambda user_id, name: True)


def _publisher(tenant):
    """A real account — the lifecycle event's actor is a foreign key, and
    `published_by_user_id` is another."""
    from modules.auth.models import User
    from modules.people.models import Person

    email = f"publisher-{tenant.id}@example.test"
    found = User.query.filter_by(tenant_id=tenant.id, email=email).first()
    if found is not None:
        return found

    person = Person(id=_new_id("pe-"), tenant_id=tenant.id, full_name="Publisher")
    db.session.add(person)
    db.session.flush()
    user = User(
        id=_new_id("us-"), tenant_id=tenant.id, email=email,
        password_hash="x", person_id=person.id,
    )
    db.session.add(user)
    db.session.flush()
    return user


def _publish(examination_id, tenant):
    return publication_service.publish_results(
        examination_id, tenant.id,
        actor_user_id=_publisher(tenant).id, commit=False,
    )


def _create(tenant, cycle, exam_type, name, **kwargs):
    return exam_services.create_examination(
        tenant_id=tenant.id, academic_cycle_id=cycle.id,
        exam_type_id=exam_type.id, name=name, commit=False, **kwargs,
    )


# ---------------------------------------------------------------------------
# Creation and the cycle it must name
# ---------------------------------------------------------------------------

def test_an_examination_must_name_a_cycle(ctx, db_session, tenant, cycles, exam_types):
    result = exam_services.create_examination(
        tenant_id=tenant.id, academic_cycle_id="", exam_type_id=exam_types["Board"].id,
        name="Board", commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "CYCLE_NOT_FOUND"


def test_another_schools_cycle_cannot_be_used(
    ctx, db_session, tenant, cycles, exam_types
):
    from core.models import Tenant, TENANT_STATUS_ACTIVE, BILLING_CYCLE_YEARLY

    other = Tenant(
        id=_new_id("t-"), name="Other", subdomain=f"o-{uuid.uuid4().hex}",
        status=TENANT_STATUS_ACTIVE, billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(other)
    db_session.flush()

    result = exam_services.create_examination(
        tenant_id=other.id, academic_cycle_id=cycles["gseb"].id,
        exam_type_id=exam_types["Board"].id, name="Theirs", commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "CYCLE_NOT_FOUND"


def test_the_same_name_is_free_in_another_cycle(
    ctx, db_session, tenant, cycles, exam_types
):
    """GSEB's "Half Yearly" and CBSE's are different examinations."""
    first = _create(tenant, cycles["gseb"], exam_types["Half Yearly"], "Half Yearly")
    second = _create(tenant, cycles["cbse"], exam_types["Half Yearly"], "Half Yearly")
    assert first["success"] and second["success"]

    again = _create(tenant, cycles["gseb"], exam_types["Half Yearly"], "Half Yearly")
    assert again["success"] is False
    assert again["code"] == "NAME_TAKEN"


def test_a_term_must_belong_to_the_same_cycle(
    ctx, db_session, tenant, year, cycles, exam_types
):
    term = AcademicTerm(
        id=_new_id("t-"), tenant_id=tenant.id, academic_year_id=year.id,
        academic_cycle_id=cycles["cbse"].id, name="Term 1", sequence=1,
        start_date=date(2026, 4, 1), end_date=date(2026, 9, 30),
    )
    db_session.add(term)
    db_session.flush()

    wrong = _create(
        tenant, cycles["gseb"], exam_types["Semester"], "Sem 1",
        academic_term_id=term.id,
    )
    assert wrong["success"] is False
    assert wrong["code"] == "TERM_WRONG_CYCLE"

    right = _create(
        tenant, cycles["cbse"], exam_types["Semester"], "Sem 1",
        academic_term_id=term.id,
    )
    assert right["success"] is True


def test_a_term_is_optional(ctx, db_session, tenant, cycles, exam_types):
    """A board examination is scheduled by the board, not by a school term."""
    result = _create(tenant, cycles["gseb"], exam_types["Board"], "Board Exam")
    assert result["success"] is True
    assert result["examination"].academic_term_id is None


def test_a_window_must_report_under_the_same_year(
    ctx, db_session, tenant, year, cycles, exam_types
):
    """`exam_windows` is year-scoped, so that is the strongest check available."""
    window = ExamWindow(
        id=_new_id("w-"), tenant_id=tenant.id, academic_year_id=year.id,
        name="Prelim window", exam_type="other",
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 20),
    )
    db_session.add(window)
    db_session.flush()

    ok = _create(
        tenant, cycles["gseb"], exam_types["Preliminary"], "Prelim",
        exam_window_id=window.id,
    )
    assert ok["success"] is True
    assert ok["examination"].exam_window_id == window.id
    # The window is a reference, not an identity — it still exists on its own.
    assert ExamWindow.query.filter_by(id=window.id).first() is not None


# ---------------------------------------------------------------------------
# Fan-out
# ---------------------------------------------------------------------------

def test_one_examination_fans_out_across_sections_and_subjects(
    ctx, db_session, tenant, cycles, exam_types, school
):
    result = _create(
        tenant, cycles["gseb"], exam_types["Half Yearly"], "Half Yearly",
        papers=[
            {"class_subject_id": school["offerings"]["gseb_10a_maths"].id,
             "max_marks": 100, "exam_date": date(2026, 9, 10)},
            {"class_subject_id": school["offerings"]["gseb_10a_science"].id,
             "max_marks": 100, "exam_date": date(2026, 9, 11)},
            {"class_subject_id": school["offerings"]["gseb_10b_maths"].id,
             "max_marks": 100, "exam_date": date(2026, 9, 10)},
        ],
    )
    assert result["success"] is True

    papers = exam_services.papers_for(result["examination"].id, tenant.id)
    assert len(papers) == 3
    sitting = set(exam_services.classes_sitting(result["examination"].id, tenant.id))
    assert sitting == {
        school["classes"]["gseb_10a"].id, school["classes"]["gseb_10b"].id
    }


def test_theory_and_practical_coexist_on_one_offering(
    ctx, db_session, tenant, cycles, exam_types, school
):
    physics = school["offerings"]["sci_physics"]
    result = _create(
        tenant, cycles["gseb"], exam_types["Semester"], "Sem 1 Science",
        papers=[
            {"class_subject_id": physics.id, "component_label": "Theory",
             "max_marks": 70, "exam_date": date(2026, 9, 10)},
            {"class_subject_id": physics.id, "component_label": "Practical",
             "max_marks": 30, "exam_date": date(2026, 9, 12)},
        ],
    )
    assert result["success"] is True

    papers = exam_services.papers_for(result["examination"].id, tenant.id)
    assert sorted(p.component_label for p in papers) == ["Practical", "Theory"]
    assert sum(float(p.max_marks) for p in papers) == 100


def test_a_papers_class_is_read_off_its_offering(
    ctx, db_session, tenant, cycles, exam_types, school
):
    """A caller never supplies class_id, so it cannot contradict the offering."""
    offering = school["offerings"]["gseb_10a_maths"]
    result = _create(
        tenant, cycles["gseb"], exam_types["Unit Test"], "UT1",
        papers=[{
            "class_subject_id": offering.id, "max_marks": 25,
            "exam_date": date(2026, 7, 1),
            # Deliberately wrong, and deliberately ignored.
            "class_id": school["classes"]["gseb_10b"].id,
        }],
    )
    assert result["success"] is True
    paper = exam_services.papers_for(result["examination"].id, tenant.id)[0]
    assert paper.class_id == offering.class_id


def test_the_database_refuses_a_paper_that_disagrees_with_its_offering(
    ctx, db_session, tenant, cycles, exam_types, school
):
    """Migration 116: the service makes this unreachable, the FK makes it unstorable."""
    created = _create(tenant, cycles["gseb"], exam_types["Unit Test"], "UT2")
    offering = school["offerings"]["gseb_10a_maths"]

    db_session.begin_nested()
    db_session.add(
        ExamPaper(
            id=_new_id("ep-"), tenant_id=tenant.id,
            examination_id=created["examination"].id,
            class_subject_id=offering.id,
            class_id=school["classes"]["gseb_10b"].id,  # not this offering's class
            max_marks=50,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_a_class_from_another_cycle_is_refused(
    ctx, db_session, tenant, cycles, exam_types, school
):
    """A CBSE section cannot sit a GSEB examination."""
    result = _create(
        tenant, cycles["gseb"], exam_types["Half Yearly"], "HY",
        papers=[{
            "class_subject_id": school["offerings"]["cbse_10a_maths"].id,
            "max_marks": 100, "exam_date": date(2026, 9, 10),
        }],
    )
    assert result["success"] is False
    assert result["code"] == "CLASS_WRONG_CYCLE"


def test_a_duplicate_paper_is_refused(
    ctx, db_session, tenant, cycles, exam_types, school
):
    offering = school["offerings"]["gseb_10a_maths"]
    spec = {"class_subject_id": offering.id, "max_marks": 100,
            "exam_date": date(2026, 9, 10)}

    result = _create(
        tenant, cycles["gseb"], exam_types["Unit Test"], "UT3",
        papers=[spec, dict(spec)],
    )
    assert result["success"] is False
    assert result["code"] == "PAPER_DUPLICATE"


def test_a_duplicate_is_refused_across_two_calls(
    ctx, db_session, tenant, cycles, exam_types, school
):
    offering = school["offerings"]["gseb_10a_maths"]
    created = _create(
        tenant, cycles["gseb"], exam_types["Unit Test"], "UT4",
        papers=[{"class_subject_id": offering.id, "max_marks": 100,
                 "exam_date": date(2026, 9, 10)}],
    )
    again = exam_services.add_papers(
        created["examination"].id, tenant.id,
        [{"class_subject_id": offering.id, "max_marks": 100,
          "exam_date": date(2026, 9, 11)}],
        commit=False,
    )
    assert again["success"] is False
    assert again["code"] == "PAPER_DUPLICATE"


def test_a_paper_cannot_sit_outside_the_cycle(
    ctx, db_session, tenant, cycles, exam_types, school
):
    """The cycle is the operating boundary (ADR-017), never the year's dates."""
    result = _create(
        tenant, cycles["batch"], exam_types["Mock"], "Mock 1",
        papers=[{
            "class_subject_id": school["offerings"]["jee_physics"].id,
            "max_marks": 300,
            # The batch runs 1 May - 9 June; this is inside the YEAR but not it.
            "exam_date": date(2026, 11, 1),
        }],
    )
    assert result["success"] is False
    assert result["code"] == "DATE_OUTSIDE_CYCLE"


def test_a_board_paper_outside_the_cycle_is_refused_and_has_a_way_through(
    ctx, db_session, tenant, year, cycles, exam_types, school
):
    """The rule holds for board examinations too, and that is deliberate.

    Board dates are set by the board, not the school, so the obvious worry is
    that a sitting lands after the school's own cycle has closed and the
    product refuses work the school cannot control.

    It is still the right rule. The two precedents in the codebase disagree on
    purpose: a *cycle* may sit outside its year, because a year is a reporting
    container; a *term* may not sit outside its cycle, because a cycle is the
    operating boundary. A paper is an operating event, so it follows the term.
    Relaxing it would mean a paper could name a class from a period that was
    not running when it was sat, and nothing downstream could tell.

    What the school does instead is state the operating period it is actually
    working in — the same move the 40-day batch already makes. The refusal
    below and the acceptance under it are the same rule.
    """
    # GSEB Main runs 1 June 2026 - 30 April 2027.
    refused = _create(
        tenant, cycles["gseb"], exam_types["Board"], "Board 2027",
        papers=[{
            "class_subject_id": school["offerings"]["gseb_10a_maths"].id,
            "max_marks": 100,
            "exam_date": date(2027, 5, 20),   # after the cycle has closed
        }],
    )
    assert refused["success"] is False
    assert refused["code"] == "DATE_OUTSIDE_CYCLE"

    # The way through: a cycle that covers the sitting. No code changes, no
    # exception for boards, no flag — the school describes its own calendar.
    supplementary = AcademicCycle(
        id=_new_id("cy-"), tenant_id=tenant.id, academic_year_id=year.id,
        name=f"Board Supplementary-{uuid.uuid4().hex[:5]}",
        start_date=date(2027, 5, 1), end_date=date(2027, 6, 30),
        cycle_kind=CYCLE_KIND_SHORT_COURSE,
    )
    db_session.add(supplementary)
    db_session.flush()
    section = _section(db_session, tenant, year, supplementary, "10A-Supp")
    offering = _offering(db_session, tenant, section, "Maths")

    allowed = _create(
        tenant, supplementary, exam_types["Board"], "Board Supplementary 2027",
        papers=[{
            "class_subject_id": offering.id, "max_marks": 100,
            "exam_date": date(2027, 5, 20),
        }],
    )
    assert allowed["success"] is True, allowed


def test_creating_papers_is_atomic(
    ctx, db_session, tenant, cycles, exam_types, school
):
    """Paper three fails; papers one and two must not survive — nor the exam."""
    before = Examination.query.filter_by(tenant_id=tenant.id).count()

    result = _create(
        tenant, cycles["gseb"], exam_types["Half Yearly"], "Atomic",
        papers=[
            {"class_subject_id": school["offerings"]["gseb_10a_maths"].id,
             "max_marks": 100, "exam_date": date(2026, 9, 10)},
            {"class_subject_id": school["offerings"]["gseb_10a_science"].id,
             "max_marks": 100, "exam_date": date(2026, 9, 11)},
            {"class_subject_id": school["offerings"]["cbse_10a_maths"].id,
             "max_marks": 100, "exam_date": date(2026, 9, 12)},
        ],
    )
    assert result["success"] is False
    assert Examination.query.filter_by(tenant_id=tenant.id).count() == before
    assert Examination.query.filter_by(
        tenant_id=tenant.id, name="Atomic"
    ).first() is None


def test_an_inactive_offering_cannot_be_examined(
    ctx, db_session, tenant, cycles, exam_types, school
):
    offering = school["offerings"]["gseb_10a_maths"]
    offering.status = "inactive"
    db_session.flush()

    result = _create(
        tenant, cycles["gseb"], exam_types["Unit Test"], "UT5",
        papers=[{"class_subject_id": offering.id, "max_marks": 100}],
    )
    assert result["success"] is False
    assert result["code"] == "OFFERING_INACTIVE"


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

@pytest.fixture
def scheduled_ready(ctx, db_session, tenant, cycles, exam_types, school):
    created = _create(
        tenant, cycles["gseb"], exam_types["Half Yearly"], "Lifecycle",
        papers=[{
            "class_subject_id": school["offerings"]["gseb_10a_maths"].id,
            "max_marks": 100, "exam_date": date(2026, 9, 10),
        }],
    )
    return created["examination"]


def test_the_happy_path_runs_draft_to_published(
    ctx, db_session, tenant, scheduled_ready
):
    exam = scheduled_ready
    assert exam.status == EXAM_DRAFT

    assert exam_services.schedule_examination(exam.id, tenant.id, commit=False)["success"]
    assert exam.status == EXAM_SCHEDULED
    assert exam_services.open_marks_entry(exam.id, tenant.id, commit=False)["success"]
    assert exam.status == EXAM_MARKS_ENTRY
    assert _publish(exam.id, tenant)["success"]
    assert exam.status == EXAM_PUBLISHED


def test_a_skipped_transition_is_refused(ctx, db_session, tenant, scheduled_ready):
    """draft cannot jump to published."""
    result = _publish(scheduled_ready.id, tenant)
    assert result["success"] is False
    assert result["code"] == "INVALID_TRANSITION"
    assert scheduled_ready.status == EXAM_DRAFT


def test_an_examination_with_no_papers_cannot_be_scheduled(
    ctx, db_session, tenant, cycles, exam_types
):
    created = _create(tenant, cycles["gseb"], exam_types["Unit Test"], "Empty")
    result = exam_services.schedule_examination(
        created["examination"].id, tenant.id, commit=False
    )
    assert result["success"] is False
    assert result["code"] == "NO_PAPERS"


def test_an_undated_paper_blocks_scheduling(
    ctx, db_session, tenant, cycles, exam_types, school
):
    created = _create(
        tenant, cycles["gseb"], exam_types["Unit Test"], "Undated",
        papers=[{"class_subject_id": school["offerings"]["gseb_10a_maths"].id,
                 "max_marks": 100}],
    )
    result = exam_services.schedule_examination(
        created["examination"].id, tenant.id, commit=False
    )
    assert result["success"] is False
    assert result["code"] == "PAPER_UNDATED"


def test_cancellation_is_not_deletion(ctx, db_session, tenant, scheduled_ready):
    exam = scheduled_ready
    paper_count = len(exam_services.papers_for(exam.id, tenant.id))

    result = exam_services.cancel_examination(
        exam.id, tenant.id, reason="Board rescheduled the date", commit=False
    )
    assert result["success"] is True
    assert exam.status == EXAM_CANCELLED
    # Still there, still findable, papers intact.
    assert exam.deleted_at is None
    assert exam_services.get_examination(exam.id, tenant.id) is not None
    assert len(exam_services.papers_for(exam.id, tenant.id)) == paper_count


def test_a_cancellation_needs_a_reason(ctx, db_session, tenant, scheduled_ready):
    result = exam_services.cancel_examination(
        scheduled_ready.id, tenant.id, reason="  ", commit=False
    )
    assert result["success"] is False
    assert result["code"] == "REASON_REQUIRED"


def test_published_results_cannot_be_cancelled(
    ctx, db_session, tenant, scheduled_ready
):
    exam = scheduled_ready
    exam_services.schedule_examination(exam.id, tenant.id, commit=False)
    exam_services.open_marks_entry(exam.id, tenant.id, commit=False)
    _publish(exam.id, tenant)

    result = exam_services.cancel_examination(
        exam.id, tenant.id, reason="changed our minds", commit=False
    )
    assert result["success"] is False
    assert result["code"] == "ALREADY_PUBLISHED"


def test_lifecycle_events_are_append_only(ctx, db_session, tenant, scheduled_ready):
    exam = scheduled_ready
    exam_services.schedule_examination(exam.id, tenant.id, commit=False)
    exam_services.open_marks_entry(exam.id, tenant.id, commit=False)
    db_session.flush()

    timeline = exam_services.timeline_for(exam.id, tenant.id)
    assert [e.event_name for e in timeline] == [
        "ExaminationScheduled", "MarksEntryOpened"
    ]
    # A later transition adds; it never rewrites what came before.
    _publish(exam.id, tenant)
    db_session.flush()
    after = exam_services.timeline_for(exam.id, tenant.id)
    assert len(after) == 3
    assert after[0].event_name == "ExaminationScheduled"


def test_papers_cannot_be_added_once_marks_entry_opened(
    ctx, db_session, tenant, scheduled_ready, school
):
    """Marks were entered against the shape the examination had."""
    exam = scheduled_ready
    exam_services.schedule_examination(exam.id, tenant.id, commit=False)
    exam_services.open_marks_entry(exam.id, tenant.id, commit=False)

    result = exam_services.add_papers(
        exam.id, tenant.id,
        [{"class_subject_id": school["offerings"]["gseb_10a_science"].id,
          "max_marks": 100, "exam_date": date(2026, 9, 15)}],
        commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "WRONG_STATUS"


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

def test_an_examination_cannot_change_cycle(ctx, db_session, tenant, cycles, exam_types):
    created = _create(tenant, cycles["gseb"], exam_types["Unit Test"], "Movable")
    result = exam_services.update_examination(
        created["examination"].id, tenant.id,
        {"academic_cycle_id": cycles["cbse"].id}, commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "CYCLE_IMMUTABLE"


def test_a_published_examination_cannot_be_edited(
    ctx, db_session, tenant, scheduled_ready
):
    exam = scheduled_ready
    exam_services.schedule_examination(exam.id, tenant.id, commit=False)
    exam_services.open_marks_entry(exam.id, tenant.id, commit=False)
    _publish(exam.id, tenant)

    result = exam_services.update_examination(
        exam.id, tenant.id, {"name": "Renamed"}, commit=False
    )
    assert result["success"] is False
    assert result["code"] == "WRONG_STATUS"


# ---------------------------------------------------------------------------
# The patterns, proved through data alone
# ---------------------------------------------------------------------------

def test_every_school_pattern_is_representable_without_a_code_branch(
    ctx, db_session, tenant, cycles, exam_types, school
):
    """GSEB semesters, CBSE half-yearly, Grade 10 prelim+board, Grade 11
    theory+practical and a JEE weekly mock — one service, no branches."""
    made = []

    # GSEB: Semester 1, Semester 2, Final
    for label in ("Semester 1", "Semester 2", "Final"):
        made.append(_create(tenant, cycles["gseb"], exam_types["Semester"], label))

    # CBSE: Half Yearly + Final
    for label in ("Half Yearly", "Final"):
        made.append(_create(tenant, cycles["cbse"], exam_types["Half Yearly"], label))

    # Grade 10 GSEB: unit tests, preliminary, board
    for label, kind in (
        ("Unit Test 1", "Unit Test"), ("Unit Test 2", "Unit Test"),
        ("Preliminary", "Preliminary"), ("Board", "Board"),
    ):
        made.append(_create(tenant, cycles["gseb"], exam_types[kind], label))

    # Grade 11 Science: theory + practical in one examination
    made.append(_create(
        tenant, cycles["gseb"], exam_types["Semester"], "Sem 1 Practicals",
        papers=[
            {"class_subject_id": school["offerings"]["sci_physics"].id,
             "component_label": "Theory", "max_marks": 70,
             "exam_date": date(2026, 10, 1)},
            {"class_subject_id": school["offerings"]["sci_physics"].id,
             "component_label": "Practical", "max_marks": 30,
             "exam_date": date(2026, 10, 3)},
        ],
    ))

    # The 40-day batch: a weekly mock inside its own cycle
    made.append(_create(
        tenant, cycles["batch"], exam_types["Mock"], "Weekly Mock 1",
        papers=[{"class_subject_id": school["offerings"]["jee_physics"].id,
                 "max_marks": 300, "exam_date": date(2026, 5, 15)}],
    ))

    assert all(r["success"] for r in made), [r for r in made if not r["success"]]
    assert len(made) == 11

    # Three cycles, one reporting year, and every examination in its own.
    by_cycle = {}
    for r in made:
        by_cycle.setdefault(r["examination"].academic_cycle_id, 0)
        by_cycle[r["examination"].academic_cycle_id] += 1
    assert len(by_cycle) == 3


def test_a_new_exam_type_needs_no_code_change(
    ctx, db_session, tenant, cycles
):
    """A school invents "Olympiad Screening" and it simply works."""
    invented = ExamType(
        id=_new_id("et-"), tenant_id=tenant.id,
        name=f"Olympiad Screening-{uuid.uuid4().hex[:5]}", sequence=99,
    )
    db_session.add(invented)
    db_session.flush()

    result = _create(tenant, cycles["gseb"], invented, "Olympiad Round 1")
    assert result["success"] is True


# ---------------------------------------------------------------------------
# What EX-02 will need
# ---------------------------------------------------------------------------

def test_a_paper_carries_what_adr_014_needs_to_name_a_marker(
    ctx, db_session, tenant, cycles, exam_types, school
):
    """EX-02 must resolve marks authority through the Teaching Assignment
    service, which asks for (class_id, subject_id, on=<date>). A paper carries
    all three, so no examination-specific authority model is needed."""
    from modules.academics.teaching_assignment import subject_teacher_of

    created = _create(
        tenant, cycles["gseb"], exam_types["Unit Test"], "Authority",
        papers=[{"class_subject_id": school["offerings"]["gseb_10a_maths"].id,
                 "max_marks": 25, "exam_date": date(2026, 7, 1)}],
    )
    paper = exam_services.papers_for(created["examination"].id, tenant.id)[0]
    offering = ClassSubject.query.filter_by(id=paper.class_subject_id).first()

    # No teacher is assigned in this fixture; the point is that the call is
    # answerable from the paper alone, dated to the sitting.
    assert paper.class_id == offering.class_id
    assert paper.exam_date is not None
    assert subject_teacher_of(
        paper.class_id, offering.subject_id, on=paper.exam_date
    ) is None


# ---------------------------------------------------------------------------
# What an examination means stops moving once marks exist
# ---------------------------------------------------------------------------
#
# The boundary is deliberately the existence of a mark, not the status. An
# examination sits in `marks_entry` for days before the first mark arrives —
# correcting a mis-picked scheme then is ordinary admin — and one mark on one
# paper of forty is already enough to make the change unsafe.


def _scheme(db_session, tenant, label):
    row = GradingScheme(
        id=_new_id("gs-"), tenant_id=tenant.id,
        name=f"{label}-{uuid.uuid4().hex[:5]}",
    )
    db_session.add(row)
    db_session.flush()
    return row


def _mark_one(db_session, tenant, paper):
    """One mark, written straight to the table.

    The rule under test keys on a mark *existing*, so the marks service's
    authority and eligibility machinery is beside the point here — but the
    student must be real: `fk_exam_marks_student` is a composite (tenant, id)
    FK and refuses an invented id, which is the point of having it.
    """
    from modules.people.models import Person
    from modules.students.models import Student

    person = Person(
        id=_new_id("pe-"), tenant_id=tenant.id, full_name="Marked Student"
    )
    db_session.add(person)
    db_session.flush()
    student = Student(
        id=_new_id("stu-"), tenant_id=tenant.id, person_id=person.id,
        admission_number=f"A{uuid.uuid4().hex[:8]}",
    )
    db_session.add(student)
    db_session.flush()

    row = ExamMark(
        id=_new_id("em-"), tenant_id=tenant.id, exam_paper_id=paper.id,
        student_id=student.id, status="present", marks_obtained=40,
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def markable(ctx, db_session, tenant, cycles, exam_types, school):
    """An examination in marks entry, with two papers and no marks yet."""
    created = _create(
        tenant, cycles["gseb"], exam_types["Unit Test"], f"UT-{uuid.uuid4().hex[:5]}",
        papers=[
            {"class_subject_id": school["offerings"]["gseb_10a_maths"].id,
             "max_marks": 50, "exam_date": date(2026, 7, 6)},
            {"class_subject_id": school["offerings"]["gseb_10a_science"].id,
             "max_marks": 50, "exam_date": date(2026, 7, 8)},
        ],
    )
    assert created["success"] is True, created
    examination = created["examination"]
    assert exam_services.schedule_examination(
        examination.id, tenant.id, commit=False
    )["success"] is True
    assert exam_services.open_marks_entry(
        examination.id, tenant.id, commit=False
    )["success"] is True
    return examination


def test_the_type_and_scheme_may_be_corrected_before_any_mark(
    ctx, db_session, tenant, exam_types, markable
):
    scheme = _scheme(db_session, tenant, "Percentage")
    result = exam_services.update_examination(
        markable.id, tenant.id,
        {"exam_type_id": exam_types["Half Yearly"].id,
         "grading_scheme_id": scheme.id},
        commit=False,
    )
    assert result["success"] is True, result
    assert markable.exam_type_id == exam_types["Half Yearly"].id
    assert markable.grading_scheme_id == scheme.id


def test_the_exam_type_freezes_at_the_first_mark(
    ctx, db_session, tenant, exam_types, markable
):
    paper = exam_services.papers_for(markable.id, tenant.id)[0]
    _mark_one(db_session, tenant, paper)

    result = exam_services.update_examination(
        markable.id, tenant.id, {"exam_type_id": exam_types["Board"].id},
        commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "EXAM_TYPE_IMMUTABLE"
    assert markable.exam_type_id == exam_types["Unit Test"].id


def test_the_grading_scheme_freezes_at_the_first_mark(
    ctx, db_session, tenant, markable
):
    """A 62 that passes under one scheme fails under the next, and nothing
    would record that the marks were re-read."""
    before = _scheme(db_session, tenant, "Percentage")
    assert exam_services.update_examination(
        markable.id, tenant.id, {"grading_scheme_id": before.id}, commit=False
    )["success"] is True

    paper = exam_services.papers_for(markable.id, tenant.id)[0]
    _mark_one(db_session, tenant, paper)

    after = _scheme(db_session, tenant, "Letter")
    result = exam_services.update_examination(
        markable.id, tenant.id, {"grading_scheme_id": after.id}, commit=False
    )
    assert result["success"] is False
    assert result["code"] == "GRADING_SCHEME_IMMUTABLE"
    assert markable.grading_scheme_id == before.id


def test_one_marked_paper_freezes_the_whole_examination(
    ctx, db_session, tenant, exam_types, markable
):
    """Two papers, one mark. The examination's meaning is shared by both."""
    papers = exam_services.papers_for(markable.id, tenant.id)
    assert len(papers) == 2
    _mark_one(db_session, tenant, papers[1])

    result = exam_services.update_examination(
        markable.id, tenant.id, {"exam_type_id": exam_types["Board"].id},
        commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "EXAM_TYPE_IMMUTABLE"


def test_resending_the_same_type_is_not_a_change(
    ctx, db_session, tenant, exam_types, markable
):
    """A caller that PATCHes the whole object must not be refused for a field
    it did not touch."""
    paper = exam_services.papers_for(markable.id, tenant.id)[0]
    _mark_one(db_session, tenant, paper)

    result = exam_services.update_examination(
        markable.id, tenant.id,
        {"exam_type_id": exam_types["Unit Test"].id, "description": "revised"},
        commit=False,
    )
    assert result["success"] is True, result
    assert markable.description == "revised"


def test_other_details_stay_editable_after_marks_exist(
    ctx, db_session, tenant, markable
):
    """Only the two fields that change what marks *mean* are frozen. Renaming
    an examination does not re-read anybody's paper."""
    paper = exam_services.papers_for(markable.id, tenant.id)[0]
    _mark_one(db_session, tenant, paper)

    result = exam_services.update_examination(
        markable.id, tenant.id, {"name": f"Renamed-{uuid.uuid4().hex[:5]}"},
        commit=False,
    )
    assert result["success"] is True, result


def test_publication_does_not_reopen_the_configuration(
    ctx, db_session, tenant, exam_types, markable
):
    paper = exam_services.papers_for(markable.id, tenant.id)[0]
    _mark_one(db_session, tenant, paper)
    assert _publish(markable.id, tenant)["success"] is True

    result = exam_services.update_examination(
        markable.id, tenant.id, {"exam_type_id": exam_types["Board"].id},
        commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "WRONG_STATUS"


def test_cancellation_does_not_reopen_the_configuration(
    ctx, db_session, tenant, exam_types, markable
):
    paper = exam_services.papers_for(markable.id, tenant.id)[0]
    _mark_one(db_session, tenant, paper)
    assert exam_services.cancel_examination(
        markable.id, tenant.id, reason="Weather", commit=False
    )["success"] is True

    result = exam_services.update_examination(
        markable.id, tenant.id, {"exam_type_id": exam_types["Board"].id},
        commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "WRONG_STATUS"


def test_another_schools_exam_type_is_still_refused_before_any_mark(
    ctx, db_session, tenant, markable
):
    """The freeze must not have displaced the tenant check that was already
    there — an unmarked examination still cannot borrow a foreign type."""
    from core.models import BILLING_CYCLE_YEARLY, TENANT_STATUS_ACTIVE, Tenant

    other = Tenant(
        id=_new_id("t-"), name="Other", subdomain=f"o-{uuid.uuid4().hex}",
        status=TENANT_STATUS_ACTIVE, billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(other)
    db_session.flush()
    foreign = ExamType(
        id=_new_id("et-"), tenant_id=other.id, name="Theirs", sequence=1,
    )
    db_session.add(foreign)
    db_session.flush()

    result = exam_services.update_examination(
        markable.id, tenant.id, {"exam_type_id": foreign.id}, commit=False
    )
    assert result["success"] is False
    assert result["code"] == "EXAM_TYPE_NOT_FOUND"
