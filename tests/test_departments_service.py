"""Department service — CRUD, listing, delete guard, tenant isolation."""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from tests.conftest import employ_for

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


@pytest.fixture
def svc():
    from modules.departments import services

    return services


def test_create_returns_the_department(db_session, tenant, svc):
    result = svc.create_department({"name": "Primary"}, tenant.id)

    assert result["success"] is True
    assert result["department"]["name"] == "Primary"
    assert result["department"]["type"] == "academic_division"
    assert result["department"]["status"] == "active"


def test_create_rejects_a_blank_name(db_session, tenant, svc):
    result = svc.create_department({"name": "   "}, tenant.id)

    assert result["success"] is False
    assert "name is required" in result["error"]


def test_create_rejects_a_duplicate_name_ignoring_case(db_session, tenant, svc):
    svc.create_department({"name": "Science"}, tenant.id)
    result = svc.create_department({"name": "  science "}, tenant.id)

    assert result["success"] is False
    assert "already exists" in result["error"]


def test_create_rejects_a_duplicate_code_ignoring_case(db_session, tenant, svc):
    svc.create_department({"name": "Science", "code": "SCI"}, tenant.id)
    result = svc.create_department({"name": "Commerce", "code": "sci"}, tenant.id)

    assert result["success"] is False
    assert "already exists" in result["error"]


def test_create_ignores_a_client_supplied_type(db_session, tenant, svc):
    result = svc.create_department(
        {"name": "Accounts", "type": "administrative"}, tenant.id
    )

    assert result["department"]["type"] == "academic_division"


def test_update_changes_the_editable_fields(db_session, tenant, svc):
    created = svc.create_department({"name": "Primary"}, tenant.id)["department"]

    result = svc.update_department(
        created["id"],
        {
            "name": "Primary Wing",
            "code": "PRI",
            "description": "Grades 1-5",
            "display_order": 3,
            "status": "inactive",
        },
        tenant.id,
    )

    assert result["success"] is True
    dept = result["department"]
    assert dept["name"] == "Primary Wing"
    assert dept["code"] == "PRI"
    assert dept["description"] == "Grades 1-5"
    assert dept["display_order"] == 3
    assert dept["status"] == "inactive"


def test_update_rejects_an_unknown_status(db_session, tenant, svc):
    created = svc.create_department({"name": "Primary"}, tenant.id)["department"]

    result = svc.update_department(created["id"], {"status": "archived"}, tenant.id)

    assert result["success"] is False
    assert "status must be one of" in result["error"]


def test_update_allows_a_department_to_keep_its_own_name(db_session, tenant, svc):
    created = svc.create_department({"name": "Primary"}, tenant.id)["department"]

    result = svc.update_department(
        created["id"], {"name": "Primary", "display_order": 2}, tenant.id
    )

    assert result["success"] is True


def test_get_returns_none_for_another_tenants_department(db_session, tenant, svc):
    created = svc.create_department({"name": "Primary"}, tenant.id)["department"]

    assert svc.get_department(created["id"], "some-other-tenant") is None


def test_list_sorts_by_display_order_then_name(db_session, tenant, svc):
    svc.create_department({"name": "Zoology", "display_order": 1}, tenant.id)
    svc.create_department({"name": "Arts", "display_order": 2}, tenant.id)
    svc.create_department({"name": "Botany", "display_order": 1}, tenant.id)

    items = svc.list_departments({}, tenant.id)["items"]

    assert [d["name"] for d in items] == ["Botany", "Zoology", "Arts"]


def test_list_filters_by_status(db_session, tenant, svc):
    svc.create_department({"name": "Primary"}, tenant.id)
    inactive = svc.create_department({"name": "Montessori"}, tenant.id)["department"]
    svc.update_department(inactive["id"], {"status": "inactive"}, tenant.id)

    items = svc.list_departments({"status": "active"}, tenant.id)["items"]

    assert [d["name"] for d in items] == ["Primary"]


def test_list_searches_name_and_code(db_session, tenant, svc):
    svc.create_department({"name": "Higher Secondary", "code": "HS"}, tenant.id)
    svc.create_department({"name": "Primary", "code": "PRI"}, tenant.id)

    by_name = svc.list_departments({"search": "second"}, tenant.id)["items"]
    by_code = svc.list_departments({"search": "pri"}, tenant.id)["items"]

    assert [d["name"] for d in by_name] == ["Higher Secondary"]
    assert [d["name"] for d in by_code] == ["Primary"]


