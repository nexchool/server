"""Classes list envelope (filter/search/sort/paginate) and the stats aggregate.

Covers the overridden ``GET /api/classes/`` service layer: the
``{items, total, page, per_page, total_pages}`` envelope, the SQL-side
student/teacher counts that replaced the per-row N+1, the derived ``status``,
and ``get_classes_stats``.

Pattern mirrors ``tests/test_branch_enforce_classes_students.py``: push
``g.tenant_id`` / ``g.current_user`` through ``flask_app.test_request_context``
and call the service directly. Runs against the localhost Postgres bound to the
savepoint connection in conftest (rolled back per test).
"""

from __future__ import annotations

import uuid

import pytest
from flask import g

from core.models import Tenant
from modules.auth.models import User
from modules.classes import services as class_services
from modules.classes.models import Class
from modules.students.models import Student
from tests.conftest import employ_for


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def unit(db_session, tenant):
    from modules.school_units.models import SchoolUnit

    su = SchoolUnit(
        id=_new_id("su-"), tenant_id=tenant.id, name="Main Campus",
        code=f"MC-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(su)
    db_session.flush()
    return su


@pytest.fixture
def programme(db_session, tenant):
    from modules.academic_programmes.models import AcademicProgramme

    prog = AcademicProgramme(
        id=_new_id("ap-"), tenant_id=tenant.id, name="Primary", board="GSEB",
        code=f"PRI-{uuid.uuid4().hex[:6]}",
    )
    db_session.add(prog)
    db_session.flush()
    return prog


@pytest.fixture
def grades(db_session, tenant):
    """Two grades whose sequence order is the inverse of their alphabetical order."""
    from modules.grades.models import Grade

    nursery = Grade(id=_new_id("g-"), tenant_id=tenant.id, name="Nursery", sequence=1)
    grade_one = Grade(id=_new_id("g-"), tenant_id=tenant.id, name="Grade 1", sequence=2)
    db_session.add_all([nursery, grade_one])
    db_session.flush()
    return nursery, grade_one


@pytest.fixture
def active_year(db_session, tenant):
    from modules.academics.academic_year.models import AcademicYear

    ay = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name="2026-2027",
        start_date="2026-06-01", end_date="2027-03-31", is_active=True,
    )
    db_session.add(ay)
    db_session.flush()
    return ay


@pytest.fixture
def past_year(db_session, tenant):
    from modules.academics.academic_year.models import AcademicYear

    ay = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name="2024-2025",
        start_date="2024-06-01", end_date="2025-03-31", is_active=False,
    )
    db_session.add(ay)
    db_session.flush()
    return ay


@pytest.fixture
def admin_user(db_session, tenant):
    """Tenant user with no UserSchoolUnit rows -> branch-unrestricted."""
    u = User(
        id=_new_id("u-"), tenant_id=tenant.id,
        email=f"admin-{uuid.uuid4().hex[:6]}@test.school",
        password_hash="x" * 60, name="Admin",
    )
    db_session.add(u)
    db_session.flush()
    return u


def _make_class(db_session, tenant, *, section, unit, programme, grade, year):
    cls = Class(
        id=_new_id("c-"), tenant_id=tenant.id, name=grade.name, section=section,
        academic_year_id=year.id, school_unit_id=unit.id,
        programme_id=programme.id, grade_id=grade.id,
    )
    db_session.add(cls)
    db_session.flush()
    return cls


def _add_students(db_session, tenant, class_id, count):
    for _ in range(count):
        suffix = uuid.uuid4().hex[:8]
        user = User(
            id=_new_id("u-"), tenant_id=tenant.id, email=f"{suffix}@test.school",
            password_hash="x" * 60, name="Student",
        )
        db_session.add(user)
        db_session.flush()
        db_session.add(Student(
            id=_new_id("s-"), tenant_id=tenant.id, user_id=user.id,
            admission_number=f"ADM-{suffix}", class_id=class_id,
        ))
    db_session.flush()


