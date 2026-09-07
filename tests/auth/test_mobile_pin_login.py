"""Phase 5 — signing in with a PIN, over HTTP.

Not a new endpoint. `POST /api/auth/login` with `method=mobile_pin`, so every
gate the pipeline already owns runs unchanged — which is the point: a fourth
method must not be a fourth copy of the gates.
"""

from __future__ import annotations

import uuid

import pytest
from werkzeug.security import check_password_hash

from core.database import db
from modules.auth.credential_admin import issue_pin
from modules.auth.identifiers import normalize_mobile
from modules.auth.models import AccountIdentifier
from modules.auth.otp_throttle import hash_value
from modules.auth.pin_throttle import clear_for_tests
from modules.auth.policy import ensure_default_policy, set_method
from modules.auth.provisioning import issue_mobile_identifier, live_pin_credential
from modules.auth.strategies.mobile_pin import MobilePinStrategy
from modules.billing.models import ServiceUsageRecord
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


@pytest.fixture(autouse=True)
def _reachable_redis(flask_app):
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
        clear_for_tests(tenant_id="", ip_address="127.0.0.1")

    yield
    flask_app.config["REDIS_URL"] = previous_url
    cache._pool = previous_pool


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _fresh_request(flask_app):
    from flask import g as flask_g

    for attribute in ("tenant_id", "tenant", "current_user"):
        if hasattr(flask_g, attribute):
            delattr(flask_g, attribute)


def _mobile() -> str:
    return f"+9198{uuid.uuid4().int % 100000000:08d}"


def _school(db_session, *, pin_enabled=True):
    tenant = make_tenant(db_session)
    ensure_default_policy(tenant.id)
    if pin_enabled:
        set_method(tenant.id, "student", METHOD, enabled=True)
    db_session.flush()
    return tenant


def _student(db_session, tenant, *, mobile=None, with_pin=True):
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

    pin = issue_pin(student)["pin"] if with_pin else None
    db_session.flush()
    return student, account, number, pin


def _sign_in(client, flask_app, tenant, *, number, pin, **extra):
    _fresh_request(flask_app)
    body = {
        "method": METHOD,
        "identifier": number,
        "password": pin,
        "tenant_id": tenant.id,
    }
    body.update(extra)
    return client.post("/api/auth/login", json=body)


# ---------------------------------------------------------------------------
# Signing in
# ---------------------------------------------------------------------------

def test_a_pin_signs_a_student_in(client, db_session, flask_app):
    tenant = _school(db_session)
    student, account, number, pin = _student(db_session, tenant)

    response = _sign_in(client, flask_app, tenant, number=number, pin=pin)

    assert response.status_code == 200
    assert response.get_json()["data"]["user"]["id"] == account.id


def test_the_session_and_token_say_it_was_a_pin(client, db_session, flask_app):
    """P7."""
    tenant = _school(db_session)
    student, account, number, pin = _student(db_session, tenant)

    body = _sign_in(client, flask_app, tenant, number=number, pin=pin).get_json()["data"]
    db_session.flush()

    session = sessions_for(account.id)[-1]
    identifier = AccountIdentifier.query.filter_by(
        account_id=account.id, identifier_type="mobile"
    ).first()
    claims = decode_access_token(body["access_token"])

    assert session.login_method == METHOD
    assert session.authenticated_identifier_id == identifier.id
    assert claims["amr"] == METHOD
    assert claims["tid"] == tenant.id


def test_a_wrong_pin_does_not_sign_in(client, db_session, flask_app):
    tenant = _school(db_session)
    student, account, number, _ = _student(db_session, tenant)

    response = _sign_in(client, flask_app, tenant, number=number, pin="999999")

    assert response.status_code == 401
    assert response.get_json()["error"] == "InvalidCredentials"


def test_a_student_with_no_pin_cannot_sign_in_this_way(client, db_session, flask_app):
    tenant = _school(db_session)
    student, account, number, _ = _student(db_session, tenant, with_pin=False)

    response = _sign_in(client, flask_app, tenant, number=number, pin="142857")

    assert response.status_code == 401


