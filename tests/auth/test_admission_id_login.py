"""Phase 1b — a student signs in with the number their school gave them.

The first authentication method after email and password, and the first one
whose identifier is unique only inside one school. Almost everything in this
file follows from that single fact: two schools will both have a ``10042`` and
neither is wrong, so the school has to be known before the number means
anything at all.

The security assertions are the ones to read first:

  * `test_no_school_named_is_refused_before_any_lookup` — A4. A tenant-less
    attempt is refused *before* resolution, so it cannot quietly return a
    different school's child.
  * `test_a_number_from_another_school_looks_exactly_like_an_unknown_one` — A8.
  * `test_a_generated_password_contains_nothing_about_the_person` — A5.
"""

from __future__ import annotations

import re
import uuid
from datetime import date

import pytest

from core.database import db
from modules.auth.event_models import (
    EVENT_LOGIN_FAILURE,
    EVENT_LOGIN_SUCCESS,
    REASON_POLICY_DENIED,
    REASON_TENANT_UNRESOLVED,
    AuthEvent,
    hash_identifier,
)
from modules.auth.identifiers import normalize_admission_id, normalize_identifier
from modules.auth.models import AccountCredential, AccountIdentifier, User
from modules.auth.policy import ensure_default_policy, set_method
from modules.auth.provisioning import (
    CREDENTIAL_ALPHABET,
    CREDENTIAL_LENGTH,
    generate_initial_password,
    issue_admission_identifier,
)
from modules.auth.strategies import IdentifierPasswordStrategy, registry
from modules.people.models import Person
from modules.students.models import Student
from tests.auth._characterization import (
    decode_access_token,
    make_platform_admin,
    make_tenant,
    make_user,
    new_id,
    sessions_for,
)

METHOD = "admission_id_password"
PASSWORD = "C0rrectHorse1"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _permit_admission_login(tenant):
    ensure_default_policy(tenant.id)
    set_method(tenant.id, "student", METHOD, enabled=True)


def _student_who_can_sign_in(db_session, tenant, *, admission_number, password):
    """A student with an account, an admission identifier and a password."""
    account = make_user(db_session, tenant, password=password)
    student = Student(
        id=new_id("s-"),
        tenant_id=tenant.id,
        user_id=account.id,
        person_id=account.person_id,
        admission_number=admission_number,
    )
    db_session.add(student)
    db_session.flush()
    identifier = issue_admission_identifier(account, admission_number)
    db_session.flush()
    return account, student, identifier


def _login(client, *, identifier, password, **body):
    payload = {"method": METHOD, "identifier": identifier, "password": password}
    payload.update(body)
    return client.post("/api/auth/login", json=payload)


def _fresh_request(flask_app):
    """Forget the school the previous request resolved.

    A test runs inside `db_session`'s app context, and Flask reuses a pushed
    app context rather than making a new one per request — so `g` survives
    between calls to the test client, which it never does in production.
    `resolve_tenant_for_auth` returns early when `g.tenant_id` is already set,
    so without this a second sign-in in one test is silently scoped to the
    first one's school. A harness artefact, not product behaviour, and only
    tests that sign in twice need to care.
    """
    from flask import g as flask_g

    for attribute in ("tenant_id", "tenant", "current_user"):
        if hasattr(flask_g, attribute):
            delattr(flask_g, attribute)


# ---------------------------------------------------------------------------
# The strategy and the registry
# ---------------------------------------------------------------------------

def test_the_strategy_is_registered_under_its_method_key():
    assert METHOD in registry
    assert registry.get(METHOD).__class__ is IdentifierPasswordStrategy


def test_the_strategy_presents_an_admission_identifier():
    assert IdentifierPasswordStrategy.identifier_type == "admission_id"
    assert IdentifierPasswordStrategy.credential_type == "password"


def test_the_strategy_requires_a_school():
    """The property the whole method hangs on."""
    assert IdentifierPasswordStrategy.requires_tenant is True


def test_the_registry_still_permits_exactly_one_tenant_less_method():
    """A4, re-asserted now that a second strategy exists."""
    registry.validate()
    tenant_less = [k for k in registry.keys() if not registry.get(k).requires_tenant]
    assert tenant_less == ["email_password"]


