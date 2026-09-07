"""Phase 6 — a parent signs in, over HTTP.

No new endpoint and no new method. A parent signs in at `POST /api/auth/login`
with the email and password every other account uses, and "parent" is what
they *are*, not how they proved it. So the interesting assertions are about
the gates around it: the school's mode, the tenant boundary, and which
children the session can reach.
"""

from __future__ import annotations

import uuid

import pytest

from core.database import db
from modules.auth.models import User
from modules.auth.parents import provision_parent_login
from modules.auth.policy import ensure_default_policy
from modules.auth.policy_models import (
    FAMILY_ACCESS_SEPARATE,
    FAMILY_ACCESS_SHARED,
    TenantAuthPolicy,
)
from modules.auth.services import generate_access_token
from modules.people.models import Person
from modules.people.service import record_family_member
from modules.rbac.role_seeder import seed_roles_for_tenant
from modules.students.models import Student
from tests.auth._characterization import (
    decode_access_token,
    grant_permissions,
    make_tenant,
    make_user,
    new_id,
    sessions_for,
)


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _fresh_request(flask_app):
    from flask import g as flask_g

    for attribute in ("tenant_id", "tenant", "current_user"):
        if hasattr(flask_g, attribute):
            delattr(flask_g, attribute)


def _school(db_session, *, separate=True):
    tenant = make_tenant(db_session)
    ensure_default_policy(tenant.id)
    seed_roles_for_tenant(tenant.id)
    if separate:
        policy = TenantAuthPolicy.query.filter_by(tenant_id=tenant.id).first()
        policy.family_access_mode = FAMILY_ACCESS_SEPARATE
    db_session.flush()
    return tenant


def _child(db_session, tenant, *, name="A Child"):
    person = Person(id=new_id("p-"), tenant_id=tenant.id, full_name=name)
    db_session.add(person)
    db_session.flush()
    student = Student(
        id=new_id("s-"),
        tenant_id=tenant.id,
        person_id=person.id,
        admission_number=f"ADM-{uuid.uuid4().hex[:8]}",
    )
    db_session.add(student)
    db_session.flush()
    return student, person


def _parent_with_login(db_session, tenant, *, name=None, email=None, children=1):
    """A parent of `children` students, with a login of their own."""
    label = name or f"Parent {uuid.uuid4().hex[:6]}"
    phone = f"98{uuid.uuid4().int % 100000000:08d}"
    students = []
    for index in range(children):
        student, person = _child(db_session, tenant, name=f"{label} child {index}")
        record_family_member(
            tenant.id, person.id, name=label, relationship="father", phone=phone
        )
        students.append(student)
    db_session.flush()

    parent = (
        Person.query.filter_by(tenant_id=tenant.id, full_name=label)
        .order_by(Person.created_at.desc())
        .first()
    )
    address = email or f"{uuid.uuid4().hex[:8]}@example.test"
    result = provision_parent_login(parent, email=address)
    db_session.flush()
    return parent, result.account, result.password, students


def _sign_in(client, flask_app, tenant, *, email, password):
    _fresh_request(flask_app)
    return client.post(
        "/api/auth/login",
        json={"email": email, "password": password, "tenant_id": tenant.id},
    )


# ---------------------------------------------------------------------------
# Signing in
# ---------------------------------------------------------------------------

def test_a_parent_signs_in_with_their_own_email_and_password(
    client, db_session, flask_app
):
    tenant = _school(db_session)
    parent, account, password, students = _parent_with_login(db_session, tenant)

    response = _sign_in(client, flask_app, tenant, email=account.email, password=password)

    assert response.status_code == 200
    assert response.get_json()["data"]["user"]["id"] == account.id


def test_the_session_says_email_password_not_parent_login(
    client, db_session, flask_app
):
    """"Parent" is a subject kind, not an authentication method."""
    tenant = _school(db_session)
    parent, account, password, students = _parent_with_login(db_session, tenant)

    body = _sign_in(
        client, flask_app, tenant, email=account.email, password=password
    ).get_json()["data"]
    db_session.flush()

    session = sessions_for(account.id)[-1]
    claims = decode_access_token(body["access_token"])

    assert session.login_method == "email_password"
    assert session.authenticated_identifier_id is not None
    assert claims["amr"] == "email_password"
    assert claims["tid"] == tenant.id


def test_a_wrong_password_does_not_sign_a_parent_in(client, db_session, flask_app):
    tenant = _school(db_session)
    parent, account, password, students = _parent_with_login(db_session, tenant)

    response = _sign_in(
        client, flask_app, tenant, email=account.email, password="NotThePassword1"
    )

    assert response.status_code == 401


def test_a_suspended_parent_cannot_sign_in(client, db_session, flask_app):
    tenant = _school(db_session)
    parent, account, password, students = _parent_with_login(db_session, tenant)
    account.is_suspended = True
    db_session.flush()

    response = _sign_in(client, flask_app, tenant, email=account.email, password=password)

    assert response.status_code in (401, 403)


