"""Phase 8 — the Phase 7 findings, each pinned closed.

One test group per finding, named for it, so that a regression names the
finding it reopens.
"""

from __future__ import annotations

import uuid

import pytest

from core.database import db
from modules.auth.event_models import AuthEvent
from modules.auth.identifiers import normalize_mobile
from modules.auth.otp_throttle import hash_value
from modules.auth.pin_throttle import MAX_FAILURES_PER_MOBILE_HOUR, clear_for_tests
from modules.auth.policy import ensure_default_policy, set_method
from modules.auth.provisioning import issue_admission_identifier, issue_mobile_identifier
from modules.auth.services import generate_access_token
from modules.students.models import Student
from tests.auth._characterization import (
    grant_permissions, make_tenant, make_user, new_id,
)

PASSWORD = "C0rrectHorse1"


@pytest.fixture(autouse=True)
def _redis(flask_app):
    import core.cache as cache

    previous_url, previous_pool = flask_app.config.get("REDIS_URL"), cache._pool
    flask_app.config["REDIS_URL"] = "redis://localhost:6379/0"
    cache._pool = None
    with flask_app.app_context():
        handle = cache.redis_client()
        try:
            assert handle is not None and handle.ping()
        except Exception:  # noqa: BLE001
            flask_app.config["REDIS_URL"] = previous_url
            cache._pool = previous_pool
            pytest.skip("needs a reachable Redis")
        clear_for_tests(tenant_id="", ip_address="127.0.0.1")
    yield
    flask_app.config["REDIS_URL"] = previous_url
    cache._pool = previous_pool


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _fresh(flask_app):
    from flask import g

    for attribute in ("tenant_id", "tenant", "current_user", "auth_session_id",
                      "auth_login_method"):
        if hasattr(g, attribute):
            delattr(g, attribute)


def _school(db_session, methods=()):
    tenant = make_tenant(db_session)
    ensure_default_policy(tenant.id)
    for kind, method in methods:
        set_method(tenant.id, kind, method, enabled=True)
    db_session.flush()
    return tenant


