"""Phase 0d — one pipeline, one registry, one place where the gates live.

The refactor is meant to be behaviour-preserving, so most of its proof is the
Phase −1 characterization suite continuing to pass. What is tested here is the
structure that suite cannot see: that the registry refuses a malformed method,
that the gates run in the order the security contract specifies, that the new
tables are read first and the old columns still answer when they do not, that
what happened is recorded without recording anybody's address, and that the
whole thing can be switched off without a deploy.
"""

from __future__ import annotations

import uuid

import pytest

from core.database import db
from modules.auth.event_models import (
    EVENT_LOGIN_FAILURE,
    EVENT_LOGIN_SUCCESS,
    REASON_ACCOUNT_LOCKED,
    REASON_CREDENTIAL_MISMATCH,
    REASON_NO_IDENTIFIER_MATCH,
    REASON_POLICY_DENIED,
    AuthEvent,
    hash_identifier,
)
from modules.auth.identifiers import normalize_email
from modules.auth.models import AccountCredential, AccountIdentifier
from modules.auth.pipeline import (
    SURFACE_UNKNOWN,
    AuthenticationRequest,
    AuthenticationService,
    pipeline_enabled,
)
from modules.auth.policy import ensure_default_policy
from modules.auth.policy_models import TenantAuthPolicyRule
from modules.auth.strategies import (
    DEFAULT_METHOD_KEY,
    AuthenticationStrategy,
    AuthenticationStrategyRegistry,
    EmailPasswordStrategy,
    RegistryInvalid,
    UnknownAuthenticationMethod,
    registry,
)
from tests.auth._characterization import (
    decode_access_token,
    login,
    make_account,
    make_platform_admin,
    make_tenant,
    make_user,
    sessions_for,
)

PASSWORD = "C0rrectHorse1"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def policed_tenant(db_session, tenant):
    ensure_default_policy(tenant.id)
    return tenant


@pytest.fixture
def account(db_session, policed_tenant):
    return make_account(db_session, policed_tenant, password=PASSWORD)


def _events_for(account_id=None, *, identifier=None):
    query = AuthEvent.query
    if account_id:
        query = query.filter_by(account_id=account_id)
    if identifier:
        query = query.filter_by(identifier_value_hash=hash_identifier(identifier))
    return query.order_by(AuthEvent.created_at).all()


# ---------------------------------------------------------------------------
# The registry, and invariant A4
# ---------------------------------------------------------------------------

def test_the_registry_holds_the_methods_this_build_can_execute():
    """Registration makes a method possible; a tenant's policy makes it
    permitted. All four are here; only email is enabled by default."""
    assert registry.keys() == [
        "admission_id_password",
        "email_password",
        "mobile_otp",
        "mobile_pin",
    ]


def test_a_known_method_resolves_to_its_strategy():
    assert registry.get("email_password").key == "email_password"


def test_an_unknown_method_is_refused_not_downgraded():
    """A silent fallback to email and password would make a typo in `method`
    look like a working sign-in."""
    with pytest.raises(UnknownAuthenticationMethod):
        registry.get("carrier_pigeon")
    with pytest.raises(UnknownAuthenticationMethod):
        registry.get("")


def test_duplicate_keys_are_refused():
    with pytest.raises(RegistryInvalid):
        AuthenticationStrategyRegistry(
            [EmailPasswordStrategy(), EmailPasswordStrategy()]
        )


class _Malformed(AuthenticationStrategy):
    key = "malformed"
    identifier_type = "passport"       # not a declared identifier type
    credential_type = "password"
    requires_tenant = True

    def resolve(self, value, tenant_id):
        return []

    def verify(self, match, proof):
        return False


def test_a_strategy_with_an_unknown_identifier_type_is_refused():
    with pytest.raises(RegistryInvalid):
        AuthenticationStrategyRegistry([_Malformed()])


class _Keyless(EmailPasswordStrategy):
    key = "   "


def test_a_strategy_with_no_key_is_refused():
    with pytest.raises(RegistryInvalid):
        AuthenticationStrategyRegistry([_Keyless()])


class _ProvesNothing(AuthenticationStrategy):
    key = "proves_nothing"
    identifier_type = "email"
    credential_type = None            # and offers no challenge either
    requires_tenant = True

    def resolve(self, value, tenant_id):
        return []

    def verify(self, match, proof):
        return False