def test_a_soft_deleted_parent_cannot_sign_in(client, db_session, flask_app):
    from core.school_time import utc_now

    tenant = _school(db_session)
    parent, account, password, students = _parent_with_login(db_session, tenant)
    account.deleted_at = utc_now()
    db_session.flush()

    response = _sign_in(client, flask_app, tenant, email=account.email, password=password)

    assert response.status_code in (401, 403)


def test_a_parent_cannot_sign_in_once_the_school_shares_one_login_again(
    client, db_session, flask_app
):
    """PARENT-9 from the other side: the account survives, the parent
    experience does not. With no other subject kind they hold no method."""
    tenant = _school(db_session)
    parent, account, password, students = _parent_with_login(db_session, tenant)

    policy = TenantAuthPolicy.query.filter_by(tenant_id=tenant.id).first()
    policy.family_access_mode = FAMILY_ACCESS_SHARED
    db_session.flush()

    response = _sign_in(client, flask_app, tenant, email=account.email, password=password)

    assert response.status_code == 401
    assert response.get_json()["error"] == "InvalidCredentials"
    # The account is still there, untouched.
    assert User.query.filter_by(id=account.id).first().deleted_at is None


def test_a_parent_at_one_school_cannot_sign_into_another(client, db_session, flask_app):
    """PARENT-5. The same address at two schools is two people."""
    ours = _school(db_session)
    theirs = _school(db_session)
    address = f"{uuid.uuid4().hex[:8]}@example.test"
    parent, account, password, students = _parent_with_login(
        db_session, theirs, email=address
    )

    response = _sign_in(client, flask_app, ours, email=address, password=password)

    assert response.status_code in (401, 403)


def test_the_same_address_may_exist_at_two_schools_independently(
    client, db_session, flask_app
):
    ours = _school(db_session)
    theirs = _school(db_session)
    address = f"{uuid.uuid4().hex[:8]}@example.test"
    _, our_account, our_password, _ = _parent_with_login(
        db_session, ours, email=address
    )
    _, their_account, their_password, _ = _parent_with_login(
        db_session, theirs, email=address
    )

    assert our_account.id != their_account.id
    ours_in = _sign_in(client, flask_app, ours, email=address, password=our_password)
    assert ours_in.status_code == 200
    assert ours_in.get_json()["data"]["user"]["id"] == our_account.id


def test_a_teacher_who_is_also_a_parent_signs_in_once_as_themselves(
    client, db_session, flask_app
):
    """PARENT-11. One human, one account, both subject kinds."""
    from modules.people.models import FAMILY_ROLE_MOTHER, Family, FamilyMember

    tenant = _school(db_session)
    teacher = make_user(db_session, tenant, password="Password123")
    grant_permissions(db_session, tenant, teacher, ("student.read.all",))
    student, child_person = _child(db_session, tenant)

    household = Family(id=new_id("f-"), tenant_id=tenant.id)
    db_session.add(household)
    db_session.flush()
    for person_id, role in ((child_person.id, "child"), (teacher.person_id, FAMILY_ROLE_MOTHER)):
        db_session.add(
            FamilyMember(
                id=new_id("fm-"),
                tenant_id=tenant.id,
                family_id=household.id,
                person_id=person_id,
                relationship=role,
            )
        )
    db_session.flush()

    response = _sign_in(
        client, flask_app, tenant, email=teacher.email, password="Password123"
    )

    assert response.status_code == 200
    assert User.query.filter_by(tenant_id=tenant.id, person_id=teacher.person_id).count() == 1


# ---------------------------------------------------------------------------
# Whose children
# ---------------------------------------------------------------------------

def test_a_signed_in_parent_can_list_their_own_children(client, db_session, flask_app):
    tenant = _school(db_session)
    parent, account, password, students = _parent_with_login(
        db_session, tenant, children=2
    )
    headers = {
        "Authorization": f"Bearer {generate_access_token(account)}",
        "X-Tenant-ID": tenant.id,
    }

    response = client.get("/api/auth/parents/me/children", headers=headers)

    assert response.status_code == 200
    listed = {c["id"] for c in response.get_json()["data"]["children"]}
    assert listed == {s.id for s in students}


def test_the_listing_never_contains_another_family_s_child(
    client, db_session, flask_app
):
    tenant = _school(db_session)
    parent, account, password, mine = _parent_with_login(db_session, tenant)
    stranger, _ = _child(db_session, tenant, name="Somebody Else's")
    headers = {
        "Authorization": f"Bearer {generate_access_token(account)}",
        "X-Tenant-ID": tenant.id,
    }

    listed = client.get(
        "/api/auth/parents/me/children", headers=headers
    ).get_json()["data"]["children"]

    assert {c["id"] for c in listed} == {mine[0].id}
    assert stranger.id not in repr(listed)


def test_somebody_who_is_not_a_parent_gets_an_empty_list_not_an_error(
    client, db_session, flask_app
):
    """Distinguishing them would say who is a parent at this school."""
    tenant = _school(db_session)
    teacher = make_user(db_session, tenant, password="Password123")
    grant_permissions(db_session, tenant, teacher, ("student.read.all",))
    headers = {
        "Authorization": f"Bearer {generate_access_token(teacher)}",
        "X-Tenant-ID": tenant.id,
    }

    response = client.get("/api/auth/parents/me/children", headers=headers)

    assert response.status_code == 200
    assert response.get_json()["data"]["children"] == []


