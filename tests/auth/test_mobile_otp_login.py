"""Phase 4 — signing in with a code, over HTTP.

Verification is not a new endpoint. It is an ordinary sign-in through
`POST /api/auth/login` with `method=mobile_otp`, so every gate the pipeline
already owns — maintenance, policy, lockout, account status, disambiguation,
events, finalization — runs exactly as it does for a password. That is the
point of these tests: a new method must not be a second copy of the gates.

Only the *request* half is new, and it is shaped almost entirely by one
requirement: it must not become a way to find out whether a phone number
belongs to a NexSchool customer.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from core.database import db
from modules.auth.identifiers import normalize_mobile
from modules.auth.models import AccountIdentifier, Session
from modules.auth.otp import request_otp
from modules.auth.otp_models import MobileOtpChallenge
from modules.auth.otp_throttle import clear_for_tests, hash_value
from modules.auth.policy import ensure_default_policy, set_method
from modules.auth.provisioning import issue_mobile_identifier
from modules.auth.strategies.mobile_otp import MobileOtpStrategy
from modules.billing.constants import PRICING_METERED
from modules.billing.services import configure_tenant_service, upsert_provider, upsert_service
from modules.integrations.capabilities import CAPABILITY_SMS, STATUS_ENABLED
from modules.integrations.providers.fake import FakeSmsProvider
from modules.integrations.services import configure_integration, set_integration_status
from tests.auth._characterization import (
    decode_access_token,
    grant_permissions,
    make_tenant,
    make_user,
    sessions_for,
)

METHOD = MobileOtpStrategy.key
FAKE = FakeSmsProvider.key


@pytest.fixture(autouse=True)
def _reachable_redis(flask_app):
    """See `test_mobile_otp.py` — the throttle fails closed, so a suite with no
    Redis would pass for the wrong reason."""
    import core.cache as cache

    previous_url = flask_app.config.get("REDIS_URL")
    previous_pool = cache._pool
    flask_app.config["REDIS_URL"] = "redis://localhost:6379/0"
    cache._pool = None

    with flask_app.app_context():
        client = cache.redis_client()
        try:
            assert client is not None and client.ping()
        except Exception:  # noqa: BLE001
            flask_app.config["REDIS_URL"] = previous_url
            cache._pool = previous_pool
            pytest.skip("mobile OTP needs a reachable Redis for its rate limiter")

    with flask_app.app_context():
        clear_for_tests(tenant_id="", ip_address="127.0.0.1")

    yield
    flask_app.config["REDIS_URL"] = previous_url
    cache._pool = previous_pool


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _fresh_request(flask_app):
    """Forget the school the previous request resolved.

    A harness artefact: Flask reuses the app context a test pushed, so `g`
    survives between test-client calls in a way it never does in production.
    Documented at length in `test_admission_id_login.py`.
    """
    from flask import g as flask_g

    for attribute in ("tenant_id", "tenant", "current_user"):
        if hasattr(flask_g, attribute):
            delattr(flask_g, attribute)


def _mobile() -> str:
    return f"+9198{uuid.uuid4().int % 100000000:08d}"


def _school(db_session):
    tenant = make_tenant(db_session)
    ensure_default_policy(tenant.id)
    for kind in ("student", "staff"):
        set_method(tenant.id, kind, METHOD, enabled=True)

    configure_integration(tenant.id, capability=CAPABILITY_SMS, provider_key=FAKE)
    set_integration_status(tenant.id, capability=CAPABILITY_SMS, status=STATUS_ENABLED)
    provider = upsert_provider(key=FAKE, name="A Vendor")
    service = upsert_service(
        provider_key=provider.key,
        key=CAPABILITY_SMS,
        name="SMS",
        unit="sms",
        pricing_mode=PRICING_METERED,
        provider_unit_cost=Decimal("0.02"),
    )
    configure_tenant_service(
        tenant.id,
        service_key=service.key,
        provider_key=provider.key,
        customer_unit_price=Decimal("0.05"),
    )
    db_session.flush()
    return tenant


def _member(db_session, tenant, *, mobile=None):
    user = make_user(db_session, tenant, password="Password123")
    grant_permissions(db_session, tenant, user, ("student.read.all",))
    number = mobile or _mobile()
    issue_mobile_identifier(user, number)
    db_session.flush()
    clear_for_tests(tenant_id=tenant.id, mobile_hash=hash_value(normalize_mobile(number)))
    return user, number


def _send(tenant, number):
    result = request_otp(tenant_id=tenant.id, mobile=number)
    return result, getattr(result.challenge, "_plaintext_code", None)


def _sign_in(client, flask_app, tenant, *, number, code, **extra):
    _fresh_request(flask_app)
    body = {
        "method": METHOD,
        "identifier": number,
        "password": code,
        "tenant_id": tenant.id,
    }
    body.update(extra)
    return client.post("/api/auth/login", json=body)


# ---------------------------------------------------------------------------
# Signing in
# ---------------------------------------------------------------------------

def test_a_code_signs_somebody_in(client, db_session, flask_app):
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)
    _, code = _send(tenant, number)
    db_session.flush()

    response = _sign_in(client, flask_app, tenant, number=number, code=code)

    assert response.status_code == 200
    assert response.get_json()["data"]["user"]["id"] == user.id


def test_the_session_says_how_they_signed_in(client, db_session, flask_app):
    """O11. A method that recorded `email` would make an OTP session
    indistinguishable from a password one in every audit afterwards."""
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)
    _, code = _send(tenant, number)
    db_session.flush()

    _sign_in(client, flask_app, tenant, number=number, code=code)
    db_session.flush()

    session = sessions_for(user.id)[-1]
    identifier = AccountIdentifier.query.filter_by(
        account_id=user.id, identifier_type="mobile"
    ).first()
    assert session.login_method == METHOD
    assert session.authenticated_identifier_id == identifier.id


def test_the_token_carries_the_method_and_the_school(client, db_session, flask_app):
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)
    _, code = _send(tenant, number)
    db_session.flush()

    body = _sign_in(client, flask_app, tenant, number=number, code=code).get_json()["data"]
    claims = decode_access_token(body["access_token"])

    assert claims["amr"] == METHOD
    assert claims["tid"] == tenant.id


def test_signing_in_proves_the_number_and_marks_it_verified(client, db_session, flask_app):
    """Issuing a mobile identifier deliberately does not claim the school has
    proved anybody holds it. Using a code sent to it is that proof."""
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)
    identifier = AccountIdentifier.query.filter_by(
        account_id=user.id, identifier_type="mobile"
    ).first()
    assert identifier.is_verified is False
    _, code = _send(tenant, number)
    db_session.flush()

    _sign_in(client, flask_app, tenant, number=number, code=code)
    db_session.flush()

    db_session.refresh(identifier)
    assert identifier.is_verified is True
    assert identifier.verified_at is not None


def test_a_wrong_code_does_not_sign_in(client, db_session, flask_app):
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)
    _send(tenant, number)
    db_session.flush()

    response = _sign_in(client, flask_app, tenant, number=number, code="000000")

    assert response.status_code == 401
    assert response.get_json()["error"] == "InvalidCredentials"


def test_a_used_code_does_not_sign_in_again(client, db_session, flask_app):
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)
    _, code = _send(tenant, number)
    db_session.flush()

    first = _sign_in(client, flask_app, tenant, number=number, code=code)
    second = _sign_in(client, flask_app, tenant, number=number, code=code)

    assert first.status_code == 200
    assert second.status_code == 401


def test_signing_in_without_naming_a_school_is_refused(client, db_session, flask_app):
    """A4. A number alone would have to be searched across every school, and
    the answer would be somebody — possibly the wrong somebody."""
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)
    _, code = _send(tenant, number)
    db_session.flush()

    _fresh_request(flask_app)
    response = client.post(
        "/api/auth/login",
        json={"method": METHOD, "identifier": number, "password": code},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "TenantRequired"


def test_a_code_from_one_school_does_not_work_at_another(client, db_session, flask_app):
    ours = _school(db_session)
    theirs = _school(db_session)
    number = _mobile()
    _member(db_session, theirs, mobile=number)
    _, code = _send(theirs, number)
    db_session.flush()

    response = _sign_in(client, flask_app, ours, number=number, code=code)

    assert response.status_code == 401


def test_a_school_that_turned_it_off_cannot_be_signed_into_this_way(
    client, db_session, flask_app
):
    """O12, at the pipeline's policy gate — evaluated before the proof."""
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)
    _, code = _send(tenant, number)
    db_session.flush()

    for kind in ("student", "staff"):
        set_method(tenant.id, kind, METHOD, enabled=False)
    db_session.flush()

    response = _sign_in(client, flask_app, tenant, number=number, code=code)

    # Uniform with a wrong password, deliberately: telling "this account
    # exists but the method is off" from "no such account" was an
    # enumeration oracle needing no password. The reason is still recorded.
    assert response.status_code == 401
    assert response.get_json()["error"] == "InvalidCredentials"


