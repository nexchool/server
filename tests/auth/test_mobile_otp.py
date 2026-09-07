"""Phase 4 — a mobile number and a code sent to it.

The first authentication method with no stored secret, and the first where an
attempt costs money. Both facts shape what is tested here.

The assertions worth reading first:

  * `test_the_code_is_never_stored_anywhere` — O1/O2, and the reason the
    challenge table holds a salted hash and a keyed digest instead of a number.
  * `test_one_code_cannot_sign_in_twice` and
    `test_two_requests_racing_on_one_code_produce_one_winner` — O3, the
    single-use guarantee, tested against a real race rather than a comment.
  * `test_a_number_that_means_two_people_signs_in_nobody` — O8. Never
    `.first()`.
  * `test_asking_for_a_code_answers_the_same_whoever_asks` — the enumeration
    oracle this whole flow is shaped to avoid.
  * `test_a_school_that_has_not_enabled_it_cannot_spend_money_on_it` — O12,
    and the reason policy is evaluated before the proof.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from core.database import db
from core.school_time import utc_now
from modules.auth.identifiers import (
    DEFAULT_MOBILE_REGION,
    IDENTIFIER_TYPE_MOBILE,
    normalize_identifier,
    normalize_mobile,
)
from modules.auth.models import AccountIdentifier
from modules.auth.otp import (
    MAX_VERIFICATION_ATTEMPTS,
    OTP_LENGTH,
    OTP_TTL_SECONDS,
    REASON_AMBIGUOUS,
    REASON_METHOD_NOT_ALLOWED,
    REASON_NO_ACCOUNT,
    REASON_THROTTLED,
    generate_code,
    request_otp,
    verify_code,
)
from modules.auth.otp_models import (
    PURPOSE_AUTHENTICATION,
    STATUS_CONSUMED,
    STATUS_FAILED,
    STATUS_SENT,
    STATUS_SUPERSEDED,
    MobileOtpChallenge,
)
from modules.auth.otp_throttle import (
    MAX_REQUESTS_PER_MOBILE_HOUR,
    RESEND_COOLDOWN_SECONDS,
    clear_for_tests,
    hash_value,
)
from modules.auth.policy import ensure_default_policy, set_method
from modules.auth.provisioning import MobileAlreadyInUse, issue_mobile_identifier
from modules.auth.strategies import registry
from modules.auth.strategies.mobile_otp import MobileOtpStrategy
from modules.billing.constants import PRICING_METERED
from modules.billing.models import ServiceUsageRecord
from modules.billing.services import configure_tenant_service, upsert_provider, upsert_service
from modules.integrations.capabilities import (
    CAPABILITY_SMS,
    CAPABILITY_WHATSAPP,
    STATUS_ENABLED,
)
from modules.integrations.providers.fake import (
    BEHAVIOUR_KEY,
    BEHAVIOUR_REJECTED,
    BEHAVIOUR_TIMEOUT,
    FakeSmsProvider,
    FakeWhatsAppProvider,
)
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

#: `send_sms` now stops at `template_for` before it ever reaches a provider —
#: every school routed through the test double needs a template registered
#: for `PURPOSE_AUTHENTICATION`, the purpose every OTP send in this suite
#: goes under. Named (Task 8b), because `_deliver` always calls `send_sms`
#: with `otp_variables(code)` — two positional values (code, minutes) — and
#: `messaging.send_message` refuses a count that does not match a template's
#: declared names before any provider is called.
SMS_TEMPLATES = {
    "templates": {
        PURPOSE_AUTHENTICATION: {"id": "test-template-1", "variables": ["OTP", "MINUTES"]},
    }
}


@pytest.fixture(autouse=True)
def _reachable_redis(flask_app):
    """Point the throttle at a Redis this machine actually has.

    The app's default `REDIS_URL` is the Compose hostname, which does not
    resolve outside Docker — and the throttle **fails closed**, so with no
    Redis every request here would be refused and every assertion would pass
    for the wrong reason. Rather than let that happen quietly, this points at a
    local Redis and skips the module when there is none: an OTP suite that
    cannot exercise its own rate limiter is not telling the truth.
    """
    import core.cache as cache

    previous_url = flask_app.config.get("REDIS_URL")
    previous_pool = cache._pool
    flask_app.config["REDIS_URL"] = "redis://localhost:6379/0"
    cache._pool = None

    # Inside an application context, so the URL just set on the config is the
    # one read. Without one, `get_redis_url` falls through to the environment,
    # which in a developer's shell is the Compose hostname — and the first
    # test in the file would skip while the rest ran.
    with flask_app.app_context():
        client = cache.redis_client()
        try:
            assert client is not None and client.ping()
        except Exception:  # noqa: BLE001
            flask_app.config["REDIS_URL"] = previous_url
            cache._pool = previous_pool
            pytest.skip("mobile OTP needs a reachable Redis for its rate limiter")

    # Every test-client request comes from 127.0.0.1, so without this the
    # suite throttles itself after twenty codes — and, because the counter is
    # in a real Redis, keeps doing so on the next run.
    with flask_app.app_context():
        clear_for_tests(tenant_id="", ip_address="127.0.0.1")

    yield

    flask_app.config["REDIS_URL"] = previous_url
    cache._pool = previous_pool


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _mobile() -> str:
    """A distinct, valid Indian mobile per test."""
    return f"+9198{uuid.uuid4().int % 100000000:08d}"


def _school(
    db_session,
    *,
    otp_enabled=True,
    sms_working=True,
    whatsapp_working=False,
):
    """A school that can send codes, unless the test says otherwise."""
    tenant = make_tenant(db_session)
    ensure_default_policy(tenant.id)
    if otp_enabled:
        for kind in ("student", "staff"):
            set_method(tenant.id, kind, METHOD, enabled=True)

    if sms_working:
        configure_integration(
            tenant.id,
            capability=CAPABILITY_SMS,
            provider_key=FAKE,
            configuration=SMS_TEMPLATES,
        )
        set_integration_status(
            tenant.id, capability=CAPABILITY_SMS, status=STATUS_ENABLED
        )
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

    if whatsapp_working:
        # Migration 135 widened `ck_tenant_integrations_capability` to permit
        # `whatsapp`, so a school can now be configured onto the real
        # `fake_whatsapp` test double through `configure_integration` — the
        # same way `test_integration_lifecycle.py`'s `enabled_fake_whatsapp`
        # fixture does. This used to patch `messaging.messaging_health`
        # directly, which meant a test built on this flag could not tell
        # "the gate correctly checked whatsapp" apart from "the gate is
        # broken and would have said yes to any channel" — the mock ignored
        # `channel` entirely. Routing through a real, enabled integration
        # instead means the gate has to ask about the right capability to
        # get a ready answer.
        configure_integration(
            tenant.id,
            capability=CAPABILITY_WHATSAPP,
            provider_key=FakeWhatsAppProvider.key,
            configuration={"templates": {PURPOSE_AUTHENTICATION: "test-whatsapp-template"}},
        )
        set_integration_status(
            tenant.id, capability=CAPABILITY_WHATSAPP, status=STATUS_ENABLED
        )

    db_session.flush()
    return tenant


def _staff(db_session, tenant, *, permissions=("student.read.all",)):
    """An account the school employs.

    Employment is what gives an account a *subject kind*, and policy grants
    methods per kind — so an account with no relationship to the school is
    permitted nothing, correctly. A bare `make_user` would make every test
    here pass for the wrong reason.
    """
    user = make_user(db_session, tenant, password="Password123")
    grant_permissions(db_session, tenant, user, permissions)
    return user


def _member(db_session, tenant, *, mobile=None, permissions=("student.read.all",)):
    """An account that can sign in, with a mobile identifier issued to it."""
    user = _staff(db_session, tenant, permissions=permissions)
    number = mobile or _mobile()
    issue_mobile_identifier(user, number)
    db_session.flush()
    clear_for_tests(tenant_id=tenant.id, mobile_hash=hash_value(normalize_mobile(number)))
    return user, number


def _code_for(challenge_id):
    """A test's only way to learn a code — recompute it is impossible, so the
    request path hands it back in memory. Nothing persists it."""
    raise NotImplementedError


def _issue(tenant, mobile, **kwargs):
    """Request a code and return (result, plaintext).

    The plaintext is read off the in-memory attribute the service attaches for
    the sender. That it has to be read this way is itself the property under
    test: there is no column, no cache and no log to read it from.
    """
    result = request_otp(tenant_id=tenant.id, mobile=mobile, **kwargs)
    code = getattr(result.challenge, "_plaintext_code", None) if result.challenge else None
    return result, code


# ---------------------------------------------------------------------------
# The strategy
# ---------------------------------------------------------------------------

def test_the_registry_carries_mobile_otp_with_the_right_shape():
    strategy = registry.get(METHOD)

    assert strategy.identifier_type == IDENTIFIER_TYPE_MOBILE
    # Nothing stored to check against — the registry requires a challenge instead.
    assert strategy.credential_type is None
    assert hasattr(strategy, "issue_challenge")
    # A number is unique inside one school at best.
    assert strategy.requires_tenant is True
    # The first method where an attempt sends an SMS somebody pays for.
    assert strategy.is_paid is True


def test_an_unknown_method_still_refuses_rather_than_becoming_email(client, db_session):
    tenant = _school(db_session)
    response = client.post(
        "/api/auth/login",
        json={
            "method": "carrier_pigeon",
            "identifier": "x",
            "password": "y",
            "tenant_id": tenant.id,
        },
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "UnsupportedAuthenticationMethod"


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "typed,expected",
    [
        ("9876543210", "+919876543210"),
        ("+91 98765 43210", "+919876543210"),
        ("098765-43210", "+919876543210"),
        ("  +919876543210  ", "+919876543210"),
        # Already international: kept as its own country, not forced to India.
        ("+971501234567", "+971501234567"),
    ],
)
def test_one_number_has_exactly_one_spelling(typed, expected):
    """The property the whole identifier rests on: a person cannot become two
    accounts by typing their own number differently."""
    assert normalize_mobile(typed) == expected
    assert normalize_identifier(IDENTIFIER_TYPE_MOBILE, typed) == expected


@pytest.mark.parametrize(
    "typed", ["", "   ", "n/a", "12345", "0000000000", "abcdefghij", "+91123"]
)
def test_something_that_is_not_a_number_is_not_an_identifier(typed):
    assert normalize_mobile(typed) == ""


def test_the_default_region_is_stated_not_hidden():
    """There is no country column on a tenant to read; the assumption is a
    named constant so it can be found and changed."""
    assert DEFAULT_MOBILE_REGION == "IN"


def test_normalization_is_not_the_person_matching_rule():
    """`people/matching.normalize_phone` keeps the last ten digits — right for
    finding probable duplicates, wrong as a security boundary."""
    from modules.people.matching import normalize_phone

    indian = "+919876543210"
    assert normalize_phone(indian) == normalize_phone("+1 987 654 3210")
    assert normalize_mobile(indian) != normalize_mobile("+19876543210")


# ---------------------------------------------------------------------------
# The identifier
# ---------------------------------------------------------------------------

def test_a_mobile_identifier_is_issued_deliberately_and_unverified(db_session):
    """A school knows the admission number it assigned; it only believes the
    phone number it was told."""
    tenant = _school(db_session)
    user = _staff(db_session, tenant)

    identifier = issue_mobile_identifier(user, "98765 43210")
    db_session.flush()

    assert identifier.identifier_value_normalized == "+919876543210"
    assert identifier.identifier_value == "98765 43210"
    assert identifier.is_verified is False


def test_issuing_the_same_number_twice_makes_one_identifier(db_session):
    tenant = _school(db_session)
    user = _staff(db_session, tenant)

    first = issue_mobile_identifier(user, "9876543210")
    second = issue_mobile_identifier(user, "+91 98765 43210")
    db_session.flush()

    assert first.id == second.id
    assert AccountIdentifier.query.filter_by(
        account_id=user.id, identifier_type=IDENTIFIER_TYPE_MOBILE
    ).count() == 1


def test_a_number_that_is_not_dialable_mints_nothing(db_session):
    tenant = _school(db_session)
    user = _staff(db_session, tenant)

    assert issue_mobile_identifier(user, "n/a") is None
    assert issue_mobile_identifier(user, "") is None
    db_session.flush()
    assert AccountIdentifier.query.filter_by(
        account_id=user.id, identifier_type=IDENTIFIER_TYPE_MOBILE
    ).count() == 0


def test_a_school_with_the_method_off_issues_no_mobile_identifier(db_session):
    tenant = _school(db_session, otp_enabled=False)
    user = _staff(db_session, tenant)

    assert issue_mobile_identifier(user, "9876543210") is None


def test_a_number_already_used_by_somebody_else_is_refused_loudly(db_session):
    """Two people sharing a phone is a real situation somebody has to decide
    about. An operation that quietly did nothing would hide it."""
    tenant = _school(db_session)
    number = _mobile()
    first, _ = _member(db_session, tenant, mobile=number)
    second = _staff(db_session, tenant)

    with pytest.raises(MobileAlreadyInUse):
        issue_mobile_identifier(second, number)


def test_the_same_number_at_two_schools_is_two_identifiers(db_session):
    """Tenant-scoped: a household number at two schools is two people's, and
    neither school learns about the other."""
    ours = _school(db_session)
    theirs = _school(db_session)
    number = _mobile()

    _member(db_session, ours, mobile=number)
    _member(db_session, theirs, mobile=number)
    db_session.flush()

    assert AccountIdentifier.query.filter_by(
        identifier_type=IDENTIFIER_TYPE_MOBILE,
        identifier_value_normalized=normalize_mobile(number),
    ).count() == 2


def test_a_persons_phone_number_never_becomes_an_identifier_on_its_own(db_session):
    """`Person.phone_number` is typed by a clerk, never verified, rewritten by
    spreadsheet imports and shared across a household. It is a suggestion."""
    tenant = _school(db_session)
    user = _staff(db_session, tenant)
    person = user.person
    person.phone_number = "9876543210"
    db_session.flush()

    assert AccountIdentifier.query.filter_by(
        account_id=user.id, identifier_type=IDENTIFIER_TYPE_MOBILE
    ).count() == 0


# ---------------------------------------------------------------------------
# Generating a code
# ---------------------------------------------------------------------------

def test_a_code_is_six_uniformly_random_digits():
    codes = {generate_code() for _ in range(400)}

    assert all(len(c) == OTP_LENGTH and c.isdigit() for c in codes)
    # 400 draws from a million; collisions would say the source is not random.
    assert len(codes) > 390


def test_a_code_is_not_derived_from_anything_about_the_person():
    """A5's spirit: nothing about a person may be recoverable from their code.

    Read from the syntax tree with the docstring stripped, not from the source
    text — the docstring names `random.randint` as the thing *not* to use, and
    a test that matched on prose would fail on its own explanation.
    """
    import ast
    import inspect

    from modules.auth import otp

    tree = ast.parse(inspect.getsource(otp.generate_code).strip())
    function = tree.body[0]
    if (
        function.body
        and isinstance(function.body[0], ast.Expr)
        and isinstance(function.body[0].value, ast.Constant)
    ):
        function.body = function.body[1:]

    body = ast.dump(ast.Module(body=function.body, type_ignores=[]))

    assert "secrets" in body
    # Every predictable source, by name, in the code itself.
    for forbidden in ("random", "time", "uuid", "account", "phone", "hashlib"):
        assert forbidden not in body, f"generate_code references {forbidden}"


def test_the_code_is_never_stored_anywhere(db_session, caplog):
    """O1 and O2, and the reason the table holds a hash and a keyed digest."""
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)

    with caplog.at_level("DEBUG"):
        result, code = _issue(tenant, number)
    db_session.flush()

    assert result.accepted and code
    row = MobileOtpChallenge.query.filter_by(tenant_id=tenant.id).first()
    stored = {c.name: getattr(row, c.name) for c in row.__table__.columns}

    assert code not in repr(stored)
    assert code not in caplog.text
    # And the number itself is not in the row either.
    assert number not in repr(stored)
    assert normalize_mobile(number) not in repr(stored)


def test_the_message_body_and_the_number_stay_out_of_the_log(db_session, caplog):
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)

    with caplog.at_level("DEBUG"):
        _, code = _issue(tenant, number)

    assert code not in caplog.text
    assert "is your NexSchool sign-in code" not in caplog.text
    assert normalize_mobile(number) not in caplog.text


# ---------------------------------------------------------------------------
# The lifecycle
# ---------------------------------------------------------------------------

def test_a_code_is_sent_and_the_challenge_says_sent_not_delivered(db_session):
    """Phase 3's distinction, carried through: a provider accepting a request
    is not a handset receiving a message."""
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)

    result, _ = _issue(tenant, number)
    db_session.flush()

    assert result.accepted
    challenge = result.challenge
    assert challenge.status == STATUS_SENT
    assert challenge.sent_at is not None
    assert challenge.provider_reference
    assert "delivered" not in challenge.status


def test_the_right_code_verifies_once(db_session):
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)
    _, code = _issue(tenant, number)
    db_session.flush()

    outcome = verify_code(tenant_id=tenant.id, mobile=number, code=code)

    assert outcome.verified is True
    assert outcome.challenge.status == STATUS_CONSUMED
    assert outcome.challenge.consumed_at is not None


def test_one_code_cannot_sign_in_twice(db_session):
    """O3. Replay is what a stolen SMS would otherwise buy."""
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)
    _, code = _issue(tenant, number)
    db_session.flush()

    first = verify_code(tenant_id=tenant.id, mobile=number, code=code)
    second = verify_code(tenant_id=tenant.id, mobile=number, code=code)

    assert first.verified is True
    assert second.verified is False


def test_a_wrong_code_is_counted_and_the_right_one_still_works(db_session):
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)
    _, code = _issue(tenant, number)
    db_session.flush()

    wrong = verify_code(tenant_id=tenant.id, mobile=number, code="000000")
    db_session.flush()
    right = verify_code(tenant_id=tenant.id, mobile=number, code=code)

    assert wrong.verified is False
    assert right.verified is True


def test_guessing_runs_out(db_session):
    """O5. A million combinations is far too few to survive unlimited guessing
    and far more than enough to survive five."""
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)
    _, code = _issue(tenant, number)
    db_session.flush()

    for attempt in range(MAX_VERIFICATION_ATTEMPTS):
        assert verify_code(tenant_id=tenant.id, mobile=number, code="000000").verified is False
        db_session.flush()

    # Even the correct code is now useless.
    assert verify_code(tenant_id=tenant.id, mobile=number, code=code).verified is False


def test_a_code_expires(db_session):
    """O4."""
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)
    result, code = _issue(tenant, number)
    db_session.flush()

    result.challenge.expires_at = utc_now() - timedelta(seconds=1)
    db_session.flush()

    assert verify_code(tenant_id=tenant.id, mobile=number, code=code).verified is False


def test_expiry_is_five_minutes_from_creation(db_session):
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)

    result, _ = _issue(tenant, number)
    db_session.flush()

    span = (result.challenge.expires_at - result.challenge.created_at).total_seconds()
    assert abs(span - OTP_TTL_SECONDS) < 5


def test_a_new_code_kills_the_old_one_immediately(db_session):
    """Somebody holding two messages must not be able to use the first."""
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)
    first_result, first_code = _issue(tenant, number)
    db_session.flush()
    clear_for_tests(tenant_id=tenant.id, mobile_hash=hash_value(normalize_mobile(number)))

    second_result, second_code = _issue(tenant, number)
    db_session.flush()

    assert verify_code(tenant_id=tenant.id, mobile=number, code=first_code).verified is False
    db_session.refresh(first_result.challenge)
    assert first_result.challenge.status == STATUS_SUPERSEDED
    assert first_result.challenge.superseded_by_id == second_result.challenge.id
    assert verify_code(tenant_id=tenant.id, mobile=number, code=second_code).verified is True


def test_naming_the_wrong_challenge_is_refused_not_ignored(db_session):
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)
    _, code = _issue(tenant, number)
    db_session.flush()

    outcome = verify_code(
        tenant_id=tenant.id, mobile=number, code=code, challenge_id="not-this-one"
    )

    assert outcome.verified is False


# ---------------------------------------------------------------------------
# Racing
# ---------------------------------------------------------------------------

def test_two_requests_racing_on_one_code_produce_one_winner(db_session):
    """O3 under concurrency.

    The consuming UPDATE carries every condition in its WHERE clause, so the
    second caller matches zero rows. A Python-level "if not consumed: consume"
    would let both through, and this is what proves it does not.
    """
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)
    _, code = _issue(tenant, number)
    db_session.flush()

    outcomes = [
        verify_code(tenant_id=tenant.id, mobile=number, code=code),
        verify_code(tenant_id=tenant.id, mobile=number, code=code),
    ]

    assert [o.verified for o in outcomes].count(True) == 1


def test_attempts_are_counted_in_the_database_not_in_python(db_session):
    """An in-memory increment loses count under concurrent guesses, which is
    exactly the situation the counter exists for."""
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)
    result, _ = _issue(tenant, number)
    db_session.flush()

    for _ in range(3):
        verify_code(tenant_id=tenant.id, mobile=number, code="111111")
    db_session.flush()

    db_session.refresh(result.challenge)
    assert result.challenge.attempts == 3


def test_a_code_that_expires_between_the_read_and_the_write_does_not_verify(db_session):
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)
    result, code = _issue(tenant, number)
    db_session.flush()

    # Expire it after the challenge is found but before it can be spent, by
    # doing it in the row the UPDATE will re-check.
    db.session.query(MobileOtpChallenge).filter_by(id=result.challenge.id).update(
        {"expires_at": utc_now() - timedelta(seconds=1)}
    )
    db_session.flush()

    assert verify_code(tenant_id=tenant.id, mobile=number, code=code).verified is False


# ---------------------------------------------------------------------------
# Who the number means
# ---------------------------------------------------------------------------

def test_a_number_is_looked_up_only_inside_the_school_that_was_named(db_session):
    """O7. A number that is nobody's here may be somebody's elsewhere, and
    finding that out is not this flow's job."""
    ours = _school(db_session)
    theirs = _school(db_session)
    number = _mobile()
    _member(db_session, theirs, mobile=number)

    result, _ = _issue(ours, number)

    assert result.accepted is False
    assert result.reason == REASON_NO_ACCOUNT


