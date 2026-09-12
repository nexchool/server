"""When a trial ends is an instant, and the operator says it in wall-clock time.

The super-admin panel sends `trial_ends_at` as either a date or an ISO
datetime. The column is `DateTime(timezone=True)`, so whatever is stored is an
instant — and a naive value handed to Postgres is read as UTC. The parser used
to strip the offset the operator sent and store the bare wall-clock digits,
which quietly moved every Indian trial end five and a half hours later than
the operator asked for; a bare date landed on UTC midnight for the same reason.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from flask import g

from core.models import (
    BILLING_CYCLE_YEARLY,
    TENANT_STATUS_ACTIVE,
    TENANT_STATUS_TRIAL,
    AuditLog,
    Tenant,
)
from modules.auth.models import User
from modules.platform.services import _parse_trial_end, update_tenant_subscription

UTC = timezone.utc


@pytest.fixture
def operator(db_session):
    """The platform admin doing the editing. A real row, because the audit
    entry the service writes carries a foreign key to `users.id`."""
    home = Tenant(
        id=f"t-{uuid.uuid4().hex[:12]}",
        name="Platform HQ",
        subdomain=f"hq-{uuid.uuid4().hex}",
        status=TENANT_STATUS_ACTIVE,
        billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(home)
    db_session.flush()
    u = User(
        id=f"pa-{uuid.uuid4().hex[:12]}",
        tenant_id=home.id,
        email=f"super-{uuid.uuid4().hex[:6]}@platform.test",
        name="Super Admin",
        is_platform_admin=True,
        email_verified=True,
    )
    u.set_password("Sup3r-secret!")
    db_session.add(u)
    db_session.flush()
    return u


def _state(flask_app, tenant_id):
    """What the write-gating decorator concludes, read fresh each time."""
    from core.decorators.subscription import _subscription_state

    with flask_app.test_request_context("/"):
        g._subscription_state = None
        return _subscription_state(tenant_id)


def test_an_offset_the_operator_sent_is_kept(db_session, tenant):
    got = _parse_trial_end("2026-10-01T10:00:00+05:30", tenant.id)
    assert got.tzinfo is not None
    assert got == datetime(2026, 10, 1, 4, 30, tzinfo=UTC)


def test_a_zulu_stamp_is_the_same_instant(db_session, tenant):
    got = _parse_trial_end("2026-10-01T04:30:00Z", tenant.id)
    assert got == datetime(2026, 10, 1, 4, 30, tzinfo=UTC)


def test_a_wall_clock_time_with_no_offset_is_the_school_s_clock(db_session, tenant):
    """An operator typing 10:00 means 10:00 at the school, not in Greenwich."""
    got = _parse_trial_end("2026-10-01T10:00:00", tenant.id)
    assert got == datetime(2026, 10, 1, 4, 30, tzinfo=UTC)


def test_a_bare_date_ends_at_midnight_at_the_school(db_session, tenant):
    got = _parse_trial_end("2026-10-01", tenant.id)
    assert got == datetime(2026, 9, 30, 18, 30, tzinfo=UTC)


def test_nonsense_is_refused_not_stored(db_session, tenant):
    with pytest.raises(ValueError):
        _parse_trial_end("next tuesday", tenant.id)


# ---------------------------------------------------------------------------
# End to end: the PATCH the panel makes, through to what the app enforces
# ---------------------------------------------------------------------------

def test_an_operator_s_change_lands_and_is_written_down(db_session, tenant, operator):
    result = update_tenant_subscription(
        tenant.id,
        operator.id,
        status=TENANT_STATUS_TRIAL,
        trial_ends_at="2026-10-01T10:00:00+05:30",
        discount_percentage="10",
        discount_start_date="2026-10-01",
        discount_end_date="2026-12-31",
    )
    assert result["success"] is True, result
    sub = result["subscription"]
    assert sub["status"] == TENANT_STATUS_TRIAL
    assert sub["discount_percentage"] == 10.0

    # The row holds the instant the operator meant, with its offset.
    db_session.refresh(tenant)
    assert tenant.trial_ends_at.tzinfo is not None
    assert tenant.trial_ends_at == datetime(2026, 10, 1, 4, 30, tzinfo=UTC)
    assert datetime.fromisoformat(sub["trial_ends_at"]) == tenant.trial_ends_at

    # And somebody can later see who did it and what it became.
    entry = (
        AuditLog.query.filter_by(tenant_id=tenant.id, action="tenant.subscription.updated")
        .order_by(AuditLog.created_at.desc())
        .first()
    )
    assert entry is not None
    assert entry.platform_admin_id == operator.id
    assert entry.extra_data["status"] == TENANT_STATUS_TRIAL
    assert datetime.fromisoformat(entry.extra_data["trial_ends_at"]) == tenant.trial_ends_at


def test_what_the_panel_writes_is_what_the_app_enforces(flask_app, db_session, tenant, operator):
    """The whole point of the field: a trial that has ended stops writes."""
    update_tenant_subscription(tenant.id, operator.id, status=TENANT_STATUS_TRIAL, trial_ends_at="2020-01-01")
    assert _state(flask_app, tenant.id)["reason"] == "TrialExpired"

    update_tenant_subscription(tenant.id, operator.id, trial_ends_at="2099-01-01")
    state = _state(flask_app, tenant.id)
    assert state["reason"] == "Trial"
    assert state["allow_writes"] is True


def test_an_empty_string_clears_the_trial_end(db_session, tenant, operator):
    update_tenant_subscription(tenant.id, operator.id, trial_ends_at="2099-01-01")
    result = update_tenant_subscription(tenant.id, operator.id, trial_ends_at="")
    assert result["success"] is True
    assert result["subscription"]["trial_ends_at"] is None
    db_session.refresh(tenant)
    assert tenant.trial_ends_at is None


def test_a_field_left_out_is_left_alone(db_session, tenant, operator):
    update_tenant_subscription(tenant.id, operator.id, trial_ends_at="2099-01-01", discount_percentage="5")
    result = update_tenant_subscription(tenant.id, operator.id, discount_percentage="7")
    assert result["subscription"]["discount_percentage"] == 7.0
    assert result["subscription"]["trial_ends_at"] is not None


def test_a_rejected_request_changes_nothing(db_session, tenant, operator):
    """One bad field must not let the good ones through: a suspension that
    arrived with an unparseable date is not a suspension."""
    before = (tenant.status, tenant.trial_ends_at)
    result = update_tenant_subscription(
        tenant.id, operator.id, status="suspended", trial_ends_at="next tuesday"
    )
    assert result["success"] is False
    assert "trial_ends_at" in result["error"]
    db_session.expire(tenant)
    assert (tenant.status, tenant.trial_ends_at) == before
    assert AuditLog.query.filter_by(tenant_id=tenant.id, action="tenant.subscription.updated").count() == 0


def test_an_unknown_status_is_refused(db_session, tenant, operator):
    result = update_tenant_subscription(tenant.id, operator.id, status="gold")
    assert result["success"] is False
    assert "status" in result["error"]


def test_an_unknown_tenant_is_not_found(db_session, operator):
    result = update_tenant_subscription("t-does-not-exist", operator.id, status=TENANT_STATUS_TRIAL)
    assert result == {"success": False, "error": "Tenant not found"}
