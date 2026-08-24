"""The Examination domain's architectural invariants.

Not CRUD. Each test here pins a decision that would be expensive to reverse
once marks exist, using the realistic shape the product has to serve: one
reporting year, three cycles, two boards and a vacation batch.
"""

from __future__ import annotations

import uuid
from datetime import date, time

import pytest
from flask import g
from sqlalchemy.exc import IntegrityError

from modules.academics.academic_year.models import AcademicYear
from modules.academics.backbone.models import AcademicTerm
from modules.academics.cycles.models import (
    CYCLE_KIND_MAIN,
    CYCLE_KIND_SHORT_COURSE,
    AcademicCycle,
)
from modules.academics.cycles.services import default_cycle_for_year
from modules.classes.models import Class, ClassSubject
from modules.examinations.models import (
    EXAM_DRAFT,
    EXAM_PUBLISHED,
    MARK_ABSENT,
    MARK_EXEMPTED,
    MARK_MALPRACTICE,
    MARK_PRESENT,
    ExamMark,
    ExamPaper,
    ExamResult,
    ExamType,
    Examination,
    GradingBand,
    GradingScheme,
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
def year(db_session, tenant):
    row = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name=f"2026-27-{uuid.uuid4().hex[:5]}",
        start_date=date(2026, 4, 1), end_date=date(2027, 3, 31),
    )
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def trust(db_session, tenant, year):
    """One reporting year; GSEB, CBSE and a 40-day vacation batch inside it."""
    gseb = default_cycle_for_year(year.id, tenant.id)
    gseb.name = f"GSEB-{uuid.uuid4().hex[:5]}"
    gseb.start_date, gseb.end_date = date(2026, 6, 1), date(2027, 4, 30)

    cbse = AcademicCycle(
        id=_new_id("cy-"), tenant_id=tenant.id, academic_year_id=year.id,
        name=f"CBSE-{uuid.uuid4().hex[:5]}",
        start_date=date(2026, 4, 1), end_date=date(2027, 3, 31),
        cycle_kind=CYCLE_KIND_MAIN,
    )
    vacation = AcademicCycle(
        id=_new_id("cy-"), tenant_id=tenant.id, academic_year_id=year.id,
        name=f"Vacation-{uuid.uuid4().hex[:5]}",
        start_date=date(2026, 5, 1), end_date=date(2026, 6, 9),
        cycle_kind=CYCLE_KIND_SHORT_COURSE,
    )
    db_session.add_all([cbse, vacation])
    db_session.flush()
    return {"gseb": gseb, "cbse": cbse, "vacation": vacation}