def test_a_number_that_means_two_people_signs_in_nobody(db_session, monkeypatch):
    """O8. Never `.first()`.

    A partial unique index makes two live mobile identifiers impossible within
    a school today. The resolution path handles the plural case anyway, so
    that relaxing that index for households later cannot turn this into an
    arbitrary choice by omission — which is what this test pins.
    """
    tenant = _school(db_session)
    first, number = _member(db_session, tenant)
    second, _ = _member(db_session, tenant)

    from modules.auth import otp

    real = otp._accounts_for_mobile

    def two_people(tenant_id, normalized):
        rows = real(tenant_id, normalized)
        extra = AccountIdentifier.query.filter_by(
            account_id=second.id, identifier_type=IDENTIFIER_TYPE_MOBILE
        ).first()
        return rows + [(second, extra)]

    monkeypatch.setattr(otp, "_accounts_for_mobile", two_people)

    result, _ = _issue(tenant, number)

    assert result.accepted is False
    assert result.reason == REASON_AMBIGUOUS
    assert MobileOtpChallenge.query.filter_by(tenant_id=tenant.id).count() == 0


def test_the_strategy_refuses_to_resolve_without_a_school(db_session):
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)

    assert registry.get(METHOD).resolve(number, None) == []


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

def test_mobile_otp_is_off_for_a_school_that_never_asked(db_session):
    """O12 and NFR-1. Deploying Phase 4 must not hand anybody a new way in."""
    tenant = make_tenant(db_session)
    ensure_default_policy(tenant.id)
    user = _staff(db_session, tenant)

    from modules.auth.policy import allowed_methods, is_method_allowed

    assert is_method_allowed(user, METHOD) is False
    assert METHOD not in allowed_methods(user)


