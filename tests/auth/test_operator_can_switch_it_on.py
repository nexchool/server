"""The two operations an operator needed a Python shell for.

Everything the phases built could be reached over HTTP except two steps, and
without them the whole of phone sign-in and parent sign-in was unreachable
without a developer:

  * recording the mobile number a code or a PIN is checked against;
  * choosing whether parents sign in as themselves.

Both are administrative operations on a school's configuration, so both belong
where the rest of that configuration already lives — the student credential
routes and the platform auth-policy route — rather than in a new surface.
"""

from __future__ import annotations

import uuid

import pytest

from core.database import db
from modules.auth.identifiers import normalize_mobile
from modules.auth.models import AccountIdentifier, User
from modules.auth.policy import (
    ensure_default_policy,
    family_access_mode,
    set_method,
    student_credential_policy,
)
from modules.auth.policy_models import (
    CREDENTIAL_FORCE_CHANGE,
    CREDENTIAL_NO_FORCED_CHANGE,
    FAMILY_ACCESS_SEPARATE,
    FAMILY_ACCESS_SHARED,
    TenantAuthPolicy,
)
from modules.auth.services import generate_access_token
from modules.people.models import Person
from modules.students.models import Student
from tests.auth._characterization import (
    grant_permissions,
    make_tenant,
    make_user,
    new_id,
)

PIN_METHOD = "mobile_pin"
OTP_METHOD = "mobile_otp"


@pytest.fixture(autouse=True)
def _reachable_redis(flask_app):
    """The PIN throttle fails closed, so the end-to-end sign-in below needs a
    Redis to count against — see `test_mobile_pin.py` for why skipping beats
    passing for the wrong reason."""
    import core.cache as cache

    from modules.auth.pin_throttle import clear_for_tests

    previous_url = flask_app.config.get("REDIS_URL")
    previous_pool = cache._pool
    flask_app.config["REDIS_URL"] = "redis://localhost:6379/0"
    cache._pool = None

    with flask_app.app_context():
        redis = cache.redis_client()
        try:
            assert redis is not None and redis.ping()
        except Exception:  # noqa: BLE001
            flask_app.config["REDIS_URL"] = previous_url
            cache._pool = previous_pool
            pytest.skip("this suite needs a reachable Redis for the PIN limiter")
        clear_for_tests(tenant_id="", ip_address="127.0.0.1")

    yield
    flask_app.config["REDIS_URL"] = previous_url
    cache._pool = previous_pool


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _school(db_session, *, phone_sign_in=True):
    tenant = make_tenant(db_session)
    ensure_default_policy(tenant.id)
    if phone_sign_in:
        set_method(tenant.id, "student", PIN_METHOD, enabled=True)
    db_session.flush()
    return tenant


def _student(db_session, tenant):
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
    return student, account


def _operator(db_session, tenant, *, permissions=("student.credential.manage",)):
    user = make_user(db_session, tenant, password="Operator123")
    grant_permissions(db_session, tenant, user, permissions)
    return {
        "Authorization": f"Bearer {generate_access_token(user)}",
        "X-Tenant-ID": tenant.id,
    }


def _platform_admin(db_session, tenant):
    operator = make_user(
        db_session,
        tenant,
        password="Platform12345",
        email=f"ops-{uuid.uuid4().hex[:8]}@nexchool.test",
        is_platform_admin=True,
    )
    return {"Authorization": f"Bearer {generate_access_token(operator)}"}


# ---------------------------------------------------------------------------
# Recording a mobile number
# ---------------------------------------------------------------------------

