"""Phase −1 — failure, lockout, the two login branches, and enumeration.

CHARACTERIZATION. Login has two branches, chosen by the request body alone:

    routes.py::login
        if tenant_id_in_body or subdomain_in_body:   -> BRANCH A (named school)
        else:                                        -> BRANCH B (search all)

Branch B exists because one mobile app serves every school. The two branches
have diverged before — the tenant-less one once returned 401 without counting
the attempt, which bought unlimited guesses to anyone who simply omitted a
field. `record_failed_login` was made the single owner of that rule as a
result. These tests pin both branches so they cannot drift apart again during
the Phase 0d refactor.

Where the branches still behave differently today, the difference is asserted
and labelled EXISTING BEHAVIOUR. Nothing here is fixed.
"""

from __future__ import annotations

import uuid

import pytest

from tests.auth._characterization import (
    login,
    make_account,
    make_tenant,
    make_user,
    sessions_for,
)

PASSWORD = "C0rrectHorse1"
WRONG = "definitely-not-it"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def account(db_session, tenant):
    return make_account(db_session, tenant, password=PASSWORD)


def _attempts_allowed():
    """The configured threshold, never a hard-coded 5."""
    from modules.auth.services import max_login_attempts

    return max_login_attempts()


# ---------------------------------------------------------------------------
# Group 4 — a wrong password
# ---------------------------------------------------------------------------

def test_a_wrong_password_is_401_invalid_credentials(client, tenant, account):
    response = login(
        client, email=account.email, password=WRONG, tenant_id=tenant.id
    )

    assert response.status_code == 401
    body = response.get_json()
    assert body["success"] is False
    assert body["error"] == "InvalidCredentials"
    assert body["message"] == "Invalid email or password"


def test_a_failed_login_issues_no_tokens(client, tenant, account):
    body = login(
        client, email=account.email, password=WRONG, tenant_id=tenant.id
    ).get_json()

    assert "data" not in body or not (body.get("data") or {}).get("access_token")


def test_a_failed_login_creates_no_session(client, db_session, tenant, account):
    login(client, email=account.email, password=WRONG, tenant_id=tenant.id)

    assert sessions_for(account.id) == []


def test_a_failed_login_leaves_the_account_otherwise_untouched(
    client, db_session, tenant, account
):
    login(client, email=account.email, password=WRONG, tenant_id=tenant.id)

    db_session.refresh(account)
    assert account.last_login_at is None
    assert account.is_suspended is False
    assert account.deleted_at is None


def test_a_failed_login_sets_no_auth_cookie(client, tenant, account):
    from tests.auth._characterization import auth_cookie

    response = login(
        client, email=account.email, password=WRONG, tenant_id=tenant.id
    )

    assert auth_cookie(response) is None


