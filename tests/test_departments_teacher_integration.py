"""Teacher list/create behaviour after the department FK migration.

Five corrections to the brief's illustrative Step 1 code, made while writing
this file (see task-5-report.md for detail):

1. The teacher list/filter/facet function is `modules.teachers.services.
   list_teachers`, not `get_teachers` — there is no `get_teachers` anywhere
   in the module.
2. `list_teachers` / `create_teacher` read the tenant from `g.tenant_id` via
   `core.tenant.get_tenant_id()`, so they need an active Flask request
   context with `g.tenant_id` set — `db_session`/`tenant` alone (as used by
   the department-service fixture) do not provide one. A `ctx` fixture below
   supplies it, mirroring the existing pattern in
   tests/test_teachers_list_department.py.
3. `create_teacher` has no `employee_id` parameter — it always
   auto-generates one (`generate_employee_id`) — so it is dropped from the
   create-teacher test calls.
4. `User` lives in `modules.auth.models`, not `core.models` — the brief's
   `_make_teacher` helper imported it from the wrong module.
5. `users.password_hash` is NOT NULL with no default; the brief's
   `_make_teacher` helper didn't set it, so every teacher created through it
   raised an IntegrityError before the test itself ran.
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


@pytest.fixture
def dept_svc():
    from modules.departments import services

    return services


@pytest.fixture
def ctx(flask_app, tenant):
    """Request context with tenant bound — list_teachers/create_teacher rely
    on the automatic tenant-scoping query listener keyed off g.tenant_id."""
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


def _other_tenant(db_session, suffix):
    """A second, distinct tenant — for asserting a department lookup/id check
    actually excludes another tenant's row, not just an unmatched one."""
    from core.models import Tenant, TENANT_STATUS_ACTIVE, BILLING_CYCLE_YEARLY

    other = Tenant(
        id=str(uuid.uuid4()),
        name=f"Other School {suffix}",
        subdomain=f"other-{suffix}-{uuid.uuid4().hex[:6]}",
        status=TENANT_STATUS_ACTIVE,
        billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(other)
    db_session.flush()
    return other


def _make_teacher(db_session, tenant, department_id, suffix):
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
        employee_id=f"EMP{suffix}",
        department_id=department_id,
    )
    db_session.add(teacher)
    db_session.flush()
    return teacher


def test_to_dict_still_emits_the_legacy_department_string(db_session, tenant, dept_svc):
    """The Expo client reads `department` as a plain string; it must survive."""
    dept = dept_svc.create_department({"name": "Science"}, tenant.id)["department"]
    teacher = _make_teacher(db_session, tenant, dept["id"], "1")

    payload = teacher.to_dict()

    assert payload["department"] == "Science"
    assert payload["department_id"] == dept["id"]


def test_to_dict_emits_null_department_when_unassigned(db_session, tenant):
    teacher = _make_teacher(db_session, tenant, None, "1")

    payload = teacher.to_dict()

    assert payload["department"] is None
    assert payload["department_id"] is None


def test_list_filters_by_department_id(ctx, db_session, tenant, dept_svc):
    from modules.teachers import services

    science = dept_svc.create_department({"name": "Science"}, tenant.id)["department"]
    arts = dept_svc.create_department({"name": "Arts"}, tenant.id)["department"]
    _make_teacher(db_session, tenant, science["id"], "sci")
    _make_teacher(db_session, tenant, arts["id"], "art")

    result = services.list_teachers(department_id=science["id"])

    assert [t["department"] for t in result["items"]] == ["Science"]


def test_list_facets_return_department_objects(ctx, db_session, tenant, dept_svc):
    from modules.teachers import services

    science = dept_svc.create_department({"name": "Science"}, tenant.id)["department"]
    arts = dept_svc.create_department(
        {"name": "Arts", "display_order": 1}, tenant.id
    )["department"]

    facets = services.list_teachers()["departments"]

    # Objects, not bare strings — and in display order, not alphabetical.
    assert facets == [
        {"id": science["id"], "name": "Science"},
        {"id": arts["id"], "name": "Arts"},
    ]


def test_facets_list_departments_with_no_teachers(ctx, db_session, tenant, dept_svc):
    """Facets come from the catalogue now, not from distinct teacher values, so
    a brand-new department appears in the filter before anyone is assigned."""
    from modules.teachers import services

    dept_svc.create_department({"name": "Montessori"}, tenant.id)

    assert [d["name"] for d in services.list_teachers()["departments"]] == ["Montessori"]