def test_an_operator_can_record_the_number_a_pin_is_checked_against(
    client, db_session
):
    tenant = _school(db_session)
    student, account = _student(db_session, tenant)
    headers = _operator(db_session, tenant)

    response = client.post(
        f"/api/students/{student.id}/mobile",
        headers=headers,
        json={"mobile": "98765 43210"},
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    # What the office typed, and the canonical form the lookup uses.
    assert data["mobile"] == "98765 43210"
    assert data["mobile_normalized"] == "+919876543210"
    # Recording it is not proof anybody holds it.
    assert data["is_verified"] is False


def test_the_number_then_shows_on_the_credential_status(client, db_session):
    tenant = _school(db_session)
    student, account = _student(db_session, tenant)
    headers = _operator(db_session, tenant)
    client.post(
        f"/api/students/{student.id}/mobile", headers=headers, json={"mobile": "9876543210"}
    )

    status = client.get(
        f"/api/students/{student.id}/credentials", headers=headers
    ).get_json()["data"]

    kinds = {i["type"] for i in status["identifiers"]}
    assert "mobile" in kinds


def test_recording_the_same_number_twice_makes_one_identifier(client, db_session):
    tenant = _school(db_session)
    student, account = _student(db_session, tenant)
    headers = _operator(db_session, tenant)

    first = client.post(
        f"/api/students/{student.id}/mobile", headers=headers, json={"mobile": "9876543210"}
    )
    second = client.post(
        f"/api/students/{student.id}/mobile",
        headers=headers,
        json={"mobile": "+91 98765 43210"},
    )

    assert first.status_code == second.status_code == 200
    assert AccountIdentifier.query.filter_by(
        account_id=account.id, identifier_type="mobile"
    ).count() == 1


def test_a_number_that_cannot_receive_a_message_is_refused(client, db_session):
    tenant = _school(db_session)
    student, account = _student(db_session, tenant)
    headers = _operator(db_session, tenant)

    response = client.post(
        f"/api/students/{student.id}/mobile", headers=headers, json={"mobile": "n/a"}
    )

    assert response.status_code == 400
    assert AccountIdentifier.query.filter_by(
        account_id=account.id, identifier_type="mobile"
    ).count() == 0


def test_a_number_another_student_uses_is_refused_not_moved(client, db_session):
    """Debt 58 said out loud at the surface: two people sharing a phone is a
    decision somebody has to make, not one this endpoint makes for them."""
    tenant = _school(db_session)
    first, first_account = _student(db_session, tenant)
    second, second_account = _student(db_session, tenant)
    headers = _operator(db_session, tenant)
    client.post(
        f"/api/students/{first.id}/mobile", headers=headers, json={"mobile": "9876543210"}
    )

    response = client.post(
        f"/api/students/{second.id}/mobile", headers=headers, json={"mobile": "9876543210"}
    )

    assert response.status_code == 409
    assert response.get_json()["error"] == "MobileAlreadyInUse"
    assert AccountIdentifier.query.filter_by(
        account_id=second_account.id, identifier_type="mobile"
    ).count() == 0


def test_a_school_with_no_phone_sign_in_is_told_why_nothing_happened(
    client, db_session
):
    tenant = _school(db_session, phone_sign_in=False)
    student, account = _student(db_session, tenant)
    headers = _operator(db_session, tenant)

    response = client.post(
        f"/api/students/{student.id}/mobile", headers=headers, json={"mobile": "9876543210"}
    )

    assert response.status_code == 409
    assert "enabled" in response.get_json()["message"]


def test_reading_a_student_is_not_enough_to_record_their_number(client, db_session):
    tenant = _school(db_session)
    student, account = _student(db_session, tenant)
    headers = _operator(db_session, tenant, permissions=("student.read.all",))

    response = client.post(
        f"/api/students/{student.id}/mobile", headers=headers, json={"mobile": "9876543210"}
    )

    assert response.status_code == 403


def test_another_school_cannot_record_a_number_for_this_student(client, db_session):
    ours = _school(db_session)
    theirs = _school(db_session)
    student, account = _student(db_session, theirs)
    headers = _operator(db_session, ours)

    response = client.post(
        f"/api/students/{student.id}/mobile", headers=headers, json={"mobile": "9876543210"}
    )

    assert response.status_code == 404
    assert AccountIdentifier.query.filter_by(
        account_id=account.id, identifier_type="mobile"
    ).count() == 0


def test_a_missing_number_is_a_validation_error(client, db_session):
    tenant = _school(db_session)
    student, account = _student(db_session, tenant)
    headers = _operator(db_session, tenant)

    response = client.post(
        f"/api/students/{student.id}/mobile", headers=headers, json={}
    )

    assert response.status_code == 400


def test_the_whole_pin_flow_now_works_without_a_shell(client, db_session, flask_app):
    """The point of the endpoint: record a number, issue a PIN, sign in."""
    from flask import g as flask_g

    tenant = _school(db_session)
    student, account = _student(db_session, tenant)
    headers = _operator(db_session, tenant)
    number = f"98{uuid.uuid4().int % 100000000:08d}"

    client.post(
        f"/api/students/{student.id}/mobile", headers=headers, json={"mobile": number}
    )
    pin = client.post(
        f"/api/students/{student.id}/pin", headers=headers
    ).get_json()["data"]["pin"]

    for attribute in ("tenant_id", "tenant", "current_user"):
        if hasattr(flask_g, attribute):
            delattr(flask_g, attribute)
    response = client.post(
        "/api/auth/login",
        json={
            "method": PIN_METHOD,
            "identifier": number,
            "password": pin,
            "tenant_id": tenant.id,
        },
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["user"]["id"] == account.id


# ---------------------------------------------------------------------------
# Choosing how families sign in
# ---------------------------------------------------------------------------

def test_an_operator_can_turn_separate_parent_logins_on_and_off(client, db_session):
    tenant = make_tenant(db_session)
    ensure_default_policy(tenant.id)
    headers = _platform_admin(db_session, tenant)

    on = client.patch(
        f"/api/platform/tenants/{tenant.id}/auth-policy",
        headers=headers,
        json={"family_access_mode": FAMILY_ACCESS_SEPARATE},
    )
    assert on.status_code == 200
    assert on.get_json()["data"]["family_access_mode"] == FAMILY_ACCESS_SEPARATE

    off = client.patch(
        f"/api/platform/tenants/{tenant.id}/auth-policy",
        headers=headers,
        json={"family_access_mode": FAMILY_ACCESS_SHARED},
    )
    assert off.get_json()["data"]["family_access_mode"] == FAMILY_ACCESS_SHARED


def test_turning_separate_logins_on_creates_no_account(client, db_session):
    """PARENT-8, now asserted at the surface an operator actually uses."""
    tenant = make_tenant(db_session)
    ensure_default_policy(tenant.id)
    headers = _platform_admin(db_session, tenant)
    before = User.query.filter_by(tenant_id=tenant.id).count()

    client.patch(
        f"/api/platform/tenants/{tenant.id}/auth-policy",
        headers=headers,
        json={"family_access_mode": FAMILY_ACCESS_SEPARATE},
    )
    db_session.flush()

    assert User.query.filter_by(tenant_id=tenant.id).count() == before


def test_the_credential_policy_can_be_set_too(client, db_session):
    tenant = make_tenant(db_session)
    ensure_default_policy(tenant.id)
    headers = _platform_admin(db_session, tenant)

    response = client.patch(
        f"/api/platform/tenants/{tenant.id}/auth-policy",
        headers=headers,
        json={"student_credential_policy": CREDENTIAL_NO_FORCED_CHANGE},
    )

    assert response.get_json()["data"]["student_credential_policy"] == (
        CREDENTIAL_NO_FORCED_CHANGE
    )
    assert student_credential_policy(tenant.id) == CREDENTIAL_NO_FORCED_CHANGE


def test_a_nonsense_mode_is_refused_rather_than_stored(client, db_session):
    tenant = make_tenant(db_session)
    ensure_default_policy(tenant.id)
    headers = _platform_admin(db_session, tenant)

    response = client.patch(
        f"/api/platform/tenants/{tenant.id}/auth-policy",
        headers=headers,
        json={"family_access_mode": "whatever_we_feel_like"},
    )

    assert response.status_code == 400
    assert family_access_mode(tenant.id) == FAMILY_ACCESS_SHARED


def test_sending_nothing_changes_nothing(client, db_session):
    tenant = make_tenant(db_session)
    ensure_default_policy(tenant.id)
    headers = _platform_admin(db_session, tenant)

    response = client.patch(
        f"/api/platform/tenants/{tenant.id}/auth-policy", headers=headers, json={}
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["family_access_mode"] == FAMILY_ACCESS_SHARED


def test_a_school_administrator_cannot_change_their_own_family_mode(
    client, db_session
):
    """Which sign-ins a school may issue is a platform decision, the same
    boundary every other policy read and write sits behind."""
    tenant = make_tenant(db_session)
    ensure_default_policy(tenant.id)
    headers = _operator(db_session, tenant, permissions=("user.manage",))

    response = client.patch(
        f"/api/platform/tenants/{tenant.id}/auth-policy",
        headers=headers,
        json={"family_access_mode": FAMILY_ACCESS_SEPARATE},
    )

    assert response.status_code == 403
    assert family_access_mode(tenant.id) == FAMILY_ACCESS_SHARED


def test_an_unknown_school_is_not_found(client, db_session):
    tenant = make_tenant(db_session)
    headers = _platform_admin(db_session, tenant)

    response = client.patch(
        "/api/platform/tenants/t-nobody/auth-policy",
        headers=headers,
        json={"family_access_mode": FAMILY_ACCESS_SEPARATE},
    )

    assert response.status_code == 404


def test_the_whole_parent_flow_now_works_without_a_shell(client, db_session):
    """Turn separate logins on, provision a parent, and they can sign in."""
    from modules.people.service import record_family_member

    tenant = make_tenant(db_session)
    ensure_default_policy(tenant.id)
    platform = _platform_admin(db_session, tenant)

    child_person = Person(id=new_id("p-"), tenant_id=tenant.id, full_name="A Child")
    db_session.add(child_person)
    db_session.flush()
    db_session.add(
        Student(
            id=new_id("s-"),
            tenant_id=tenant.id,
            person_id=child_person.id,
            admission_number=f"ADM-{uuid.uuid4().hex[:8]}",
        )
    )
    db_session.flush()
    record_family_member(
        tenant.id, child_person.id, name="A Father", relationship="father",
        phone="9876500123",
    )
    db_session.flush()
    parent = Person.query.filter_by(tenant_id=tenant.id, full_name="A Father").first()

    client.patch(
        f"/api/platform/tenants/{tenant.id}/auth-policy",
        headers=platform,
        json={"family_access_mode": FAMILY_ACCESS_SEPARATE},
    )

    school = _operator(db_session, tenant, permissions=("user.manage",))
    provisioned = client.post(
        f"/api/auth/parents/{parent.id}/login",
        headers=school,
        json={"email": "father@example.test"},
    )

    assert provisioned.status_code == 200
    assert provisioned.get_json()["data"]["password"]
