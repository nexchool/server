"""Phase 5 — a student signs in with a mobile number and a PIN.

Six digits is a million values. That is a number an offline attacker exhausts
in seconds and an online one never reaches, provided the online path counts —
so most of what is tested here is the counting, and the rest is that a PIN is
genuinely its own credential rather than a password wearing a different name.

The assertions worth reading first:

  * `test_a_wrong_pin_is_counted_and_guessing_runs_out` — P3, and the whole
    security of the method.
  * `test_a_pin_and_a_password_live_side_by_side_untouched` — P4/P9: the
    credential model already allowed both, and neither reset disturbs the other.
  * `test_only_a_student_can_sign_in_with_a_pin` — the product scope, enforced
    twice over.
  * `test_signing_in_with_a_pin_sends_nothing_and_costs_nothing` — P8.
"""

from __future__ import annotations

import uuid

import pytest
from werkzeug.security import check_password_hash

from core.database import db
from modules.auth.credential_admin import (
    SKIP_ALREADY_HAD_CREDENTIAL,
    SKIP_METHOD_NOT_ENABLED,
    SKIP_NO_CREDENTIAL,
    bulk_issue_pins,
    credential_status,
    force_pin_change,
    issue_pin,
)
from modules.auth.identifiers import normalize_mobile
from modules.auth.models import AccountCredential, AccountIdentifier, Session
from modules.auth.otp_throttle import hash_value
from modules.auth.pin import (
    PIN_LENGTH,
    TRIVIAL_PINS,
    InvalidPin,
    WeakPin,
    generate_pin,
    is_trivial,
    validate_pin,
)
from modules.auth.pin_throttle import (
    MAX_FAILURES_PER_MOBILE_HOUR,
    clear_for_tests,
)
from modules.auth.policy import ensure_default_policy, is_method_allowed, set_method
from modules.auth.provisioning import issue_mobile_identifier, live_pin_credential
from modules.auth.strategies import registry
from modules.auth.strategies.mobile_pin import MobilePinStrategy
from modules.billing.models import ServiceUsageRecord
from modules.people.models import Person
from modules.students.models import Student
from tests.auth._characterization import (
    decode_access_token,
    grant_permissions,
    make_tenant,
    make_user,
    new_id,
    sessions_for,
)

METHOD = MobilePinStrategy.key
OTP_METHOD = "mobile_otp"


@pytest.fixture(autouse=True)
def _reachable_redis(flask_app):
    """The PIN throttle fails closed, so a suite with no Redis would refuse
    every attempt and pass for the wrong reason."""
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
            pytest.skip("mobile PIN needs a reachable Redis for its rate limiter")

        # Every test-client request comes from 127.0.0.1; without this the
        # suite throttles itself, and across runs, because Redis remembers.
        clear_for_tests(tenant_id="", ip_address="127.0.0.1")

    yield
    flask_app.config["REDIS_URL"] = previous_url
    cache._pool = previous_pool


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _mobile() -> str:
    return f"+9198{uuid.uuid4().int % 100000000:08d}"


def _fresh_request(flask_app):
    """Forget the school the previous request resolved — a harness artefact,
    documented at length in `test_admission_id_login.py`."""
    from flask import g as flask_g

    for attribute in ("tenant_id", "tenant", "current_user"):
        if hasattr(flask_g, attribute):
            delattr(flask_g, attribute)


def _school(db_session, *, pin_enabled=True):
    tenant = make_tenant(db_session)
    ensure_default_policy(tenant.id)
    if pin_enabled:
        # Students only — the product scope, expressed in policy.
        set_method(tenant.id, "student", METHOD, enabled=True)
    db_session.flush()
    return tenant