def _student(db_session, tenant, *, mobile=None, admission=None):
    account = make_user(db_session, tenant, password=PASSWORD)
    grant_permissions(db_session, tenant, account, ("student.read.self",))
    student = Student(
        id=new_id("s-"), tenant_id=tenant.id, user_id=account.id,
        person_id=account.person_id,
        admission_number=admission or f"ADM-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(student)
    db_session.flush()
    if mobile:
        issue_mobile_identifier(account, mobile)
        db_session.flush()
        clear_for_tests(
            tenant_id=tenant.id, mobile_hash=hash_value(normalize_mobile(mobile))
        )
    if admission:
        issue_admission_identifier(account, admission)
        db_session.flush()
    return student, account


# ===========================================================================
# F2 — the pre-authentication enumeration oracle
# ===========================================================================

def test_F2_an_existing_account_and_an_unknown_one_answer_identically(
    client, db_session, flask_app
):
    """The oracle: `403 MethodNotAllowed` for a real account and `401` for a
    fake one told an unauthenticated attacker which identifiers exist, with no
    password at all."""
    tenant = _school(db_session, [("student", "admission_id_password")])
    student, account = _student(db_session, tenant, admission="ADM-REAL-0001")
    set_method(tenant.id, "student", "admission_id_password", enabled=False)
    db_session.flush()

    def attempt(identifier):
        _fresh(flask_app)
        return client.post("/api/auth/login", json={
            "method": "admission_id_password", "identifier": identifier,
            "password": "anything", "tenant_id": tenant.id})

    real, fake = attempt("ADM-REAL-0001"), attempt("ADM-NOBODY-9999")

    assert real.status_code == fake.status_code == 401
    assert real.get_json()["error"] == fake.get_json()["error"] == "InvalidCredentials"
    assert real.get_json()["message"] == fake.get_json()["message"]


def test_F2_a_locked_account_is_not_announced(client, db_session, flask_app):
    """A distinct 429 said not only that an account exists but that it is
    currently under attack — a live signal about which are worth attacking."""
    tenant = _school(db_session)
    student, account = _student(db_session, tenant)
    from core.school_time import utc_now
    from datetime import timedelta

    account.login_locked_until = utc_now() + timedelta(minutes=5)
    db_session.flush()

    _fresh(flask_app)
    locked = client.post("/api/auth/login", json={
        "email": account.email, "password": "wrong", "tenant_id": tenant.id})
    _fresh(flask_app)
    unknown = client.post("/api/auth/login", json={
        "email": f"{uuid.uuid4().hex[:8]}@nobody.test", "password": "wrong",
        "tenant_id": tenant.id})

    assert locked.status_code == unknown.status_code == 401
    assert locked.get_json()["error"] == unknown.get_json()["error"]


def test_F2_the_real_reason_is_still_recorded(client, db_session, flask_app):
    """Uniformity outward, precision inward. Auditability is not the price."""
    tenant = _school(db_session, [("student", "admission_id_password")])
    student, account = _student(db_session, tenant, admission="ADM-REAL-0002")
    set_method(tenant.id, "student", "admission_id_password", enabled=False)
    db_session.flush()

    _fresh(flask_app)
    client.post("/api/auth/login", json={
        "method": "admission_id_password", "identifier": "ADM-REAL-0002",
        "password": "anything", "tenant_id": tenant.id})

    event = (
        AuthEvent.query.filter_by(account_id=account.id)
        .order_by(AuthEvent.created_at.desc()).first()
    )
    assert event.reason == "policy_denied"


# ===========================================================================
# F3 — a PIN throttle must not lock the account out of everything else
# ===========================================================================

def test_F3_spamming_a_pin_does_not_lock_the_email_password(
    client, db_session, flask_app
):
    """Anyone who knew a student's mobile number could lock them out of every
    method by spending attempts they were never allowed to make."""
    from modules.auth.credential_admin import issue_pin

    tenant = _school(db_session, [("student", "mobile_pin")])
    number = f"+9198{uuid.uuid4().int % 100000000:08d}"
    student, account = _student(db_session, tenant, mobile=number)
    issue_pin(student)
    db_session.flush()

    for _ in range(MAX_FAILURES_PER_MOBILE_HOUR + 5):
        _fresh(flask_app)
        client.post("/api/auth/login", json={
            "method": "mobile_pin", "identifier": number,
            "password": "000000", "tenant_id": tenant.id})

    _fresh(flask_app)
    honest = client.post("/api/auth/login", json={
        "email": account.email, "password": PASSWORD, "tenant_id": tenant.id})

    assert honest.status_code == 200, (
        "a PIN attacker locked the owner out of their own password"
    )


def test_F3_the_pin_itself_is_still_thoroughly_throttled(db_session, flask_app):
    """The fix must not be "remove the limit"."""
    from modules.auth.credential_admin import issue_pin
    from modules.auth.strategies import registry
    from modules.auth.strategies.base import ThrottledOut

    tenant = _school(db_session, [("student", "mobile_pin")])
    number = f"+9198{uuid.uuid4().int % 100000000:08d}"
    student, account = _student(db_session, tenant, mobile=number)
    pin = issue_pin(student)["pin"]
    db_session.flush()
    strategy = registry.get("mobile_pin")

    with flask_app.test_request_context():
        match = strategy.resolve(number, tenant.id)[0]
        for _ in range(MAX_FAILURES_PER_MOBILE_HOUR):
            assert strategy.verify(match, "999999") is False
        with pytest.raises(ThrottledOut):
            strategy.verify(match, pin)


# ===========================================================================
# F4 — the production JWT secret
# ===========================================================================

def test_F4_production_refuses_the_public_default(monkeypatch):
    from config.settings import ProductionConfig
    from modules.auth.services import INSECURE_JWT_SECRET

    monkeypatch.setenv("JWT_SECRET_KEY", INSECURE_JWT_SECRET)
    monkeypatch.setattr(ProductionConfig, "BACKEND_URL", "https://example.test")
    monkeypatch.setattr(ProductionConfig, "SECRET_KEY", "a-real-production-secret")

    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        ProductionConfig.init_app(None)


def test_F4_production_refuses_a_missing_secret(monkeypatch):
    from config.settings import ProductionConfig

    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.setattr(ProductionConfig, "BACKEND_URL", "https://example.test")
    monkeypatch.setattr(ProductionConfig, "SECRET_KEY", "a-real-production-secret")

    with pytest.raises(ValueError, match="JWT_SECRET_KEY"):
        ProductionConfig.init_app(None)


def test_F4_production_refuses_one_secret_doing_both_jobs(monkeypatch):
    from config.settings import ProductionConfig

    monkeypatch.setenv("JWT_SECRET_KEY", "shared-secret")
    monkeypatch.setattr(ProductionConfig, "BACKEND_URL", "https://example.test")
    monkeypatch.setattr(ProductionConfig, "SECRET_KEY", "shared-secret")

    with pytest.raises(ValueError, match="differ"):
        ProductionConfig.init_app(None)


def test_F4_a_real_configuration_starts(monkeypatch):
    from config.settings import ProductionConfig

    monkeypatch.setenv("JWT_SECRET_KEY", "a-genuinely-separate-token-secret")
    monkeypatch.setattr(ProductionConfig, "BACKEND_URL", "https://example.test")
    monkeypatch.setattr(ProductionConfig, "SECRET_KEY", "a-real-production-secret")

    ProductionConfig.init_app(None)  # does not raise


def test_F4_development_is_unaffected():
    """Local work must not need a production secret."""
    from config.settings import DevelopmentConfig

    assert not hasattr(DevelopmentConfig, "_requires_jwt_secret")


# ===========================================================================
# F5 — must_change on a PIN means something
# ===========================================================================

def test_F5_a_provisional_pin_cannot_reach_the_application(
    client, db_session, flask_app
):
    """Phase 5 wrote the flag and nothing read it: a school that clicked "Ask
    for a new PIN" got a stored boolean and no behaviour."""
    from modules.auth.credential_admin import force_pin_change, issue_pin

    tenant = _school(db_session, [("student", "mobile_pin")])
    number = f"+9198{uuid.uuid4().int % 100000000:08d}"
    student, account = _student(db_session, tenant, mobile=number)
    pin = issue_pin(student)["pin"]
    force_pin_change(student)
    db_session.flush()

    _fresh(flask_app)
    signed_in = client.post("/api/auth/login", json={
        "method": "mobile_pin", "identifier": number,
        "password": pin, "tenant_id": tenant.id})
    assert signed_in.status_code == 200

    tokens = signed_in.get_json()["data"]
    headers = {"Authorization": f"Bearer {tokens['access_token']}",
               "X-Tenant-ID": tenant.id}

    blocked = client.get("/api/students/", headers=headers)
    assert blocked.status_code == 403
    assert blocked.get_json()["error"] == "PinChangeRequired"

    # But the change flow itself is reachable, or they would be stuck.
    assert client.get("/api/auth/profile", headers=headers).status_code == 200
    changed = client.post("/api/auth/pin/change", headers=headers,
                          json={"current_pin": pin, "new_pin": "418306"})
    assert changed.status_code == 200

    assert client.get("/api/students/", headers=headers).status_code in (200, 403)
    from modules.auth.provisioning import live_pin_credential

    credential = live_pin_credential(account)
    assert credential.must_change is False
    assert credential.is_provisional is False


def test_F5_a_password_session_is_not_stopped_by_a_provisional_pin(
    client, db_session, flask_app
):
    """The requirement is about the credential in use, not about the account.
    A pupil signing in with their password should not be stopped by a PIN they
    have not touched."""
    from modules.auth.credential_admin import force_pin_change, issue_pin

    tenant = _school(db_session, [("student", "mobile_pin")])
    number = f"+9198{uuid.uuid4().int % 100000000:08d}"
    student, account = _student(db_session, tenant, mobile=number)
    issue_pin(student)
    force_pin_change(student)
    grant_permissions(db_session, tenant, account, ("student.read.all",))
    db_session.flush()

    _fresh(flask_app)
    tokens = client.post("/api/auth/login", json={
        "email": account.email, "password": PASSWORD,
        "tenant_id": tenant.id}).get_json()["data"]
    headers = {"Authorization": f"Bearer {tokens['access_token']}",
               "X-Tenant-ID": tenant.id}

    assert client.get("/api/students/", headers=headers).status_code == 200


# ===========================================================================
# F6 — credential issuance cannot be used to harvest a school
# ===========================================================================

def test_F6_bulk_issuance_is_bounded_per_actor(
    client, db_session, flask_app, throttling
):
    """A compromised operator session could harvest fresh plaintext for a whole
    school at the global 200/min, with no per-actor ceiling."""
    tenant = _school(db_session)
    operator = make_user(db_session, tenant, password=PASSWORD)
    grant_permissions(db_session, tenant, operator, ("student.credential.manage",))
    students = [_student(db_session, tenant)[0] for _ in range(3)]
    headers = {"Authorization": f"Bearer {generate_access_token(operator)}",
               "X-Tenant-ID": tenant.id}

    statuses = []
    for _ in range(10):
        response = client.post(
            "/api/students/credentials/bulk-issue",
            headers=headers,
            json={"student_ids": [s.id for s in students]},
        )
        statuses.append(response.status_code)

    assert 429 in statuses, "bulk credential issuance is unbounded per actor"


def test_F6_the_limit_is_keyed_on_the_actor_not_the_address():
    """A school behind one NAT would otherwise share a limit, while an attacker
    with a proxy pool would evade it."""
    import inspect

    from core.extensions import actor_rate_key

    source = inspect.getsource(actor_rate_key)
    assert "current_user" in source
    assert "get_remote_address" in source  # the fallback, for anonymous callers
