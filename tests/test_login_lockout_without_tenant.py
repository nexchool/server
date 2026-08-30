"""A failed password guess counts, whether or not the caller named a school.

Login has two paths. When the body carries `tenant_id`/`subdomain` it
authenticates inside that school and, on failure, increments
`failed_login_count` and locks the account past `max_login_attempts`.

When the body names no school it searches across tenants — and returned 401
without counting anything. The branch is chosen by the **body alone**
(`routes.py`: `if tenant_id_in_body or subdomain_in_body`), so an attacker
simply omits one field and guesses forever. The only remaining limit was
Flask-Limiter's 5/min *per IP*, which a rotating-IP attacker ignores.
"""

from __future__ import annotations

import uuid

import pytest

PASSWORD = "C0rrect!Horse"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def person(db_session, tenant):
    """Somebody with a real password, in a real school."""
    from modules.auth.models import User

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}", tenant_id=tenant.id,
        email=f"{suffix}@test.school", name="Target",
    )
    user.set_password(PASSWORD)
    db_session.add(user)
    db_session.flush()
    return user


def _guess(client, email, *, subdomain=None):
    """A wrong password. With `subdomain=None` the body names no school."""
    body = {"email": email, "password": "wrong-guess"}
    if subdomain:
        body["subdomain"] = subdomain
    return client.post("/api/auth/login", json=body)


def test_a_guess_that_names_no_school_still_counts(client, db_session, person):
    before = person.failed_login_count or 0

    response = _guess(client, person.email)

    assert response.status_code == 401
    db_session.refresh(person)
    assert (person.failed_login_count or 0) == before + 1, (
        "omitting the school must not buy unlimited guesses"
    )


def test_repeated_tenantless_guesses_lock_the_account(
    client, db_session, person, tenant
):
    for _ in range(5):
        _guess(client, person.email)

    db_session.refresh(person)
    assert person.login_locked_until is not None, "the account should be locked"

    # And the lock is honoured on the path that named the school all along.
    response = _guess(client, person.email, subdomain=tenant.subdomain)
    assert response.status_code == 429


def test_naming_the_school_still_counts(client, db_session, person, tenant):
    """Regression guard: the path that already worked keeps working."""
    before = person.failed_login_count or 0

    _guess(client, person.email, subdomain=tenant.subdomain)

    db_session.refresh(person)
    assert (person.failed_login_count or 0) == before + 1


def test_an_unknown_email_is_still_refused_cleanly(client):
    """No account to count against — must not error, must not leak existence."""
    response = _guess(client, f"nobody-{uuid.uuid4().hex[:8]}@example.test")

    assert response.status_code == 401