def test_a_strategy_that_proves_nothing_is_refused():
    with pytest.raises(RegistryInvalid):
        AuthenticationStrategyRegistry([_ProvesNothing()])


class _TenantlessAdmission(AuthenticationStrategy):
    key = "admission_id_password"
    identifier_type = "admission_id"
    credential_type = "password"
    requires_tenant = False           # the dangerous one

    def resolve(self, value, tenant_id):
        return []

    def verify(self, match, proof):
        return False


def test_only_the_email_strategy_may_resolve_without_a_tenant():
    """A4, and the most important line in this file.

    An admission number is unique only inside one school and a household
    mobile number is not unique even there, so resolving either without a
    school is not a leak but a wrong answer. The registry refuses to exist in
    a build where a second method has inherited email's exception.
    """
    with pytest.raises(RegistryInvalid) as refused:
        AuthenticationStrategyRegistry([EmailPasswordStrategy(), _TenantlessAdmission()])
    assert "without a tenant" in str(refused.value)

    with pytest.raises(RegistryInvalid):
        AuthenticationStrategyRegistry([_TenantlessAdmission()])


def test_the_shipped_registry_satisfies_a4():
    registry.validate()
    tenant_less = [k for k in registry.keys() if not registry.get(k).requires_tenant]
    assert tenant_less == ["email_password"], (
        "only an email address is globally near-unique; every other identifier "
        "is unique per tenant at best"
    )


# ---------------------------------------------------------------------------
# The request
# ---------------------------------------------------------------------------

def test_an_omitted_method_defaults_to_email_password(flask_app):
    with flask_app.test_request_context(
        "/api/auth/login", json={"email": "a@b.test", "password": "x"}
    ):
        from flask import request as flask_request

        attempt = AuthenticationRequest.from_flask(flask_request)

    assert attempt.method_key == DEFAULT_METHOD_KEY


def test_an_explicit_method_is_carried(flask_app):
    with flask_app.test_request_context(
        "/api/auth/login",
        json={"email": "a@b.test", "password": "x", "method": "email_password"},
    ):
        from flask import request as flask_request

        attempt = AuthenticationRequest.from_flask(flask_request)

    assert attempt.method_key == "email_password"


def test_a_missing_surface_header_is_unknown(flask_app):
    with flask_app.test_request_context(
        "/api/auth/login", json={"email": "a@b.test", "password": "x"}
    ):
        from flask import request as flask_request

        attempt = AuthenticationRequest.from_flask(flask_request)

    assert attempt.client_surface == SURFACE_UNKNOWN


def test_a_declared_surface_is_carried(flask_app):
    with flask_app.test_request_context(
        "/api/auth/login",
        json={"email": "a@b.test", "password": "x"},
        headers={"X-Client-Surface": "student-mobile"},
    ):
        from flask import request as flask_request

        attempt = AuthenticationRequest.from_flask(flask_request)

    assert attempt.client_surface == "student-mobile"


