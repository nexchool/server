"""Which wire a school's sign-in codes go down."""

import re

import pytest
from sqlalchemy import CheckConstraint
from sqlalchemy.exc import IntegrityError

from core.database import db
from modules.auth import policy
from modules.auth.policy_models import TenantAuthPolicy
from modules.integrations.capabilities import MESSAGING_CAPABILITIES

_CONSTRAINT_NAME = "ck_tenant_auth_policies_otp_delivery_channel"


def test_a_school_that_has_chosen_nothing_is_on_sms(db_session, tenant):
    """The default is what every school does today. A migration that changed
    behaviour for anybody would be the wrong kind of surprise."""
    assert policy.otp_delivery_channel(tenant.id) == "sms"


def test_an_operator_can_move_a_school_to_whatsapp(db_session, tenant):
    policy.set_otp_delivery_channel(tenant.id, "whatsapp")
    db.session.commit()
    assert policy.otp_delivery_channel(tenant.id) == "whatsapp"


def test_a_channel_this_build_cannot_deliver_is_refused(db_session, tenant):
    with pytest.raises(ValueError):
        policy.set_otp_delivery_channel(tenant.id, "carrier_pigeon")


def test_the_channel_is_in_what_the_panel_reads(db_session, tenant):
    described = policy.describe(tenant.id)
    assert described["otp_delivery_channel"] == "sms"


def test_the_database_refuses_a_channel_the_application_would_have_caught(
    db_session, tenant
):
    """The setter validates, but a script or a shell does not go through it.

    `ck_tenant_auth_policies_otp_delivery_channel` is the backstop for
    whatever bypasses `set_otp_delivery_channel` — set directly on the model
    the way a one-off script or a future code path might, skipping the
    `ValueError` the setter already covers above.
    """
    policy_row = policy.ensure_default_policy(tenant.id)
    policy_row.otp_delivery_channel = "carrier_pigeon"
    with pytest.raises(IntegrityError):
        db.session.flush()
    db.session.rollback()


def test_the_constraint_matches_messaging_capabilities():
    """The database's list and the application's list must never drift.

    `ck_tenant_auth_policies_otp_delivery_channel` is a SQL literal — it
    cannot read `MESSAGING_CAPABILITIES` at runtime — so nothing but a test
    keeps them in step. Without this, adding a third messaging capability
    would silently leave the database still refusing it, and the first
    school to be moved onto it would find out from a failed OTP rather than
    from a review comment.
    """
    constraints = {
        constraint.name: constraint
        for constraint in TenantAuthPolicy.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    constraint = constraints[_CONSTRAINT_NAME]

    match = re.search(r"IN \(([^)]+)\)", str(constraint.sqltext))
    assert match, f"Could not parse values out of {constraint.sqltext!r}"
    allowed = {value.strip().strip("'") for value in match.group(1).split(",")}

    assert allowed == set(MESSAGING_CAPABILITIES)
