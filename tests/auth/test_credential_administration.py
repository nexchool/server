"""Phase 1c — the office issues, resets and reports on student passwords.

Phase 1b proved a student *can* sign in with an admission number. This is the
part a school actually operates: a child forgets a password in week two and
somebody at the front desk has to fix it, for one child or for a whole class,
without a developer and without locking anybody else out.

The assertions worth reading first are the ones about restraint:

  * `test_the_plaintext_password_is_never_written_down_anywhere` — the
    generated password lives in one HTTP response and nowhere else.
  * `test_there_is_no_way_to_read_a_password_back` — no read path can produce
    one, so a leak would take a code change rather than a request.
  * `test_another_school_cannot_touch_this_school_s_student` — the operation
    is reached through a *studentship*, so a foreign id is not found.
  * `test_issuing_twice_does_not_take_away_a_working_password` — the safety
    property that makes bulk issuance runnable on a live school.
"""

from __future__ import annotations

import uuid

import pytest

from core.database import db
from modules.auth.credential_admin import (
    SKIP_ALREADY_HAD_CREDENTIAL,
    SKIP_ALREADY_HAD_IDENTIFIER,
    SKIP_NO_ACCOUNT,
    backfill_admission_identifiers,
    bulk_issue_credentials,
    credential_status,
    issue_credential,
)
from modules.auth.event_models import AuthEvent
from modules.auth.models import AccountCredential, AccountIdentifier, Session, User
from modules.auth.policy import ensure_default_policy, set_method
from modules.auth.services import generate_access_token
from modules.students.models import Student
from tests.auth._characterization import grant_permissions, make_tenant, make_user, new_id

METHOD = "admission_id_password"
PERM = "student.credential.manage"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _school(db_session, **kwargs):
    """A school that has turned admission-number sign-in on."""
    tenant = make_tenant(db_session, **kwargs)
    ensure_default_policy(tenant.id)
    set_method(tenant.id, "student", METHOD, enabled=True)
    return tenant


def _operator(db_session, tenant, *, permissions=(PERM,)):
    """Somebody at the front desk, with a token and the school's header."""
    user = make_user(db_session, tenant, password="Operator123")
    grant_permissions(db_session, tenant, user, permissions)
    token = generate_access_token(user)
    return user, {"Authorization": f"Bearer {token}", "X-Tenant-ID": tenant.id}


def _a_class_in(db_session, tenant):
    """A real class to hang students off, so bulk scoping is exercised for
    real rather than against an id that happens to match."""
    from modules.academics.academic_year.models import AcademicYear
    from modules.classes.models import Class

    year = AcademicYear(
        id=new_id("ay-"),
        tenant_id=tenant.id,
        name="2025-2026",
        start_date="2025-06-01",
        end_date="2026-03-31",
    )
    db_session.add(year)
    db_session.flush()
    klass = Class(
        id=new_id("c-"),
        tenant_id=tenant.id,
        name="Grade 1",
        section="A",
        academic_year_id=year.id,
    )
    db_session.add(klass)
    db_session.flush()
    return klass


def _enrol(db_session, tenant, *, with_account=True, class_id=None):
    """A student, with or without the account that lets them sign in.

    A child is a person whether or not the school gave them a way in — which
    is exactly the case `with_account=False` exists to cover.
    """
    from modules.people.models import Person

    if with_account:
        account = make_user(db_session, tenant, password="Child12345")
        person_id = account.person_id
    else:
        account = None
        person = Person(id=new_id("p-"), tenant_id=tenant.id, full_name="Unregistered Child")
        db_session.add(person)
        db_session.flush()
        person_id = person.id

    student = Student(
        id=new_id("s-"),
        tenant_id=tenant.id,
        user_id=account.id if account else None,
        person_id=person_id,
        admission_number=f"ADM-{uuid.uuid4().hex[:8]}",
        class_id=class_id,
    )
    db_session.add(student)
    db_session.flush()
    return student, account