# ---------------------------------------------------------------------------
# Provisioning over HTTP
# ---------------------------------------------------------------------------

def _operator(db_session, tenant):
    user = make_user(db_session, tenant, password="Operator123")
    grant_permissions(db_session, tenant, user, ("user.manage",))
    return {
        "Authorization": f"Bearer {generate_access_token(user)}",
        "X-Tenant-ID": tenant.id,
    }


def test_an_operator_provisions_a_parent_login_and_sees_the_password_once(
    client, db_session, flask_app
):
    tenant = _school(db_session)
    student, child_person = _child(db_session, tenant)
    record_family_member(
        tenant.id, child_person.id, name="A Father", relationship="father",
        phone="9876544444",
    )
    db_session.flush()
    parent = Person.query.filter_by(tenant_id=tenant.id, full_name="A Father").first()
    headers = _operator(db_session, tenant)

    response = client.post(
        f"/api/auth/parents/{parent.id}/login",
        headers=headers,
        json={"email": "father@example.test"},
    )

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["created_account"] is True
    assert data["password"]
    assert data["email"] == "father@example.test"


def test_a_school_administrator_without_user_manage_cannot_provision(
    client, db_session, flask_app
):
    tenant = _school(db_session)
    student, child_person = _child(db_session, tenant)
    record_family_member(
        tenant.id, child_person.id, name="A Father", relationship="father",
        phone="9876555555",
    )
    db_session.flush()
    parent = Person.query.filter_by(tenant_id=tenant.id, full_name="A Father").first()
    reader = make_user(db_session, tenant, password="Reader123")
    grant_permissions(db_session, tenant, reader, ("student.read.all",))
    headers = {
        "Authorization": f"Bearer {generate_access_token(reader)}",
        "X-Tenant-ID": tenant.id,
    }

    response = client.post(
        f"/api/auth/parents/{parent.id}/login",
        headers=headers,
        json={"email": "father@example.test"},
    )

    assert response.status_code == 403


def test_another_school_cannot_provision_this_parent(client, db_session, flask_app):
    """NFR-5."""
    ours = _school(db_session)
    theirs = _school(db_session)
    student, child_person = _child(db_session, theirs)
    record_family_member(
        theirs.id, child_person.id, name="Their Father", relationship="father",
        phone="9876566666",
    )
    db_session.flush()
    parent = Person.query.filter_by(tenant_id=theirs.id, full_name="Their Father").first()
    headers = _operator(db_session, ours)

    response = client.post(
        f"/api/auth/parents/{parent.id}/login",
        headers=headers,
        json={"email": "theirfather@example.test"},
    )

    assert response.status_code == 404
    assert User.query.filter_by(tenant_id=theirs.id, person_id=parent.id).count() == 0


def test_provisioning_without_an_email_is_refused_over_http(
    client, db_session, flask_app
):
    tenant = _school(db_session)
    student, child_person = _child(db_session, tenant)
    record_family_member(
        tenant.id, child_person.id, name="A Father", relationship="father",
        phone="9876577777",
    )
    db_session.flush()
    parent = Person.query.filter_by(tenant_id=tenant.id, full_name="A Father").first()
    headers = _operator(db_session, tenant)

    response = client.post(
        f"/api/auth/parents/{parent.id}/login", headers=headers, json={}
    )

    assert response.status_code == 422
    assert response.get_json()["error"] == "ParentLoginNotProvisioned"


def test_provisioning_never_logs_the_password(client, db_session, flask_app, caplog):
    tenant = _school(db_session)
    student, child_person = _child(db_session, tenant)
    record_family_member(
        tenant.id, child_person.id, name="A Father", relationship="father",
        phone="9876588888",
    )
    db_session.flush()
    parent = Person.query.filter_by(tenant_id=tenant.id, full_name="A Father").first()
    headers = _operator(db_session, tenant)

    with caplog.at_level("DEBUG"):
        response = client.post(
            f"/api/auth/parents/{parent.id}/login",
            headers=headers,
            json={"email": "quiet@example.test"},
        )

    password = response.get_json()["data"]["password"]
    assert password not in caplog.text


def test_provisioning_creates_no_sms_or_usage(client, db_session, flask_app):
    """A parent login is email and password. Nothing is sent and nothing is
    billed."""
    from modules.billing.models import ServiceUsageRecord

    tenant = _school(db_session)
    student, child_person = _child(db_session, tenant)
    record_family_member(
        tenant.id, child_person.id, name="A Father", relationship="father",
        phone="9876599999",
    )
    db_session.flush()
    parent = Person.query.filter_by(tenant_id=tenant.id, full_name="A Father").first()
    headers = _operator(db_session, tenant)

    client.post(
        f"/api/auth/parents/{parent.id}/login",
        headers=headers,
        json={"email": "nobill@example.test"},
    )
    db_session.flush()

    assert ServiceUsageRecord.query.filter_by(tenant_id=tenant.id).count() == 0