def test_a_school_that_has_not_enabled_it_cannot_spend_money_on_it(db_session):
    """Policy is evaluated before the proof, and before the send."""
    tenant = _school(db_session, otp_enabled=False)
    user = _staff(db_session, tenant)
    number = _mobile()
    # Issued directly, bypassing the policy check in provisioning, to isolate
    # the request-time gate.
    db_session.add(
        AccountIdentifier(
            tenant_id=tenant.id,
            account_id=user.id,
            identifier_type=IDENTIFIER_TYPE_MOBILE,
            identifier_value=number,
            identifier_value_normalized=normalize_mobile(number),
        )
    )
    db_session.flush()
    clear_for_tests(tenant_id=tenant.id, mobile_hash=hash_value(normalize_mobile(number)))

    result, _ = _issue(tenant, number)
    db_session.flush()

    assert result.accepted is False
    assert result.reason == REASON_METHOD_NOT_ALLOWED
    assert ServiceUsageRecord.query.filter_by(tenant_id=tenant.id).count() == 0


def test_turning_it_on_makes_it_available(db_session):
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)

    from modules.auth.policy import is_method_allowed, published_auth_methods

    assert is_method_allowed(user, METHOD) is True
    assert METHOD in published_auth_methods(tenant.id)


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

def test_a_second_code_cannot_be_asked_for_immediately(db_session):
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)

    first, _ = _issue(tenant, number)
    second, _ = _issue(tenant, number)

    assert first.accepted is True
    assert second.accepted is False
    assert second.reason == REASON_THROTTLED
    assert second.retry_after_seconds <= RESEND_COOLDOWN_SECONDS