# ---------------------------------------------------------------------------
# Reading: what an operator is allowed to see
# ---------------------------------------------------------------------------

def test_the_status_says_whether_a_child_can_sign_in(client, db_session):
    tenant = _school(db_session)
    _, headers = _operator(db_session, tenant)
    student, _ = _enrol(db_session, tenant)

    before = client.get(f"/api/students/{student.id}/credentials", headers=headers)
    assert before.status_code == 200
    assert before.get_json()["data"]["credential"] is None

    client.post(f"/api/students/{student.id}/credentials/issue", headers=headers)

    after = client.get(f"/api/students/{student.id}/credentials", headers=headers).get_json()
    assert after["data"]["credential"]["type"] == "password"
    assert after["data"]["admission_number"] == student.admission_number


def test_a_student_with_no_account_is_reported_not_repaired(client, db_session):
    """No email means no account (ADR-003). That is a decision, not a fault."""
    tenant = _school(db_session)
    _, headers = _operator(db_session, tenant)
    student, _ = _enrol(db_session, tenant, with_account=False)

    body = client.get(f"/api/students/{student.id}/credentials", headers=headers).get_json()
    assert body["data"]["has_account"] is False
    assert body["data"]["reason"] == SKIP_NO_ACCOUNT

    issued = client.post(f"/api/students/{student.id}/credentials/issue", headers=headers)
    assert issued.status_code == 409

    # And, crucially, no account was conjured to make the operation succeed.
    assert Student.query.filter_by(id=student.id).first().user_id is None


def test_there_is_no_way_to_read_a_password_back(client, db_session):
    """The status endpoint is the only read path, and it carries no secret."""
    tenant = _school(db_session)
    _, headers = _operator(db_session, tenant)
    student, _ = _enrol(db_session, tenant)
    client.post(f"/api/students/{student.id}/credentials/issue", headers=headers)

    body = client.get(f"/api/students/{student.id}/credentials", headers=headers).get_json()

    serialized = repr(body)
    assert "password" not in body["data"]
    assert "secret_hash" not in serialized
    assert "hash" not in serialized


# ---------------------------------------------------------------------------
# Issuing
# ---------------------------------------------------------------------------

def test_issuing_gives_a_working_password_and_an_admission_identifier(client, db_session):
    tenant = _school(db_session)
    _, headers = _operator(db_session, tenant)
    student, account = _enrol(db_session, tenant)

    response = client.post(f"/api/students/{student.id}/credentials/issue", headers=headers)

    assert response.status_code == 200
    password = response.get_json()["data"]["password"]
    assert User.query.filter_by(id=account.id).first().check_password(password)
    identifier = AccountIdentifier.query.filter_by(
        account_id=account.id, identifier_type="admission_id"
    ).first()
    # As entered for the office to recognise; folded for the lookup to match.
    assert identifier.identifier_value == student.admission_number
    assert identifier.identifier_value_normalized == student.admission_number.upper()


def test_issuing_twice_does_not_take_away_a_working_password(client, db_session):
    """The property the whole bulk operation rests on."""
    tenant = _school(db_session)
    _, headers = _operator(db_session, tenant)
    student, account = _enrol(db_session, tenant)

    first = client.post(f"/api/students/{student.id}/credentials/issue", headers=headers)
    password = first.get_json()["data"]["password"]

    second = client.post(f"/api/students/{student.id}/credentials/issue", headers=headers)

    assert second.status_code == 409
    assert second.get_json()["error"] == "CredentialNotIssued"
    assert User.query.filter_by(id=account.id).first().check_password(password)