def test_a_suspended_account_cannot_sign_in_with_a_code(client, db_session, flask_app):
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)
    _, code = _send(tenant, number)
    user.is_suspended = True
    db_session.flush()

    response = _sign_in(client, flask_app, tenant, number=number, code=code)

    assert response.status_code in (401, 403)


def test_a_password_change_requirement_survives_an_otp_sign_in(
    client, db_session, flask_app
):
    """§25's explicit decision, pinned.

    An OTP proves possession of a phone. It does not set a password, so it
    cannot discharge a requirement to change one — and silently clearing the
    flag would let anybody holding the phone skip a security requirement an
    operator deliberately imposed. The state is reported, unchanged.
    """
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)
    user.force_password_reset = True
    db_session.flush()
    _, code = _send(tenant, number)
    db_session.flush()

    body = _sign_in(client, flask_app, tenant, number=number, code=code).get_json()["data"]
    db_session.refresh(user)

    assert body["force_password_reset"] is True
    assert user.force_password_reset is True


def test_email_and_password_still_work_exactly_as_before(client, db_session, flask_app):
    """O13. The regression that matters most."""
    tenant = _school(db_session)
    user, _ = _member(db_session, tenant)

    _fresh_request(flask_app)
    response = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": "Password123", "tenant_id": tenant.id},
    )
    db_session.flush()

    assert response.status_code == 200
    assert sessions_for(user.id)[-1].login_method == "email_password"