@pytest.fixture
def populated(db_session, tenant, unit, programme, grades, active_year):
    """Nursery-A with 3 students, Grade 1-A with 1 student, Grade 1-B with none."""
    nursery, grade_one = grades
    nursery_a = _make_class(
        db_session, tenant, section="A", unit=unit, programme=programme,
        grade=nursery, year=active_year,
    )
    grade_one_a = _make_class(
        db_session, tenant, section="A", unit=unit, programme=programme,
        grade=grade_one, year=active_year,
    )
    grade_one_b = _make_class(
        db_session, tenant, section="B", unit=unit, programme=programme,
        grade=grade_one, year=active_year,
    )
    _add_students(db_session, tenant, nursery_a.id, 3)
    _add_students(db_session, tenant, grade_one_a.id, 1)
    return nursery_a, grade_one_a, grade_one_b


@pytest.fixture
def ctx(flask_app, tenant, admin_user):
    """Request context with tenant + unrestricted user bound."""
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = admin_user
        yield


# ---------------------------------------------------------------------------
# Envelope + pagination
# ---------------------------------------------------------------------------

def test_returns_envelope_with_every_row_when_unpaginated(ctx, populated):
    result = class_services.get_all_classes()

    assert set(result) == {"items", "total", "page", "per_page", "total_pages"}
    assert result["total"] == 3
    assert len(result["items"]) == 3
    assert result["total_pages"] == 1
    assert result["page"] == 1


def test_paginating_slices_items_but_total_counts_every_match(ctx, populated):
    first = class_services.get_all_classes(page=1, per_page=2)

    assert len(first["items"]) == 2
    assert first["total"] == 3
    assert first["total_pages"] == 2
    assert first["per_page"] == 2


def test_last_page_returns_the_remainder(ctx, populated):
    second = class_services.get_all_classes(page=2, per_page=2)

    assert len(second["items"]) == 1
    assert second["page"] == 2


def test_pages_do_not_overlap(ctx, populated):
    first = class_services.get_all_classes(page=1, per_page=2)
    second = class_services.get_all_classes(page=2, per_page=2)

    ids = {c["id"] for c in first["items"]} | {c["id"] for c in second["items"]}
    assert len(ids) == 3


def test_paging_is_stable_when_every_row_ties_on_the_sort_key(
    ctx, db_session, tenant, unit, programme, grades, active_year
):
    """Sorting by a count ties every empty class together, and section repeats
    across grades — without a unique final tiebreaker the DB may order ties
    differently per query and drop or repeat rows between pages."""
    from modules.grades.models import Grade

    # Distinct grades (the unique constraint spans grade+section), but all tie
    # on student_count = 0 and on section "A" — so only Class.id separates them.
    for i in range(8):
        grade = Grade(
            id=_new_id("g-"), tenant_id=tenant.id,
            name=f"Tie-{uuid.uuid4().hex[:6]}", sequence=100 + i,
        )
        db_session.add(grade)
        db_session.flush()
        _make_class(
            db_session, tenant, section="A", unit=unit, programme=programme,
            grade=grade, year=active_year,
        )
        db_session.flush()

    seen = []
    for page in (1, 2, 3, 4):
        result = class_services.get_all_classes(
            sort_by="student_count", sort_dir="desc", page=page, per_page=2
        )
        seen.extend(c["id"] for c in result["items"])

    assert len(seen) == len(set(seen)) == 8


# ---------------------------------------------------------------------------
# Counts
# ---------------------------------------------------------------------------

def test_student_and_teacher_counts_come_back_per_class(ctx, populated):
    nursery_a, grade_one_a, grade_one_b = populated
    by_id = {c["id"]: c for c in class_services.get_all_classes()["items"]}

    assert by_id[nursery_a.id]["student_count"] == 3
    assert by_id[grade_one_a.id]["student_count"] == 1
    assert by_id[grade_one_b.id]["student_count"] == 0


