"""Department model — constraints and indexes, exercised against real Postgres."""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def _dept(tenant, **overrides):
    from modules.departments.models import Department

    fields = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant.id,
        "name": "Primary",
    }
    fields.update(overrides)
    return Department(**fields)


def test_defaults_are_academic_division_and_active(db_session, tenant):
    dept = _dept(tenant)
    db_session.add(dept)
    db_session.flush()

    assert dept.type == "academic_division"
    assert dept.status == "active"
    assert dept.display_order == 0
    assert dept.deleted_at is None


def test_name_is_unique_per_tenant_case_insensitively(db_session, tenant):
    db_session.add(_dept(tenant, name="Science"))
    db_session.flush()

    db_session.add(_dept(tenant, name="science"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_same_name_allowed_in_a_different_tenant(db_session, tenant):
    from core.models import Tenant, TENANT_STATUS_ACTIVE, BILLING_CYCLE_YEARLY

    other = Tenant(
        id=str(uuid.uuid4()),
        name="Other School",
        subdomain=f"other-{uuid.uuid4().hex[:6]}",
        status=TENANT_STATUS_ACTIVE,
        billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(other)
    db_session.flush()

    db_session.add(_dept(tenant, name="Science"))
    db_session.add(_dept(other, name="Science"))
    db_session.flush()  # must not raise


def test_name_can_be_reused_after_soft_delete(db_session, tenant):
    from datetime import datetime, timezone

    first = _dept(tenant, name="Commerce")
    db_session.add(first)
    db_session.flush()

    first.deleted_at = datetime.now(timezone.utc)
    db_session.flush()

    db_session.add(_dept(tenant, name="Commerce"))
    db_session.flush()  # must not raise


def test_code_is_unique_per_tenant_case_insensitively(db_session, tenant):
    db_session.add(_dept(tenant, name="Science", code="SCI"))
    db_session.flush()

    db_session.add(_dept(tenant, name="Senior Science", code="sci"))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_null_codes_do_not_collide(db_session, tenant):
    db_session.add(_dept(tenant, name="Primary", code=None))
    db_session.add(_dept(tenant, name="Secondary", code=None))
    db_session.flush()  # must not raise


def test_status_check_constraint_rejects_unknown_value(db_session, tenant):
    db_session.add(_dept(tenant, status="archived"))
    with pytest.raises(IntegrityError):
        db_session.flush()
