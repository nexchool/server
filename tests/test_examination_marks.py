"""Recording what students scored.

The fixture is a real school, not a minimum: one year holding a GSEB main cycle
and a 40-day JEE batch, a Grade 10 section with two subjects taught by two
different teachers, and a child who is enrolled in both the section and the
batch. Every rule below is proved against that shape, because the rules that
break in production are the ones that only ever met one class and one teacher.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from flask import g

from core.database import db
from modules.academics.academic_year.models import AcademicYear
from modules.academics.backbone.models import (
    ClassSubjectTeacher,
    StudentClassEnrollment,
)
from modules.academics.cycles.models import (
    CYCLE_KIND_MAIN,
    CYCLE_KIND_SHORT_COURSE,
    AcademicCycle,
)
from modules.academics.cycles.services import default_cycle_for_year
from modules.auth.models import User
from modules.classes.models import Class, ClassSubject
from modules.examinations import marks_service, services as exam_services
from modules.examinations.models import (
    MARK_ABSENT,
    MARK_EXEMPTED,
    MARK_MALPRACTICE,
    MARK_PRESENT,
    ExamMark,
    ExamType,
)
from modules.people.employment import Staff
from modules.people.models import Person
from modules.students.models import Student
from modules.subjects.models import Subject
from modules.teachers.models import Teacher


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
    main = default_cycle_for_year(year.id, tenant.id)
    main.name = f"Main-{uuid.uuid4().hex[:5]}"
    main.start_date, main.end_date = date(2026, 4, 1), date(2027, 3, 31)
    batch = AcademicCycle(
        id=_new_id("cy-"), tenant_id=tenant.id, academic_year_id=year.id,
        name=f"JEE Batch-{uuid.uuid4().hex[:5]}",
        start_date=date(2026, 5, 1), end_date=date(2026, 6, 9),
        cycle_kind=CYCLE_KIND_SHORT_COURSE,
    )
    db_session.add(batch)
    db_session.flush()
    return {"main": main, "batch": batch}


def _person(db_session, tenant, name):
    row = Person(id=_new_id("pe-"), tenant_id=tenant.id, full_name=name)
    db_session.add(row)
    db_session.flush()
    return row


def _user(db_session, tenant, person):
    row = User(
        id=_new_id("us-"), tenant_id=tenant.id,
        email=f"{uuid.uuid4().hex[:10]}@example.test",
        password_hash="x", person_id=person.id,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _teacher(db_session, tenant, name):
    """A person the school employs, who teaches (ADR-001 → ADR-005)."""
    person = _person(db_session, tenant, name)
    user = _user(db_session, tenant, person)
    staff = Staff(id=_new_id("sf-"), tenant_id=tenant.id, person_id=person.id)
    db_session.add(staff)
    db_session.flush()
    teacher = Teacher(id=_new_id("te-"), tenant_id=tenant.id, staff_id=staff.id)
    db_session.add(teacher)
    db_session.flush()
    return {"teacher": teacher, "user": user, "person": person}


def _student(db_session, tenant, year, name):
    person = _person(db_session, tenant, name)
    row = Student(
        id=_new_id("st-"), tenant_id=tenant.id, person_id=person.id,
        admission_number=f"A{uuid.uuid4().hex[:8]}", academic_year_id=year.id,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _enroll(db_session, tenant, student, cls, year, *, kind="primary", roll=None):
    row = StudentClassEnrollment(
        id=_new_id("en-"), tenant_id=tenant.id, student_id=student.id,
        class_id=cls.id, academic_year_id=year.id, enrollment_type=kind,
        is_current=True, roll_number=roll,
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
    row = ClassSubject(
        id=_new_id("cs-"), tenant_id=tenant.id, class_id=cls.id,
        subject_id=subject.id, weekly_periods=5, status="active",
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def school(db_session, tenant, year, cycles):
    """Grade 10-A on the main cycle, a JEE batch, and one child in both."""
    def section(label, cycle):
        row = Class(
            id=_new_id("cl-"), tenant_id=tenant.id, section=label,
            name=f"Section {label}", academic_year_id=year.id,
            academic_cycle_id=cycle.id,
        )
        db_session.add(row)
        db_session.flush()
        return row

    ten_a = section("10A", cycles["main"])
    jee = section("JEE1", cycles["batch"])

    maths = _offering(db_session, tenant, ten_a, "Maths")
    science = _offering(db_session, tenant, ten_a, "Science")
    jee_physics = _offering(db_session, tenant, jee, "JEEPhysics")

    maths_teacher = _teacher(db_session, tenant, "Asha Mehta")
    science_teacher = _teacher(db_session, tenant, "Rakesh Shah")
    head = _teacher(db_session, tenant, "Principal Iyer")

    for offering, who in ((maths, maths_teacher), (science, science_teacher),
                          (jee_physics, science_teacher)):
        db_session.add(ClassSubjectTeacher(
            id=_new_id("ct-"), tenant_id=tenant.id,
            class_subject_id=offering.id, teacher_id=who["teacher"].id,
            role="primary", is_active=True,
        ))
    db_session.flush()

    riya = _student(db_session, tenant, year, "Riya Patel")
    dev = _student(db_session, tenant, year, "Dev Sharma")
    meera = _student(db_session, tenant, year, "Meera Joshi")
    outsider = _student(db_session, tenant, year, "Kabir Rao")

    _enroll(db_session, tenant, riya, ten_a, year, roll=1)
    _enroll(db_session, tenant, dev, ten_a, year, roll=2)
    _enroll(db_session, tenant, meera, ten_a, year, roll=3)
    # The batch child: a *second*, additional enrollment. She sits both.
    _enroll(db_session, tenant, meera, jee, year, kind="additional")

    return {
        "ten_a": ten_a, "jee": jee,
        "maths": maths, "science": science, "jee_physics": jee_physics,
        "maths_teacher": maths_teacher, "science_teacher": science_teacher,
        "head": head,
        "riya": riya, "dev": dev, "meera": meera, "outsider": outsider,
    }


@pytest.fixture
def exam_type(db_session, tenant):
    row = ExamType(
        id=_new_id("et-"), tenant_id=tenant.id,
        name=f"Unit Test-{uuid.uuid4().hex[:5]}", sequence=10,
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def marking(ctx, db_session, tenant, cycles, exam_type, school):
    """An examination open for marking, with a Maths paper out of 100."""
    created = exam_services.create_examination(
        tenant_id=tenant.id, academic_cycle_id=cycles["main"].id,
        exam_type_id=exam_type.id, name=f"UT1-{uuid.uuid4().hex[:5]}",
        papers=[{
            "class_subject_id": school["maths"].id,
            "max_marks": 100, "pass_marks": 35,
            "exam_date": date(2026, 7, 10),
        }],
        commit=False,
    )
    assert created["success"] is True, created
    examination = created["examination"]

    assert exam_services.schedule_examination(
        examination.id, tenant.id, commit=False
    )["success"] is True
    assert exam_services.open_marks_entry(
        examination.id, tenant.id, commit=False
    )["success"] is True

    paper = exam_services.papers_for(examination.id, tenant.id)[0]
    return {"examination": examination, "paper": paper}


@pytest.fixture
def anyone_may(monkeypatch):
    """Grant every assessment permission, so a test isolates *authority*.

    Permission and authority are separate gates (ADR-014); a test that wants to
    prove one must not be silently failing on the other.
    """
    import modules.rbac.services as rbac

    monkeypatch.setattr(rbac, "has_permission", lambda user_id, name: True)


@pytest.fixture
def only_teachers_may(monkeypatch, school):
    """The realistic grant: teachers may enter and correct, the head manages."""
    import modules.rbac.services as rbac

    head_user = school["head"]["user"].id

    def granted(user_id, name):
        if name == marks_service.PERM_MANAGE:
            return user_id == head_user
        return name in (marks_service.PERM_ENTER, marks_service.PERM_UPDATE)

    monkeypatch.setattr(rbac, "has_permission", granted)


def _teacher_of_maths(school):
    return school["maths_teacher"]["user"].id


# ---------------------------------------------------------------------------
# Eligibility — who may be marked
# ---------------------------------------------------------------------------

def test_everyone_enrolled_in_the_class_may_be_marked(
    ctx, tenant, school, marking, anyone_may
):
    eligible = set(marks_service.eligible_student_ids(marking["paper"]))
    assert eligible == {
        school["riya"].id, school["dev"].id, school["meera"].id
    }


def test_a_student_from_another_class_cannot_be_marked(
    ctx, tenant, school, marking, anyone_may
):
    result = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=school["outsider"].id, status=MARK_PRESENT,
        marks_obtained=60, actor_user_id=_teacher_of_maths(school), commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "STUDENT_NOT_ELIGIBLE"
    # The refusal names the child, because a row number is not actionable to
    # the teacher holding the sheet.
    assert "Kabir Rao" in result["error"]


def test_a_batch_student_is_eligible_for_the_batchs_paper(
    ctx, db_session, tenant, cycles, exam_type, school, anyone_may
):
    """The additional enrollment is the whole point of enrollment_type.

    Meera's JEE place is an `additional` enrollment. If eligibility filtered to
    primary, the batch would have no one to mark.
    """
    created = exam_services.create_examination(
        tenant_id=tenant.id, academic_cycle_id=cycles["batch"].id,
        exam_type_id=exam_type.id, name=f"JEE Mock-{uuid.uuid4().hex[:5]}",
        papers=[{
            "class_subject_id": school["jee_physics"].id,
            "max_marks": 300, "exam_date": date(2026, 5, 20),
        }],
        commit=False,
    )
    assert created["success"] is True, created
    paper = exam_services.papers_for(created["examination"].id, tenant.id)[0]

    assert marks_service.eligible_student_ids(paper) == [school["meera"].id]


def test_a_student_who_has_left_is_no_longer_eligible(
    ctx, db_session, tenant, school, marking, anyone_may
):
    enrollment = StudentClassEnrollment.query.filter_by(
        student_id=school["dev"].id, class_id=school["ten_a"].id
    ).first()
    enrollment.is_current = False
    db_session.flush()

    assert school["dev"].id not in marks_service.eligible_student_ids(
        marking["paper"]
    )


def test_students_are_identified_by_id_not_roll_number(
    ctx, tenant, school, marking, anyone_may
):
    """Roll numbers are nullable and repeat across sections, so they are never
    the key. Passing one where an id belongs must not resolve to anybody."""
    result = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id="1", status=MARK_PRESENT, marks_obtained=60,
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "STUDENT_NOT_ELIGIBLE"


# ---------------------------------------------------------------------------
# Authority — who may do the marking (ADR-014)
# ---------------------------------------------------------------------------

def test_the_subject_teacher_may_mark_their_paper(
    ctx, tenant, school, marking, only_teachers_may
):
    result = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=school["riya"].id, status=MARK_PRESENT, marks_obtained=88,
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    assert result["success"] is True, result


def test_a_teacher_of_another_subject_may_not(
    ctx, tenant, school, marking, only_teachers_may
):
    """Holding `assessment.enter` is not authority over *this* paper.

    The Science teacher can mark Science. Nothing about that lets them into the
    Maths register.
    """
    result = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=school["riya"].id, status=MARK_PRESENT, marks_obtained=88,
        actor_user_id=school["science_teacher"]["user"].id, commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "NOT_THE_MARKER"


def test_whoever_runs_assessment_may_mark_any_paper(
    ctx, tenant, school, marking, only_teachers_may
):
    """Somebody has to be able to, when a teacher is away mid-examination."""
    result = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=school["riya"].id, status=MARK_PRESENT, marks_obtained=88,
        actor_user_id=school["head"]["user"].id, commit=False,
    )
    assert result["success"] is True, result


def test_authority_without_the_permission_is_refused(
    ctx, monkeypatch, tenant, school, marking
):
    """The other half of the same pair: the right teacher, no key."""
    import modules.rbac.services as rbac

    monkeypatch.setattr(rbac, "has_permission", lambda user_id, name: False)
    result = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=school["riya"].id, status=MARK_PRESENT, marks_obtained=88,
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "FORBIDDEN"


def test_authority_is_read_on_the_day_of_the_paper(
    ctx, db_session, tenant, school, marking, only_teachers_may
):
    """A teacher who left before the paper was sat is not its marker.

    Assignments carry effective dates precisely so mid-year handovers work; the
    marks service must ask the same question attendance does, on the paper's
    own date rather than today's.
    """
    assignment = ClassSubjectTeacher.query.filter_by(
        class_subject_id=school["maths"].id
    ).first()
    assignment.effective_to = date(2026, 6, 30)   # paper is 2026-07-10
    db_session.flush()

    result = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=school["riya"].id, status=MARK_PRESENT, marks_obtained=88,
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "NOT_THE_MARKER"


# ---------------------------------------------------------------------------
# Absence is a status, never a number
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", [MARK_ABSENT, MARK_EXEMPTED, MARK_MALPRACTICE])
def test_a_student_who_did_not_sit_has_no_mark(
    ctx, tenant, school, marking, anyone_may, status
):
    result = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=school["riya"].id, status=status,
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    assert result["success"] is True, result
    assert result["mark"].marks_obtained is None
    assert result["mark"].status == status


@pytest.mark.parametrize("status", [MARK_ABSENT, MARK_EXEMPTED, MARK_MALPRACTICE])
def test_zero_is_not_how_absence_is_recorded(
    ctx, tenant, school, marking, anyone_may, status
):
    """Zero says they sat the paper and scored nothing. It is a different fact,
    it fails the student, and it drags every average computed later."""
    result = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=school["riya"].id, status=status, marks_obtained=0,
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "MARKS_NOT_ALLOWED"


def test_a_present_student_needs_a_mark(
    ctx, tenant, school, marking, anyone_may
):
    result = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=school["riya"].id, status=MARK_PRESENT,
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "MARKS_REQUIRED"


def test_a_mark_cannot_exceed_the_paper(ctx, tenant, school, marking, anyone_may):
    result = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=school["riya"].id, status=MARK_PRESENT, marks_obtained=101,
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "MARKS_ABOVE_MAX"
    assert "100" in result["error"]


def test_a_mark_cannot_be_negative(ctx, tenant, school, marking, anyone_may):
    result = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=school["riya"].id, status=MARK_PRESENT, marks_obtained=-1,
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "MARKS_INVALID"


def test_full_marks_are_allowed(ctx, tenant, school, marking, anyone_may):
    """The boundary is inclusive — a student can score 100 out of 100."""
    result = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=school["riya"].id, status=MARK_PRESENT, marks_obtained=100,
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    assert result["success"] is True, result


def test_a_mark_arriving_as_text_is_stored_as_a_number(
    ctx, tenant, school, marking, anyone_may
):
    """Every sheet that comes from a file arrives as text."""
    result = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=school["riya"].id, status=MARK_PRESENT, marks_obtained="88",
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    assert result["success"] is True, result
    assert float(result["mark"].marks_obtained) == 88.0


def test_a_mark_that_is_not_a_number_is_refused(
    ctx, tenant, school, marking, anyone_may
):
    result = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=school["riya"].id, status=MARK_PRESENT, marks_obtained="absent",
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "MARKS_INVALID"


@pytest.mark.parametrize(
    "value",
    [float("nan"), "nan", "NaN", "NAN", float("inf"), float("-inf"), "inf", "-inf"],
    ids=["nan", "s-nan", "s-NaN", "s-NAN", "inf", "-inf", "s-inf", "s--inf"],
)
def test_nan_and_infinity_never_reach_the_column(
    ctx, db_session, tenant, school, marking, anyone_may, value
):
    """`float()` accepts all of these, and NaN then passes every range check —
    every comparison against it is False, so `< 0` and `> max_marks` both let it
    through, and Postgres `numeric` stores it with `>= 0` evaluating TRUE. One
    such cell turns each later total into NaN.
    """
    result = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=school["riya"].id, status=MARK_PRESENT, marks_obtained=value,
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    assert result["success"] is False, f"{value!r} was accepted"
    assert result["code"] == "MARKS_INVALID"
    assert marks_service.marks_for_paper(marking["paper"].id, tenant.id) == []


def test_a_valid_decimal_mark_is_kept_exactly(
    ctx, tenant, school, marking, anyone_may
):
    """The guard rejects what is not a number; it must not disturb what is."""
    result = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=school["riya"].id, status=MARK_PRESENT, marks_obtained=72.5,
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    assert result["success"] is True, result
    assert float(result["mark"].marks_obtained) == 72.5


def test_an_unknown_status_is_refused(ctx, tenant, school, marking, anyone_may):
    result = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=school["riya"].id, status="maybe", marks_obtained=10,
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "STATUS_INVALID"


# ---------------------------------------------------------------------------
# One mark per student per paper
# ---------------------------------------------------------------------------

def test_marking_the_same_student_twice_corrects_rather_than_duplicates(
    ctx, db_session, tenant, school, marking, anyone_may
):
    marker = _teacher_of_maths(school)
    first = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=school["riya"].id, status=MARK_PRESENT, marks_obtained=61,
        actor_user_id=marker, commit=False,
    )
    assert first["created"] == 1

    second = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=school["riya"].id, status=MARK_PRESENT, marks_obtained=71,
        actor_user_id=marker, commit=False,
    )
    assert second["success"] is True
    assert second["created"] == 0

    rows = ExamMark.query.filter_by(
        exam_paper_id=marking["paper"].id, student_id=school["riya"].id
    ).all()
    assert len(rows) == 1
    assert float(rows[0].marks_obtained) == 71


def test_a_correction_can_change_present_to_absent(
    ctx, tenant, school, marking, anyone_may
):
    """The mark has to disappear with the status, or the row contradicts itself
    — which is what the database CHECK refuses."""
    marker = _teacher_of_maths(school)
    marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=school["riya"].id, status=MARK_PRESENT, marks_obtained=61,
        actor_user_id=marker, commit=False,
    )
    result = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=school["riya"].id, status=MARK_ABSENT,
        actor_user_id=marker, commit=False,
    )
    assert result["success"] is True, result
    assert result["mark"].marks_obtained is None


def test_the_same_student_twice_in_one_sheet_is_refused(
    ctx, tenant, school, marking, anyone_may
):
    result = marks_service.record_marks(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        rows=[
            {"student_id": school["riya"].id, "status": MARK_PRESENT,
             "marks_obtained": 40},
            {"student_id": school["riya"].id, "status": MARK_PRESENT,
             "marks_obtained": 90},
        ],
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "STUDENT_REPEATED"


# ---------------------------------------------------------------------------
# A sheet lands whole or not at all
# ---------------------------------------------------------------------------

def test_a_register_is_recorded_in_one_go(
    ctx, tenant, school, marking, anyone_may
):
    result = marks_service.record_marks(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        rows=[
            {"student_id": school["riya"].id, "status": MARK_PRESENT,
             "marks_obtained": 88},
            {"student_id": school["dev"].id, "status": MARK_ABSENT},
            {"student_id": school["meera"].id, "status": MARK_PRESENT,
             "marks_obtained": 72, "remarks": "Re-checked Q7"},
        ],
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    assert result["success"] is True, result
    assert result["created"] == 3
    assert len(marks_service.marks_for_paper(marking["paper"].id, tenant.id)) == 3


def test_one_bad_row_writes_nothing(ctx, tenant, school, marking, anyone_may):
    """Partial success would leave a teacher unable to tell what landed, and
    re-submitting the sheet ambiguous."""
    result = marks_service.record_marks(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        rows=[
            {"student_id": school["riya"].id, "status": MARK_PRESENT,
             "marks_obtained": 88},
            {"student_id": school["dev"].id, "status": MARK_PRESENT,
             "marks_obtained": 5000},
        ],
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "MARKS_ABOVE_MAX"
    assert marks_service.marks_for_paper(marking["paper"].id, tenant.id) == []


def test_an_empty_sheet_is_refused(ctx, tenant, school, marking, anyone_may):
    result = marks_service.record_marks(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id, rows=[],
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "NO_ROWS"


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

def test_marks_cannot_be_entered_before_the_examination_opens(
    ctx, tenant, cycles, exam_type, school, anyone_may
):
    created = exam_services.create_examination(
        tenant_id=tenant.id, academic_cycle_id=cycles["main"].id,
        exam_type_id=exam_type.id, name=f"Draft-{uuid.uuid4().hex[:5]}",
        papers=[{
            "class_subject_id": school["maths"].id, "max_marks": 50,
            "exam_date": date(2026, 8, 3),
        }],
        commit=False,
    )
    paper = exam_services.papers_for(created["examination"].id, tenant.id)[0]

    result = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=paper.id,
        student_id=school["riya"].id, status=MARK_PRESENT, marks_obtained=40,
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "WRONG_STATUS"


def test_a_closed_paper_refuses_further_marks(
    ctx, tenant, school, marking, only_teachers_may
):
    marker = _teacher_of_maths(school)
    marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=school["riya"].id, status=MARK_PRESENT, marks_obtained=88,
        actor_user_id=marker, commit=False,
    )
    locked = marks_service.lock_paper(
        marking["paper"].id, tenant.id,
        actor_user_id=school["head"]["user"].id, commit=False,
    )
    assert locked["success"] is True, locked

    result = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=school["dev"].id, status=MARK_PRESENT, marks_obtained=55,
        actor_user_id=marker, commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "PAPER_LOCKED"


def test_a_teacher_cannot_close_the_paper_they_marked(
    ctx, tenant, school, marking, only_teachers_may
):
    """Marking and closing are different decisions, as they are in attendance."""
    result = marks_service.lock_paper(
        marking["paper"].id, tenant.id,
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "FORBIDDEN"


def test_closing_a_paper_twice_is_refused(
    ctx, tenant, school, marking, only_teachers_may
):
    head = school["head"]["user"].id
    assert marks_service.lock_paper(
        marking["paper"].id, tenant.id, actor_user_id=head, commit=False
    )["success"] is True
    again = marks_service.lock_paper(
        marking["paper"].id, tenant.id, actor_user_id=head, commit=False
    )
    assert again["success"] is False
    assert again["code"] == "ALREADY_LOCKED"


def test_closing_one_paper_leaves_the_others_open(
    ctx, tenant, cycles, exam_type, school, only_teachers_may
):
    """Papers finish on different days — Maths on Tuesday, Science on Friday —
    so locking is per paper, not per examination.

    Both papers are declared up front because EX-01 refuses to add one after
    marking opens: the shape marks were entered against cannot change.
    """
    created = exam_services.create_examination(
        tenant_id=tenant.id, academic_cycle_id=cycles["main"].id,
        exam_type_id=exam_type.id, name=f"UT2-{uuid.uuid4().hex[:5]}",
        papers=[
            {"class_subject_id": school["maths"].id, "max_marks": 100,
             "exam_date": date(2026, 7, 10)},
            {"class_subject_id": school["science"].id, "max_marks": 100,
             "exam_date": date(2026, 7, 12)},
        ],
        commit=False,
    )
    assert created["success"] is True, created
    examination = created["examination"]
    assert exam_services.schedule_examination(
        examination.id, tenant.id, commit=False
    )["success"] is True
    assert exam_services.open_marks_entry(
        examination.id, tenant.id, commit=False
    )["success"] is True

    papers = exam_services.papers_for(examination.id, tenant.id)
    maths_paper = next(p for p in papers if p.class_subject_id == school["maths"].id)
    science_paper = next(p for p in papers if p.class_subject_id == school["science"].id)

    marks_service.lock_paper(
        maths_paper.id, tenant.id,
        actor_user_id=school["head"]["user"].id, commit=False,
    )
    assert maths_paper.marks_are_locked is True
    assert science_paper.marks_are_locked is False

    result = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=science_paper.id,
        student_id=school["riya"].id, status=MARK_PRESENT, marks_obtained=64,
        actor_user_id=school["science_teacher"]["user"].id, commit=False,
    )
    assert result["success"] is True, result


def test_closing_a_paper_is_recorded_on_the_examinations_timeline(
    ctx, tenant, school, marking, only_teachers_may
):
    head = school["head"]["user"].id
    marks_service.lock_paper(
        marking["paper"].id, tenant.id, actor_user_id=head, commit=False
    )
    events = exam_services.timeline_for(marking["examination"].id, tenant.id)
    assert marks_service.EVENT_MARKS_LOCKED in [e.event_name for e in events]


def test_entering_a_mark_writes_no_lifecycle_event(
    ctx, tenant, school, marking, anyone_may
):
    """Forty marks would be forty rows saying nothing the mark itself does not
    already carry in entered_by / entered_at."""
    before = len(exam_services.timeline_for(marking["examination"].id, tenant.id))
    marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=school["riya"].id, status=MARK_PRESENT, marks_obtained=88,
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    after = len(exam_services.timeline_for(marking["examination"].id, tenant.id))
    assert after == before


def test_who_entered_the_mark_is_recorded(ctx, tenant, school, marking, anyone_may):
    marker = _teacher_of_maths(school)
    result = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=school["riya"].id, status=MARK_PRESENT, marks_obtained=88,
        actor_user_id=marker, commit=False,
    )
    assert result["mark"].entered_by_user_id == marker
    assert result["mark"].entered_at is not None


# ---------------------------------------------------------------------------
# Tenancy
# ---------------------------------------------------------------------------

def test_another_schools_paper_cannot_be_marked(
    ctx, db_session, tenant, school, marking, anyone_may
):
    from core.models import BILLING_CYCLE_YEARLY, TENANT_STATUS_ACTIVE, Tenant

    other = Tenant(
        id=_new_id("t-"), name="Other", subdomain=f"o-{uuid.uuid4().hex}",
        status=TENANT_STATUS_ACTIVE, billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(other)
    db_session.flush()

    result = marks_service.record_mark(
        tenant_id=other.id, exam_paper_id=marking["paper"].id,
        student_id=school["riya"].id, status=MARK_PRESENT, marks_obtained=88,
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "PAPER_NOT_FOUND"


# ---------------------------------------------------------------------------
# The historical register — a locked paper answers from its own marks
# ---------------------------------------------------------------------------
#
# Every test here does the same thing to the enrollment that a real workflow
# does, and asserts the closed register did not move. The mutations are the
# ones the services actually perform, cited at each site.


def _mark_and_lock(tenant, school, marking, *, students):
    """Mark the given students and close the paper."""
    rows = [
        {"student_id": s.id, "status": MARK_PRESENT, "marks_obtained": 70 + n}
        for n, s in enumerate(students)
    ]
    recorded = marks_service.record_marks(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id, rows=rows,
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    assert recorded["success"] is True, recorded
    locked = marks_service.lock_paper(
        marking["paper"].id, tenant.id,
        actor_user_id=school["head"]["user"].id, commit=False,
    )
    assert locked["success"] is True, locked
    return {s.id for s in students}


def test_a_locked_register_survives_promotion(
    ctx, db_session, tenant, school, marking, only_teachers_may
):
    """The one that silently emptied every prior year.

    Promotion sets `is_current = False` on the enrollment it promotes from
    (`promotion_service.py:483`). Under the old rule last year's papers each
    reported an empty class the day after rollover.
    """
    sat = _mark_and_lock(
        tenant, school, marking,
        students=[school["riya"], school["dev"], school["meera"]],
    )

    for enrollment in StudentClassEnrollment.query.filter_by(
        class_id=school["ten_a"].id, tenant_id=tenant.id
    ).all():
        enrollment.is_current = False
        enrollment.enrollment_status = "promoted"
        enrollment.ended_on = date(2027, 3, 31)
    db_session.flush()

    assert set(marks_service.eligible_student_ids(marking["paper"])) == sat
    assert marks_service.marking_progress(
        marking["paper"].id, tenant.id
    )["cohort_source"] == marks_service.COHORT_REGISTER


def test_a_locked_register_survives_a_section_transfer(
    ctx, db_session, tenant, school, marking, only_teachers_may
):
    """A section transfer *rewrites* `class_id` on the same enrollment row
    (`class_enrollment_service.py:177`, per the canon) — it does not open a new
    one. So the child moved to 10B in August used to vanish from 10A's July
    register and appear in a 10B register for a paper they never sat.
    """
    sat = _mark_and_lock(
        tenant, school, marking,
        students=[school["riya"], school["dev"], school["meera"]],
    )

    other = Class(
        id=_new_id("cl-"), tenant_id=tenant.id, section="10B",
        name="Section 10B", academic_year_id=school["ten_a"].academic_year_id,
        academic_cycle_id=school["ten_a"].academic_cycle_id,
    )
    db_session.add(other)
    db_session.flush()

    moved = StudentClassEnrollment.query.filter_by(
        student_id=school["dev"].id, class_id=school["ten_a"].id
    ).first()
    moved.class_id = other.id          # the in-place rewrite
    db_session.flush()

    # Still all three, including the one whose enrollment now says 10B.
    assert set(marks_service.eligible_student_ids(marking["paper"])) == sat
    assert marks_service.is_eligible(marking["paper"], school["dev"].id) is True


def test_a_locked_register_survives_withdrawal(
    ctx, db_session, tenant, school, marking, only_teachers_may
):
    """A child who leaves in September still sat July's paper."""
    sat = _mark_and_lock(
        tenant, school, marking,
        students=[school["riya"], school["dev"], school["meera"]],
    )

    leaving = StudentClassEnrollment.query.filter_by(
        student_id=school["meera"].id, class_id=school["ten_a"].id
    ).first()
    leaving.is_current = False
    leaving.enrollment_status = "withdrawn"
    db_session.flush()

    assert set(marks_service.eligible_student_ids(marking["paper"])) == sat