def test_class_with_no_students_reports_zero_not_null(ctx, populated):
    _, _, grade_one_b = populated
    row = next(
        c for c in class_services.get_all_classes()["items"] if c["id"] == grade_one_b.id
    )

    assert row["student_count"] == 0
    assert row["teacher_count"] == 0


def _make_teacher(db_session, tenant, name="Teacher"):
    """Returns (teacher_profile, user) — the two ids teachers are reached by."""
    from modules.teachers.models import Teacher

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=_new_id("u-"), tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name=name,
    )
    db_session.add(user)
    db_session.flush()
    teacher = Teacher(
        id=_new_id("t-"), tenant_id=tenant.id, user_id=user.id,
        staff_id=employ_for(user, employee_number=f"EMP-{suffix}").id,
    )
    db_session.add(teacher)
    db_session.flush()
    return teacher, user


def _make_subject_teacher(db_session, tenant, cls, teacher):
    """Record that this teacher takes a subject in this class.

    Owned by class_subject_teachers, which hangs off the subject the class
    offers (ADR-014).
    """
    from modules.academics.backbone.models import ClassSubjectTeacher
    from modules.classes.models import ClassSubject
    from modules.subjects.models import Subject

    subject = Subject(
        id=_new_id("sub-"), tenant_id=tenant.id, name=f"Subject {uuid.uuid4().hex[:4]}",
        code=f"S{uuid.uuid4().hex[:4]}",
    )
    db_session.add(subject)
    db_session.flush()
    offered = ClassSubject(
        id=_new_id("cs-"), tenant_id=tenant.id, class_id=cls.id,
        subject_id=subject.id, weekly_periods=4,
    )
    db_session.add(offered)
    db_session.flush()
    db_session.add(
        ClassSubjectTeacher(
            id=_new_id("cst-"), tenant_id=tenant.id,
            class_subject_id=offered.id, teacher_id=teacher.id,
            role="primary", is_active=True,
        )
    )
    db_session.flush()


def _make_class_teacher(db_session, tenant, cls, teacher, user):
    """Name a class teacher the way the application does.

    The responsibility is recorded in class_teacher_assignments, which owns it;
    classes.teacher_id is a cache that follows (ADR-014). Setting the cache
    alone is a state no supported path can produce any more.
    """
    from modules.academics.backbone.models import ClassTeacherAssignment

    db_session.add(
        ClassTeacherAssignment(
            id=_new_id("cta-"), tenant_id=tenant.id, class_id=cls.id,
            teacher_id=teacher.id, role="primary", is_active=True,
        )
    )
    cls.teacher_id = teacher.id  # the cache names the teacher (migration 095)
    db_session.add(cls)
    db_session.flush()


def test_teacher_count_includes_a_class_teacher_set_on_the_class(
    ctx, db_session, tenant, populated
):
    """create_class/update_class set classes.teacher_id without a junction row,
    so counting class_teachers alone showed 0 teachers beside a teacher name."""
    nursery_a, _, _ = populated
    teacher, user = _make_teacher(db_session, tenant)
    _make_class_teacher(db_session, tenant, nursery_a, teacher, user)

    row = next(
        c for c in class_services.get_all_classes()["items"] if c["id"] == nursery_a.id
    )
    assert row["teacher_name"] is not None
    assert row["teacher_count"] == 1


def test_teacher_counted_once_when_class_teacher_and_subject_teacher(
    ctx, db_session, tenant, populated
):
    """Holding both responsibilities for a class still makes one teacher."""
    nursery_a, _, _ = populated
    teacher, user = _make_teacher(db_session, tenant)
    _make_class_teacher(db_session, tenant, nursery_a, teacher, user)
    _make_subject_teacher(db_session, tenant, nursery_a, teacher)

    row = next(
        c for c in class_services.get_all_classes()["items"] if c["id"] == nursery_a.id
    )
    assert row["teacher_count"] == 1


