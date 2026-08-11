"""Classes carry a department reference and can be filtered by it.

Covers the class-side half of the departments catalogue (Task 7): the
`Class.to_dict()` serializer fields added in Task 2 (regression guard here,
not new behaviour — see the report), the new `department_id` filter on
`get_all_classes`, and cross-tenant rejection on create/update mirroring
`modules.teachers.services._resolve_department`.

Pattern mirrors `tests/test_classes_list_and_stats.py`: push `g.tenant_id`
through `flask_app.test_request_context` for any call that reaches
`get_tenant_id()` (`get_all_classes`, `create_class`, `update_class`). The
department service functions take `tenant_id` explicitly and don't need it.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from flask import g

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from modules.classes.models import Class


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def dept_svc():
    from modules.departments import services

    return services


@pytest.fixture
def academic_year(db_session, tenant):
    from modules.academics.academic_year.models import AcademicYear

    ay = AcademicYear(
        id=_new_id("ay-"), tenant_id=tenant.id, name="2026-2027",
        start_date="2026-06-01", end_date="2027-03-31", is_active=True,
    )
    db_session.add(ay)
    db_session.flush()
    return ay


@pytest.fixture
def make_class(db_session, tenant, academic_year):
    """Build a persisted Class with the columns the model requires.

    Constructed per `tests/test_branch_enforce_class_config.py:82-96`, minus
    the unused `school_unit_id` — the identity-uniqueness constraint only
    bites when school_unit/programme/grade all repeat, and this file never
    needs two classes with the same section.
    """

    def _make(*, department_id=None, section="A"):
        cls = Class(
            id=_new_id("c-"),
            tenant_id=tenant.id,
            name="Grade 1",
            section=section,
            academic_year_id=academic_year.id,
            department_id=department_id,
        )
        db_session.add(cls)
        db_session.flush()
        return cls

    return _make


@pytest.fixture
def ctx(flask_app, tenant):
    """Request context binding g.tenant_id — required by get_tenant_id()."""
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


@pytest.fixture
def other_tenant(db_session):
    """A second tenant, for cross-tenant department_id rejection tests."""
    from core.models import BILLING_CYCLE_YEARLY, TENANT_STATUS_ACTIVE, Tenant

    t = Tenant(
        id=_new_id("t-"),
        name="Other School",
        subdomain=f"other-{uuid.uuid4().hex}",
        status=TENANT_STATUS_ACTIVE,
        billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(t)
    db_session.flush()
    return t


def test_class_serializer_includes_the_department(db_session, tenant, dept_svc, make_class):
    dept = dept_svc.create_department({"name": "Higher Secondary"}, tenant.id)["department"]
    klass = make_class(department_id=dept["id"])

    payload = klass.to_dict()

    assert payload["department_id"] == dept["id"]
    assert payload["department_name"] == "Higher Secondary"


def test_class_serializer_handles_no_department(db_session, tenant, make_class):
    payload = make_class(department_id=None).to_dict()

    assert payload["department_id"] is None
    assert payload["department_name"] is None


def test_class_list_filters_by_department(ctx, db_session, tenant, dept_svc, make_class):
    from modules.classes import services

    hs = dept_svc.create_department({"name": "Higher Secondary"}, tenant.id)["department"]
    primary = dept_svc.create_department({"name": "Primary"}, tenant.id)["department"]
    make_class(department_id=hs["id"], section="A")
    make_class(department_id=primary["id"], section="B")

    result = services.get_all_classes(department_id=hs["id"])

    assert [c["section"] for c in result["items"]] == ["A"]


def test_stats_filters_by_department(ctx, db_session, tenant, dept_svc, make_class):
    """get_classes_stats must honour department_id the same way the list
    endpoint does — otherwise the header cards (total classes/students/
    teachers) describe the whole tenant while the table beneath them shows
    only the department-filtered rows."""
    from modules.classes import services

    hs = dept_svc.create_department({"name": "Higher Secondary"}, tenant.id)["department"]
    primary = dept_svc.create_department({"name": "Primary"}, tenant.id)["department"]
    make_class(department_id=hs["id"], section="A")
    make_class(department_id=primary["id"], section="B")
    make_class(department_id=primary["id"], section="C")

    stats = services.get_classes_stats(department_id=hs["id"])

    assert stats["total_classes"] == 1


def test_class_list_does_not_n_plus_one_on_department(
    flask_app, db_session, tenant, dept_svc, make_class
):
    """department_ref must be in the same eager-load block as the other
    to_dict() relationships — otherwise every row with a department set fires
    its own `SELECT ... FROM departments`, and the query count grows with the
    row count instead of staying flat."""
    from sqlalchemy import event
    from modules.classes import services

    from core.database import db

    dept = dept_svc.create_department({"name": "Higher Secondary"}, tenant.id)["department"]
    made = 0

    def count_statements(additional_classes):
        nonlocal made
        for i in range(additional_classes):
            make_class(department_id=dept["id"], section=f"S{made + i}")
        made += additional_classes

        statements = []

        def record(conn, cursor, statement, params, context, executemany):
            statements.append(statement)

        with flask_app.test_request_context("/"):
            g.tenant_id = tenant.id
            event.listen(db.engine, "before_cursor_execute", record)
            try:
                result = services.get_all_classes()
                assert len(result["items"]) == made
                assert all(c["department_name"] == "Higher Secondary" for c in result["items"])
            finally:
                event.remove(db.engine, "before_cursor_execute", record)
        return len(statements)

    few = count_statements(2)
    many = count_statements(6)

    assert many <= few, f"query count grew with row count ({few} -> {many}): N+1"


def test_department_delete_is_blocked_while_classes_are_assigned(
    db_session, tenant, dept_svc, make_class
):
    dept = dept_svc.create_department({"name": "Higher Secondary"}, tenant.id)["department"]
    make_class(department_id=dept["id"])

    result = dept_svc.delete_department(dept["id"], tenant.id)

    assert result["success"] is False
    assert result["in_use"] == {"teachers": 0, "classes": 1}
    assert "1 classes" in result["error"]


def test_create_class_rejects_department_from_another_tenant(
    ctx, db_session, tenant, academic_year, dept_svc, other_tenant
):
    """The FK has no tenant component; Postgres alone would accept a foreign
    tenant's department id, so the service must reject it explicitly."""
    from modules.classes import services

    foreign_dept = dept_svc.create_department({"name": "Foreign"}, other_tenant.id)["department"]

    result = services.create_class(
        name="Grade 2",
        section="Z",
        academic_year_id=academic_year.id,
        department_id=foreign_dept["id"],
    )

    assert result["success"] is False
    assert result["error"] == "Department not found"


