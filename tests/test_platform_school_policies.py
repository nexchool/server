"""Per-client school policies, set from the panel.

Schools differ on who signs off a child's leave. In a small primary the class
teacher's word is final; a larger secondary wants the principal to see every
absence. The product had no way to express that difference, so it imposed one
answer on every client.

These live on `academic_settings`, not in `tenants.feature_flags`: flags say
which modules a school *has*, and their double duty as a settings bag is
documented in-code as something to undo rather than extend.
"""

from __future__ import annotations

import uuid

import pytest

from core.models import BILLING_CYCLE_YEARLY, TENANT_STATUS_ACTIVE, Tenant
from modules.auth.models import User
from modules.platform import services


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


def test_a_school_starts_with_the_class_teacher_having_the_last_word(db_session, tenant):
    """The default is the simpler school, and every existing client keeps the
    behaviour it already has."""
    result = services.get_tenant_school_policies(tenant.id)

    assert result["success"] is True
    assert result["policies"]["student_leave_requires_principal_approval"] is False


def test_the_operator_turns_principal_approval_on(db_session, tenant, operator):
    from modules.academics.backbone.models import AcademicSettings

    result = services.update_tenant_school_policies(
        tenant_id=tenant.id,
        platform_admin_id=operator.id,
        policies={"student_leave_requires_principal_approval": True},
    )

    assert result["success"] is True
    assert result["policies"]["student_leave_requires_principal_approval"] is True

    row = (
        db_session.query(AcademicSettings)
        .filter(AcademicSettings.tenant_id == tenant.id)
        .first()
    )
    assert row.student_leave_admin_approval_required is True


def test_the_operator_turns_it_back_off(db_session, tenant, operator):
    services.update_tenant_school_policies(
        tenant_id=tenant.id, platform_admin_id=operator.id,
        policies={"student_leave_requires_principal_approval": True},
    )
    result = services.update_tenant_school_policies(
        tenant_id=tenant.id, platform_admin_id=operator.id,
        policies={"student_leave_requires_principal_approval": False},
    )

    assert result["policies"]["student_leave_requires_principal_approval"] is False


@pytest.mark.parametrize("bad", ["yes", 1, None, "true"])
def test_a_policy_that_is_not_a_yes_or_no_is_refused(db_session, tenant, operator, bad):
    """A string "false" is truthy, and silently storing it as on would switch a
    school's workflow by accident."""
    result = services.update_tenant_school_policies(
        tenant_id=tenant.id, platform_admin_id=operator.id,
        policies={"student_leave_requires_principal_approval": bad},
    )
    assert result["success"] is False
    assert "true or false" in result["error"]


def test_an_unknown_policy_is_ignored_rather_than_stored(db_session, tenant, operator):
    """Same contract as feature flags: unrecognised keys do not become settings."""
    result = services.update_tenant_school_policies(
        tenant_id=tenant.id, platform_admin_id=operator.id,
        policies={"invented_policy": True},
    )
    assert result["success"] is True
    assert "invented_policy" not in result["policies"]


def test_an_unknown_tenant_is_reported_not_created(db_session, operator):
    result = services.update_tenant_school_policies(
        tenant_id="does-not-exist", platform_admin_id=operator.id,
        policies={"student_leave_requires_principal_approval": True},
    )
    assert result["success"] is False
    assert result["error"] == "Tenant not found"


def test_the_change_is_written_to_the_platform_audit_log(db_session, tenant, operator):
    """Who switched a school's approval chain, and when, is not a detail."""
    from core.models import AuditLog

    services.update_tenant_school_policies(
        tenant_id=tenant.id, platform_admin_id=operator.id,
        policies={"student_leave_requires_principal_approval": True},
    )

    entry = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.tenant_id == tenant.id,
            AuditLog.action == "tenant.school_policies.updated",
        )
        .first()
    )
    assert entry is not None
    assert entry.platform_admin_id == operator.id