def _student(db_session, tenant, *, mobile=None, with_pin=False):
    """A child of the school, with an account and a mobile identifier."""
    account = make_user(db_session, tenant, password="Password123")
    grant_permissions(db_session, tenant, account, ("student.read.self",))
    student = Student(
        id=new_id("s-"),
        tenant_id=tenant.id,
        user_id=account.id,
        person_id=account.person_id,
        admission_number=f"ADM-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(student)
    db_session.flush()

    number = mobile or _mobile()
    issue_mobile_identifier(account, number)
    db_session.flush()
    clear_for_tests(
        tenant_id=tenant.id, mobile_hash=hash_value(normalize_mobile(number))
    )

    pin = None
    if with_pin:
        pin = issue_pin(student)["pin"]
        db_session.flush()
    return student, account, number, pin


def _staff(db_session, tenant, *, mobile=None):
    """Somebody the school employs, and nobody's child."""
    account = make_user(db_session, tenant, password="Password123")
    grant_permissions(db_session, tenant, account, ("student.read.all",))
    number = mobile or _mobile()
    issue_mobile_identifier(account, number)
    db_session.flush()
    return account, number


def _sign_in(client, flask_app, tenant, *, number, pin):
    _fresh_request(flask_app)
    return client.post(
        "/api/auth/login",
        json={
            "method": METHOD,
            "identifier": number,
            "password": pin,
            "tenant_id": tenant.id,
        },
    )


# ---------------------------------------------------------------------------
# The method
# ---------------------------------------------------------------------------

def test_the_registry_carries_mobile_pin_with_the_right_shape():
    strategy = registry.get(METHOD)

    assert strategy.identifier_type == "mobile"
    # Its own credential type, not the password's.
    assert strategy.credential_type == "pin"
    assert strategy.requires_tenant is True
    # Nothing is sent, so nothing is billed.
    assert strategy.is_paid is False


def test_a_pin_login_is_not_reported_as_something_else(client, db_session, flask_app):
    tenant = _school(db_session)
    student, account, number, pin = _student(db_session, tenant, with_pin=True)

    _sign_in(client, flask_app, tenant, number=number, pin=pin)
    db_session.flush()

    session = sessions_for(account.id)[-1]
    assert session.login_method == METHOD
    assert session.login_method not in ("email_password", "mobile_otp")


# ---------------------------------------------------------------------------
# What a PIN may be
# ---------------------------------------------------------------------------

def test_a_pin_is_six_digits_and_leading_zeros_survive():
    assert validate_pin("000123") == "000123"
    assert len(generate_pin()) == PIN_LENGTH
    assert all(generate_pin().isdigit() for _ in range(20))


def test_a_pin_is_never_treated_as_a_number(db_session):
    """`000123` parsed as an integer becomes `123` — a different, shorter
    secret, and one that would collide with anybody who chose it."""
    tenant = _school(db_session)
    student, account, _, _ = _student(db_session, tenant)

    from modules.auth.provisioning import issue_pin_credential

    issue_pin_credential(account, "000123")
    db_session.flush()

    credential = live_pin_credential(account)
    assert check_password_hash(credential.secret_hash, "000123")
    assert not check_password_hash(credential.secret_hash, "123")


@pytest.mark.parametrize("bad", ["12345", "1234567", "abcdef", "12 34 56", "", "12345a"])
def test_something_that_is_not_six_digits_is_not_a_pin(bad):
    with pytest.raises(InvalidPin):
        validate_pin(bad)


@pytest.mark.parametrize(
    "weak", ["000000", "111111", "123456", "654321", "123123", "112233", "121212"]
)
def test_the_obvious_pins_are_refused(weak):
    """Against a limited number of online guesses, an attacker spends them on
    the handful of values people actually pick."""
    assert is_trivial(weak)
    with pytest.raises(WeakPin):
        validate_pin(weak)


def test_a_real_pin_is_not_refused():
    for ordinary in ("142857", "904312", "738261", "580394"):
        assert validate_pin(ordinary) == ordinary


def test_a_generated_pin_is_never_a_trivial_one():
    generated = {generate_pin() for _ in range(600)}

    assert not (generated & TRIVIAL_PINS)
    # 600 draws from a million; heavy collision would say the source is weak.
    assert len(generated) > 590


def test_a_pin_is_not_derived_from_anything_about_the_person():
    """P10 / A5, read from the syntax tree rather than the prose — the
    docstring names the things not to use."""
    import ast
    import inspect

    from modules.auth import pin as pin_module

    tree = ast.parse(inspect.getsource(pin_module.generate_pin).strip())
    function = tree.body[0]
    if isinstance(function.body[0], ast.Expr):
        function.body = function.body[1:]
    body = ast.dump(ast.Module(body=function.body, type_ignores=[]))

    assert "secrets" in body
    for forbidden in ("random", "time", "uuid", "account", "phone", "admission", "birth"):
        assert forbidden not in body


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def test_a_pin_is_never_stored_or_logged(db_session, caplog):
    """P1 and P2."""
    tenant = _school(db_session)
    student, account, _, _ = _student(db_session, tenant)

    with caplog.at_level("DEBUG"):
        pin = issue_pin(student)["pin"]
    db_session.flush()

    credential = live_pin_credential(account)
    stored = {c.name: getattr(credential, c.name) for c in credential.__table__.columns}

    assert pin not in repr(stored)
    assert pin not in caplog.text
    assert credential.secret_hash != pin


def test_a_pin_is_hashed_the_way_a_password_is(db_session):
    """Shorter, not less valuable. A weaker hash chosen because the input is
    short is how a database leak becomes a million recovered PINs."""
    tenant = _school(db_session)
    student, account, _, pin = _student(db_session, tenant, with_pin=True)

    credential = live_pin_credential(account)
    assert credential.hash_algorithm
    assert credential.hash_algorithm == account.password_hash.split("$", 1)[0][:40]
    assert check_password_hash(credential.secret_hash, pin)


def test_no_read_path_can_produce_a_pin(db_session):
    tenant = _school(db_session)
    student, account, _, pin = _student(db_session, tenant, with_pin=True)
    db_session.flush()

    status = credential_status(student)

    assert status["pin"]["issued"] is True
    assert pin not in repr(status)
    assert "secret_hash" not in repr(status)


# ---------------------------------------------------------------------------
# A PIN is not a password
# ---------------------------------------------------------------------------

def test_a_pin_and_a_password_live_side_by_side_untouched(db_session):
    """P4/P9. The credential table has allowed both since it was created; this
    proves neither reset disturbs the other."""
    tenant = _school(db_session)
    student, account, _, pin = _student(db_session, tenant, with_pin=True)
    from modules.auth.provisioning import issue_password_credential

    issue_password_credential(account, "Password123")
    db_session.flush()

    live = AccountCredential.query.filter_by(account_id=account.id).filter(
        AccountCredential.deleted_at.is_(None)
    ).all()

    assert {c.credential_type for c in live} == {"password", "pin"}
    assert account.check_password("Password123")
    assert check_password_hash(live_pin_credential(account).secret_hash, pin)


def test_changing_a_password_leaves_the_pin_alone(db_session):
    """`person_link`'s sync mirrors the account's hash into the *password*
    credential specifically."""
    tenant = _school(db_session)
    student, account, _, pin = _student(db_session, tenant, with_pin=True)
    before = live_pin_credential(account).secret_hash

    account.set_password("SomethingElse99")
    db_session.flush()

    assert live_pin_credential(account).secret_hash == before
    assert check_password_hash(live_pin_credential(account).secret_hash, pin)


def test_resetting_a_pin_leaves_the_password_alone(db_session):
    tenant = _school(db_session)
    student, account, _, _ = _student(db_session, tenant, with_pin=True)

    issue_pin(student, reset=True)
    db_session.flush()

    assert account.check_password("Password123")


def test_a_pin_force_change_says_nothing_about_the_password(db_session):
    """§16: `must_change` is per credential, so one requirement is not the
    other."""
    tenant = _school(db_session)
    student, account, _, _ = _student(db_session, tenant, with_pin=True)

    force_pin_change(student)
    db_session.flush()

    assert live_pin_credential(account).must_change is True
    assert account.force_password_reset is False
    password_credential = AccountCredential.query.filter_by(
        account_id=account.id, credential_type="password"
    ).first()
    if password_credential is not None:
        assert password_credential.must_change is False


def test_issuing_a_pin_does_not_clear_a_password_change_requirement(db_session):
    tenant = _school(db_session)
    student, account, _, _ = _student(db_session, tenant)
    account.force_password_reset = True
    db_session.flush()

    issue_pin(student)
    db_session.flush()

    assert account.force_password_reset is True


# ---------------------------------------------------------------------------
# Issuing and resetting
# ---------------------------------------------------------------------------

def test_issuing_twice_does_not_take_away_a_working_pin(db_session):
    tenant = _school(db_session)
    student, account, _, pin = _student(db_session, tenant, with_pin=True)

    again = issue_pin(student)
    db_session.flush()

    assert again["status"] == "skipped"
    assert again["reason"] == SKIP_ALREADY_HAD_CREDENTIAL
    assert check_password_hash(live_pin_credential(account).secret_hash, pin)


def test_a_reset_replaces_the_pin_and_ends_the_sessions_using_it(db_session):
    tenant = _school(db_session)
    student, account, _, old = _student(db_session, tenant, with_pin=True)
    db_session.add(
        Session(
            id=new_id("sess-"),
            tenant_id=tenant.id,
            user_id=account.id,
            refresh_token=new_id("rt-"),
        )
    )
    db_session.flush()

    result = issue_pin(student, reset=True)
    db_session.flush()

    assert result["status"] == "reset"
    assert result["sessions_revoked"] == 1
    credential = live_pin_credential(account)
    assert not check_password_hash(credential.secret_hash, old)
    assert check_password_hash(credential.secret_hash, result["pin"])


def test_a_reset_rotates_one_row_rather_than_making_a_second(db_session):
    """§31: one live credential of a type per account, which the unique index
    enforces and this proves the service honours."""
    tenant = _school(db_session)
    student, account, _, _ = _student(db_session, tenant, with_pin=True)
    first = live_pin_credential(account).id

    issue_pin(student, reset=True)
    issue_pin(student, reset=True)
    db_session.flush()

    live = AccountCredential.query.filter_by(
        account_id=account.id, credential_type="pin"
    ).filter(AccountCredential.deleted_at.is_(None)).all()
    assert len(live) == 1
    assert live[0].id == first


def test_a_reset_leaves_the_mobile_identifier_and_the_admission_number(db_session):
    tenant = _school(db_session)
    student, account, number, _ = _student(db_session, tenant, with_pin=True)
    before = {
        (i.identifier_type, i.identifier_value_normalized)
        for i in AccountIdentifier.query.filter_by(account_id=account.id).all()
    }

    issue_pin(student, reset=True)
    db_session.flush()

    after = {
        (i.identifier_type, i.identifier_value_normalized)
        for i in AccountIdentifier.query.filter(
            AccountIdentifier.account_id == account.id,
            AccountIdentifier.deleted_at.is_(None),
        ).all()
    }
    assert after == before


def test_a_school_that_has_not_enabled_pins_issues_none(db_session):
    tenant = _school(db_session, pin_enabled=False)
    student, account, _, _ = _student(db_session, tenant)

    result = issue_pin(student)
    db_session.flush()

    assert result["status"] == "skipped"
    assert result["reason"] == SKIP_METHOD_NOT_ENABLED
    assert live_pin_credential(account) is None


def test_forcing_a_change_where_there_is_no_pin_is_reported(db_session):
    tenant = _school(db_session)
    student, account, _, _ = _student(db_session, tenant)

    result = force_pin_change(student)

    assert result["status"] == "skipped"
    assert result["reason"] == SKIP_NO_CREDENTIAL


def test_a_class_can_be_given_pins_and_running_it_twice_is_safe(db_session):
    tenant = _school(db_session)
    students = [_student(db_session, tenant)[0] for _ in range(3)]

    first = bulk_issue_pins(students)
    second = bulk_issue_pins(students)
    db_session.flush()

    assert first["issued"] == 3
    assert all(row["pin"] for row in first["pins"])
    assert second["issued"] == 0
    assert second["counts_by_skip_reason"] == {SKIP_ALREADY_HAD_CREDENTIAL: 3}


# ---------------------------------------------------------------------------
# Students only
# ---------------------------------------------------------------------------

def test_only_a_student_can_sign_in_with_a_pin(db_session):
    """Enforced twice: policy grants the method per subject kind, and the
    strategy will not resolve an account that is not a student's."""
    tenant = _school(db_session)
    staff, staff_number = _staff(db_session, tenant)
    from modules.auth.provisioning import issue_pin_credential

    issue_pin_credential(staff, "471926")
    db_session.flush()

    assert registry.get(METHOD).resolve(staff_number, tenant.id) == []
    assert is_method_allowed(staff, METHOD) is False


def test_a_student_who_is_also_staff_is_still_a_student(db_session):
    """A person may hold both relationships; the check is membership, not
    equality."""
    tenant = _school(db_session)
    student, account, number, pin = _student(db_session, tenant, with_pin=True)
    grant_permissions(db_session, tenant, account, ("student.read.all",))
    db_session.flush()

    from modules.auth.policy import subject_kinds

    kinds = subject_kinds(account)
    assert "student" in kinds and "staff" in kinds
    assert len(registry.get(METHOD).resolve(number, tenant.id)) == 1


# ---------------------------------------------------------------------------
# Guessing
# ---------------------------------------------------------------------------

def test_a_wrong_pin_is_counted_and_guessing_runs_out(db_session, flask_app):
    """P3 — the whole security of a six-digit secret."""
    tenant = _school(db_session)
    student, account, number, pin = _student(db_session, tenant, with_pin=True)
    strategy = registry.get(METHOD)

    from modules.auth.strategies.base import ThrottledOut

    with flask_app.test_request_context():
        match = strategy.resolve(number, tenant.id)[0]
        for _ in range(MAX_FAILURES_PER_MOBILE_HOUR):
            assert strategy.verify(match, "999999") is False
        # Even the right PIN is now refused — and refused by *declining to
        # look*, which the strategy signals by raising. The pipeline turns
        # that into the same coarse answer a wrong PIN gets, but does not
        # count it against the account's own lockout.
        with pytest.raises(ThrottledOut):
            strategy.verify(match, pin)


def test_a_right_pin_clears_the_count_against_that_number(db_session, flask_app):
    tenant = _school(db_session)
    student, account, number, pin = _student(db_session, tenant, with_pin=True)
    strategy = registry.get(METHOD)

    with flask_app.test_request_context():
        match = strategy.resolve(number, tenant.id)[0]
        for _ in range(MAX_FAILURES_PER_MOBILE_HOUR - 1):
            strategy.verify(match, "999999")
        assert strategy.verify(match, pin) is True
        # And the allowance is back.
        assert strategy.verify(match, "999999") is False
        assert strategy.verify(match, pin) is True


def test_guessing_at_a_number_with_no_pin_is_counted_too(db_session, flask_app):
    """Otherwise the allowance itself is the oracle: unlimited guesses at
    numbers without a PIN and limited ones at numbers with one is an answer."""
    tenant = _school(db_session)
    student, account, number, _ = _student(db_session, tenant)
    strategy = registry.get(METHOD)

    with flask_app.test_request_context():
        match = strategy.resolve(number, tenant.id)[0]
        for _ in range(MAX_FAILURES_PER_MOBILE_HOUR):
            assert strategy.verify(match, "999999") is False

        from modules.auth.pin_throttle import check_attempt_allowed

        decision = check_attempt_allowed(
            tenant_id=tenant.id, mobile_hash=hash_value(normalize_mobile(number))
        )
        assert decision.allowed is False


def test_the_throttle_refuses_when_it_cannot_count(db_session, flask_app, monkeypatch):
    """Fails closed. A PIN check that cannot be counted is a free guess, and
    free guesses are the one thing a six-digit secret cannot survive."""
    import modules.auth.otp_throttle as otp_throttle

    tenant = _school(db_session)
    student, account, number, pin = _student(db_session, tenant, with_pin=True)
    strategy = registry.get(METHOD)

    monkeypatch.setattr(otp_throttle, "redis_client", lambda: None, raising=False)
    monkeypatch.setattr("core.cache.redis_client", lambda: None)

    from modules.auth.strategies.base import ThrottledOut

    with flask_app.test_request_context():
        match = strategy.resolve(number, tenant.id)[0]
        with pytest.raises(ThrottledOut):
            strategy.verify(match, pin)


# ---------------------------------------------------------------------------
# Nothing is sent, nothing is billed
# ---------------------------------------------------------------------------

def test_signing_in_with_a_pin_sends_nothing_and_costs_nothing(
    client, db_session, flask_app, monkeypatch
):
    """P8. A PIN is an internal credential, not a third-party service."""
    import modules.integrations.sms as sms_module

    tenant = _school(db_session)
    student, account, number, pin = _student(db_session, tenant, with_pin=True)

    def must_not_be_called(**kwargs):
        raise AssertionError("PIN authentication tried to send an SMS")

    monkeypatch.setattr(sms_module, "send_sms", must_not_be_called)

    response = _sign_in(client, flask_app, tenant, number=number, pin=pin)
    db_session.flush()

    assert response.status_code == 200
    assert ServiceUsageRecord.query.filter_by(tenant_id=tenant.id).count() == 0


def test_issuing_and_resetting_a_pin_costs_nothing(db_session):
    tenant = _school(db_session)
    student, account, _, _ = _student(db_session, tenant)

    issue_pin(student)
    issue_pin(student, reset=True)
    force_pin_change(student)
    db_session.flush()

    assert ServiceUsageRecord.query.filter_by(tenant_id=tenant.id).count() == 0


def test_the_pin_code_never_reaches_a_provider():
    """Structural: nothing in the PIN path imports the SMS capability."""
    import ast
    import pathlib

    for name in ("pin.py", "pin_throttle.py", "strategies/mobile_pin.py"):
        path = pathlib.Path("modules/auth") / name
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            for module in names:
                assert "integrations" not in module, f"{path} reaches a provider"
                assert "billing" not in module, f"{path} reaches billing"