def test_list_paginates(db_session, tenant, svc):
    for i in range(5):
        svc.create_department({"name": f"Dept {i}", "display_order": i}, tenant.id)

    result = svc.list_departments({"page": 2, "per_page": 2}, tenant.id)

    assert result["total"] == 5
    assert result["page"] == 2
    assert result["per_page"] == 2
    assert result["total_pages"] == 3
    assert len(result["items"]) == 2


def test_list_caps_per_page_at_100(db_session, tenant, svc):
    svc.create_department({"name": "Primary"}, tenant.id)

    result = svc.list_departments({"per_page": 5000}, tenant.id)

    assert result["per_page"] == 100


def test_list_excludes_soft_deleted(db_session, tenant, svc):
    created = svc.create_department({"name": "Primary"}, tenant.id)["department"]
    svc.delete_department(created["id"], tenant.id)

    assert svc.list_departments({}, tenant.id)["items"] == []


def test_list_excludes_other_tenants(db_session, tenant, svc):
    from core.models import Tenant, TENANT_STATUS_ACTIVE, BILLING_CYCLE_YEARLY

    other = Tenant(
        id=str(uuid.uuid4()),
        name="Other School",
        subdomain=f"other-{uuid.uuid4().hex}",
        status=TENANT_STATUS_ACTIVE,
        billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(other)
    db_session.flush()

    svc.create_department({"name": "Mine"}, tenant.id)
    svc.create_department({"name": "Theirs"}, other.id)

    assert [d["name"] for d in svc.list_departments({}, tenant.id)["items"]] == ["Mine"]


def test_delete_soft_deletes_an_unreferenced_department(db_session, tenant, svc):
    created = svc.create_department({"name": "Primary"}, tenant.id)["department"]

    result = svc.delete_department(created["id"], tenant.id)

    assert result["success"] is True
    assert svc.get_department(created["id"], tenant.id) is None


def test_delete_returns_not_found_for_another_tenant(db_session, tenant, svc):
    created = svc.create_department({"name": "Primary"}, tenant.id)["department"]

    result = svc.delete_department(created["id"], "some-other-tenant")

    assert result["success"] is False


def test_stats_counts_total_and_active(db_session, tenant, svc):
    svc.create_department({"name": "Primary"}, tenant.id)
    inactive = svc.create_department({"name": "Montessori"}, tenant.id)["department"]
    svc.update_department(inactive["id"], {"status": "inactive"}, tenant.id)

    stats = svc.get_department_stats(tenant.id)

    assert stats["total"] == 2
    assert stats["active"] == 1
    assert stats["teachers_assigned"] == 0
    assert stats["classes_assigned"] == 0


def _make_teacher(db_session, tenant, department_id, suffix, status="active"):
    """Minimal teacher row. Teacher.user_id is NOT NULL, so a user comes first.

    NOTE: the actual User model lives at modules.auth.models.User (not
    core.models.User, which has no such class) and requires a non-null
    password_hash — see tests/test_classes_list_and_stats.py for the
    existing pattern this mirrors.
    """
    from modules.auth.models import User
    from modules.teachers.models import Teacher

    user = User(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        name=f"Teacher {suffix}",
        email=f"teacher-{suffix}-{uuid.uuid4().hex[:6]}@example.test",
        password_hash="x" * 60,
    )
    db_session.add(user)
    db_session.flush()

    teacher = Teacher(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        user_id=user.id,
        staff_id=employ_for(user).id,
        employee_id=f"EMP{suffix}",
        department_id=department_id,
        status=status,
    )
    db_session.add(teacher)
    db_session.flush()
    return teacher


def _make_academic_year(db_session, tenant, suffix):
    from modules.academics.academic_year.models import AcademicYear

    year = AcademicYear(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        name=f"AY-{suffix}",
        start_date="2026-06-01",
        end_date="2027-03-31",
        is_active=True,
    )
    db_session.add(year)
    db_session.flush()
    return year


def _make_class(db_session, tenant, department_id, suffix):
    """Minimal class row. Class.academic_year_id and .section are NOT NULL;
    school_unit_id/programme_id/grade_id stay unset (nullable) — construction
    pattern copied from tests/test_classes_list_and_stats.py's _make_class."""
    from modules.classes.models import Class

    year = _make_academic_year(db_session, tenant, suffix)
    cls = Class(
        id=str(uuid.uuid4()),
        tenant_id=tenant.id,
        section=f"S{suffix}",
        academic_year_id=year.id,
        department_id=department_id,
    )
    db_session.add(cls)
    db_session.flush()
    return cls


def test_list_reports_the_teacher_count(db_session, tenant, svc):
    dept = svc.create_department({"name": "Science"}, tenant.id)["department"]
    _make_teacher(db_session, tenant, dept["id"], "1")
    _make_teacher(db_session, tenant, dept["id"], "2")

    items = svc.list_departments({}, tenant.id)["items"]

    assert items[0]["teacher_count"] == 2


def test_teacher_count_excludes_other_tenants(db_session, tenant, svc):
    """The count subquery must carry its own tenant_id predicate —
    with_loader_criteria does not reach column-level subqueries."""
    from core.models import Tenant, TENANT_STATUS_ACTIVE, BILLING_CYCLE_YEARLY

    other = Tenant(
        id=str(uuid.uuid4()),
        name="Other School",
        subdomain=f"other-{uuid.uuid4().hex}",
        status=TENANT_STATUS_ACTIVE,
        billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(other)
    db_session.flush()

    dept = svc.create_department({"name": "Science"}, tenant.id)["department"]
    _make_teacher(db_session, tenant, dept["id"], "mine")
    _make_teacher(db_session, other, dept["id"], "theirs")

    items = svc.list_departments({}, tenant.id)["items"]

    assert items[0]["teacher_count"] == 1


def test_delete_is_blocked_while_teachers_are_assigned(db_session, tenant, svc):
    dept = svc.create_department({"name": "Science"}, tenant.id)["department"]
    _make_teacher(db_session, tenant, dept["id"], "1")

    result = svc.delete_department(dept["id"], tenant.id)

    assert result["success"] is False
    assert result["in_use"] == {"teachers": 1, "classes": 0}
    assert "1 teachers" in result["error"]
    # Zero-count references are omitted from the message entirely.
    assert "classes" not in result["error"]


def test_stats_counts_assigned_teachers(db_session, tenant, svc):
    dept = svc.create_department({"name": "Science"}, tenant.id)["department"]
    _make_teacher(db_session, tenant, dept["id"], "1")

    assert svc.get_department_stats(tenant.id)["teachers_assigned"] == 1


# ---------------------------------------------------------------------------
# Review fixes (round 1): rejected update must not leave a dirty rename;
# update must return real counts; duplicate-vs-other IntegrityError
# discrimination; class-count coverage; update-path uniqueness collisions;
# active-teachers-only scope change.
# ---------------------------------------------------------------------------


def test_update_rejects_invalid_status_without_leaving_a_dirty_rename(
    db_session, tenant, svc
):
    """Pins the autoflush bug: a rejected update must not leave the rejected
    rename sitting in the session ready to be committed by a later call."""
    created = svc.create_department({"name": "Primary"}, tenant.id)["department"]

    result = svc.update_department(
        created["id"], {"name": "Renamed", "status": "archived"}, tenant.id
    )

    assert result["success"] is False

    # Simulate the next thing to touch the session — if the rename were
    # still dirty, this unrelated commit would persist it.
    db_session.commit()

    dept = svc.get_department(created["id"], tenant.id)
    assert dept["name"] == "Primary"


def test_update_returns_the_current_teacher_and_class_count(db_session, tenant, svc):
    dept = svc.create_department({"name": "Science"}, tenant.id)["department"]
    _make_teacher(db_session, tenant, dept["id"], "1")
    _make_class(db_session, tenant, dept["id"], "1")

    result = svc.update_department(dept["id"], {"display_order": 5}, tenant.id)

    assert result["success"] is True
    assert result["department"]["teacher_count"] == 1
    assert result["department"]["class_count"] == 1


def test_create_returns_a_generic_error_for_a_non_duplicate_integrity_violation(
    db_session, tenant, svc
):
    """created_by is a real FK to users.id. A user id that does not exist
    triggers a foreign-key violation (pgcode 23503), not a unique violation
    (23505) — it must not be reported as a duplicate name/code."""
    result = svc.create_department(
        {"name": "Ops"}, tenant.id, user_id="does-not-exist"
    )

    assert result["success"] is False
    assert "already exists" not in result["error"]


def test_update_rejects_renaming_to_another_departments_name(db_session, tenant, svc):
    svc.create_department({"name": "Science"}, tenant.id)
    other = svc.create_department({"name": "Commerce"}, tenant.id)["department"]

    result = svc.update_department(other["id"], {"name": "Science"}, tenant.id)

    assert result["success"] is False
    assert "already exists" in result["error"]


def test_update_rejects_renaming_to_another_departments_name_ignoring_case(
    db_session, tenant, svc
):
    svc.create_department({"name": "Science"}, tenant.id)
    other = svc.create_department({"name": "Commerce"}, tenant.id)["department"]

    result = svc.update_department(other["id"], {"name": "  SCIENCE "}, tenant.id)

    assert result["success"] is False
    assert "already exists" in result["error"]


def test_update_rejects_a_code_collision_with_another_department(
    db_session, tenant, svc
):
    svc.create_department({"name": "Science", "code": "SCI"}, tenant.id)
    other = svc.create_department(
        {"name": "Commerce", "code": "COM"}, tenant.id
    )["department"]

    result = svc.update_department(other["id"], {"code": "sci"}, tenant.id)

    assert result["success"] is False
    assert "already exists" in result["error"]


def test_list_reports_the_class_count(db_session, tenant, svc):
    dept = svc.create_department({"name": "Science"}, tenant.id)["department"]
    _make_class(db_session, tenant, dept["id"], "1")
    _make_class(db_session, tenant, dept["id"], "2")

    items = svc.list_departments({}, tenant.id)["items"]

    assert items[0]["class_count"] == 2


def test_class_count_excludes_other_tenants(db_session, tenant, svc):
    """Mirrors test_teacher_count_excludes_other_tenants: the other tenant's
    class points at *this* tenant's department, so an unscoped subquery
    would return 2 and fail this assertion."""
    from core.models import Tenant, TENANT_STATUS_ACTIVE, BILLING_CYCLE_YEARLY

    other = Tenant(
        id=str(uuid.uuid4()),
        name="Other School",
        subdomain=f"other-{uuid.uuid4().hex}",
        status=TENANT_STATUS_ACTIVE,
        billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(other)
    db_session.flush()

    dept = svc.create_department({"name": "Science"}, tenant.id)["department"]
    _make_class(db_session, tenant, dept["id"], "mine")
    _make_class(db_session, other, dept["id"], "theirs")

    items = svc.list_departments({}, tenant.id)["items"]

    assert items[0]["class_count"] == 1


def test_delete_is_blocked_while_classes_are_assigned(db_session, tenant, svc):
    dept = svc.create_department({"name": "Science"}, tenant.id)["department"]
    _make_class(db_session, tenant, dept["id"], "1")

    result = svc.delete_department(dept["id"], tenant.id)

    assert result["success"] is False
    assert result["in_use"] == {"teachers": 0, "classes": 1}
    assert "1 classes" in result["error"]
    assert "teachers" not in result["error"]


def test_teacher_count_excludes_inactive_teachers(db_session, tenant, svc):
    dept = svc.create_department({"name": "Science"}, tenant.id)["department"]
    _make_teacher(db_session, tenant, dept["id"], "1", status="active")
    _make_teacher(db_session, tenant, dept["id"], "2", status="inactive")

    items = svc.list_departments({}, tenant.id)["items"]

    assert items[0]["teacher_count"] == 1


def test_stats_counts_only_active_teachers(db_session, tenant, svc):
    dept = svc.create_department({"name": "Science"}, tenant.id)["department"]
    _make_teacher(db_session, tenant, dept["id"], "1", status="active")
    _make_teacher(db_session, tenant, dept["id"], "2", status="inactive")

    assert svc.get_department_stats(tenant.id)["teachers_assigned"] == 1


def test_delete_allowed_when_only_teacher_is_inactive(db_session, tenant, svc):
    dept = svc.create_department({"name": "Science"}, tenant.id)["department"]
    _make_teacher(db_session, tenant, dept["id"], "1", status="inactive")

    result = svc.delete_department(dept["id"], tenant.id)

    assert result["success"] is True


def test_delete_clears_department_id_on_inactive_teachers(db_session, tenant, svc):
    """The inactive teacher is excluded from `_counts_for` so the delete guard
    passes, but the deletion is soft (deleted_at) — ON DELETE RESTRICT never
    fires, so the FK must be cleared explicitly or the teacher is left
    pointing at a department no listing shows."""
    dept = svc.create_department({"name": "Science"}, tenant.id)["department"]
    teacher = _make_teacher(db_session, tenant, dept["id"], "1", status="inactive")

    result = svc.delete_department(dept["id"], tenant.id)

    assert result["success"] is True
    db_session.refresh(teacher)
    assert teacher.department_id is None