def test_a_login_with_no_password_is_a_400_not_a_401(client, tenant, account):
    response = client.post(
        "/api/auth/login", json={"email": account.email, "tenant_id": tenant.id}
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "ValidationError"


# ---------------------------------------------------------------------------
# Group 5 — lockout
# ---------------------------------------------------------------------------

def test_each_wrong_password_increments_the_counter(
    client, db_session, tenant, account
):
    for expected in (1, 2):
        login(client, email=account.email, password=WRONG, tenant_id=tenant.id)
        db_session.refresh(account)
        assert account.failed_login_count == expected


def test_the_account_locks_at_the_configured_threshold(
    client, db_session, tenant, account
):
    limit = _attempts_allowed()

    for _ in range(limit - 1):
        login(client, email=account.email, password=WRONG, tenant_id=tenant.id)
    db_session.refresh(account)
    assert account.login_locked_until is None, "not locked before the threshold"

    login(client, email=account.email, password=WRONG, tenant_id=tenant.id)
    db_session.refresh(account)
    assert account.login_locked_until is not None


def test_locking_resets_the_counter_to_zero(client, db_session, tenant, account):
    """EXISTING BEHAVIOUR: the counter is a countdown to the *next* lock, not a
    running total — `record_failed_login` zeroes it when it locks."""
    for _ in range(_attempts_allowed()):
        login(client, email=account.email, password=WRONG, tenant_id=tenant.id)

    db_session.refresh(account)
    assert account.failed_login_count == 0


def test_the_lock_lasts_the_configured_window(client, db_session, tenant, account):
    from core.school_time import utc_now
    from modules.auth.services import LOGIN_LOCKOUT_MINUTES

    for _ in range(_attempts_allowed()):
        login(client, email=account.email, password=WRONG, tenant_id=tenant.id)

    db_session.refresh(account)
    minutes = (account.login_locked_until - utc_now()).total_seconds() / 60
    assert minutes == pytest.approx(LOGIN_LOCKOUT_MINUTES, abs=1)


def test_a_locked_account_is_refused_even_with_the_right_password(
    client, db_session, tenant, account
):
    for _ in range(_attempts_allowed()):
        login(client, email=account.email, password=WRONG, tenant_id=tenant.id)

    response = login(
        client, email=account.email, password=PASSWORD, tenant_id=tenant.id
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "InvalidCredentials"
    assert sessions_for(account.id) == []


def test_the_right_password_works_again_once_the_lock_expires(
    client, db_session, tenant, account
):
    from datetime import timedelta

    from core.school_time import utc_now

    for _ in range(_attempts_allowed()):
        login(client, email=account.email, password=WRONG, tenant_id=tenant.id)
    db_session.refresh(account)
    assert account.login_locked_until is not None

    # Wind the clock forward rather than sleeping.
    account.login_locked_until = utc_now() - timedelta(minutes=1)
    db_session.flush()

    response = login(
        client, email=account.email, password=PASSWORD, tenant_id=tenant.id
    )

    assert response.status_code == 200, response.get_json()
    db_session.refresh(account)
    assert account.login_locked_until is None


# ---------------------------------------------------------------------------
# Group 6 — both branches count a failure
# ---------------------------------------------------------------------------

def test_branch_a_naming_the_school_counts_the_failure(
    client, db_session, tenant, account
):
    login(client, email=account.email, password=WRONG, subdomain=tenant.subdomain)

    db_session.refresh(account)
    assert account.failed_login_count == 1


def test_branch_b_naming_no_school_also_counts_the_failure(
    client, db_session, tenant, account
):
    """The regression this rule was written for: omitting the school must not
    buy unlimited guesses."""
    login(client, email=account.email, password=WRONG)

    db_session.refresh(account)
    assert account.failed_login_count == 1


def test_branch_b_counts_against_every_school_holding_that_email(
    client, db_session, tenant, account
):
    """EXISTING BEHAVIOUR: with no school named there is no way to know which
    account was meant, so every account with that address is counted against —
    which also means one attacker can lock the same person out of two
    schools at once."""
    other_tenant = make_tenant(db_session, subdomain_prefix="chz-other")
    twin = make_account(
        db_session, other_tenant, password="Someth1ngElse", email=account.email
    )

    login(client, email=account.email, password=WRONG)

    db_session.refresh(account)
    db_session.refresh(twin)
    assert account.failed_login_count == 1
    assert twin.failed_login_count == 1


def test_both_branches_reach_the_same_lock(client, db_session, tenant, account):
    """Half the guesses through each branch still locks the account, which is
    the invariant that matters: the branches share one counter."""
    limit = _attempts_allowed()
    for index in range(limit):
        if index % 2:
            login(client, email=account.email, password=WRONG, tenant_id=tenant.id)
        else:
            login(client, email=account.email, password=WRONG)

    db_session.refresh(account)
    assert account.login_locked_until is not None


def test_both_branches_now_report_a_locked_account_the_same_way(
    client, db_session, tenant, account
):
    """The one behaviour Phase 0d deliberately changed, and why.

    Before the pipeline the two branches disagreed. Branch A checked the lock
    before verifying, so a locked account got 429 whatever it sent. Branch B
    reached its lock check only *after* a successful match, so a locked account
    sending a WRONG password fell into the no-match path, got 401, and was
    counted against again while already locked.

    That difference existed only because each branch carried its own copy of
    the gates. Centralising them is the phase, so the difference could not
    survive it — and the direction is the safe one: an already-locked account
    now stops accruing failures, and the response no longer depends on which
    fields the caller happened to send. It reveals nothing branch A did not
    already reveal.
    """
    for _ in range(_attempts_allowed()):
        login(client, email=account.email, password=WRONG, tenant_id=tenant.id)
    db_session.refresh(account)
    assert account.login_locked_until is not None
    locked_count = account.failed_login_count

    named = login(
        client, email=account.email, password=WRONG, tenant_id=tenant.id
    )
    unnamed = login(client, email=account.email, password=WRONG)

    # Both 401 since Phase 8: a distinct 429 told an unauthenticated caller
    # not only that the account exists but that it is currently under attack.
    # The lock still holds; it is simply not announced.
    assert named.status_code == 401
    assert unnamed.status_code == 401

    # And neither attempt counted against an account that is already locked.
    db_session.refresh(account)
    assert account.failed_login_count == locked_count


def test_branch_b_honours_the_lock_when_the_password_is_right(
    client, db_session, tenant, account
):
    for _ in range(_attempts_allowed()):
        login(client, email=account.email, password=WRONG, tenant_id=tenant.id)

    response = login(client, email=account.email, password=PASSWORD)

    assert response.status_code == 401
    assert response.get_json()["error"] == "InvalidCredentials"


def test_a_platform_admin_is_never_locked_out(client, db_session, tenant):
    """A super-admin authenticates against every school, so letting one
    school's attacker lock them would lock them out of all of them."""
    from tests.auth._characterization import make_platform_admin

    home = make_tenant(db_session, subdomain_prefix="chz-hq")
    admin = make_platform_admin(db_session, home, password=PASSWORD)

    for _ in range(_attempts_allowed() + 2):
        login(client, email=admin.email, password=WRONG, tenant_id=tenant.id)

    db_session.refresh(admin)
    assert admin.failed_login_count == 0
    assert admin.login_locked_until is None

    response = login(
        client, email=admin.email, password=PASSWORD, tenant_id=tenant.id
    )
    assert response.status_code == 200, response.get_json()


# ---------------------------------------------------------------------------
# Group 7 — enumeration
# ---------------------------------------------------------------------------

def _unknown_email():
    return f"nobody-{uuid.uuid4().hex[:10]}@example.test"


def test_an_unknown_email_and_a_wrong_password_are_indistinguishable(
    client, tenant, account
):
    """The property that keeps login from being a directory of the school."""
    unknown = login(
        client, email=_unknown_email(), password=WRONG, tenant_id=tenant.id
    )
    wrong = login(
        client, email=account.email, password=WRONG, tenant_id=tenant.id
    )

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.get_json() == wrong.get_json()


def test_the_same_holds_on_the_branch_that_names_no_school(client, account):
    unknown = login(client, email=_unknown_email(), password=WRONG)
    wrong = login(client, email=account.email, password=WRONG)

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.get_json() == wrong.get_json()


def test_an_unknown_email_does_not_error(client, tenant):
    """Nothing to count against must not become a 500."""
    response = login(
        client, email=_unknown_email(), password=WRONG, tenant_id=tenant.id
    )

    assert response.status_code == 401


def test_a_correct_password_for_the_wrong_school_looks_like_a_wrong_password(
    client, db_session, tenant, account
):
    """EXISTING BEHAVIOUR, and a good one: naming another school does not
    reveal that the account exists elsewhere."""
    other_tenant = make_tenant(db_session, subdomain_prefix="chz-elsewhere")

    response = login(
        client, email=account.email, password=PASSWORD, tenant_id=other_tenant.id
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "InvalidCredentials"


def test_an_unverified_account_is_distinguishable_from_a_wrong_password(
    client, db_session, tenant
):
    """EXISTING BEHAVIOUR, asserted rather than endorsed.

    `EmailNotVerified` is returned only after the password has been verified,
    so it does not let an attacker who does not know the password enumerate
    accounts. It does tell somebody who *does* know it that the address is
    real, which is the intended product behaviour.
    """
    user = make_account(
        db_session, tenant, password=PASSWORD, email_verified=False
    )

    verified_failure = login(
        client, email=user.email, password=WRONG, tenant_id=tenant.id
    )
    unverified_success = login(
        client, email=user.email, password=PASSWORD, tenant_id=tenant.id
    )

    assert verified_failure.get_json()["error"] == "InvalidCredentials"
    assert unverified_success.get_json()["error"] == "EmailNotVerified"


def test_an_unknown_tenant_id_silently_falls_back_to_the_default_tenant(
    client, account
):
    """EXISTING BEHAVIOUR, and the most surprising thing in this file.

    `resolve_tenant_for_auth` calls `find_tenant(..., fall_back_to_default=True)`,
    so a `tenant_id` that resolves to nothing does NOT produce `TenantRequired`.
    It quietly resolves to `DEFAULT_TENANT_SUBDOMAIN` instead, and the account
    is then looked for in *that* school — hence a plain 401.

    Asserted rather than fixed. It matters for Phase 1: admission numbers are
    unique per tenant only, so a login that means to name a school and gets the
    default one instead would resolve the wrong school's student. The tenant
    context has to be right before an identifier is trusted.
    """
    response = login(
        client,
        email=account.email,
        password=PASSWORD,
        tenant_id=f"t-{uuid.uuid4().hex[:12]}",
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "InvalidCredentials"


def test_an_unknown_subdomain_also_falls_back_rather_than_refusing(
    client, account
):
    """Same fallback through the other body key."""
    response = login(
        client,
        email=account.email,
        password=PASSWORD,
        subdomain=f"no-such-school-{uuid.uuid4().hex[:8]}",
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "InvalidCredentials"


def test_a_suspended_tenant_refuses_everyone(client, db_session, account):
    from core.models import TENANT_STATUS_SUSPENDED

    suspended = make_tenant(db_session, subdomain_prefix="chz-susp")
    guest = make_account(db_session, suspended, password=PASSWORD)
    suspended.status = TENANT_STATUS_SUSPENDED
    db_session.flush()

    response = login(
        client, email=guest.email, password=PASSWORD, tenant_id=suspended.id
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "TenantSuspended"
