"""Regression: paginated tenant-scoped lists must not leak other tenants' rows.

Guards the fix for a cross-tenant data leak. The legacy ``before_compile``
tenant-scope listener silently dropped its ``WHERE tenant_id = :id`` clause when
a query already had ``LIMIT``/``OFFSET`` (the criterion would have to move into a
subquery). The effect: ``Model.query.count()`` (no LIMIT) scoped correctly while
the paginated ``Model.query.limit().offset().all()`` returned **every** tenant's
rows — so a list endpoint could report "0 total" yet render another tenant's
records. Replaced with ``with_loader_criteria`` in ``core/database.py``, which is
applied at execution time and is safe under LIMIT/OFFSET, JOINs and subqueries.

These tests exercise the exact query shape the bug hid in, plus interleaved
tenants in one process to prove the scoping value is not cached across requests.
"""

from __future__ import annotations

import uuid

import pytest
from flask import g


def _make_tenant(db_session):
    from core.models import Tenant, TENANT_STATUS_ACTIVE, BILLING_CYCLE_YEARLY

    t = Tenant(
        id=f"t-{uuid.uuid4().hex[:12]}",
        name="Isolation Test School",
        subdomain=f"iso-{uuid.uuid4().hex[:6]}",
        status=TENANT_STATUS_ACTIVE,
        billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(t)
    db_session.flush()
    return t


def _add_student(db_session, tenant_id, suffix):
    from modules.auth.models import User
    from modules.students.models import Student

    user = User(
        id=f"u-{uuid.uuid4().hex[:12]}",
        tenant_id=tenant_id,
        email=f"{suffix}@iso.school",
        password_hash="x" * 60,
        name=f"Student {suffix}",
    )
    db_session.add(user)
    db_session.flush()
    student = Student(
        id=f"s-{uuid.uuid4().hex[:12]}",
        tenant_id=tenant_id,
        user_id=user.id,
        admission_number=f"ADM-{suffix}",
    )
    db_session.add(student)
    db_session.flush()
    return student


def test_paginated_list_does_not_leak_other_tenants(flask_app, db_session):
    """A LIMIT/OFFSET query scoped to tenant A never returns tenant B's rows."""
    tenant_a = _make_tenant(db_session)
    tenant_b = _make_tenant(db_session)

    _add_student(db_session, tenant_a.id, "a1")
    _add_student(db_session, tenant_b.id, "b1")
    _add_student(db_session, tenant_b.id, "b2")

    from modules.students.models import Student

    with flask_app.test_request_context("/api/students/?page=1&per_page=50"):
        g.tenant_id = tenant_a.id
        # The exact shape that used to leak: ORDER BY + LIMIT + OFFSET.
        rows = (
            Student.query.order_by(Student.admission_number.asc())
            .limit(50)
            .offset(0)
            .all()
        )
        row_tenants = {r.tenant_id for r in rows}
        count = Student.query.count()

    assert tenant_b.id not in row_tenants, "cross-tenant leak under LIMIT/OFFSET"
    assert row_tenants <= {tenant_a.id}
    # count() (no LIMIT) and the paginated list must agree — the bug made the
    # count scope to 0-for-empty while the list leaked all rows.
    assert len(rows) == count == 1


def test_count_and_paginated_list_agree_when_tenant_empty(flask_app, db_session):
    """An empty tenant reports 0 for both count and the paginated list."""
    empty_tenant = _make_tenant(db_session)
    other = _make_tenant(db_session)
    _add_student(db_session, other.id, "x1")
    _add_student(db_session, other.id, "x2")

    from modules.students.models import Student

    with flask_app.test_request_context("/api/students/?page=1&per_page=20"):
        g.tenant_id = empty_tenant.id
        rows = Student.query.limit(20).offset(0).all()
        count = Student.query.count()

    assert count == 0
    assert rows == []


def test_scope_not_cached_across_interleaved_tenants(flask_app, db_session):
    """Switching tenants between requests re-scopes correctly (no cached value).

    with_loader_criteria is built from a lambda closing over ``tenant_id``; this
    proves the closure value is re-bound per execution rather than baked once.
    """
    tenant_a = _make_tenant(db_session)
    tenant_b = _make_tenant(db_session)
    _add_student(db_session, tenant_a.id, "a1")
    _add_student(db_session, tenant_b.id, "b1")
    _add_student(db_session, tenant_b.id, "b2")

    from modules.students.models import Student

    def visible_ids(tenant_id):
        with flask_app.test_request_context("/api/students/?page=1&per_page=50"):
            g.tenant_id = tenant_id
            rows = Student.query.limit(50).offset(0).all()
            return {r.tenant_id for r in rows}

    # Interleave A, B, A, B — a cached scope would surface the first tenant again.
    assert visible_ids(tenant_a.id) <= {tenant_a.id}
    assert visible_ids(tenant_b.id) <= {tenant_b.id}
    assert visible_ids(tenant_a.id) <= {tenant_a.id}
    assert visible_ids(tenant_b.id) <= {tenant_b.id}