@pytest.fixture
def exam_type(db_session, tenant):
    row = ExamType(
        id=_new_id("et-"), tenant_id=tenant.id,
        name=f"Half Yearly-{uuid.uuid4().hex[:5]}", code=None, sequence=30,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _class_in(db_session, tenant, year, cycle, section):
    row = Class(
        id=_new_id("cl-"), tenant_id=tenant.id, section=section,
        name=f"Grade 10 {section}", academic_year_id=year.id,
        academic_cycle_id=cycle.id,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _offering(db_session, tenant, cls, label="Maths"):
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


def _examination(db_session, tenant, cycle, exam_type, name=None, term=None):
    row = Examination(
        id=_new_id("ex-"), tenant_id=tenant.id, academic_cycle_id=cycle.id,
        exam_type_id=exam_type.id, name=name or f"Exam-{uuid.uuid4().hex[:6]}",
        status=EXAM_DRAFT, academic_term_id=term.id if term else None,
    )
    db_session.add(row)
    db_session.flush()
    return row


def _paper(db_session, tenant, examination, offering, cls, *, component="", max_marks=100):
    row = ExamPaper(
        id=_new_id("ep-"), tenant_id=tenant.id, examination_id=examination.id,
        class_subject_id=offering.id, class_id=cls.id,
        component_label=component, max_marks=max_marks,
        exam_date=date(2026, 9, 10),
    )
    db_session.add(row)
    db_session.flush()
    return row


def _student(db_session, tenant, year):
    from modules.people.models import Person

    person = Person(id=_new_id("p-"), tenant_id=tenant.id, full_name="A Student")
    db_session.add(person)
    db_session.flush()
    row = Student(
        id=_new_id("s-"), tenant_id=tenant.id, person_id=person.id,
        admission_number=f"ADM{uuid.uuid4().hex[:8]}", academic_year_id=year.id,
    )
    db_session.add(row)
    db_session.flush()
    return row


# ---------------------------------------------------------------------------
# Grain: an examination is an event; a paper is a sitting (ADR-016)
# ---------------------------------------------------------------------------

def test_one_examination_spans_many_subjects_and_sections(
    ctx, db_session, tenant, year, trust, exam_type
):
    """The shape a report card needs and a one-subject exam could not provide."""
    exam = _examination(db_session, tenant, trust["gseb"], exam_type, "Half Yearly")
    section_a = _class_in(db_session, tenant, year, trust["gseb"], "A")
    section_b = _class_in(db_session, tenant, year, trust["gseb"], "B")

    for cls in (section_a, section_b):
        for subject in ("Maths", "Science", "English"):
            _paper(db_session, tenant, exam, _offering(db_session, tenant, cls, subject), cls)

    papers = ExamPaper.query.filter_by(examination_id=exam.id).all()
    assert len(papers) == 6
    assert len({p.class_id for p in papers}) == 2


def test_an_examination_may_have_a_single_paper(
    ctx, db_session, tenant, year, trust, exam_type
):
    """A weekly subject test is one paper. The event grain must not force more."""
    exam = _examination(db_session, tenant, trust["gseb"], exam_type)
    cls = _class_in(db_session, tenant, year, trust["gseb"], "A")
    _paper(db_session, tenant, exam, _offering(db_session, tenant, cls), cls)

    assert ExamPaper.query.filter_by(examination_id=exam.id).count() == 1


def test_theory_and_practical_are_two_papers(
    ctx, db_session, tenant, year, trust, exam_type
):
    """Science 80+20 is two sittings, which is what a school actually holds."""
    exam = _examination(db_session, tenant, trust["gseb"], exam_type)
    cls = _class_in(db_session, tenant, year, trust["gseb"], "A")
    science = _offering(db_session, tenant, cls, "Science")

    _paper(db_session, tenant, exam, science, cls, component="Theory", max_marks=80)
    _paper(db_session, tenant, exam, science, cls, component="Practical", max_marks=20)

    papers = ExamPaper.query.filter_by(class_subject_id=science.id).all()
    assert sorted(p.component_label for p in papers) == ["Practical", "Theory"]
    assert sum(float(p.max_marks) for p in papers) == 100


def test_the_same_offering_and_component_cannot_be_scheduled_twice(
    ctx, db_session, tenant, year, trust, exam_type
):
    exam = _examination(db_session, tenant, trust["gseb"], exam_type)
    cls = _class_in(db_session, tenant, year, trust["gseb"], "A")
    maths = _offering(db_session, tenant, cls)
    _paper(db_session, tenant, exam, maths, cls)

    db_session.begin_nested()
    _bad = ExamPaper(
        id=_new_id("ep-"), tenant_id=tenant.id, examination_id=exam.id,
        class_subject_id=maths.id, class_id=cls.id, component_label="",
        max_marks=100,
    )
    db_session.add(_bad)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_an_examination_declares_no_applicability():
    """Locked (ADR-016): which sections sit an exam is answered by its papers.

    A header saying "Grade 10" while its papers name Grade 9 is a contradiction
    the schema must not be able to hold — the rule AcademicCycle already follows.
    """
    columns = set(Examination.__table__.columns.keys())
    for forbidden in (
        "programme_id", "grade_id", "stream_id", "class_id",
        "school_unit_id", "medium_id", "applicable_class_ids",
    ):
        assert forbidden not in columns, (
            f"Examination.{forbidden} makes the event a second owner of "
            "applicability. Its papers already say which sections sit it."
        )


# ---------------------------------------------------------------------------
# Temporal context (ADR-017)
# ---------------------------------------------------------------------------

def test_an_examination_belongs_to_a_cycle_not_a_year():
    columns = set(Examination.__table__.columns.keys())
    assert "academic_cycle_id" in columns
    assert "academic_year_id" not in columns, (
        "the year is reporting context; storing it beside the cycle would be a "
        "denormalisation to keep in step for no reader"
    )


def test_examinations_in_different_cycles_may_share_a_name(
    ctx, db_session, tenant, trust, exam_type
):
    """GSEB's "Half Yearly" and CBSE's are different examinations."""
    _examination(db_session, tenant, trust["gseb"], exam_type, "Half Yearly")
    _examination(db_session, tenant, trust["cbse"], exam_type, "Half Yearly")

    found = Examination.query.filter_by(tenant_id=tenant.id, name="Half Yearly").all()
    assert len(found) == 2
    assert len({e.academic_cycle_id for e in found}) == 2


def test_one_cycle_cannot_hold_two_examinations_of_a_name(
    ctx, db_session, tenant, trust, exam_type
):
    _examination(db_session, tenant, trust["gseb"], exam_type, "Half Yearly")

    db_session.begin_nested()
    db_session.add(
        Examination(
            id=_new_id("ex-"), tenant_id=tenant.id,
            academic_cycle_id=trust["gseb"].id, exam_type_id=exam_type.id,
            name="Half Yearly", status=EXAM_DRAFT,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_a_term_is_optional(ctx, db_session, tenant, year, trust, exam_type):
    """A board examination is scheduled by the board, not by the school's terms."""
    exam = _examination(db_session, tenant, trust["gseb"], exam_type)
    assert exam.academic_term_id is None

    term = AcademicTerm(
        id=_new_id("t-"), tenant_id=tenant.id, academic_year_id=year.id,
        academic_cycle_id=trust["gseb"].id, name="Term 1", sequence=1,
        start_date=date(2026, 6, 1), end_date=date(2026, 10, 31),
    )
    db_session.add(term)
    db_session.flush()

    with_term = _examination(db_session, tenant, trust["gseb"], exam_type, term=term)
    assert with_term.academic_term_id == term.id


def test_an_examination_may_reference_a_calendar_window_without_being_one(
    ctx, db_session, tenant, year, trust, exam_type
):
    """`exam_windows` stays the calendar's reservation; this is the event."""
    from modules.academics.calendar.models import ExamWindow

    window = ExamWindow(
        id=_new_id("w-"), tenant_id=tenant.id, academic_year_id=year.id,
        name="Half Yearly window", exam_type="half_yearly",
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 20),
    )
    db_session.add(window)
    db_session.flush()

    exam = _examination(db_session, tenant, trust["gseb"], exam_type)
    exam.exam_window_id = window.id
    db_session.flush()

    assert exam.exam_window_id == window.id
    # The window is untouched by the examination existing.
    assert ExamWindow.query.filter_by(id=window.id).first() is not None


def test_the_vacation_batch_holds_its_own_examinations(
    ctx, db_session, tenant, year, trust, exam_type
):
    """A 40-day batch is a cycle, so its assessments are ordinary examinations."""
    exam = _examination(db_session, tenant, trust["vacation"], exam_type, "Batch Final")
    cls = _class_in(db_session, tenant, year, trust["vacation"], "VAC")
    _paper(db_session, tenant, exam, _offering(db_session, tenant, cls), cls)

    assert exam.academic_cycle_id == trust["vacation"].id


# ---------------------------------------------------------------------------
# Marks: absence is a status, never a number
# ---------------------------------------------------------------------------

@pytest.fixture
def paper(db_session, tenant, year, trust, exam_type):
    exam = _examination(db_session, tenant, trust["gseb"], exam_type)
    cls = _class_in(db_session, tenant, year, trust["gseb"], "A")
    return _paper(db_session, tenant, exam, _offering(db_session, tenant, cls), cls)


@pytest.mark.parametrize(
    "status", [MARK_ABSENT, MARK_EXEMPTED, MARK_MALPRACTICE]
)
def test_a_non_numeric_outcome_is_representable(
    ctx, db_session, tenant, year, paper, status
):
    student = _student(db_session, tenant, year)
    db_session.add(
        ExamMark(
            id=_new_id("m-"), tenant_id=tenant.id, exam_paper_id=paper.id,
            student_id=student.id, status=status, marks_obtained=None,
        )
    )
    db_session.flush()

    row = ExamMark.query.filter_by(student_id=student.id).first()
    assert row.status == status
    assert row.marks_obtained is None


def test_an_absent_student_cannot_carry_marks(ctx, db_session, tenant, year, paper):
    """The CHECK that stops absence being recorded as a zero."""
    student = _student(db_session, tenant, year)

    db_session.begin_nested()
    db_session.add(
        ExamMark(
            id=_new_id("m-"), tenant_id=tenant.id, exam_paper_id=paper.id,
            student_id=student.id, status=MARK_ABSENT, marks_obtained=0,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_a_present_student_must_carry_marks(ctx, db_session, tenant, year, paper):
    """The other half: "present with no mark" is not-yet-entered, not a result."""
    student = _student(db_session, tenant, year)

    db_session.begin_nested()
    db_session.add(
        ExamMark(
            id=_new_id("m-"), tenant_id=tenant.id, exam_paper_id=paper.id,
            student_id=student.id, status=MARK_PRESENT, marks_obtained=None,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_one_mark_per_student_per_paper(ctx, db_session, tenant, year, paper):
    student = _student(db_session, tenant, year)
    db_session.add(
        ExamMark(
            id=_new_id("m-"), tenant_id=tenant.id, exam_paper_id=paper.id,
            student_id=student.id, status=MARK_PRESENT, marks_obtained=71,
        )
    )
    db_session.flush()

    db_session.begin_nested()
    db_session.add(
        ExamMark(
            id=_new_id("m-"), tenant_id=tenant.id, exam_paper_id=paper.id,
            student_id=student.id, status=MARK_PRESENT, marks_obtained=80,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


# ---------------------------------------------------------------------------
# Results: published snapshots are frozen, revised rather than edited
# ---------------------------------------------------------------------------

def _result(tenant, exam, student, version, *, current=True, percentage=83.5, grade="A"):
    return ExamResult(
        id=_new_id("r-"), tenant_id=tenant.id, examination_id=exam.id,
        student_id=student.id, version=version, is_current=current,
        total_max=600, total_obtained=501, percentage=percentage,
        grade_label=grade, is_pass=True,
    )


def test_a_student_keeps_a_result_per_examination(
    ctx, db_session, tenant, year, trust, exam_type
):
    """Half Yearly and Final in one year, and next year's too — none overwritten."""
    student = _student(db_session, tenant, year)
    half = _examination(db_session, tenant, trust["gseb"], exam_type, "Half Yearly")
    final = _examination(db_session, tenant, trust["gseb"], exam_type, "Final")

    db_session.add_all([
        _result(tenant, half, student, 1, percentage=71.0, grade="B"),
        _result(tenant, final, student, 1, percentage=83.5, grade="A"),
    ])
    db_session.flush()

    rows = ExamResult.query.filter_by(student_id=student.id).all()
    assert len(rows) == 2
    assert {float(r.percentage) for r in rows} == {71.0, 83.5}


def test_a_revision_adds_a_version_and_leaves_the_old_one(
    ctx, db_session, tenant, year, trust, exam_type
):
    student = _student(db_session, tenant, year)
    exam = _examination(db_session, tenant, trust["gseb"], exam_type)

    first = _result(tenant, exam, student, 1, percentage=71.0, grade="B")
    db_session.add(first)
    db_session.flush()

    first.is_current = False
    db_session.add(_result(tenant, exam, student, 2, percentage=74.0, grade="B+"))
    db_session.flush()

    versions = {
        r.version: (float(r.percentage), r.is_current)
        for r in ExamResult.query.filter_by(student_id=student.id).all()
    }
    assert versions[1] == (71.0, False), "the published version was rewritten"
    assert versions[2] == (74.0, True)


def test_only_one_result_is_current(ctx, db_session, tenant, year, trust, exam_type):
    student = _student(db_session, tenant, year)
    exam = _examination(db_session, tenant, trust["gseb"], exam_type)
    db_session.add(_result(tenant, exam, student, 1))
    db_session.flush()

    db_session.begin_nested()
    db_session.add(_result(tenant, exam, student, 2))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_changing_the_grading_scheme_does_not_move_a_published_result(
    ctx, db_session, tenant, year, trust, exam_type
):
    """The whole reason a result is a snapshot rather than a view."""
    scheme = GradingScheme(
        id=_new_id("gs-"), tenant_id=tenant.id,
        name=f"CBSE-{uuid.uuid4().hex[:5]}", scheme_type="letter",
    )
    db_session.add(scheme)
    db_session.flush()
    band = GradingBand(
        id=_new_id("gb-"), tenant_id=tenant.id, grading_scheme_id=scheme.id,
        label="A", min_value=80, max_value=100, is_pass=True, sequence=1,
    )
    db_session.add(band)
    db_session.flush()

    student = _student(db_session, tenant, year)
    exam = _examination(db_session, tenant, trust["gseb"], exam_type)
    exam.grading_scheme_id = scheme.id
    published = _result(tenant, exam, student, 1, percentage=83.5, grade="A")
    published.status_at_publish = None
    db_session.add(published)
    db_session.flush()

    # The school redraws its bands: 83.5 would now be a B.
    band.min_value = 85
    db_session.flush()

    db_session.refresh(published)
    assert published.grade_label == "A", (
        "a published result must not follow a later change to the scheme"
    )


# ---------------------------------------------------------------------------
# Grading is configuration, not code
# ---------------------------------------------------------------------------

def test_a_school_defines_its_own_bands(ctx, db_session, tenant):
    """No band values ship in the product; CBSE and GSEB differ."""
    scheme = GradingScheme(
        id=_new_id("gs-"), tenant_id=tenant.id,
        name=f"GSEB-{uuid.uuid4().hex[:5]}", scheme_type="letter",
    )
    db_session.add(scheme)
    db_session.flush()
    db_session.add_all([
        GradingBand(
            id=_new_id("gb-"), tenant_id=tenant.id, grading_scheme_id=scheme.id,
            label=label, min_value=lo, max_value=hi, is_pass=lo >= 33, sequence=i,
        )
        for i, (label, lo, hi) in enumerate(
            [("A1", 91, 100), ("A2", 81, 90.99), ("F", 0, 32.99)]
        )
    ])
    db_session.flush()

    assert len(scheme.bands) == 3
    assert {b.label for b in scheme.bands} == {"A1", "A2", "F"}


def test_no_grading_bands_are_seeded(ctx, db_session, tenant):
    """Seeding A+ at 90 would put one board's policy in every school."""
    assert GradingBand.query.filter_by(tenant_id=tenant.id).count() == 0


def test_exam_types_are_data_not_code(ctx, db_session, tenant):
    """A school may name a kind of examination nobody shipped."""
    row = ExamType(
        id=_new_id("et-"), tenant_id=tenant.id,
        name=f"Olympiad Screening {uuid.uuid4().hex[:5]}", sequence=99,
    )
    db_session.add(row)
    db_session.flush()
    assert row.id is not None


# ---------------------------------------------------------------------------
# Tenancy — declared in the database
# ---------------------------------------------------------------------------

@pytest.fixture
def other_tenant(db_session):
    from core.models import Tenant, TENANT_STATUS_ACTIVE, BILLING_CYCLE_YEARLY

    other = Tenant(
        id=_new_id("t-"), name="Other School",
        subdomain=f"test-{uuid.uuid4().hex}",
        status=TENANT_STATUS_ACTIVE, billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(other)
    db_session.flush()
    return other


def test_an_examination_cannot_reach_another_schools_cycle(
    ctx, db_session, tenant, trust, exam_type, other_tenant
):
    db_session.begin_nested()
    db_session.add(
        Examination(
            id=_new_id("ex-"), tenant_id=other_tenant.id,
            academic_cycle_id=trust["gseb"].id, exam_type_id=exam_type.id,
            name="Theirs", status=EXAM_DRAFT,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_a_paper_cannot_reach_another_schools_examination(
    ctx, db_session, tenant, year, trust, exam_type, other_tenant
):
    exam = _examination(db_session, tenant, trust["gseb"], exam_type)
    cls = _class_in(db_session, tenant, year, trust["gseb"], "A")
    offering = _offering(db_session, tenant, cls)

    db_session.begin_nested()
    db_session.add(
        ExamPaper(
            id=_new_id("ep-"), tenant_id=other_tenant.id, examination_id=exam.id,
            class_subject_id=offering.id, class_id=cls.id, max_marks=100,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_a_mark_cannot_reach_another_schools_student(
    ctx, db_session, tenant, year, paper, other_tenant
):
    student = _student(db_session, tenant, year)

    db_session.begin_nested()
    db_session.add(
        ExamMark(
            id=_new_id("m-"), tenant_id=other_tenant.id, exam_paper_id=paper.id,
            student_id=student.id, status=MARK_PRESENT, marks_obtained=50,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


# ---------------------------------------------------------------------------
# What must NOT have been introduced
# ---------------------------------------------------------------------------

def test_no_global_current_examination_context():
    """Several cycles run at once; a global "current examination" would be wrong."""
    from modules.academics.backbone.models import AcademicSettings

    columns = set(AcademicSettings.__table__.columns.keys())
    for forbidden in (
        "current_academic_cycle_id", "current_examination_id",
        "current_exam_cycle_id",
    ):
        assert forbidden not in columns


def test_examination_introduces_no_second_authorization_system():
    """Authority is `assessment.*` / `examination.*` keys in the one catalogue."""
    from modules.rbac.catalog import PERMISSIONS

    names = {name for name, _ in PERMISSIONS}
    assert {"assessment.enter", "assessment.manage", "examination.manage"} <= names
    # The dead namespace is gone, and the grade master is untouched.
    assert not any(n.startswith("grades.") for n in names)
    assert "grade.read" in names and "grade.manage" in names


def test_examination_documents_reuse_the_shared_store():
    """No exam_documents table: `documents` already serves any owner kind."""
    from core.database import db as _db
    from modules.documents.registry import is_registered

    assert "exam_documents" not in _db.metadata.tables
    assert is_registered("exam_paper")
    assert is_registered("exam_mark")


def test_no_assessment_scheme_table_was_created():
    """Theory + practical is two papers. A scheme would be a template over
    that, not a different model — deferred rather than guessed at."""
    from core.database import db as _db

    for absent in ("assessment_schemes", "assessment_components"):
        assert absent not in _db.metadata.tables