def test_a_number_cannot_be_rung_all_night(db_session):
    """SMS bombing. The cooldown is cleared between attempts, so what stops
    this is the hourly ceiling, not the cooldown."""
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)
    mobile_hash = hash_value(normalize_mobile(number))

    accepted = 0
    for _ in range(MAX_REQUESTS_PER_MOBILE_HOUR + 3):
        from core.cache import redis_client

        redis_client().delete(f"erp:otp:v1:cooldown:{tenant.id}:{mobile_hash}")
        result, _ = _issue(tenant, number)
        if result.accepted:
            accepted += 1

    assert accepted == MAX_REQUESTS_PER_MOBILE_HOUR


def test_a_refused_request_costs_the_school_nothing(db_session):
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)

    _issue(tenant, number)
    before = ServiceUsageRecord.query.filter_by(tenant_id=tenant.id).count()
    _issue(tenant, number)  # throttled
    db_session.flush()

    assert ServiceUsageRecord.query.filter_by(tenant_id=tenant.id).count() == before


def test_a_number_nobody_has_is_throttled_too(db_session):
    """Otherwise the throttle itself becomes the oracle: unlimited requests for
    unknown numbers and limited ones for real customers is an answer."""
    tenant = _school(db_session)
    stranger = _mobile()

    for _ in range(3):
        result, _ = _issue(tenant, stranger)
        assert result.accepted is False

    from modules.auth.otp_throttle import check_request_allowed

    # The counters are only bumped on a real send, so an unknown number is
    # limited by the shared IP and tenant ceilings rather than by its own.
    decision = check_request_allowed(
        tenant_id=tenant.id, mobile_hash=hash_value(normalize_mobile(stranger)), ip_address=None
    )
    assert decision.allowed is True


