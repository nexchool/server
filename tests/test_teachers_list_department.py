"""list_teachers department filter/search/sort/facet — rewritten in migration
077 to join through Teacher.department_id/Department instead of the dropped
free-text department column.

Covers the behaviour the reviewer flagged as changed-but-untested: the
outerjoin must keep teachers with no department in the results (filter/sort
unaffected), the facet must list distinct department names (inner join, no
duplicates), and pagination's `total` must not be inflated by the join
(a teacher has at most one department via the FK, so no fanout is expected —
this test pins that down so a future join change that breaks it is caught
here rather than silently in production).
"""
from __future__ import annotations

import uuid

import pytest
from flask import g

from modules.auth.models import User
from modules.departments.models import Department
from modules.teachers import services as teacher_services
from modules.teachers.models import Teacher
from tests.conftest import employ_for


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def departments(db_session, tenant):
    maths = Department(id=_new_id("d-"), tenant_id=tenant.id, name="Maths")
    science = Department(id=_new_id("d-"), tenant_id=tenant.id, name="Science")
    db_session.add_all([maths, science])
    db_session.flush()
    return {"maths": maths, "science": science}


def _make_teacher(db_session, tenant, name, *, department_id=None):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=_new_id("u-"), tenant_id=tenant.id,
        email=f"t-{suffix}@test.school", password_hash="x" * 60, name=name,
    )
    db_session.add(user)
    db_session.flush()
    teacher = Teacher(
        id=_new_id("t-"), tenant_id=tenant.id, user_id=user.id,
        staff_id=employ_for(user).id,
        employee_id=f"EMP-{suffix}", department_id=department_id,
    )
    db_session.add(teacher)
    db_session.flush()
    return teacher


@pytest.fixture
def teachers(db_session, tenant, departments):
    """Alice (Maths), Bob (Science), Carol (no department)."""
    alice = _make_teacher(db_session, tenant, "Alice", department_id=departments["maths"].id)
    bob = _make_teacher(db_session, tenant, "Bob", department_id=departments["science"].id)
    carol = _make_teacher(db_session, tenant, "Carol", department_id=None)
    return {"alice": alice, "bob": bob, "carol": carol}


@pytest.fixture
def ctx(flask_app, tenant):
    """Request context with tenant bound — list_teachers relies on the
    automatic tenant-scoping query listener keyed off g.tenant_id."""
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


def _names(result):
    return {t["name"] for t in result["items"]}


# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------

def test_department_filter_matches_by_exact_department_id(ctx, teachers, departments):
    result = teacher_services.list_teachers(department_id=departments["maths"].id)

    assert _names(result) == {"Alice"}


def test_department_filter_matches_only_the_exact_id_not_a_name_substring(
    ctx, db_session, tenant, departments, teachers
):
    """The filter changed from a name substring match to an exact
    department_id match (Task 5). A teacher in a differently-named
    department whose name happens to contain the target department's name as
    a substring (e.g. "Advanced Maths" contains "Maths") must not leak in —
    the old `Department.name.ilike(f"%{department}%")` filter would have
    matched it."""
    advanced_maths = Department(id=_new_id("d-"), tenant_id=tenant.id, name="Advanced Maths")
    db_session.add(advanced_maths)
    db_session.flush()
    _make_teacher(db_session, tenant, "Eve", department_id=advanced_maths.id)

    result = teacher_services.list_teachers(department_id=departments["maths"].id)

    assert _names(result) == {"Alice"}


def test_department_filter_excludes_teachers_with_no_department(ctx, teachers, departments):
    result = teacher_services.list_teachers(department_id=departments["maths"].id)

    assert "Carol" not in _names(result)


def test_no_department_filter_still_returns_teachers_with_no_department(ctx, teachers):
    """The outerjoin must not drop undepartmented teachers when the filter
    isn't in play."""
    result = teacher_services.list_teachers()

    assert _names(result) == {"Alice", "Bob", "Carol"}


# ---------------------------------------------------------------------------
# Search ("all fields")
# ---------------------------------------------------------------------------

def test_search_all_matches_department_name(ctx, teachers):
    result = teacher_services.list_teachers(search="Science", search_field="all")

    assert _names(result) == {"Bob"}


def test_search_all_still_matches_other_fields_for_undepartmented_teachers(ctx, teachers):
    result = teacher_services.list_teachers(search="Carol", search_field="all")

    assert _names(result) == {"Carol"}


# ---------------------------------------------------------------------------
# Sort
# ---------------------------------------------------------------------------

def test_sort_by_department_orders_alphabetically_with_nulls_last(ctx, teachers):
    result = teacher_services.list_teachers(sort_by="department", sort_dir="asc")

    assert [t["name"] for t in result["items"]] == ["Alice", "Bob", "Carol"]


def test_sort_by_department_desc_still_puts_nulls_last(ctx, teachers):
    result = teacher_services.list_teachers(sort_by="department", sort_dir="desc")

    assert [t["name"] for t in result["items"]] == ["Bob", "Alice", "Carol"]


# ---------------------------------------------------------------------------
# Facet — Task 5: sourced from the department catalogue (as {id, name}
# objects, display-order then name), not distinct names off teacher rows.
# ---------------------------------------------------------------------------

def test_departments_facet_lists_the_catalogue_as_id_name_objects(ctx, teachers, departments):
    result = teacher_services.list_teachers()

    assert result["departments"] == [
        {"id": departments["maths"].id, "name": "Maths"},
        {"id": departments["science"].id, "name": "Science"},
    ]


def test_departments_facet_count_is_independent_of_teacher_assignment_count(
    ctx, db_session, tenant, departments, teachers
):
    """Facets are catalogue-sourced now (list_active_departments), not a
    distinct-teacher join, so a department shared by several teachers still
    appears exactly once — no join fanout is even possible here."""
    _make_teacher(db_session, tenant, "Dan", department_id=departments["maths"].id)

    result = teacher_services.list_teachers()

    assert result["departments"] == [
        {"id": departments["maths"].id, "name": "Maths"},
        {"id": departments["science"].id, "name": "Science"},
    ]


def test_departments_facet_excludes_inactive_departments(
    ctx, db_session, tenant, departments, teachers
):
    """Facets list only active departments (list_active_departments) — an
    inactive department (hidden from new assignments) must not appear in the
    filter dropdown, even though it still has a name like any other row."""
    from modules.departments.models import DEPARTMENT_STATUS_INACTIVE

    archived = Department(
        id=_new_id("d-"),
        tenant_id=tenant.id,
        name="Archived Dept",
        status=DEPARTMENT_STATUS_INACTIVE,
    )
    db_session.add(archived)
    db_session.flush()

    result = teacher_services.list_teachers()

    assert "Archived Dept" not in [d["name"] for d in result["departments"]]


# ---------------------------------------------------------------------------
# Pagination — join-cardinality regression
# ---------------------------------------------------------------------------

def test_pagination_total_is_not_inflated_by_the_department_join(ctx, teachers):
    """department_id is a many-to-one FK, so the outerjoin must not multiply
    rows. Guards against a future join change (e.g. a many-to-many) silently
    breaking `total`/`count()` for pagination."""
    first_page = teacher_services.list_teachers(page=1, per_page=2)

    assert first_page["total"] == 3
    assert len(first_page["items"]) == 2

    second_page = teacher_services.list_teachers(page=2, per_page=2)
    assert len(second_page["items"]) == 1