def test_a_reset_ends_the_old_password_and_the_sessions_using_it(client, db_session):
    tenant = _school(db_session)
    _, headers = _operator(db_session, tenant)
    student, account = _enrol(db_session, tenant)

    old = client.post(
        f"/api/students/{student.id}/credentials/issue", headers=headers
    ).get_json()["data"]["password"]
    db_session.add(
        Session(
            id=new_id("sess-"),
            tenant_id=tenant.id,
            user_id=account.id,
            refresh_token=new_id("rt-"),
        )
    )
    db_session.flush()

    response = client.post(
        f"/api/students/{student.id}/credentials/issue",
        headers=headers,
        json={"reset": True},
    )

    data = response.get_json()["data"]
    assert data["status"] == "reset"
    assert data["sessions_revoked"] == 1
    account = User.query.filter_by(id=account.id).first()
    assert not account.check_password(old)
    assert account.check_password(data["password"])
    assert Session.query.filter_by(user_id=account.id, revoked=False).count() == 0


def test_forcing_a_change_does_not_lock_the_child_out_today(client, db_session):
    """A shared password should be replaced, not confiscated mid-lesson."""
    tenant = _school(db_session)
    _, headers = _operator(db_session, tenant)
    student, account = _enrol(db_session, tenant)
    password = client.post(
        f"/api/students/{student.id}/credentials/issue", headers=headers
    ).get_json()["data"]["password"]

    response = client.post(
        f"/api/students/{student.id}/credentials/force-change", headers=headers
    )

    assert response.status_code == 200
    account = User.query.filter_by(id=account.id).first()
    assert account.force_password_reset is True
    assert account.check_password(password)


# ---------------------------------------------------------------------------
# Nothing leaks
# ---------------------------------------------------------------------------

def test_the_plaintext_password_is_never_written_down_anywhere(client, db_session, caplog):
    tenant = _school(db_session)
    _, headers = _operator(db_session, tenant)
    student, account = _enrol(db_session, tenant)

    with caplog.at_level("DEBUG"):
        password = client.post(
            f"/api/students/{student.id}/credentials/issue", headers=headers
        ).get_json()["data"]["password"]

    credential = AccountCredential.query.filter_by(account_id=account.id).first()
    # Every column of the row, not just the obvious one — a plaintext that
    # survived in some incidental field would be just as leaked.
    assert password not in _row_text(credential)
    assert password not in caplog.text

    for event in AuthEvent.query.filter_by(account_id=account.id).all():
        assert password not in _row_text(event)


def _row_text(row) -> str:
    return repr({c.name: getattr(row, c.name) for c in row.__table__.columns})


def test_an_administrative_change_is_written_down(client, db_session):
    tenant = _school(db_session)
    operator, headers = _operator(db_session, tenant)
    student, account = _enrol(db_session, tenant)

    client.post(f"/api/students/{student.id}/credentials/issue", headers=headers)

    events = AuthEvent.query.filter_by(account_id=account.id).all()
    types = {event.event_type for event in events}
    assert "credential_issued" in types
    # The actor has a column of its own since migration 133; it used to be
    # encoded into the user-agent slot because there was nowhere else.
    assert any(event.actor_user_id == operator.id for event in events)


# ---------------------------------------------------------------------------
# Whose student is this?
# ---------------------------------------------------------------------------

def test_another_school_cannot_touch_this_school_s_student(client, db_session):
    """A4/A8 at the administrative surface, not just the login one."""
    ours = _school(db_session)
    theirs = _school(db_session)
    _, our_headers = _operator(db_session, ours)
    their_student, their_account = _enrol(db_session, theirs)

    status = client.get(
        f"/api/students/{their_student.id}/credentials", headers=our_headers
    )
    issue = client.post(
        f"/api/students/{their_student.id}/credentials/issue", headers=our_headers
    )

    # Not 403 — a student who is not ours is not a student we can distinguish
    # from one who does not exist.
    assert status.status_code == 404
    assert issue.status_code == 404
    assert AccountCredential.query.filter_by(account_id=their_account.id).count() == 0