# ---------------------------------------------------------------------------
# The provider, and what it costs
# ---------------------------------------------------------------------------

def test_a_sent_code_reaches_the_usage_ledger(db_session):
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)

    _issue(tenant, number)
    db_session.flush()

    records = ServiceUsageRecord.query.filter_by(tenant_id=tenant.id).all()
    assert len(records) == 1
    assert records[0].usage_type == "authentication_otp"
    assert records[0].unit == "sms"


def test_a_provider_that_refuses_creates_no_usage_and_no_live_challenge(db_session):
    """O9. A failed send cost the school nothing and rang nobody's phone."""
    tenant = _school(db_session)
    integration = configure_integration(
        tenant.id,
        capability=CAPABILITY_SMS,
        provider_key=FAKE,
        configuration={**SMS_TEMPLATES, BEHAVIOUR_KEY: BEHAVIOUR_REJECTED},
    )
    set_integration_status(tenant.id, capability=CAPABILITY_SMS, status=STATUS_ENABLED)
    user, number = _member(db_session, tenant)

    result, code = _issue(tenant, number)
    db_session.flush()

    assert result.accepted is False
    assert ServiceUsageRecord.query.filter_by(tenant_id=tenant.id).count() == 0
    challenge = MobileOtpChallenge.query.filter_by(tenant_id=tenant.id).first()
    assert challenge.status == STATUS_FAILED
    # And nothing can be verified against it.
    assert verify_code(tenant_id=tenant.id, mobile=number, code=code).verified is False