def test_stats_counts_a_class_teacher_set_on_the_class(
    ctx, db_session, tenant, populated
):
    nursery_a, _, _ = populated
    teacher, user = _make_teacher(db_session, tenant)
    _make_class_teacher(db_session, tenant, nursery_a, teacher, user)

    assert class_services.get_classes_stats()["total_teachers"] == 1


def test_counts_ignore_other_tenants_rows(ctx, db_session, tenant, populated):
    """The count subqueries are column-level SELECTs, so the automatic
    with_loader_criteria tenant scope does not cover them. Guards the explicit
    tenant filter in `_count_subqueries`."""
    nursery_a, _, _ = populated

    other = Tenant(
        id=_new_id("t-"), name="Other School",
        subdomain=f"other-{uuid.uuid4().hex}",
    )
    db_session.add(other)
    db_session.flush()
    # A student in a *different* tenant pointed at this tenant's class id.
    suffix = uuid.uuid4().hex[:8]
    other_user = User(
        id=_new_id("u-"), tenant_id=other.id, email=f"{suffix}@other.school",
        password_hash="x" * 60, name="Other Student",
    )
    db_session.add(other_user)
    db_session.flush()
    db_session.add(Student(
        id=_new_id("s-"), tenant_id=other.id, user_id=other_user.id,
        admission_number=f"ADM-{suffix}", class_id=nursery_a.id,
    ))
    db_session.flush()

    row = next(
        c for c in class_services.get_all_classes()["items"] if c["id"] == nursery_a.id
    )
    assert row["student_count"] == 3


def test_query_count_does_not_grow_with_the_number_of_classes(
    flask_app, db_session, tenant, admin_user, unit, programme, active_year
):
    """The counts and relationships resolve in SQL, not per row.

    Guards the N+1 this endpoint was rewritten to remove: it previously issued
    two COUNTs plus six lazy relationship loads *per class*.
    """
    from sqlalchemy import event
    from modules.grades.models import Grade

    from core.database import db

    def seed(n):
        for _ in range(n):
            grade = Grade(
                id=_new_id("g-"), tenant_id=tenant.id,
                name=f"G-{uuid.uuid4().hex[:6]}", sequence=1,
            )
            db_session.add(grade)
            db_session.flush()
            _make_class(
                db_session, tenant, section="A", unit=unit,
                programme=programme, grade=grade, year=active_year,
            )

    def count_statements(expected_rows):
        statements = []

        def record(conn, cursor, statement, params, context, executemany):
            statements.append(statement)

        with flask_app.test_request_context("/"):
            g.tenant_id = tenant.id
            g.current_user = admin_user
            event.listen(db.engine, "before_cursor_execute", record)
            try:
                assert len(class_services.get_all_classes()["items"]) == expected_rows
            finally:
                event.remove(db.engine, "before_cursor_execute", record)
        return len(statements)

    seed(3)
    few = count_statements(3)
    seed(12)
    many = count_statements(15)

    # Five-fold the rows must not mean more queries. Bounded absolutely too,
    # so this still fails if the whole thing regresses to per-row loads.
    assert many <= few, f"query count grew with row count ({few} -> {many}): N+1"
    assert many <= 4, f"expected a handful of queries for 15 classes, got {many}"


# ---------------------------------------------------------------------------
# Derived status
# ---------------------------------------------------------------------------

def test_class_in_active_year_is_active(ctx, populated):
    statuses = {c["status"] for c in class_services.get_all_classes()["items"]}

    assert statuses == {"active"}


def test_class_in_inactive_year_is_archived(
    ctx, db_session, tenant, unit, programme, grades, past_year, populated
):
    nursery, _ = grades
    old = _make_class(
        db_session, tenant, section="Z", unit=unit, programme=programme,
        grade=nursery, year=past_year,
    )

    row = next(
        c for c in class_services.get_all_classes()["items"] if c["id"] == old.id
    )
    assert row["status"] == "archived"


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def test_search_matches_grade_name(ctx, populated):
    result = class_services.get_all_classes(search="Nursery", search_field="grade")

    assert result["total"] == 1
    assert result["items"][0]["grade_name"] == "Nursery"