# ---------------------------------------------------------------------------
# Asking for a code
# ---------------------------------------------------------------------------

def test_asking_for_a_code_answers_the_same_whoever_asks(client, db_session, flask_app):
    """The enumeration oracle this whole flow is shaped to avoid.

    A real customer, a stranger's number and a school that has not enabled the
    method all produce one response. Anything else answers, for free, the
    question an attacker is asking.
    """
    tenant = _school(db_session)
    user, known = _member(db_session, tenant)
    stranger = _mobile()

    _fresh_request(flask_app)
    real = client.post(
        "/api/auth/otp/request", json={"mobile": known, "tenant_id": tenant.id}
    )
    _fresh_request(flask_app)
    unknown = client.post(
        "/api/auth/otp/request", json={"mobile": stranger, "tenant_id": tenant.id}
    )

    assert real.status_code == unknown.status_code == 200
    assert real.get_json()["message"] == unknown.get_json()["message"]
    # The challenge id is the one difference, and it says nothing about a
    # person — a client that gets none simply waits for a code that will not
    # come, exactly as it would if the message were lost.
    assert unknown.get_json()["data"].get("challenge_id") is None


def test_a_request_never_reveals_a_number_or_an_account(client, db_session, flask_app):
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)

    _fresh_request(flask_app)
    body = client.post(
        "/api/auth/otp/request", json={"mobile": number, "tenant_id": tenant.id}
    ).get_data(as_text=True)

    assert user.id not in body
    assert user.email not in body
    assert number.replace("+", "") not in body
    # And no code, ever.
    challenge = MobileOtpChallenge.query.filter_by(tenant_id=tenant.id).first()
    assert challenge is not None
    assert challenge.code_hash not in body


def test_asking_without_naming_a_school_is_refused(client, db_session, flask_app):
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)

    _fresh_request(flask_app)
    response = client.post("/api/auth/otp/request", json={"mobile": number})

    assert response.status_code in (400, 404)


def test_asking_too_often_is_told_plainly(client, db_session, flask_app):
    """The one thing a caller is told, because they already know it — they are
    the one who sent the requests — and a client that does not know it is
    throttled simply retries."""
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)

    _fresh_request(flask_app)
    client.post("/api/auth/otp/request", json={"mobile": number, "tenant_id": tenant.id})
    _fresh_request(flask_app)
    again = client.post(
        "/api/auth/otp/request", json={"mobile": number, "tenant_id": tenant.id}
    )

    assert again.status_code == 429
    assert again.get_json()["error"] == "TooManyRequests"


def test_a_missing_number_is_a_validation_error(client, db_session, flask_app):
    tenant = _school(db_session)

    _fresh_request(flask_app)
    response = client.post("/api/auth/otp/request", json={"tenant_id": tenant.id})

    assert response.status_code == 400


def test_the_platform_operator_is_untouched_by_any_of_this(client, db_session, flask_app):
    """God-login precedence and semantics are Phase 0d's and stay exactly as
    they were; OTP adds a method, not a change to how operators enter."""
    from tests.auth._characterization import make_platform_admin

    home = _school(db_session)
    entering = _school(db_session)
    operator = make_platform_admin(db_session, home, password="Operator12345")
    db_session.flush()

    _fresh_request(flask_app)
    response = client.post(
        "/api/auth/login",
        json={
            "email": operator.email,
            "password": "Operator12345",
            "tenant_id": entering.id,
        },
    )

    assert response.status_code == 200