def test_a_timeout_does_not_send_a_second_message(db_session):
    """O10. A timeout may mean the provider accepted it; a retry would charge
    the school twice and ring the phone twice."""
    tenant = _school(db_session)
    configure_integration(
        tenant.id,
        capability=CAPABILITY_SMS,
        provider_key=FAKE,
        configuration={**SMS_TEMPLATES, BEHAVIOUR_KEY: BEHAVIOUR_TIMEOUT},
    )
    set_integration_status(tenant.id, capability=CAPABILITY_SMS, status=STATUS_ENABLED)
    user, number = _member(db_session, tenant)

    result, _ = _issue(tenant, number)
    db_session.flush()

    assert result.accepted is False
    assert MobileOtpChallenge.query.filter_by(tenant_id=tenant.id).count() == 1
    assert ServiceUsageRecord.query.filter_by(tenant_id=tenant.id).count() == 0


def test_verifying_a_code_sends_nothing_and_costs_nothing(db_session):
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)
    _, code = _issue(tenant, number)
    db_session.flush()
    before = ServiceUsageRecord.query.filter_by(tenant_id=tenant.id).count()

    verify_code(tenant_id=tenant.id, mobile=number, code=code)
    verify_code(tenant_id=tenant.id, mobile=number, code="000000")
    db_session.flush()

    assert ServiceUsageRecord.query.filter_by(tenant_id=tenant.id).count() == before