def test_update_class_rejects_department_from_another_tenant(
    ctx, db_session, tenant, make_class, dept_svc, other_tenant
):
    from modules.classes import services

    klass = make_class()
    foreign_dept = dept_svc.create_department({"name": "Foreign"}, other_tenant.id)["department"]

    result = services.update_class(klass.id, department_id=foreign_dept["id"])

    assert result["success"] is False
    assert result["error"] == "Department not found"


# ---------------------------------------------------------------------------
# Positive path: department_id actually persists through the service (not
# just rejected on cross-tenant input, and not bypassed via direct model
# construction like `make_class` does for the other tests above).
# ---------------------------------------------------------------------------

def test_create_class_persists_the_department_id(
    ctx, db_session, tenant, academic_year, dept_svc
):
    from modules.classes import services

    dept = dept_svc.create_department({"name": "Higher Secondary"}, tenant.id)["department"]

    result = services.create_class(
        name="Grade 2",
        section="Z",
        academic_year_id=academic_year.id,
        department_id=dept["id"],
    )

    assert result["success"] is True
    assert result["class"]["department_id"] == dept["id"]


def test_update_class_assigns_a_department(ctx, db_session, tenant, make_class, dept_svc):
    from modules.classes import services

    klass = make_class(department_id=None)
    dept = dept_svc.create_department({"name": "Higher Secondary"}, tenant.id)["department"]

    result = services.update_class(klass.id, department_id=dept["id"])

    assert result["success"] is True
    assert result["class"]["department_id"] == dept["id"]