def test_an_open_paper_still_reads_the_live_class(
    ctx, db_session, tenant, year, school, marking, anyone_may
):
    """The other half of the rule: while a paper is open, the cohort is the
    class as it stands — a child who joins on Monday can be marked on Monday."""
    progress = marks_service.marking_progress(marking["paper"].id, tenant.id)
    assert progress["cohort_source"] == marks_service.COHORT_ENROLLMENT

    joiner = _student(db_session, tenant, year, "Late Arrival")
    _enroll(db_session, tenant, joiner, school["ten_a"], year)

    assert joiner.id in marks_service.eligible_student_ids(marking["paper"])
    assert marks_service.is_eligible(marking["paper"], joiner.id) is True

    marked = marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=joiner.id, status=MARK_PRESENT, marks_obtained=51,
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    assert marked["success"] is True, marked


def test_a_locked_register_does_not_invent_the_unmarked(
    ctx, tenant, school, marking, only_teachers_may
):
    """Three students, two marked, then closed.

    The third is not recoverable — nothing recorded that they were expected —
    and filling them in from today's enrollment would be exactly the
    substitution the register exists to prevent.
    """
    sat = _mark_and_lock(
        tenant, school, marking, students=[school["riya"], school["dev"]],
    )
    assert set(marks_service.eligible_student_ids(marking["paper"])) == sat
    assert school["meera"].id not in sat
    assert marks_service.is_eligible(marking["paper"], school["meera"].id) is False

    progress = marks_service.marking_progress(marking["paper"].id, tenant.id)
    assert progress["eligible"] == 2 and progress["recorded"] == 2
    assert progress["outstanding"] is None


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------