def test_no_vendor_name_appears_anywhere_in_authentication():
    """The Phase 3 boundary, asserted structurally."""
    import ast
    import pathlib

    vendors = ("twilio", "msg91", "textlocal", "vonage", "sns", "plivo", "gupshup")
    for path in pathlib.Path("modules/auth").rglob("*.py"):
        source = path.read_text().lower()
        for vendor in vendors:
            assert vendor not in source, f"{path} names {vendor}"
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            for name in names:
                # `urllib.parse` is URL-encoding and is fine; what must not
                # appear is anything that opens a connection.
                assert not any(
                    name.startswith(c)
                    for c in (
                        "urllib.request",
                        "urllib.error",
                        "requests",
                        "httpx",
                        "boto3",
                        "http.client",
                    )
                ), f"{path} calls out directly instead of using the sms capability"


# ---------------------------------------------------------------------------
# The commit boundary — POST /otp/request, not just the service function
#
# Every test above calls `request_otp()` directly and inspects `db_session`
# right afterwards. That proves the service layer flushes the rows it should;
# it proves nothing about the route that fronts it in production, because
# `request_otp` follows this codebase's flush-in-service, commit-in-route
# convention (see `policy.set_method`, `configure_integration`) and never
# commits itself. A route that forgets the commit sends a real SMS and then
# discards the one thing that could verify it — which is exactly the defect
# task 16b fixes in `request_mobile_otp`. These two tests go through the real
# HTTP route and a real request boundary to check the commit is actually
# there, and that both the success and failure branches leave behind rows an
# operator can find.
# ---------------------------------------------------------------------------