# ---------------------------------------------------------------------------
# Three-state update semantics — mirrors modules.teachers.services
# .update_teacher's NOT_PROVIDED handling for the identical problem: key
# omitted, key explicitly null, and key set to a value must all behave
# differently. `update_class` reuses this module's existing `_MISSING`
# sentinel (already used for `grade_level`) rather than introducing a
# second sentinel with the same meaning.
# ---------------------------------------------------------------------------

def test_update_class_leaves_department_unchanged_when_field_omitted(
    ctx, db_session, tenant, make_class, dept_svc
):
    from modules.classes import services

    dept = dept_svc.create_department({"name": "Higher Secondary"}, tenant.id)["department"]
    klass = make_class(department_id=dept["id"])

    result = services.update_class(klass.id, name="Renamed")

    assert result["success"] is True
    assert result["class"]["department_id"] == dept["id"]


def test_update_class_clears_department_when_explicitly_null(
    ctx, db_session, tenant, make_class, dept_svc
):
    from modules.classes import services

    dept = dept_svc.create_department({"name": "Higher Secondary"}, tenant.id)["department"]
    klass = make_class(department_id=dept["id"])

    result = services.update_class(klass.id, department_id=None)

    assert result["success"] is True
    assert result["class"]["department_id"] is None


# ---------------------------------------------------------------------------
# Inactive departments cannot be newly assigned, matching the teacher side and
# the UI picker. Retention of an already-assigned inactive division stays legal.
# ---------------------------------------------------------------------------


def test_create_class_rejects_an_inactive_department(ctx, db_session, tenant, dept_svc, academic_year):
    from modules.classes import services

    dept = dept_svc.create_department({"name": "Montessori"}, tenant.id)["department"]
    dept_svc.update_department(dept["id"], {"status": "inactive"}, tenant.id)

    result = services.create_class(
        name="Grade 1",
        section="Z",
        academic_year_id=academic_year.id,
        department_id=dept["id"],
    )

    assert result["success"] is False
    assert "inactive" in result["error"]
    assert "Montessori" in result["error"]


def test_update_class_rejects_reassigning_to_an_inactive_department(
    ctx, db_session, tenant, dept_svc, make_class
):
    from modules.classes import services

    primary = dept_svc.create_department({"name": "Primary"}, tenant.id)["department"]
    archived = dept_svc.create_department({"name": "Junior Wing"}, tenant.id)["department"]
    dept_svc.update_department(archived["id"], {"status": "inactive"}, tenant.id)
    klass = make_class(department_id=primary["id"], section="Y")

    result = services.update_class(klass.id, department_id=archived["id"])

    assert result["success"] is False
    assert "inactive" in result["error"]
    db_session.refresh(klass)
    assert klass.department_id == primary["id"], "existing data must not change"


def test_update_class_allows_keeping_an_already_assigned_inactive_department(
    ctx, db_session, tenant, dept_svc, make_class
):
    from modules.classes import services

    dept = dept_svc.create_department({"name": "Senior Wing"}, tenant.id)["department"]
    klass = make_class(department_id=dept["id"], section="X")
    dept_svc.update_department(dept["id"], {"status": "inactive"}, tenant.id)

    result = services.update_class(klass.id, department_id=dept["id"])

    assert result["success"] is True
    db_session.refresh(klass)
    assert klass.department_id == dept["id"]


def test_update_class_can_still_clear_an_inactive_department(
    ctx, db_session, tenant, dept_svc, make_class
):
    from modules.classes import services

    dept = dept_svc.create_department({"name": "Middle School"}, tenant.id)["department"]
    klass = make_class(department_id=dept["id"], section="W")
    dept_svc.update_department(dept["id"], {"status": "inactive"}, tenant.id)

    result = services.update_class(klass.id, department_id=None)

    assert result["success"] is True
    db_session.refresh(klass)
    assert klass.department_id is None