def test_signing_in_without_naming_a_school_is_refused(client, db_session, flask_app):
    """P5/A4."""
    tenant = _school(db_session)
    student, account, number, pin = _student(db_session, tenant)

    _fresh_request(flask_app)
    response = client.post(
        "/api/auth/login",
        json={"method": METHOD, "identifier": number, "password": pin},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "TenantRequired"


def test_a_tenant_header_alone_does_not_name_a_school(client, db_session, flask_app):
    """The constraint every phone client has to know about.

    The pipeline decides whether a school was named by reading the **body** —
    a Phase 0d decision that keeps email sign-in choosing between its two
    branches exactly as it always has. The Expo app scopes every other request
    with `X-Tenant-ID`, so a PIN attempt carrying only that header names no
    school and is refused.

    Pinned here rather than fixed in the pipeline: changing `names_a_tenant` to
    consider headers would alter branch selection for every header-scoped
    client on a path this phase has no business touching. The client sends
    `tenant_id` in the body instead.
    """
    tenant = _school(db_session)
    student, account, number, pin = _student(db_session, tenant)

    _fresh_request(flask_app)
    response = client.post(
        "/api/auth/login",
        headers={"X-Tenant-ID": tenant.id},
        json={"method": METHOD, "identifier": number, "password": pin},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "TenantRequired"


def test_a_pin_from_one_school_does_not_work_at_another(client, db_session, flask_app):
    ours = _school(db_session)
    theirs = _school(db_session)
    number = _mobile()
    _student(db_session, theirs, mobile=number)
    student, account, _, pin = _student(db_session, theirs, mobile=_mobile())

    response = _sign_in(client, flask_app, ours, number=number, pin=pin)

    assert response.status_code == 401


def test_a_school_that_turned_it_off_cannot_be_signed_into_this_way(
    client, db_session, flask_app
):
    tenant = _school(db_session)
    student, account, number, pin = _student(db_session, tenant)
    set_method(tenant.id, "student", METHOD, enabled=False)
    db_session.flush()

    response = _sign_in(client, flask_app, tenant, number=number, pin=pin)

    # Uniform with a wrong password, deliberately: telling "this account
    # exists but the method is off" from "no such account" was an
    # enumeration oracle needing no password. The reason is still recorded.
    assert response.status_code == 401
    assert response.get_json()["error"] == "InvalidCredentials"


def test_a_suspended_student_cannot_sign_in_with_a_pin(client, db_session, flask_app):
    """P6 — a valid PIN does not bypass account status."""
    tenant = _school(db_session)
    student, account, number, pin = _student(db_session, tenant)
    account.is_suspended = True
    db_session.flush()

    response = _sign_in(client, flask_app, tenant, number=number, pin=pin)

    assert response.status_code in (401, 403)


def test_a_soft_deleted_account_cannot_sign_in_with_a_pin(client, db_session, flask_app):
    from core.school_time import utc_now

    tenant = _school(db_session)
    student, account, number, pin = _student(db_session, tenant)
    account.deleted_at = utc_now()
    db_session.flush()

    response = _sign_in(client, flask_app, tenant, number=number, pin=pin)

    assert response.status_code in (401, 403)


def test_a_password_change_requirement_survives_a_pin_sign_in(
    client, db_session, flask_app
):
    """A PIN does not set a password, so it cannot discharge a requirement to
    change one."""
    tenant = _school(db_session)
    student, account, number, pin = _student(db_session, tenant)
    account.force_password_reset = True
    db_session.flush()

    body = _sign_in(client, flask_app, tenant, number=number, pin=pin).get_json()["data"]
    db_session.refresh(account)

    assert body["force_password_reset"] is True
    assert account.force_password_reset is True


def test_the_other_three_methods_are_unchanged(client, db_session, flask_app):
    """P9, the regression that matters most."""
    tenant = _school(db_session)
    student, account, number, pin = _student(db_session, tenant)

    _fresh_request(flask_app)
    response = client.post(
        "/api/auth/login",
        json={"email": account.email, "password": "Password123", "tenant_id": tenant.id},
    )
    db_session.flush()

    assert response.status_code == 200
    assert sessions_for(account.id)[-1].login_method == "email_password"


# ---------------------------------------------------------------------------
# Changing your own PIN
# ---------------------------------------------------------------------------

def test_a_student_can_change_their_own_pin(client, db_session, flask_app):
    from modules.auth.services import generate_access_token

    tenant = _school(db_session)
    student, account, number, pin = _student(db_session, tenant)
    headers = {
        "Authorization": f"Bearer {generate_access_token(account)}",
        "X-Tenant-ID": tenant.id,
    }

    response = client.post(
        "/api/auth/pin/change",
        headers=headers,
        json={"current_pin": pin, "new_pin": "418306"},
    )
    db_session.flush()

    assert response.status_code == 200
    credential = live_pin_credential(account)
    assert check_password_hash(credential.secret_hash, "418306")
    assert not check_password_hash(credential.secret_hash, pin)
    # Chosen by the holder now, not issued by the school.
    assert credential.is_provisional is False


def test_changing_a_pin_needs_the_current_one(client, db_session, flask_app):
    """Being signed in is not by itself permission to change a second
    credential."""
    from modules.auth.services import generate_access_token

    tenant = _school(db_session)
    student, account, number, pin = _student(db_session, tenant)
    headers = {
        "Authorization": f"Bearer {generate_access_token(account)}",
        "X-Tenant-ID": tenant.id,
    }

    response = client.post(
        "/api/auth/pin/change",
        headers=headers,
        json={"current_pin": "999999", "new_pin": "418306"},
    )

    assert response.status_code == 401
    assert check_password_hash(live_pin_credential(account).secret_hash, pin)


def test_a_weak_replacement_pin_is_refused(client, db_session, flask_app):
    from modules.auth.services import generate_access_token

    tenant = _school(db_session)
    student, account, number, pin = _student(db_session, tenant)
    headers = {
        "Authorization": f"Bearer {generate_access_token(account)}",
        "X-Tenant-ID": tenant.id,
    }

    response = client.post(
        "/api/auth/pin/change",
        headers=headers,
        json={"current_pin": pin, "new_pin": "123456"},
    )

    assert response.status_code == 422
    assert response.get_json()["error"] == "WeakPin"


def test_changing_a_pin_never_returns_or_logs_it(client, db_session, flask_app, caplog):
    from modules.auth.services import generate_access_token

    tenant = _school(db_session)
    student, account, number, pin = _student(db_session, tenant)
    headers = {
        "Authorization": f"Bearer {generate_access_token(account)}",
        "X-Tenant-ID": tenant.id,
    }

    with caplog.at_level("DEBUG"):
        response = client.post(
            "/api/auth/pin/change",
            headers=headers,
            json={"current_pin": pin, "new_pin": "418306"},
        )

    assert "418306" not in response.get_data(as_text=True)
    assert "418306" not in caplog.text


# ---------------------------------------------------------------------------
# Administration, over HTTP
# ---------------------------------------------------------------------------

def _operator(db_session, tenant):
    from modules.auth.services import generate_access_token

    user = make_user(db_session, tenant, password="Operator123")
    grant_permissions(db_session, tenant, user, ("student.credential.manage",))
    return {
        "Authorization": f"Bearer {generate_access_token(user)}",
        "X-Tenant-ID": tenant.id,
    }


def test_an_operator_can_issue_a_pin_and_sees_it_once(client, db_session, flask_app):
    tenant = _school(db_session)
    student, account, number, _ = _student(db_session, tenant, with_pin=False)
    headers = _operator(db_session, tenant)

    response = client.post(f"/api/students/{student.id}/pin", headers=headers)

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert len(data["pin"]) == 6 and data["pin"].isdigit()

    # And never again.
    status = client.get(
        f"/api/students/{student.id}/credentials", headers=headers
    ).get_json()["data"]
    assert status["pin"]["issued"] is True
    assert data["pin"] not in repr(status)


def test_reading_a_student_is_not_enough_to_issue_a_pin(client, db_session, flask_app):
    from modules.auth.services import generate_access_token

    tenant = _school(db_session)
    student, account, number, _ = _student(db_session, tenant, with_pin=False)
    reader = make_user(db_session, tenant, password="Reader123")
    grant_permissions(db_session, tenant, reader, ("student.read.all",))
    headers = {
        "Authorization": f"Bearer {generate_access_token(reader)}",
        "X-Tenant-ID": tenant.id,
    }

    response = client.post(f"/api/students/{student.id}/pin", headers=headers)

    assert response.status_code == 403


def test_another_school_cannot_issue_a_pin_for_this_student(
    client, db_session, flask_app
):
    ours = _school(db_session)
    theirs = _school(db_session)
    student, account, number, _ = _student(db_session, theirs, with_pin=False)
    headers = _operator(db_session, ours)

    response = client.post(f"/api/students/{student.id}/pin", headers=headers)

    assert response.status_code == 404
    assert live_pin_credential(account) is None


def test_issuing_a_pin_over_http_creates_no_usage(client, db_session, flask_app):
    tenant = _school(db_session)
    student, account, number, _ = _student(db_session, tenant, with_pin=False)
    headers = _operator(db_session, tenant)

    client.post(f"/api/students/{student.id}/pin", headers=headers)
    db_session.flush()

    assert ServiceUsageRecord.query.filter_by(tenant_id=tenant.id).count() == 0
