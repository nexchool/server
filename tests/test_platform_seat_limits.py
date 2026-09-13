"""Seat limits are set per school from the panel, next to the price.

The operator patches `max_active_students` and `max_employed_teachers` on the
same pricing call that sets the price; the tenant payload the panel reads
carries the limits and the live active/employed counts they are measured
against, so the screen can show "263 of 150" without a second request.
"""

from __future__ import annotations

import uuid

import pytest

from core.models import BILLING_CYCLE_YEARLY, TENANT_STATUS_ACTIVE, Tenant
from modules.auth.models import User
from modules.platform import services
from tests.conftest import _make_student


@pytest.fixture
def operator(db_session):
    home = Tenant(id=f"t-{uuid.uuid4().hex[:12]}", name="Platform HQ",
                  subdomain=f"hq-{uuid.uuid4().hex}", status=TENANT_STATUS_ACTIVE,
                  billing_cycle=BILLING_CYCLE_YEARLY)
    db_session.add(home)
    db_session.flush()
    u = User(id=f"pa-{uuid.uuid4().hex[:12]}", tenant_id=home.id,
             email=f"super-{uuid.uuid4().hex[:6]}@platform.test", name="Super Admin",
             is_platform_admin=True, email_verified=True)
    u.set_password("Sup3r-secret!")
    db_session.add(u)
    db_session.flush()
    return u


def test_the_operator_sets_both_seat_limits_with_the_price(db_session, tenant, operator):
    result = services.update_tenant_pricing(
        tenant_id=tenant.id, platform_admin_id=operator.id,
        price_per_student_per_year=1200, max_active_students=150, max_employed_teachers=20,
    )
    assert result["success"] is True
    assert tenant.max_active_students == 150
    assert tenant.max_employed_teachers == 20
    assert result["tenant"]["max_active_students"] == 150
    assert result["tenant"]["max_employed_teachers"] == 20


def test_an_empty_value_lifts_the_limit(db_session, tenant, operator):
    tenant.max_active_students = 150
    db_session.flush()

    result = services.update_tenant_pricing(
        tenant_id=tenant.id, platform_admin_id=operator.id, max_active_students="",
    )
    assert result["success"] is True
    assert tenant.max_active_students is None
    assert result["tenant"]["max_active_students"] is None


@pytest.mark.parametrize("bad", [0, -5, "twelve", 2.5])
def test_a_limit_below_one_or_not_a_whole_number_is_refused(db_session, tenant, operator, bad):
    result = services.update_tenant_pricing(
        tenant_id=tenant.id, platform_admin_id=operator.id, max_employed_teachers=bad,
    )
    assert result["success"] is False
    assert "whole number" in result["error"]


def test_the_tenant_payload_carries_the_counts_the_limits_are_measured_against(
    db_session, tenant
):
    active = _make_student(db_session, tenant, name="Here", admission_suffix="here1")
    gone = _make_student(db_session, tenant, name="Gone", admission_suffix="gone1")
    gone.student_status = "graduated"
    db_session.flush()

    payload = services._serialize_tenant(tenant)
    assert payload["student_count"] == 2
    assert payload["active_student_count"] == 1
    assert payload["employed_teacher_count"] == 0
    assert payload["max_active_students"] is None