def test_an_unknown_method_is_a_clean_refusal(client, policed_tenant, account):
    response = client.post(
        "/api/auth/login",
        json={
            "email": account.email,
            "password": PASSWORD,
            "method": "carrier_pigeon",
            "tenant_id": policed_tenant.id,
        },
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "UnsupportedAuthenticationMethod"
    assert sessions_for(account.id) == []


# ---------------------------------------------------------------------------
# Dual read
# ---------------------------------------------------------------------------

def test_the_identifier_table_resolves_the_account(
    client, db_session, policed_tenant, account
):
    identifier = AccountIdentifier.query.filter_by(
        account_id=account.id, identifier_type="email"
    ).one()

    response = login(
        client, email=account.email, password=PASSWORD, tenant_id=policed_tenant.id
    )

    assert response.status_code == 200
    assert sessions_for(account.id)[0].authenticated_identifier_id == identifier.id


def test_an_account_with_no_identifier_row_falls_back_to_the_column(
    client, db_session, policed_tenant, account
):
    """The dual-read fallback: an account whose identifier is missing — created
    before the backfill, or by a path that bypassed the ORM — must still sign
    in."""
    AccountIdentifier.query.filter_by(account_id=account.id).delete()
    db_session.flush()

    response = login(
        client, email=account.email, password=PASSWORD, tenant_id=policed_tenant.id
    )

    assert response.status_code == 200, response.get_json()
    # Nothing to record, and the session says so rather than guessing.
    assert sessions_for(account.id)[0].authenticated_identifier_id is None


def test_the_credential_table_verifies_the_password(
    client, db_session, policed_tenant, account
):
    """A credential row is authoritative when it exists: a wrong hash there
    refuses the sign-in even though `users.password_hash` would accept it."""
    db_session.add(
        AccountCredential(
            id=f"ac-{uuid.uuid4().hex[:12]}",
            tenant_id=policed_tenant.id,
            account_id=account.id,
            credential_type="password",
            secret_hash="scrypt:32768:8:1$deliberately$wrong",
            hash_algorithm="scrypt:32768:8:1",
        )
    )
    db_session.flush()

    response = login(
        client, email=account.email, password=PASSWORD, tenant_id=policed_tenant.id
    )

    assert response.status_code == 401


def test_a_credential_row_that_matches_signs_the_account_in(
    client, db_session, policed_tenant, account
):
    from werkzeug.security import generate_password_hash

    db_session.add(
        AccountCredential(
            id=f"ac-{uuid.uuid4().hex[:12]}",
            tenant_id=policed_tenant.id,
            account_id=account.id,
            credential_type="password",
            secret_hash=generate_password_hash(PASSWORD),
            hash_algorithm="scrypt",
        )
    )
    db_session.flush()

    response = login(
        client, email=account.email, password=PASSWORD, tenant_id=policed_tenant.id
    )

    assert response.status_code == 200, response.get_json()


def test_with_no_credential_row_the_legacy_column_answers(
    client, db_session, policed_tenant, account
):
    assert AccountCredential.query.filter_by(account_id=account.id).count() == 0

    response = login(
        client, email=account.email, password=PASSWORD, tenant_id=policed_tenant.id
    )

    assert response.status_code == 200, response.get_json()


def test_the_two_resolution_paths_agree_for_every_account_in_the_database(
    db_session,
):
    """Equivalence, measured rather than asserted: for every live account, the
    identifier table and the legacy column name the same account."""
    disagreements = db_session.execute(
        db.text(
            """
            SELECT count(*) FROM users u
             WHERE u.deleted_at IS NULL
               AND u.email IS NOT NULL AND btrim(u.email) <> ''
               AND NOT EXISTS (
                   SELECT 1 FROM account_identifiers i
                    WHERE i.account_id = u.id
                      AND i.identifier_type = 'email'
                      AND i.deleted_at IS NULL
                      AND i.identifier_value_normalized = lower(btrim(u.email))
               )
            """
        )
    ).scalar()

    assert disagreements == 0


def test_the_two_credential_paths_agree_for_every_account_in_the_database(
    db_session,
):
    disagreements = db_session.execute(
        db.text(
            """
            SELECT count(*) FROM users u
              JOIN account_credentials c
                ON c.account_id = u.id
               AND c.credential_type = 'password'
               AND c.deleted_at IS NULL
             WHERE c.secret_hash IS DISTINCT FROM u.password_hash
            """
        )
    ).scalar()

    assert disagreements == 0


# ---------------------------------------------------------------------------
# Gate ordering
# ---------------------------------------------------------------------------

def _last_reason(response, account):
    """Why the pipeline refused, from the audit record it just wrote.

    The external answer is deliberately coarse; this reads the internal one.
    """
    from modules.auth.event_models import AuthEvent

    assert response.status_code == 401
    event = (
        AuthEvent.query.filter_by(account_id=account.id)
        .order_by(AuthEvent.created_at.desc(), AuthEvent.id.desc())
        .first()
    )
    return event.reason if event else None


def test_the_gates_run_in_the_specified_order(
    client, db_session, policed_tenant, monkeypatch
):
    """Not "all the gates exist somewhere" — the order itself.

    Each gate is made to fail one at a time, starting from the last, and the
    response must always name the *earliest* failing gate. That is only true if
    they run in sequence.
    """
    account = make_account(db_session, policed_tenant, password=PASSWORD)

    def attempt(**body):
        return client.post(
            "/api/auth/login",
            json={
                "email": account.email,
                "password": PASSWORD,
                "tenant_id": policed_tenant.id,
                **body,
            },
        )

    # Baseline: everything passes.
    assert attempt().status_code == 200

    # Gate 7 — lockout, before the proof.
    from core.school_time import utc_now
    from datetime import timedelta

    account.login_locked_until = utc_now() + timedelta(minutes=5)
    db_session.flush()
    # The order is now read from the *recorded reason* rather than the status.
    # Since Phase 8 the policy and lockout gates both answer
    # `401 InvalidCredentials` externally — telling them apart without a
    # password was an account-enumeration oracle — so the response can no
    # longer distinguish which gate spoke. The audit record still can, which
    # is the whole point of keeping the two separate.
    assert _last_reason(attempt(password="wrong"), account) == REASON_ACCOUNT_LOCKED

    # Gate 6 — policy, before lockout: still locked, but policy answers first.
    for rule in TenantAuthPolicyRule.query.filter_by(tenant_id=policed_tenant.id):
        rule.is_enabled = False
    db_session.flush()
    assert _last_reason(attempt(password="wrong"), account) == REASON_POLICY_DENIED

    # Gate 4 — maintenance, before policy.
    from modules.platform import services as platform_services

    monkeypatch.setattr(
        platform_services, "get_platform_settings", lambda: {"maintenance_mode": "true"}
    )
    assert attempt(password="wrong").status_code == 503

    # Gate 1 — validation, before everything.
    assert client.post(
        "/api/auth/login", json={"email": account.email, "tenant_id": policed_tenant.id}
    ).status_code == 400


def test_a_denied_method_never_reaches_the_proof(
    client, db_session, policed_tenant
):
    account = make_account(db_session, policed_tenant, password=PASSWORD)
    for rule in TenantAuthPolicyRule.query.filter_by(tenant_id=policed_tenant.id):
        rule.is_enabled = False
    db_session.flush()

    client.post(
        "/api/auth/login",
        json={
            "email": account.email, "password": "wrong", "tenant_id": policed_tenant.id
        },
    )

    db_session.refresh(account)
    assert (account.failed_login_count or 0) == 0
    assert _events_for(account.id)[-1].reason == REASON_POLICY_DENIED


def test_a_platform_admin_passes_the_policy_gate(client, db_session, policed_tenant):
    """A3 through the pipeline, not only through the service."""
    for rule in TenantAuthPolicyRule.query.filter_by(tenant_id=policed_tenant.id):
        rule.is_enabled = False
    db_session.flush()

    home = make_tenant(db_session, subdomain_prefix="p0d-hq")
    admin = make_platform_admin(db_session, home, password=PASSWORD)

    response = login(
        client, email=admin.email, password=PASSWORD, tenant_id=policed_tenant.id
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["data"]["is_platform_admin"] is True


# ---------------------------------------------------------------------------
# Session metadata and token claims
# ---------------------------------------------------------------------------

def test_a_session_records_method_surface_and_identifier(
    client, db_session, policed_tenant, account
):
    identifier = AccountIdentifier.query.filter_by(
        account_id=account.id, identifier_type="email"
    ).one()

    client.post(
        "/api/auth/login",
        json={
            "email": account.email, "password": PASSWORD, "tenant_id": policed_tenant.id
        },
        headers={"X-Client-Surface": "student-mobile"},
    )

    session = sessions_for(account.id)[0]
    assert session.login_method == "email_password"
    assert session.client_surface == "student-mobile"
    assert session.authenticated_identifier_id == identifier.id


def test_the_token_carries_the_tenant_and_the_method(
    client, policed_tenant, account
):
    data = login(
        client, email=account.email, password=PASSWORD, tenant_id=policed_tenant.id
    ).get_json()["data"]

    claims = decode_access_token(data["access_token"])
    assert claims["tid"] == str(policed_tenant.id)
    assert claims["amr"] == "email_password"
    # And the compatibility claim is still there.
    assert claims["email"] == account.email


def test_a_refreshed_token_keeps_the_method(
    client, db_session, policed_tenant, account
):
    """`amr` must survive a refresh rather than silently disappearing."""
    from modules.auth.services import generate_access_token

    tokens = login(
        client, email=account.email, password=PASSWORD, tenant_id=policed_tenant.id
    ).get_json()["data"]

    response = client.get(
        "/api/auth/profile",
        headers={
            "X-Tenant-Subdomain": policed_tenant.subdomain,
            "Authorization": f"Bearer {generate_access_token(account, access_minutes=-1)}",
            "X-Refresh-Token": tokens["refresh_token"],
        },
    )

    minted = response.headers.get("X-New-Access-Token")
    assert minted
    assert decode_access_token(minted)["amr"] == "email_password"


# ---------------------------------------------------------------------------
# Authentication events
# ---------------------------------------------------------------------------

def test_a_successful_sign_in_is_recorded(
    client, db_session, policed_tenant, account
):
    client.post(
        "/api/auth/login",
        json={
            "email": account.email, "password": PASSWORD, "tenant_id": policed_tenant.id
        },
        headers={"X-Client-Surface": "admin-web"},
        environ_base={"REMOTE_ADDR": "203.0.113.7"},
    )

    event = _events_for(account.id)[-1]
    assert event.event_type == EVENT_LOGIN_SUCCESS
    assert event.method_key == "email_password"
    assert event.tenant_id == policed_tenant.id
    assert event.client_surface == "admin-web"
    assert event.ip_address == "203.0.113.7"
    assert event.reason is None


def test_a_failed_sign_in_is_recorded_with_its_reason(
    client, db_session, policed_tenant, account
):
    login(client, email=account.email, password="wrong", tenant_id=policed_tenant.id)

    event = _events_for(account.id)[-1]
    assert event.event_type == EVENT_LOGIN_FAILURE
    assert event.reason == REASON_CREDENTIAL_MISMATCH


def test_an_attempt_on_an_unknown_address_is_recorded_without_an_account(
    client, db_session, policed_tenant
):
    unknown = f"nobody-{uuid.uuid4().hex[:8]}@example.test"

    login(client, email=unknown, password="whatever", tenant_id=policed_tenant.id)

    events = _events_for(identifier=unknown)
    assert len(events) == 1
    assert events[0].account_id is None
    assert events[0].reason == REASON_NO_IDENTIFIER_MATCH


def test_the_identifier_is_hashed_never_stored(
    client, db_session, policed_tenant, account
):
    """An events table holding every address anyone typed would be a directory
    of the school."""
    login(client, email=account.email, password=PASSWORD, tenant_id=policed_tenant.id)

    event = _events_for(account.id)[-1]
    assert event.identifier_value_hash == hash_identifier(account.email)
    assert account.email not in str(event.identifier_value_hash)
    assert len(event.identifier_value_hash) == 64

    # And nowhere else in the row either.
    row = {c.name: getattr(event, c.name) for c in AuthEvent.__table__.columns}
    assert account.email not in str(row)


def test_a_locked_account_is_recorded_as_locked(
    client, db_session, policed_tenant, account
):
    from datetime import timedelta

    from core.school_time import utc_now

    account.login_locked_until = utc_now() + timedelta(minutes=5)
    db_session.flush()

    login(client, email=account.email, password=PASSWORD, tenant_id=policed_tenant.id)

    assert _events_for(account.id)[-1].reason == REASON_ACCOUNT_LOCKED


def test_one_event_per_attempt(client, db_session, policed_tenant, account):
    """The pipeline records; a strategy does not. Two recorders would show up
    here as two rows."""
    before = len(_events_for(account.id))

    login(client, email=account.email, password=PASSWORD, tenant_id=policed_tenant.id)

    assert len(_events_for(account.id)) == before + 1


# ---------------------------------------------------------------------------
# The kill switch
# ---------------------------------------------------------------------------

def test_the_pipeline_is_on_when_nothing_is_configured(db_session):
    from core.models import PlatformSetting

    PlatformSetting.query.filter_by(key="auth_pipeline_enabled").delete()
    db_session.flush()

    assert pipeline_enabled() is True


def test_the_switch_turns_the_pipeline_off(db_session):
    from core.models import PlatformSetting

    db_session.add(PlatformSetting(key="auth_pipeline_enabled", value="false"))
    db_session.flush()

    assert pipeline_enabled() is False


def test_disabling_the_pipeline_restores_the_legacy_path(
    client, db_session, policed_tenant
):
    """The rollback, demonstrated rather than asserted.

    The same account signs in both ways and gets the same answer. What differs
    is the metadata only the pipeline knows how to record — which is exactly
    the shape a rollback should have: nobody loses access, some observability
    is lost until it is switched back on.
    """
    from core.models import PlatformSetting

    account = make_account(db_session, policed_tenant, password=PASSWORD)

    through_pipeline = login(
        client, email=account.email, password=PASSWORD, tenant_id=policed_tenant.id
    )
    assert through_pipeline.status_code == 200
    pipeline_session = sessions_for(account.id)[0]
    assert pipeline_session.login_method == "email_password"

    db_session.add(PlatformSetting(key="auth_pipeline_enabled", value="false"))
    db_session.flush()

    through_legacy = login(
        client, email=account.email, password=PASSWORD, tenant_id=policed_tenant.id
    )

    assert through_legacy.status_code == 200
    # The response contract is identical.
    assert set(through_legacy.get_json()["data"]) == set(
        through_pipeline.get_json()["data"]
    )
    assert through_legacy.get_json()["data"]["user"]["id"] == account.id
    # The legacy path leaves the column default, as it always did.
    legacy_session = [
        s for s in sessions_for(account.id) if s.id != pipeline_session.id
    ][0]
    assert legacy_session.login_method == "email"


def test_the_legacy_path_still_refuses_a_wrong_password(
    client, db_session, policed_tenant
):
    from core.models import PlatformSetting

    account = make_account(db_session, policed_tenant, password=PASSWORD)
    db_session.add(PlatformSetting(key="auth_pipeline_enabled", value="false"))
    db_session.flush()

    response = login(
        client, email=account.email, password="wrong", tenant_id=policed_tenant.id
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "InvalidCredentials"


def test_the_legacy_path_ignores_the_policy(client, db_session, policed_tenant):
    """Rolling back rolls back the policy gate too — which is the point of a
    rollback, and worth knowing when using one."""
    from core.models import PlatformSetting

    account = make_account(db_session, policed_tenant, password=PASSWORD)
    for rule in TenantAuthPolicyRule.query.filter_by(tenant_id=policed_tenant.id):
        rule.is_enabled = False
    db_session.add(PlatformSetting(key="auth_pipeline_enabled", value="false"))
    db_session.flush()

    response = login(
        client, email=account.email, password=PASSWORD, tenant_id=policed_tenant.id
    )

    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Tenant handling
# ---------------------------------------------------------------------------

def test_email_still_resolves_across_schools_when_none_is_named(
    client, db_session
):
    """The one legitimate cross-tenant lookup, preserved."""
    first = make_tenant(db_session, subdomain_prefix="p0d-x")
    second = make_tenant(db_session, subdomain_prefix="p0d-y")
    ensure_default_policy(first.id)
    ensure_default_policy(second.id)
    shared = f"twin-{uuid.uuid4().hex[:8]}@test.school"
    make_account(db_session, first, password=PASSWORD, email=shared)
    make_account(db_session, second, password=PASSWORD, email=shared)

    data = login(client, email=shared, password=PASSWORD).get_json()["data"]

    assert data["requires_tenant_choice"] is True
    assert len(data["tenants"]) == 2


def test_the_email_strategy_declares_that_it_needs_no_tenant():
    assert EmailPasswordStrategy.requires_tenant is False


def test_a_tenant_requiring_strategy_is_refused_without_a_school(flask_app):
    """Future methods must not inherit email's exception. Proven by running
    the pipeline with a registry that has one."""

    class _NeedsTenant(EmailPasswordStrategy):
        key = "needs_tenant"
        requires_tenant = True

    service = AuthenticationService(
        AuthenticationStrategyRegistry([_NeedsTenant()])
    )
    with flask_app.test_request_context():
        outcome = service.authenticate(
            AuthenticationRequest(
                identifier="someone@test.school",
                proof=PASSWORD,
                method_key="needs_tenant",
            )
        )

    assert outcome.error == "TenantRequired"