def test_the_strategy_refuses_to_resolve_without_a_school(flask_app):
    """Belt and braces below the pipeline: even called directly with no
    tenant, it searches nothing rather than searching everything."""
    with flask_app.test_request_context():
        assert IdentifierPasswordStrategy().resolve("10042", None) == []


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("  adm2026/001  ", "ADM2026/001"),
        ("adm2026/001", "ADM2026/001"),
        ("ADM2026/001", "ADM2026/001"),
        ("ADM  2026  001", "ADM 2026 001"),
    ],
)
def test_case_and_stray_spaces_do_not_make_a_second_number(raw, expected):
    assert normalize_admission_id(raw) == expected


def test_punctuation_and_leading_zeros_are_preserved():
    """Two different children, and folding them would merge them."""
    assert normalize_admission_id("2026/001") != normalize_admission_id("2026-001")
    assert normalize_admission_id("001") != normalize_admission_id("1")


def test_normalizing_is_idempotent():
    once = normalize_admission_id("  adm 2026/001 ")
    assert normalize_admission_id(once) == once


def test_the_dispatcher_routes_admission_ids():
    assert normalize_identifier("admission_id", " adm-1 ") == "ADM-1"


# ---------------------------------------------------------------------------
# A5 — the generated credential
# ---------------------------------------------------------------------------

def test_a_generated_password_is_the_right_length_and_alphabet():
    for _ in range(200):
        password = generate_initial_password()
        assert len(password) == CREDENTIAL_LENGTH
        assert 8 <= len(password) <= 10
        assert set(password) <= set(CREDENTIAL_ALPHABET)


def test_a_generated_password_excludes_ambiguous_glyphs():
    """It is read off paper and typed by a child."""
    for _ in range(200):
        assert not (set(generate_initial_password()) & set("0O1lI"))


def test_generated_passwords_are_not_deterministic():
    produced = {generate_initial_password() for _ in range(200)}
    assert len(produced) > 190, "a generator this repetitive is not random"


def test_a_generated_password_contains_nothing_about_the_person():
    """A5 stated as the property it is, not as one expected string.

    A thousand passwords, and none of them carries the child's name, date of
    birth, admission number, phone or academic year — the five things the two
    generators this replaced were built out of.
    """
    attributes = [
        "PRIYA", "SHARMA", "priya", "sharma",
        "2013", "0821", "2013-08-21",
        "ADM2026001", "adm2026001",
        "9876511111", "2026", "2027",
    ]
    for _ in range(1000):
        password = generate_initial_password()
        upper = password.upper()
        for attribute in attributes:
            assert attribute.upper() not in upper


def test_the_generator_draws_on_the_secure_source():
    """`random` is seeded predictably and is not for anything guarding an
    account. Asserted by reading the module rather than by statistics."""
    import inspect

    from modules.auth import provisioning

    source = inspect.getsource(provisioning)
    assert "import secrets" in source
    assert "secrets.choice" in source
    assert "import random" not in source


# ---------------------------------------------------------------------------
# Issuance
# ---------------------------------------------------------------------------

def test_an_admission_identifier_is_issued_when_the_school_permits_it(
    db_session, tenant
):
    _permit_admission_login(tenant)
    account, _student, identifier = _student_who_can_sign_in(
        db_session, tenant, admission_number="ADM2026001", password=PASSWORD
    )

    assert identifier is not None
    assert identifier.account_id == account.id
    assert identifier.identifier_value == "ADM2026001"
    assert identifier.identifier_value_normalized == "ADM2026001"
    assert identifier.is_verified is True
    assert identifier.deleted_at is None


def test_no_identifier_is_issued_when_the_school_has_not_enabled_it(
    db_session, tenant
):
    """Off by default. The table does not fill up with credentials for a door
    that is closed."""
    ensure_default_policy(tenant.id)
    account = make_user(db_session, tenant, password=PASSWORD)

    assert issue_admission_identifier(account, "ADM2026001") is None
    assert (
        AccountIdentifier.query.filter_by(
            account_id=account.id, identifier_type="admission_id"
        ).count()
        == 0
    )


