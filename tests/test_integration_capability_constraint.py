"""A school may be configured for WhatsApp, not just SMS.

`tenant_integrations` carries `ck_tenant_integrations_capability`. Migration
129 created it as `f"capability IN {CAPABILITIES}"` — an f-string that
interpolated the *live* Python constant at the moment the migration ran, when
`CAPABILITIES` was `('sms',)`. Every database that has already applied 129
therefore has a constraint that permits only `sms`, while
`modules/integrations/models.py` builds the same constraint dynamically from
the same constant, which is now `('sms', 'whatsapp')`. Model and database
disagree, and only the database's opinion is enforced at the SQL level — a
school cannot be stored with a WhatsApp integration until migration 135
widens the stored constraint.

This is deliberately two tests, the same split
`tests/auth/test_otp_delivery_channel.py` uses for
`ck_tenant_auth_policies_otp_delivery_channel`: one proves the constraint
behaves correctly for the capability that matters *today* (whatsapp), the
other proves it will keep matching `MESSAGING_CAPABILITIES` as that list
grows, by reading the constraint's definition back off the live table rather
than off the model. The model builds its `CheckConstraint` from the same
constant it is being checked against, so asserting against the model's own
`__table__.constraints` would be tautological — it can never fail, even
against the exact database that this whole task exists because of. Only a
read of `pg_constraint` proves what the database actually enforces.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from core.database import db
from modules.integrations.capabilities import CAPABILITY_WHATSAPP, MESSAGING_CAPABILITIES
from modules.integrations.providers.fake import FakeWhatsAppProvider
from modules.integrations.services import configure_integration

_CONSTRAINT_NAME = "ck_tenant_integrations_capability"


def _constraint_definition(db_session) -> str:
    """The constraint's definition as Postgres actually stores it.

    Read from `pg_constraint`, not from the SQLAlchemy model — the model
    builds this same constraint by string-formatting the same constant a
    migration would need to have interpolated correctly the first time, so
    checking the model against itself would prove nothing about what a real
    database enforces.
    """
    row = db_session.execute(
        text("SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :name"),
        {"name": _CONSTRAINT_NAME},
    ).first()
    assert row is not None, f"{_CONSTRAINT_NAME!r} does not exist on this database"
    return row[0]


def test_a_school_can_be_configured_for_whatsapp(db_session, tenant):
    """The defect, directly: this call raises `IntegrityError` against a
    database still carrying migration 129's narrow, interpolated constraint,
    and succeeds once 135's literal, widened constraint is applied."""
    configure_integration(
        tenant.id,
        capability=CAPABILITY_WHATSAPP,
        provider_key=FakeWhatsAppProvider.key,
    )
    db.session.flush()


def test_the_constraint_matches_messaging_capabilities(db_session, tenant):
    """The database's list and the application's list must never drift.

    The constraint is a SQL literal — it cannot read `MESSAGING_CAPABILITIES`
    at runtime — so nothing but a test keeps them in step. Without this,
    adding a third messaging capability would silently leave the database
    still refusing it, and the first school moved onto it would find out
    from a failed integration rather than from a review comment.
    """
    definition = _constraint_definition(db_session)
    allowed = set(re.findall(r"'([^']+)'", definition))

    assert allowed == set(MESSAGING_CAPABILITIES)


def test_a_capability_outside_messaging_capabilities_is_still_refused(
    db_session, tenant
):
    """The widened constraint must not have been widened into a no-op — it
    should still refuse something that is neither `sms` nor `whatsapp`."""
    integration_capability_column = "carrier_pigeon"
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                "INSERT INTO tenant_integrations "
                "(id, tenant_id, capability, provider_key, status, "
                "configuration, credential_references, created_at, updated_at) "
                "VALUES (:id, :tenant_id, :capability, 'fake_sms', 'disabled', "
                "'{}', '{}', now(), now())"
            ),
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "tenant_id": tenant.id,
                "capability": integration_capability_column,
            },
        )
        db_session.flush()
    db_session.rollback()
