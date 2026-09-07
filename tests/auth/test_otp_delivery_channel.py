"""Which wire a school's sign-in codes go down."""

import pytest

from core.database import db
from modules.auth import policy


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