def test_create_accepts_a_legacy_department_name(ctx, tenant, dept_svc):
    """The mobile teacher form still posts a free-text name."""
    from modules.teachers import services

    dept = dept_svc.create_department({"name": "Science"}, tenant.id)["department"]

    result = services.create_teacher(
        name="New Teacher",
        email=f"new-{uuid.uuid4().hex[:6]}@example.test",
        department="science",
    )

    assert result["success"] is True
    assert result["teacher"]["department_id"] == dept["id"]


def test_create_rejects_an_unknown_department_name(ctx, tenant):
    """Auto-creating would reinstate the uncontrolled vocabulary this module ends."""
    from modules.teachers import services

    result = services.create_teacher(
        name="New Teacher",
        email=f"new-{uuid.uuid4().hex[:6]}@example.test",
        department="Nonexistent Department",
    )

    assert result["success"] is False
    assert "Nonexistent Department" in result["error"]


def test_create_rejects_a_department_id_from_another_tenant(ctx, tenant, db_session, dept_svc):
    """A department_id must belong to the caller's own tenant — the FK column
    itself doesn't scope by tenant, so this has to be checked in the service."""
    from modules.teachers import services

    other_tenant = _other_tenant(db_session, "a")
    foreign_dept = dept_svc.create_department({"name": "Foreign Dept"}, other_tenant.id)["department"]

    result = services.create_teacher(
        name="New Teacher",
        email=f"new-{uuid.uuid4().hex[:6]}@example.test",
        department_id=foreign_dept["id"],
    )

    assert result["success"] is False


def test_create_rejects_a_department_name_owned_by_another_tenant(ctx, tenant, db_session, dept_svc):
    """The name-resolution path must exclude another tenant's row of the same
    name, not just fail on names that exist nowhere (that's a weaker check —
    it would pass even if resolve_department_name's tenant_id filter were
    deleted entirely)."""
    from modules.teachers import services

    other_tenant = _other_tenant(db_session, "b")
    dept_svc.create_department({"name": "Robotics"}, other_tenant.id)

    result = services.create_teacher(
        name="New Teacher",
        email=f"new-{uuid.uuid4().hex[:6]}@example.test",
        department="Robotics",
    )

    assert result["success"] is False
    assert "Robotics" in result["error"]


def test_create_with_a_blank_department_name_is_a_no_op_not_an_error(ctx, tenant):
    """A blank `department` means "no department", matching pre-migration
    behaviour where an empty free-text value cleared the field — not the
    confusing "Unknown department ''" that a naive empty-string lookup would
    otherwise produce."""
    from modules.teachers import services

    result = services.create_teacher(
        name="New Teacher",
        email=f"new-{uuid.uuid4().hex[:6]}@example.test",
        department="",
    )

    assert result["success"] is True
    assert result["teacher"]["department_id"] is None


def test_create_department_id_wins_over_legacy_department_name(ctx, tenant, dept_svc):
    from modules.teachers import services

    science = dept_svc.create_department({"name": "Science"}, tenant.id)["department"]
    arts = dept_svc.create_department({"name": "Arts"}, tenant.id)["department"]

    result = services.create_teacher(
        name="New Teacher",
        email=f"new-{uuid.uuid4().hex[:6]}@example.test",
        department_id=science["id"],
        department="Arts",
    )

    assert result["success"] is True
    assert result["teacher"]["department_id"] == science["id"]
    assert arts["id"] != science["id"]


# ---------------------------------------------------------------------------
# update_teacher — previously zero coverage anywhere in the suite. Mirrors
# the create_teacher cross-tenant checks above, plus the update-only "leave
# unchanged vs. explicitly clear" distinction that create_teacher has no
# analogue for (a brand-new teacher has nothing to "leave unchanged").
# ---------------------------------------------------------------------------

def test_update_rejects_a_department_id_from_another_tenant(ctx, tenant, db_session, dept_svc):
    from modules.teachers import services

    teacher = _make_teacher(db_session, tenant, None, "u1")
    other_tenant = _other_tenant(db_session, "c")
    foreign_dept = dept_svc.create_department({"name": "Foreign Dept"}, other_tenant.id)["department"]

    result = services.update_teacher(teacher.id, department_id=foreign_dept["id"])

    assert result["success"] is False