def test_search_is_case_insensitive(ctx, populated):
    result = class_services.get_all_classes(search="nursery", search_field="grade")

    assert result["total"] == 1


def test_search_all_spans_grade_and_branch(ctx, populated):
    assert class_services.get_all_classes(search="Main Campus")["total"] == 3
    assert class_services.get_all_classes(search="Nursery")["total"] == 1


def test_search_with_no_match_returns_empty_envelope(ctx, populated):
    result = class_services.get_all_classes(search="zzz-nothing")

    assert result["total"] == 0
    assert result["items"] == []


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------

def test_default_sort_uses_grade_sequence_not_alphabetical(ctx, populated):
    names = [c["grade_name"] for c in class_services.get_all_classes()["items"]]

    # Nursery (sequence 1) precedes Grade 1 (sequence 2) despite sorting after
    # it alphabetically.
    assert names[0] == "Nursery"


def test_sort_by_student_count_descending(ctx, populated):
    items = class_services.get_all_classes(
        sort_by="student_count", sort_dir="desc"
    )["items"]

    assert [c["student_count"] for c in items] == [3, 1, 0]


def test_sort_direction_reverses_order(ctx, populated):
    ascending = class_services.get_all_classes(
        sort_by="student_count", sort_dir="asc"
    )["items"]

    assert [c["student_count"] for c in ascending] == [0, 1, 3]


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------

def test_grade_filter_narrows_the_list(ctx, grades, populated):
    _, grade_one = grades
    result = class_services.get_all_classes(grade_id=grade_one.id)

    assert result["total"] == 2


def test_programme_filter_narrows_the_list(ctx, programme, populated):
    assert class_services.get_all_classes(programme_id=programme.id)["total"] == 3


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def test_stats_totals_cover_every_matching_class(ctx, populated):
    stats = class_services.get_classes_stats()

    assert stats["total_classes"] == 3
    assert stats["total_students"] == 4


def test_stats_average_class_size_is_students_over_classes(ctx, populated):
    stats = class_services.get_classes_stats()

    assert stats["average_class_size"] == pytest.approx(4 / 3, abs=0.05)


def test_stats_respects_the_same_filters_as_the_list(ctx, grades, populated):
    nursery, _ = grades
    stats = class_services.get_classes_stats(grade_id=nursery.id)

    assert stats["total_classes"] == 1
    assert stats["total_students"] == 3


def test_stats_counts_a_teacher_once_across_several_classes(
    ctx, db_session, tenant, populated
):
    from modules.teachers.models import Teacher

    nursery_a, grade_one_a, _ = populated
    teacher_user = User(
        id=_new_id("u-"), tenant_id=tenant.id,
        email=f"t-{uuid.uuid4().hex[:6]}@test.school",
        password_hash="x" * 60, name="Shared Teacher",
    )
    db_session.add(teacher_user)
    db_session.flush()
    teacher = Teacher(
        id=_new_id("t-"), tenant_id=tenant.id, user_id=teacher_user.id,
        staff_id=employ_for(teacher_user, employee_number=f"EMP-{uuid.uuid4().hex[:6]}").id,
    )
    db_session.add(teacher)
    db_session.flush()
    for cls in (nursery_a, grade_one_a):
        _make_subject_teacher(db_session, tenant, cls, teacher)

    assert class_services.get_classes_stats()["total_teachers"] == 1


def test_stats_returns_zeroes_when_nothing_matches(ctx, populated):
    stats = class_services.get_classes_stats(grade_id=_new_id("g-"))

    assert stats == {
        "total_classes": 0,
        "total_students": 0,
        "total_teachers": 0,
        "average_class_size": 0.0,
    }