def test_naming_a_foreign_class_in_bulk_reaches_nobody(client, db_session):
    ours = _school(db_session)
    theirs = _school(db_session)
    _, our_headers = _operator(db_session, ours)
    their_class = _a_class_in(db_session, theirs)
    their_student, their_account = _enrol(db_session, theirs, class_id=their_class.id)

    response = client.post(
        "/api/students/credentials/bulk-issue",
        headers=our_headers,
        json={"class_id": their_class.id},
    )

    # The class id resolves to no students of ours, so the operation succeeds
    # against an empty set rather than reporting that the class exists
    # elsewhere — which would itself be an answer about another school.
    assert response.status_code == 200
    assert response.get_json()["data"]["requested"] == 0
    assert AccountCredential.query.filter_by(account_id=their_account.id).count() == 0


def test_reading_a_student_is_not_enough_to_issue_them_a_password(client, db_session):
    tenant = _school(db_session)
    _, headers = _operator(db_session, tenant, permissions=("student.read.all",))
    student, _ = _enrol(db_session, tenant)

    assert client.get(
        f"/api/students/{student.id}/credentials", headers=headers
    ).status_code == 403
    assert client.post(
        f"/api/students/{student.id}/credentials/issue", headers=headers
    ).status_code == 403


def test_an_unauthenticated_caller_gets_nowhere(client, db_session):
    tenant = _school(db_session)
    student, _ = _enrol(db_session, tenant)

    response = client.get(
        f"/api/students/{student.id}/credentials", headers={"X-Tenant-ID": tenant.id}
    )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# A class at a time
# ---------------------------------------------------------------------------

def test_a_class_gets_its_slips_in_one_operation(client, db_session):
    tenant = _school(db_session)
    _, headers = _operator(db_session, tenant)
    class_id = _a_class_in(db_session, tenant).id
    students = [_enrol(db_session, tenant, class_id=class_id)[0] for _ in range(3)]

    response = client.post(
        "/api/students/credentials/bulk-issue", headers=headers, json={"class_id": class_id}
    )

    data = response.get_json()["data"]
    assert data["requested"] == 3
    assert data["issued"] == 3
    assert {row["student_id"] for row in data["credentials"]} == {s.id for s in students}
    assert all(row["password"] for row in data["credentials"])


def test_running_bulk_issuance_twice_is_safe(client, db_session):
    """The scenario that would otherwise invalidate a term of credentials."""
    tenant = _school(db_session)
    _, headers = _operator(db_session, tenant)
    class_id = _a_class_in(db_session, tenant).id
    for _ in range(2):
        _enrol(db_session, tenant, class_id=class_id)

    first = client.post(
        "/api/students/credentials/bulk-issue", headers=headers, json={"class_id": class_id}
    ).get_json()["data"]
    passwords = {row["student_id"]: row["password"] for row in first["credentials"]}

    second = client.post(
        "/api/students/credentials/bulk-issue", headers=headers, json={"class_id": class_id}
    ).get_json()["data"]

    assert second["issued"] == 0
    assert second["skipped"] == 2
    assert second["counts_by_skip_reason"] == {SKIP_ALREADY_HAD_CREDENTIAL: 2}
    for student_id, password in passwords.items():
        account = Student.query.filter_by(id=student_id).first().user
        assert account.check_password(password)