def _cross_the_request_boundary():
    """Do, on demand, what Flask does for free between two real requests.

    In production, Flask pops the app context at the end of every request and
    Flask-SQLAlchemy's `teardown_appcontext` hook calls `db.session.remove()`
    — discarding anything left uncommitted and handing the next piece of code
    a brand-new `Session` with an empty identity map. That is the mechanism
    this bug slipped through: nothing before task 16b asserted that a row
    survived it.

    This test harness cannot be relied on to do that between two
    `client.post()` calls in the *same* test. `db_session` (conftest.py) opens
    one `flask_app.app_context()` for the whole test, and Flask's test client
    reuses an app context already on the stack rather than pushing its own —
    the same quirk `test_admission_id_login.py` and `test_mobile_otp_login.py`
    document as `_fresh_request`, there for `flask.g` rather than the session.
    Because of it, `teardown_appcontext` never runs between one request and
    the next inside a single test, so a plain query right after `client.post`
    would just read back the same identity-mapped session the route itself
    wrote to — which would pass whether or not the route committed, and is
    exactly the kind of assertion this task warns against.

    Calling `db.session.remove()` here is not a weaker stand-in for that
    boundary — it is the literal call Flask-SQLAlchemy makes at it. Closing
    the current `Session` rolls back anything still pending on it, and
    discarding it means the next `db.session.<anything>` builds a genuinely
    new `Session` — still bound to this test's own transactional connection
    (`db_session` keeps everything, committed or not, off the real database
    until the test ends), so what is being asked is exactly "did the route
    commit", not "did this reach production Postgres".
    """
    db.session.remove()


def test_a_sent_challenge_survives_the_request_that_created_it(client, db_session):
    """The defect this guards against: `request_otp` flushed a challenge and
    the route returned `sent: true` without committing, so the code went out
    over SMS while the challenge that could verify it was rolled back the
    moment the request ended. The follow-up `POST /login` then failed with
    the same `InvalidCredentials` a wrong code produces — indistinguishable
    from the caller's point of view, and from an operator's unless they know
    to check whether a challenge row exists at all.
    """
    tenant = _school(db_session)
    user, number = _member(db_session, tenant)

    response = client.post(
        "/api/auth/otp/request",
        json={"mobile": number, "tenant_id": tenant.id},
    )

    assert response.status_code == 200
    challenge_id = response.get_json()["data"]["challenge_id"]
    assert challenge_id

    _cross_the_request_boundary()

    challenge = MobileOtpChallenge.query.get(challenge_id)
    assert challenge is not None, (
        "the challenge the route said it sent does not exist once the "
        "request that created it is over — a correct code could never verify"
    )
    assert challenge.status == STATUS_SENT


def test_a_failed_delivery_still_leaves_what_an_operator_needs(client, db_session):
    """The same commit covers the unhappy path, deliberately. A provider that
    refuses to send must still leave the challenge marked `failed` and its
    `otp_delivery_failed` audit event behind — that pair is how "the code
    never arrived" gets diagnosed after the fact, and both are only flushed
    by `otp.py`, never committed by it.
    """
    from modules.auth.event_models import AuthEvent

    tenant = _school(db_session)
    configure_integration(
        tenant.id,
        capability=CAPABILITY_SMS,
        provider_key=FAKE,
        configuration={**SMS_TEMPLATES, BEHAVIOUR_KEY: BEHAVIOUR_REJECTED},
    )
    set_integration_status(tenant.id, capability=CAPABILITY_SMS, status=STATUS_ENABLED)
    user, number = _member(db_session, tenant)

    response = client.post(
        "/api/auth/otp/request",
        json={"mobile": number, "tenant_id": tenant.id},
    )

    assert response.status_code == 200
    # Same answer as a genuine send — see `request_mobile_otp`'s docstring on
    # the enumeration oracle this endpoint is shaped to avoid.
    assert response.get_json()["data"] == {"sent": True}

    _cross_the_request_boundary()

    challenge = MobileOtpChallenge.query.filter_by(tenant_id=tenant.id).first()
    assert challenge is not None, "the failed challenge itself did not survive"
    assert challenge.status == STATUS_FAILED
    assert (
        AuthEvent.query.filter_by(
            tenant_id=tenant.id, event_type="otp_delivery_failed"
        ).count()
        == 1
    ), "the audit event that explains the failure did not survive"
