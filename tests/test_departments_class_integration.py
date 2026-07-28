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
        subdomain=f"other-{uuid.uuid4().hex[:6]}",
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