def test_issuing_twice_does_not_create_a_second_identifier(db_session, tenant):
    _permit_admission_login(tenant)
    account, _s, first = _student_who_can_sign_in(
        db_session, tenant, admission_number="ADM2026001", password=PASSWORD
    )

    again = issue_admission_identifier(account, "ADM2026001")
    db_session.flush()

    assert again.id == first.id
    assert (
        AccountIdentifier.query.filter_by(
            account_id=account.id, identifier_type="admission_id", deleted_at=None
        ).count()
        == 1
    )


def test_the_email_identifier_survives_the_admission_one(db_session, tenant):
    """Adding a way in never removes one."""
    _permit_admission_login(tenant)
    account, _s, _i = _student_who_can_sign_in(
        db_session, tenant, admission_number="ADM2026001", password=PASSWORD
    )

    kinds = {
        i.identifier_type
        for i in AccountIdentifier.query.filter_by(
            account_id=account.id, deleted_at=None
        )
    }
    assert kinds == {"email", "admission_id"}


def test_two_schools_may_each_issue_the_same_number(db_session, tenant):
    other = make_tenant(db_session, subdomain_prefix="p1b-other")
    _permit_admission_login(tenant)
    _permit_admission_login(other)

    _student_who_can_sign_in(
        db_session, tenant, admission_number="10042", password=PASSWORD
    )
    _student_who_can_sign_in(
        db_session, other, admission_number="10042", password=PASSWORD
    )

    assert (
        AccountIdentifier.query.filter_by(
            identifier_type="admission_id",
            identifier_value_normalized="10042",
            deleted_at=None,
        ).count()
        == 2
    )


def test_one_school_cannot_issue_the_same_number_twice(db_session, tenant):
    """The identifier index, not the students one.

    Two students in a school cannot share an admission number either, but that
    is `uq_students_admission_number_tenant` and it fires first — so this
    issues a second identifier to a *different* account to reach the rule
    under test.
    """
    from sqlalchemy.exc import IntegrityError

    _permit_admission_login(tenant)
    _student_who_can_sign_in(
        db_session, tenant, admission_number="10042", password=PASSWORD
    )

    other_account = make_user(db_session, tenant, password=PASSWORD)
    db_session.add(
        Student(
            id=new_id("s-"), tenant_id=tenant.id, user_id=other_account.id,
            person_id=other_account.person_id, admission_number="10043",
        )
    )
    db_session.flush()
    db_session.add(
        AccountIdentifier(
            tenant_id=tenant.id, account_id=other_account.id,
            identifier_type="admission_id", identifier_value="10042",
            identifier_value_normalized="10042", is_verified=True,
        )
    )

    with pytest.raises(IntegrityError) as refused:
        db_session.flush()
    assert "uq_account_identifiers_live" in str(refused.value)


# ---------------------------------------------------------------------------
# Signing in
# ---------------------------------------------------------------------------

def test_a_student_signs_in_with_their_admission_number(client, db_session, tenant):
    _permit_admission_login(tenant)
    account, _s, _i = _student_who_can_sign_in(
        db_session, tenant, admission_number="ADM2026001", password=PASSWORD
    )

    response = _login(
        client, identifier="ADM2026001", password=PASSWORD, tenant_id=tenant.id
    )

    assert response.status_code == 200, response.get_json()
    data = response.get_json()["data"]
    assert data["user"]["id"] == account.id
    assert data["tenant_id"] == str(tenant.id)


def test_the_response_is_the_same_shape_as_an_email_sign_in(
    flask_app, client, db_session, tenant
):
    """One finalization, one contract."""
    _permit_admission_login(tenant)
    account, _s, _i = _student_who_can_sign_in(
        db_session, tenant, admission_number="ADM2026001", password=PASSWORD
    )

    by_number = _login(
        client, identifier="ADM2026001", password=PASSWORD, tenant_id=tenant.id
    ).get_json()["data"]
    _fresh_request(flask_app)
    by_email = client.post(
        "/api/auth/login",
        json={"email": account.email, "password": PASSWORD, "tenant_id": tenant.id},
    ).get_json()["data"]

    assert set(by_number) == set(by_email)