def test_progress_reports_what_is_outstanding_without_enforcing_it(
    ctx, tenant, school, marking, anyone_may
):
    """A half-marked register is normal. It is reported, never refused."""
    marks_service.record_marks(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        rows=[{"student_id": school["riya"].id, "status": MARK_PRESENT,
               "marks_obtained": 88}],
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    progress = marks_service.marking_progress(marking["paper"].id, tenant.id)
    assert progress == {
        "eligible": 3, "recorded": 1, "outstanding": 2, "locked": False,
        "cohort_source": marks_service.COHORT_ENROLLMENT,
    }


def test_a_paper_may_be_closed_with_marks_outstanding(
    ctx, tenant, school, marking, only_teachers_may
):
    """Whether an incomplete register may close is the school's judgement, not
    a rule this service should invent — a student may genuinely have no row
    pending a decision, and blocking the close would strand the examination.

    What closing *does* cost is the count of who was never marked: the cohort
    becomes the register, so `outstanding` is unanswerable rather than zero.
    Recovering it would need a snapshot taken at lock time, which this slice
    deliberately does not add.
    """
    result = marks_service.lock_paper(
        marking["paper"].id, tenant.id,
        actor_user_id=school["head"]["user"].id, commit=False,
    )
    assert result["success"] is True, result

    progress = marks_service.marking_progress(marking["paper"].id, tenant.id)
    assert progress["locked"] is True
    assert progress["cohort_source"] == marks_service.COHORT_REGISTER
    assert progress["recorded"] == 0
    # Not zero — zero would claim all three were marked.
    assert progress["outstanding"] is None