def test_a_bulk_request_that_names_nobody_is_refused(client, db_session):
    tenant = _school(db_session)
    _, headers = _operator(db_session, tenant)

    response = client.post(
        "/api/students/credentials/bulk-issue", headers=headers, json={}
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "ValidationError"


def test_one_student_without_an_account_does_not_stop_the_class(client, db_session):
    tenant = _school(db_session)
    _, headers = _operator(db_session, tenant)
    class_id = _a_class_in(db_session, tenant).id
    _enrol(db_session, tenant, class_id=class_id)
    _enrol(db_session, tenant, class_id=class_id, with_account=False)

    data = client.post(
        "/api/students/credentials/bulk-issue", headers=headers, json={"class_id": class_id}
    ).get_json()["data"]

    assert data["issued"] == 1
    assert data["counts_by_skip_reason"] == {SKIP_NO_ACCOUNT: 1}


# ---------------------------------------------------------------------------
# Students who were already here
# ---------------------------------------------------------------------------

def test_backfilling_lets_an_existing_student_be_found_by_their_number(client, db_session):
    tenant = _school(db_session)
    _, headers = _operator(db_session, tenant)
    student, account = _enrol(db_session, tenant)

    response = client.post(
        "/api/students/credentials/backfill-admission-ids",
        headers=headers,
        json={"student_ids": [student.id]},
    )

    assert response.get_json()["data"]["issued"] == 1
    assert AccountIdentifier.query.filter_by(
        account_id=account.id, identifier_type="admission_id"
    ).count() == 1


def test_backfilling_never_touches_a_password(client, db_session):
    tenant = _school(db_session)
    _, headers = _operator(db_session, tenant)
    student, account = _enrol(db_session, tenant)
    password = client.post(
        f"/api/students/{student.id}/credentials/issue", headers=headers
    ).get_json()["data"]["password"]
    forced_before = User.query.filter_by(id=account.id).first().force_password_reset

    client.post(
        "/api/students/credentials/backfill-admission-ids",
        headers=headers,
        json={"student_ids": [student.id]},
    )

    account = User.query.filter_by(id=account.id).first()
    assert account.check_password(password)
    assert account.force_password_reset == forced_before


def test_backfilling_twice_produces_one_identifier(client, db_session):
    tenant = _school(db_session)
    _, headers = _operator(db_session, tenant)
    student, account = _enrol(db_session, tenant)
    body = {"student_ids": [student.id]}

    client.post("/api/students/credentials/backfill-admission-ids", headers=headers, json=body)
    second = client.post(
        "/api/students/credentials/backfill-admission-ids", headers=headers, json=body
    ).get_json()["data"]

    assert second["issued"] == 0
    assert second["counts_by_skip_reason"] == {SKIP_ALREADY_HAD_IDENTIFIER: 1}
    assert AccountIdentifier.query.filter_by(
        account_id=account.id, identifier_type="admission_id"
    ).count() == 1


# ---------------------------------------------------------------------------
# The lifecycle, end to end, through the real pipeline
# ---------------------------------------------------------------------------

def _fresh_request(flask_app):
    """Forget the school the previous request resolved.

    A harness artefact, not product behaviour: Flask reuses the app context a
    test pushed, so `g` survives between test-client calls in a way it never
    does in production. Only tests that sign in twice need to care. Documented
    at length in `test_admission_id_login.py`.
    """
    from flask import g as flask_g

    for attribute in ("tenant_id", "tenant", "current_user"):
        if hasattr(flask_g, attribute):
            delattr(flask_g, attribute)


def _sign_in(client, flask_app, tenant, *, identifier, password):
    _fresh_request(flask_app)
    return client.post(
        "/api/auth/login",
        json={
            "method": METHOD,
            "identifier": identifier,
            "password": password,
            "tenant_id": tenant.id,
        },
    )


def test_a_reset_password_carries_the_child_all_the_way_to_a_new_one(
    client, db_session, flask_app
):
    """Reset → sign in → set your own → the old one is dead.

    Driven through the real login pipeline and the real password routes, with
    nothing mocked, because the value of this test is that the pieces from
    four phases still fit together.

    One honest note about the third step: today's login does **not** refuse a
    sign-in when `force_password_reset` is set. It succeeds and reports the
    flag, and admin-web is what stops the user. That is a standing gap
    recorded in earlier phases; asserted here as it actually behaves rather
    than as it ought to, because changing login is not this phase's work.
    """
    tenant = _school(db_session)
    _, headers = _operator(db_session, tenant)
    student, account = _enrol(db_session, tenant)
    grant_permissions(db_session, tenant, account, ("student.read.self",))

    provisional = client.post(
        f"/api/students/{student.id}/credentials/issue", headers=headers
    ).get_json()["data"]["password"]

    signed_in = _sign_in(
        client,
        flask_app,
        tenant,
        identifier=student.admission_number,
        password=provisional,
    )
    assert signed_in.status_code == 200
    body = signed_in.get_json()["data"]
    assert body["force_password_reset"] is True

    as_student = {
        "Authorization": f"Bearer {body['access_token']}",
        "X-Tenant-ID": tenant.id,
    }
    _fresh_request(flask_app)
    changed = client.post(
        "/api/auth/password/force-reset",
        headers=as_student,
        json={"new_password": "MyOwnWord99"},
    )
    assert changed.status_code == 200

    account = User.query.filter_by(id=account.id).first()
    assert account.check_password("MyOwnWord99")
    assert not account.check_password(provisional)
    assert account.force_password_reset is False

    # The two records of the same secret stayed in step, which is what the
    # `person_link` synchronisation exists for.
    credential = AccountCredential.query.filter_by(account_id=account.id).first()
    assert credential.secret_hash == account.password_hash
    assert credential.must_change is False


def test_resetting_one_child_does_not_touch_another(client, db_session):
    """The scope of a reset is one student, never a class and never a school."""
    tenant = _school(db_session)
    _, headers = _operator(db_session, tenant)
    mine, my_account = _enrol(db_session, tenant)
    theirs, their_account = _enrol(db_session, tenant)

    their_password = client.post(
        f"/api/students/{theirs.id}/credentials/issue", headers=headers
    ).get_json()["data"]["password"]
    their_session = Session(
        id=new_id("sess-"),
        tenant_id=tenant.id,
        user_id=their_account.id,
        refresh_token=new_id("rt-"),
    )
    db_session.add(their_session)
    db_session.flush()

    client.post(f"/api/students/{mine.id}/credentials/issue", headers=headers)
    client.post(
        f"/api/students/{mine.id}/credentials/issue",
        headers=headers,
        json={"reset": True},
    )

    assert User.query.filter_by(id=their_account.id).first().check_password(
        their_password
    )
    assert Session.query.filter_by(id=their_session.id).first().revoked is False


def test_a_reset_replaces_the_password_and_leaves_the_identifiers_alone(
    client, db_session
):
    """Both ways in survive. A reset is about the secret, not the names."""
    tenant = _school(db_session)
    _, headers = _operator(db_session, tenant)
    student, account = _enrol(db_session, tenant)
    client.post(f"/api/students/{student.id}/credentials/issue", headers=headers)
    before = {
        (row.identifier_type, row.identifier_value)
        for row in AccountIdentifier.query.filter_by(account_id=account.id).all()
    }

    client.post(
        f"/api/students/{student.id}/credentials/issue",
        headers=headers,
        json={"reset": True},
    )

    after = {
        (row.identifier_type, row.identifier_value)
        for row in AccountIdentifier.query.filter(
            AccountIdentifier.account_id == account.id,
            AccountIdentifier.deleted_at.is_(None),
        ).all()
    }
    assert after == before
    assert any(kind == "email" for kind, _ in after)
    # One credential row, rotated — not a second one shadowing the first.
    assert AccountCredential.query.filter_by(account_id=account.id).count() == 1


def test_forcing_a_change_does_not_quietly_issue_a_password(client, db_session):
    tenant = _school(db_session)
    _, headers = _operator(db_session, tenant)
    student, account = _enrol(db_session, tenant)
    password = client.post(
        f"/api/students/{student.id}/credentials/issue", headers=headers
    ).get_json()["data"]["password"]

    response = client.post(
        f"/api/students/{student.id}/credentials/force-change", headers=headers
    )

    assert "password" not in response.get_json()["data"]
    account = User.query.filter_by(id=account.id).first()
    assert account.check_password(password)
    # The legacy flag and the credential row say the same thing.
    credential = AccountCredential.query.filter_by(account_id=account.id).first()
    assert account.force_password_reset is True
    assert credential.must_change is True


# ---------------------------------------------------------------------------
# What the school's policy permits
# ---------------------------------------------------------------------------

def test_a_school_that_has_not_enabled_admission_sign_in_gets_no_identifier(
    client, db_session
):
    tenant = make_tenant(db_session)
    ensure_default_policy(tenant.id)  # admission_id_password left off
    _, headers = _operator(db_session, tenant)
    student, account = _enrol(db_session, tenant)

    issued = client.post(
        f"/api/students/{student.id}/credentials/issue", headers=headers
    ).get_json()["data"]

    # The password is still the school's to hand out — it is the *method* that
    # is off, not the credential.
    assert issued["password"]
    assert issued["admission_identifier_issued"] is False
    assert AccountIdentifier.query.filter_by(
        account_id=account.id, identifier_type="admission_id"
    ).count() == 0


def test_backfilling_where_the_method_is_off_issues_nothing_and_says_so(
    client, db_session
):
    tenant = make_tenant(db_session)
    ensure_default_policy(tenant.id)
    _, headers = _operator(db_session, tenant)
    student, _ = _enrol(db_session, tenant)

    data = client.post(
        "/api/students/credentials/backfill-admission-ids",
        headers=headers,
        json={"student_ids": [student.id]},
    ).get_json()["data"]

    assert data["issued"] == 0
    assert data["counts_by_skip_reason"] == {"method_not_enabled": 1}


def test_turning_the_method_off_and_on_again_keeps_the_way_in(client, db_session):
    """Disabling a method must not destroy what a school already handed out."""
    tenant = _school(db_session)
    _, headers = _operator(db_session, tenant)
    student, account = _enrol(db_session, tenant)
    client.post(f"/api/students/{student.id}/credentials/issue", headers=headers)

    set_method(tenant.id, "student", METHOD, enabled=False)
    db_session.flush()
    surviving = AccountIdentifier.query.filter(
        AccountIdentifier.account_id == account.id,
        AccountIdentifier.identifier_type == "admission_id",
        AccountIdentifier.deleted_at.is_(None),
    ).count()

    set_method(tenant.id, "student", METHOD, enabled=True)
    db_session.flush()

    assert surviving == 1
    assert AccountCredential.query.filter_by(account_id=account.id).count() == 1
    # Re-enabling needs no reissue: the identifier was never taken away.
    assert AccountIdentifier.query.filter(
        AccountIdentifier.account_id == account.id,
        AccountIdentifier.identifier_type == "admission_id",
        AccountIdentifier.deleted_at.is_(None),
    ).count() == 1


# ---------------------------------------------------------------------------
# When one student in a batch cannot be served
# ---------------------------------------------------------------------------

def test_one_student_failing_does_not_cost_the_others_their_slips(db_session):
    """Driven at the service, because the failure has to be made to happen."""
    tenant = _school(db_session)
    first, _ = _enrol(db_session, tenant)
    broken, _ = _enrol(db_session, tenant)
    last, _ = _enrol(db_session, tenant)

    class Exploding:
        """A student whose account cannot be read. Stands in for any row-level
        failure — a constraint, a stale relationship — without pretending to
        predict which one a real school will hit."""

        id = broken.id
        admission_number = broken.admission_number
        user_id = broken.user_id

        @property
        def user(self):
            raise RuntimeError("this student's account could not be loaded")

    result = bulk_issue_credentials([first, Exploding(), last])

    assert result["issued"] == 2
    assert result["failed"] == 1
    assert result["processed"] == 3
    assert result["failed_students"][0]["student_id"] == broken.id
    assert {row["student_id"] for row in result["credentials"]} == {first.id, last.id}


def test_a_backfill_is_written_down_as_a_backfill(client, db_session):
    """Distinguishable from the identifier a new account gets on day one."""
    tenant = _school(db_session)
    _, headers = _operator(db_session, tenant)
    student, account = _enrol(db_session, tenant)

    client.post(
        "/api/students/credentials/backfill-admission-ids",
        headers=headers,
        json={"student_ids": [student.id]},
    )

    events = AuthEvent.query.filter_by(account_id=account.id).all()
    assert {event.event_type for event in events} == {"admission_identifier_backfilled"}
    # The number itself is hashed like every other identifier in this table.
    assert student.admission_number not in repr(
        [_row_text(event) for event in events]
    )