def test_the_number_may_be_typed_in_any_case_or_with_spaces(
    client, db_session, tenant
):
    _permit_admission_login(tenant)
    _student_who_can_sign_in(
        db_session, tenant, admission_number="ADM2026001", password=PASSWORD
    )

    response = _login(
        client, identifier="  adm2026001  ", password=PASSWORD, tenant_id=tenant.id
    )

    assert response.status_code == 200, response.get_json()


def test_the_school_may_be_named_by_subdomain(client, db_session, tenant):
    _permit_admission_login(tenant)
    _student_who_can_sign_in(
        db_session, tenant, admission_number="ADM2026001", password=PASSWORD
    )

    response = _login(
        client,
        identifier="ADM2026001",
        password=PASSWORD,
        subdomain=tenant.subdomain,
    )

    assert response.status_code == 200, response.get_json()


def test_email_sign_in_still_works_for_the_same_account(
    client, db_session, tenant
):
    """The identifier chooses the account; it does not replace the other one."""
    _permit_admission_login(tenant)
    account, _s, _i = _student_who_can_sign_in(
        db_session, tenant, admission_number="ADM2026001", password=PASSWORD
    )

    response = client.post(
        "/api/auth/login",
        json={"email": account.email, "password": PASSWORD, "tenant_id": tenant.id},
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["data"]["user"]["id"] == account.id


# ---------------------------------------------------------------------------
# A4 — the school must be known
# ---------------------------------------------------------------------------

def test_no_school_named_is_refused_before_any_lookup(
    client, db_session, tenant, monkeypatch
):
    """A4, and the most important test in this file.

    An admission number without a school does not identify anybody. The
    refusal happens before resolution, so a tenant-less attempt cannot fall
    through to the default school and return a different child — which is what
    the email path's default-tenant fallback would otherwise do.
    """
    _permit_admission_login(tenant)
    _student_who_can_sign_in(
        db_session, tenant, admission_number="10042", password=PASSWORD
    )

    looked_up = []
    original = IdentifierPasswordStrategy.resolve

    def _record(self, value, tenant_id):
        looked_up.append((value, tenant_id))
        return original(self, value, tenant_id)

    monkeypatch.setattr(IdentifierPasswordStrategy, "resolve", _record)

    response = _login(client, identifier="10042", password=PASSWORD)

    assert response.status_code == 400
    assert response.get_json()["error"] == "TenantRequired"
    assert looked_up == [], "no identifier lookup may happen without a school"


def test_the_tenant_less_refusal_is_recorded(client, db_session, tenant):
    _permit_admission_login(tenant)

    _login(client, identifier="10042", password=PASSWORD)

    event = (
        AuthEvent.query.filter_by(method_key=METHOD)
        .order_by(AuthEvent.created_at.desc())
        .first()
    )
    assert event.event_type == EVENT_LOGIN_FAILURE
    assert event.reason == REASON_TENANT_UNRESOLVED


def test_email_sign_in_keeps_its_tenant_less_path(client, db_session, tenant):
    """The exception is email's alone, and it is untouched."""
    _permit_admission_login(tenant)
    account, _s, _i = _student_who_can_sign_in(
        db_session, tenant, admission_number="ADM2026001", password=PASSWORD
    )

    response = client.post(
        "/api/auth/login", json={"email": account.email, "password": PASSWORD}
    )

    assert response.status_code == 200, response.get_json()


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------

def test_the_same_number_in_two_schools_resolves_to_its_own_child(
    flask_app, client, db_session, tenant
):
    other = make_tenant(db_session, subdomain_prefix="p1b-iso")
    _permit_admission_login(tenant)
    _permit_admission_login(other)
    here, _s1, _i1 = _student_who_can_sign_in(
        db_session, tenant, admission_number="10042", password="Here-Passw0rd"
    )
    there, _s2, _i2 = _student_who_can_sign_in(
        db_session, other, admission_number="10042", password="There-Passw0rd"
    )

    first = _login(
        client, identifier="10042", password="Here-Passw0rd", tenant_id=tenant.id
    )
    _fresh_request(flask_app)
    second = _login(
        client, identifier="10042", password="There-Passw0rd", tenant_id=other.id
    )

    assert first.get_json()["data"]["user"]["id"] == here.id
    assert second.get_json()["data"]["user"]["id"] == there.id


def test_a_number_from_another_school_looks_exactly_like_an_unknown_one(
    flask_app, client, db_session, tenant
):
    """A8. Naming the wrong school must not reveal that the child exists."""
    other = make_tenant(db_session, subdomain_prefix="p1b-wrong")
    _permit_admission_login(tenant)
    _permit_admission_login(other)
    _student_who_can_sign_in(
        db_session, tenant, admission_number="10042", password=PASSWORD
    )

    wrong_school = _login(
        client, identifier="10042", password=PASSWORD, tenant_id=other.id
    )
    _fresh_request(flask_app)
    unknown = _login(
        client, identifier="99999", password=PASSWORD, tenant_id=other.id
    )

    assert wrong_school.status_code == unknown.status_code == 401
    assert wrong_school.get_json() == unknown.get_json()


def test_a_wrong_password_says_no_more_than_an_unknown_number(
    flask_app, client, db_session, tenant
):
    _permit_admission_login(tenant)
    _student_who_can_sign_in(
        db_session, tenant, admission_number="10042", password=PASSWORD
    )

    wrong = _login(
        client, identifier="10042", password="not-it", tenant_id=tenant.id
    )
    _fresh_request(flask_app)
    unknown = _login(
        client, identifier="99999", password="not-it", tenant_id=tenant.id
    )

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.get_json() == unknown.get_json()


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------

def test_a_school_that_has_not_enabled_it_refuses_the_method(
    client, db_session, tenant
):
    """Deploying Phase 1b does not change any school's behaviour."""
    ensure_default_policy(tenant.id)
    account = make_user(db_session, tenant, password=PASSWORD)
    student = Student(
        id=new_id("s-"), tenant_id=tenant.id, user_id=account.id,
        person_id=account.person_id, admission_number="10042",
    )
    db_session.add(student)
    # Issued directly, bypassing the policy gate, so the refusal below is the
    # policy's and not merely a missing identifier.
    db_session.add(
        AccountIdentifier(
            tenant_id=tenant.id, account_id=account.id,
            identifier_type="admission_id", identifier_value="10042",
            identifier_value_normalized="10042", is_verified=True, is_primary=True,
        )
    )
    db_session.flush()

    response = _login(
        client, identifier="10042", password=PASSWORD, tenant_id=tenant.id
    )

    # Uniform with a wrong password, deliberately: telling "this account
    # exists but the method is off" from "no such account" was an
    # enumeration oracle needing no password. The reason is still recorded.
    assert response.status_code == 401
    assert response.get_json()["error"] == "InvalidCredentials"


def test_the_method_is_denied_before_the_password_is_checked(
    client, db_session, tenant
):
    """A denied method never consumes a verification, and the refusal does not
    depend on whether the password was right."""
    ensure_default_policy(tenant.id)
    account = make_user(db_session, tenant, password=PASSWORD)
    db_session.add(
        AccountIdentifier(
            tenant_id=tenant.id, account_id=account.id,
            identifier_type="admission_id", identifier_value="10042",
            identifier_value_normalized="10042", is_verified=True, is_primary=True,
        )
    )
    db_session.flush()

    response = _login(
        client, identifier="10042", password="wrong-entirely", tenant_id=tenant.id
    )

    assert response.status_code == 401
    db_session.refresh(account)
    assert (account.failed_login_count or 0) == 0
    event = (
        AuthEvent.query.filter_by(account_id=account.id)
        .order_by(AuthEvent.created_at.desc())
        .first()
    )
    assert event.reason == REASON_POLICY_DENIED


def test_disabling_the_method_closes_it_and_leaves_email_open(
    flask_app, client, db_session, tenant
):
    _permit_admission_login(tenant)
    account, _s, _i = _student_who_can_sign_in(
        db_session, tenant, admission_number="10042", password=PASSWORD
    )
    assert _login(
        client, identifier="10042", password=PASSWORD, tenant_id=tenant.id
    ).status_code == 200

    set_method(tenant.id, "student", METHOD, enabled=False)
    db_session.flush()

    _fresh_request(flask_app)
    assert _login(
        client, identifier="10042", password=PASSWORD, tenant_id=tenant.id
    ).status_code == 401
    _fresh_request(flask_app)
    assert client.post(
        "/api/auth/login",
        json={"email": account.email, "password": PASSWORD, "tenant_id": tenant.id},
    ).status_code == 200


def test_enabling_it_for_students_does_not_enable_it_for_staff(
    db_session, tenant
):
    from modules.auth.policy import methods_for

    _permit_admission_login(tenant)

    assert METHOD in methods_for(tenant.id, ["student"])
    assert METHOD not in methods_for(tenant.id, ["staff"])


def test_an_unknown_method_key_cannot_be_enabled(db_session, tenant):
    ensure_default_policy(tenant.id)

    with pytest.raises(ValueError):
        set_method(tenant.id, "student", "telepathy", enabled=True)


def test_a_platform_admin_is_unaffected(client, db_session, tenant):
    """A3 holds: the operator's way in is not the school's to withdraw."""
    _permit_admission_login(tenant)
    set_method(tenant.id, "student", METHOD, enabled=False)
    set_method(tenant.id, "staff", "email_password", enabled=False)
    db_session.flush()

    home = make_tenant(db_session, subdomain_prefix="p1b-hq")
    admin = make_platform_admin(db_session, home, password=PASSWORD)

    response = client.post(
        "/api/auth/login",
        json={"email": admin.email, "password": PASSWORD, "tenant_id": tenant.id},
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["data"]["is_platform_admin"] is True


# ---------------------------------------------------------------------------
# Session, token and events
# ---------------------------------------------------------------------------

def test_the_session_records_the_method_and_the_identifier(
    client, db_session, tenant
):
    _permit_admission_login(tenant)
    account, _s, identifier = _student_who_can_sign_in(
        db_session, tenant, admission_number="ADM2026001", password=PASSWORD
    )

    client.post(
        "/api/auth/login",
        json={
            "method": METHOD, "identifier": "ADM2026001",
            "password": PASSWORD, "tenant_id": tenant.id,
        },
        headers={"X-Client-Surface": "student-mobile"},
    )

    session = sessions_for(account.id)[0]
    assert session.login_method == METHOD
    assert session.client_surface == "student-mobile"
    assert session.authenticated_identifier_id == identifier.id


def test_login_method_fits_the_column(db_session, tenant):
    """`admission_id_password` is 21 characters; the column was widened to 40
    in Phase 0d for exactly this."""
    from modules.auth.models import Session

    assert len(METHOD) > 20
    assert Session.__table__.c.login_method.type.length >= len(METHOD)


def test_the_token_names_the_school_and_the_method(client, db_session, tenant):
    _permit_admission_login(tenant)
    _student_who_can_sign_in(
        db_session, tenant, admission_number="ADM2026001", password=PASSWORD
    )

    data = _login(
        client, identifier="ADM2026001", password=PASSWORD, tenant_id=tenant.id
    ).get_json()["data"]

    claims = decode_access_token(data["access_token"])
    assert claims["tid"] == str(tenant.id)
    assert claims["amr"] == METHOD
    # `jti` names this token and `sid` names the session it came from — the
    # latter is what makes revoking a session felt immediately rather than at
    # the token's own expiry.
    # `jti` names this token; `sid` names the session it came from, which is
    # what makes revoking a session felt immediately rather than at expiry.
    assert set(claims) == {
        "sub", "email", "is_platform_admin", "type", "iat", "exp", "tid", "amr",
        "jti", "sid",
    }
    # The session the token belongs to, and the reason revoking one is felt
    # immediately rather than at the token's own expiry.
    assert claims["sid"]


def test_a_successful_sign_in_is_recorded_with_a_hashed_number(
    client, db_session, tenant
):
    _permit_admission_login(tenant)
    account, _s, _i = _student_who_can_sign_in(
        db_session, tenant, admission_number="ADM2026001", password=PASSWORD
    )

    _login(client, identifier="ADM2026001", password=PASSWORD, tenant_id=tenant.id)

    event = (
        AuthEvent.query.filter_by(account_id=account.id)
        .order_by(AuthEvent.created_at.desc())
        .first()
    )
    assert event.event_type == EVENT_LOGIN_SUCCESS
    assert event.method_key == METHOD
    assert event.identifier_type == "admission_id"
    assert event.identifier_value_hash == hash_identifier("ADM2026001")
    # The number itself appears nowhere in the row.
    row = {c.name: getattr(event, c.name) for c in AuthEvent.__table__.columns}
    assert "ADM2026001" not in str(row)


def test_a_failed_sign_in_is_recorded_under_the_same_method(
    client, db_session, tenant
):
    _permit_admission_login(tenant)
    account, _s, _i = _student_who_can_sign_in(
        db_session, tenant, admission_number="ADM2026001", password=PASSWORD
    )

    _login(client, identifier="ADM2026001", password="wrong", tenant_id=tenant.id)

    event = (
        AuthEvent.query.filter_by(account_id=account.id)
        .order_by(AuthEvent.created_at.desc())
        .first()
    )
    assert event.event_type == EVENT_LOGIN_FAILURE
    assert event.method_key == METHOD


# ---------------------------------------------------------------------------
# Tenant branding
# ---------------------------------------------------------------------------

def test_branding_advertises_the_method_only_where_it_is_permitted(
    flask_app, client, db_session, tenant
):
    ensure_default_policy(tenant.id)

    before = client.get(
        "/api/auth/tenant-branding",
        headers={"X-Tenant-Subdomain": tenant.subdomain},
    ).get_json()["data"]
    assert before["auth"]["methods"] == ["email_password"]

    set_method(tenant.id, "student", METHOD, enabled=True)
    db_session.flush()

    _fresh_request(flask_app)
    after = client.get(
        "/api/auth/tenant-branding",
        headers={"X-Tenant-Subdomain": tenant.subdomain},
    ).get_json()["data"]
    assert sorted(after["auth"]["methods"]) == [METHOD, "email_password"]


def test_branding_never_says_which_person_may_use_what(client, db_session, tenant):
    """The union across kinds, and nothing finer — the endpoint is
    unauthenticated."""
    _permit_admission_login(tenant)

    data = client.get(
        "/api/auth/tenant-branding",
        headers={"X-Tenant-Subdomain": tenant.subdomain},
    ).get_json()["data"]

    assert set(data["auth"]) == {"methods"}
    assert isinstance(data["auth"]["methods"], list)


# ---------------------------------------------------------------------------
# Provisioning through the real services
# ---------------------------------------------------------------------------

@pytest.fixture
def academic_year(db_session, tenant):
    from modules.academics.academic_year.models import AcademicYear

    year = AcademicYear(
        id=new_id("ay-"), tenant_id=tenant.id, name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 6, 1), end_date=date(2027, 3, 31), is_active=True,
    )
    db_session.add(year)
    db_session.flush()
    return year


def test_creating_a_student_issues_the_identifier_and_a_random_password(
    flask_app, db_session, tenant, academic_year
):
    from flask import g

    from modules.students.services import create_student

    _permit_admission_login(tenant)
    email = f"student-{uuid.uuid4().hex[:8]}@test.school"

    with flask_app.test_request_context():
        g.tenant_id = tenant.id
        result = create_student(
            name="Priya Sharma",
            academic_year_id=academic_year.id,
            guardian_name="A Guardian",
            guardian_relationship="father",
            guardian_phone="9876500001",
            email=email,
            date_of_birth="2013-08-21",
        )

    assert result.get("success") is True, result
    issued = result["credentials"]["password"]
    account = User.query.filter_by(tenant_id=tenant.id, email=email).one()

    # The identifier is the school's own admission number.
    identifier = AccountIdentifier.query.filter_by(
        account_id=account.id, identifier_type="admission_id", deleted_at=None
    ).one()
    assert identifier.identifier_value == result["student"]["admission_number"]

    # And the credential says nothing about her.
    assert len(issued) == CREDENTIAL_LENGTH
    assert set(issued) <= set(CREDENTIAL_ALPHABET)
    for attribute in ("PRIYA", "SHARMA", "2013", identifier.identifier_value.upper()):
        assert attribute not in issued.upper()

    assert account.force_password_reset is True
    assert (
        User.query.filter_by(
            tenant_id=tenant.id, person_id=account.person_id, deleted_at=None
        ).count()
        == 1
    )
    assert Person.query.filter_by(id=account.person_id).count() == 1


def test_a_created_student_can_then_sign_in_with_their_number(
    flask_app, client, db_session, tenant, academic_year
):
    """End to end, through the real pipeline."""
    from flask import g

    from modules.students.services import create_student

    _permit_admission_login(tenant)
    with flask_app.test_request_context():
        g.tenant_id = tenant.id
        result = create_student(
            name="Arun Menon",
            academic_year_id=academic_year.id,
            guardian_name="A Guardian",
            guardian_relationship="father",
            guardian_phone="9876500002",
            email=f"student-{uuid.uuid4().hex[:8]}@test.school",
        )

    admission_number = result["student"]["admission_number"]
    issued = result["credentials"]["password"]

    response = _login(
        client, identifier=admission_number, password=issued, tenant_id=tenant.id
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["data"]["force_password_reset"] is True


def test_a_student_created_where_the_method_is_off_gets_no_identifier(
    flask_app, db_session, tenant, academic_year
):
    from flask import g

    from modules.students.services import create_student

    ensure_default_policy(tenant.id)
    email = f"student-{uuid.uuid4().hex[:8]}@test.school"

    with flask_app.test_request_context():
        g.tenant_id = tenant.id
        result = create_student(
            name="No Number Login",
            academic_year_id=academic_year.id,
            guardian_name="A Guardian",
            guardian_relationship="father",
            guardian_phone="9876500003",
            email=email,
        )

    assert result.get("success") is True, result
    account = User.query.filter_by(tenant_id=tenant.id, email=email).one()
    assert (
        AccountIdentifier.query.filter_by(
            account_id=account.id, identifier_type="admission_id"
        ).count()
        == 0
    )
    # And the email identifier is still there.
    assert (
        AccountIdentifier.query.filter_by(
            account_id=account.id, identifier_type="email", deleted_at=None
        ).count()
        == 1
    )


def test_a_created_student_gets_a_credential_row_matching_the_account(
    flask_app, db_session, tenant, academic_year
):
    """The dual write: the pipeline reads the credential first, so it must
    carry the same secret the account does."""
    from flask import g

    from modules.students.services import create_student

    _permit_admission_login(tenant)
    email = f"student-{uuid.uuid4().hex[:8]}@test.school"
    with flask_app.test_request_context():
        g.tenant_id = tenant.id
        create_student(
            name="Credential Child",
            academic_year_id=academic_year.id,
            guardian_name="A Guardian",
            guardian_relationship="father",
            guardian_phone="9876500004",
            email=email,
        )

    account = User.query.filter_by(tenant_id=tenant.id, email=email).one()
    credential = AccountCredential.query.filter_by(
        account_id=account.id, credential_type="password", deleted_at=None
    ).one()
    assert credential.secret_hash == account.password_hash
    assert credential.is_provisional is True
    assert credential.must_change is True


def test_changing_the_password_keeps_the_credential_in_step(
    flask_app, client, db_session, tenant, academic_year
):
    """The trap the dual write creates, closed.

    The pipeline verifies against the credential row when one exists, so a
    password changed on the account and not here would leave the person unable
    to sign in with the password they just chose.
    """
    from flask import g

    from modules.students.services import create_student

    _permit_admission_login(tenant)
    email = f"student-{uuid.uuid4().hex[:8]}@test.school"
    with flask_app.test_request_context():
        g.tenant_id = tenant.id
        result = create_student(
            name="Rotating Child",
            academic_year_id=academic_year.id,
            guardian_name="A Guardian",
            guardian_relationship="father",
            guardian_phone="9876500005",
            email=email,
        )

    admission_number = result["student"]["admission_number"]
    account = User.query.filter_by(tenant_id=tenant.id, email=email).one()

    account.set_password("Ch0senByMe99")
    db_session.flush()

    credential = AccountCredential.query.filter_by(
        account_id=account.id, credential_type="password", deleted_at=None
    ).one()
    assert credential.secret_hash == account.password_hash

    # And the new password actually works through the pipeline.
    account.force_password_reset = False
    db_session.flush()
    response = _login(
        client,
        identifier=admission_number,
        password="Ch0senByMe99",
        tenant_id=tenant.id,
    )
    assert response.status_code == 200, response.get_json()