def test_update_rejects_a_department_name_owned_by_another_tenant(ctx, tenant, db_session, dept_svc):
    from modules.teachers import services

    teacher = _make_teacher(db_session, tenant, None, "u2")
    other_tenant = _other_tenant(db_session, "d")
    dept_svc.create_department({"name": "Robotics"}, other_tenant.id)

    result = services.update_teacher(teacher.id, department="Robotics")

    assert result["success"] is False
    assert "Robotics" in result["error"]


def test_update_without_department_keys_leaves_department_unchanged(ctx, tenant, db_session, dept_svc):
    """The whole point of update_teacher's department_id default being the
    NOT_PROVIDED sentinel rather than None: a caller updating an unrelated
    field (phone, here) must not touch the department at all."""
    from modules.teachers import services

    science = dept_svc.create_department({"name": "Science"}, tenant.id)["department"]
    teacher = _make_teacher(db_session, tenant, science["id"], "u3")

    result = services.update_teacher(teacher.id, phone="9998887777")

    assert result["success"] is True
    assert result["teacher"]["department_id"] == science["id"]
    assert result["teacher"]["phone"] == "9998887777"


def test_update_clears_department_when_department_id_explicitly_null(ctx, tenant, db_session, dept_svc):
    """department_id present-but-null is the "clear the department" signal —
    distinct from omitting the key entirely (tested above)."""
    from modules.teachers import services

    science = dept_svc.create_department({"name": "Science"}, tenant.id)["department"]
    teacher = _make_teacher(db_session, tenant, science["id"], "u4")

    result = services.update_teacher(teacher.id, department_id=None)

    assert result["success"] is True
    assert result["teacher"]["department_id"] is None


def test_update_clears_department_when_legacy_name_is_blank(ctx, tenant, db_session, dept_svc):
    """Pre-migration, `department=""` cleared the free-text column — this
    keeps that contract for a client that still speaks the legacy field."""
    from modules.teachers import services

    science = dept_svc.create_department({"name": "Science"}, tenant.id)["department"]
    teacher = _make_teacher(db_session, tenant, science["id"], "u5")

    result = services.update_teacher(teacher.id, department="")

    assert result["success"] is True
    assert result["teacher"]["department_id"] is None


def test_update_department_id_wins_over_legacy_department_name(ctx, tenant, db_session, dept_svc):
    from modules.teachers import services

    science = dept_svc.create_department({"name": "Science"}, tenant.id)["department"]
    arts = dept_svc.create_department({"name": "Arts"}, tenant.id)["department"]
    teacher = _make_teacher(db_session, tenant, None, "u6")

    result = services.update_teacher(teacher.id, department_id=science["id"], department="Arts")

    assert result["success"] is True
    assert result["teacher"]["department_id"] == science["id"]


# ---------------------------------------------------------------------------
# N+1 guard — list_teachers must eager-load department_ref alongside the
# join it already uses for filter/sort, or every teacher row with a
# department set fires its own `SELECT ... FROM departments`.
#
# This counts only statements touching the `departments` table specifically
# (not the total statement count): `Teacher.user` is a separate, pre-existing
# lazy relationship that already issues one query per row regardless of this
# fix (out of scope here — see the review notes), so a blanket total-query
# assertion would fail either way and prove nothing about department_ref.
# ---------------------------------------------------------------------------

def test_list_does_not_n_plus_one_on_department(flask_app, db_session, tenant, dept_svc):
    from sqlalchemy import event

    from core.database import db
    from modules.teachers import services

    science = dept_svc.create_department({"name": "Science"}, tenant.id)["department"]
    made = 0

    def count_department_statements(additional_teachers):
        nonlocal made
        for i in range(additional_teachers):
            _make_teacher(db_session, tenant, science["id"], f"n1-{made + i}")
        made += additional_teachers

        statements = []

        def record(conn, cursor, statement, params, context, executemany):
            if "departments" in statement.lower():
                statements.append(statement)

        with flask_app.test_request_context("/"):
            g.tenant_id = tenant.id
            event.listen(db.engine, "before_cursor_execute", record)
            try:
                result = services.list_teachers()
                assert len(result["items"]) == made
                assert all(t["department"] == "Science" for t in result["items"])
            finally:
                event.remove(db.engine, "before_cursor_execute", record)
        return len(statements)

    few = count_department_statements(2)
    many = count_department_statements(6)

    assert many <= few, (
        f"department query count grew with row count ({few} -> {many}): N+1"
    )
