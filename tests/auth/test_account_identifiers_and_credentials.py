"""Phase 0b — an account is named by identifiers and proved by credentials.

Storage only. Nothing in this phase reads these tables: login still resolves
through `User.get_user_by_email` and still verifies against
`users.password_hash`, and the tests at the bottom of this file assert exactly
that, because the boundary is the point of the phase.

What is proved here is that the foundation is sound — the uniqueness scope,
the normalization rule, the soft-delete semantics, and a backfill that says
the same thing as the columns it was copied from and can be run twice.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from core.database import db
from core.school_time import utc_now
from modules.auth.identifiers import (
    IDENTIFIER_TYPES,
    UnknownIdentifierType,
    normalize_email,
    normalize_identifier,
)
from modules.auth.models import AccountCredential, AccountIdentifier, User
from tests.auth._characterization import make_tenant, make_user, new_id

PASSWORD = "C0rrectHorse1"


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


@pytest.fixture
def account(db_session, tenant):
    return make_user(db_session, tenant, password=PASSWORD)


def _identifier(db_session, tenant, account, *, value, type_="email", **overrides):
    row = AccountIdentifier(
        id=new_id("ai-"),
        tenant_id=tenant.id,
        account_id=account.id,
        identifier_type=type_,
        identifier_value=value,
        identifier_value_normalized=overrides.pop(
            "normalized", value.strip().lower()
        ),
        **overrides,
    )
    db_session.add(row)
    return row


def _credential(db_session, tenant, account, *, type_="password", **overrides):
    row = AccountCredential(
        id=new_id("ac-"),
        tenant_id=tenant.id,
        account_id=account.id,
        credential_type=type_,
        secret_hash=overrides.pop("secret_hash", "scrypt:32768:8:1$abc$def"),
        hash_algorithm=overrides.pop("hash_algorithm", "scrypt:32768:8:1"),
        **overrides,
    )
    db_session.add(row)
    return row


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw",
    [" Test@Example.COM ", "Test@Example.com", "TEST@EXAMPLE.COM", "test@example.com "],
)
def test_an_email_normalizes_to_one_comparison_key(raw):
    assert normalize_email(raw) == "test@example.com"


def test_normalizing_is_idempotent():
    once = normalize_email(" Ravi@School.IN ")
    assert normalize_email(once) == once


def test_the_dispatcher_routes_email(monkeypatch=None):
    assert normalize_identifier("email", " A@B.COM ") == "a@b.com"


def test_an_identifier_type_with_no_rule_yet_is_refused_not_guessed():
    """A wrong normalization is worse than a missing one: it would either
    collide two humans or split one. Each type's rule arrives with its phase —
    `email` with the identifier foundation, `admission_id` with student
    sign-in, `mobile` with OTP; `employee_code` is still waiting for its."""
    with pytest.raises(UnknownIdentifierType):
        normalize_identifier("employee_code", "anything")


def test_every_declared_type_is_accepted_by_the_check_constraint(
    db_session, tenant, account
):
    """The schema is the foundation for all four; only email is issued today."""
    assert set(IDENTIFIER_TYPES) == {
        "email",
        "admission_id",
        "mobile",
        "employee_code",
    }
    for index, identifier_type in enumerate(IDENTIFIER_TYPES):
        _identifier(
            db_session,
            tenant,
            account,
            value=f"value-{index}",
            type_=identifier_type,
        )
    db_session.flush()


def test_an_unknown_identifier_type_is_refused_by_the_database(
    db_session, tenant, account
):
    _identifier(db_session, tenant, account, value="x", type_="passport")
    with pytest.raises(IntegrityError) as refused:
        db_session.flush()
    assert "ck_account_identifiers_type" in str(refused.value)


# ---------------------------------------------------------------------------
# The identifier row
# ---------------------------------------------------------------------------

def test_an_identifier_can_be_created_and_reads_back(db_session, tenant, account):
    """Written against `admission_id` rather than `email`: the email
    identifier is maintained by the A2 hook, and a test about the *model*
    should not be competing with it for the one live email slot."""
    row = _identifier(
        db_session, tenant, account, value=" ADM/2026/001 ",
        normalized="ADM/2026/001", type_="admission_id",
        is_verified=True, verified_at=utc_now(), is_primary=True,
    )
    db_session.flush()

    stored = db_session.get(AccountIdentifier, row.id)
    assert stored.account_id == account.id
    assert stored.tenant_id == tenant.id
    # The raw value survives for display; the key is what is compared.
    assert stored.identifier_value == " ADM/2026/001 "
    assert stored.identifier_value_normalized == "ADM/2026/001"
    assert stored.is_verified is True
    assert stored.is_primary is True
    assert stored.deleted_at is None


def test_an_identifier_reaches_its_account_and_back(db_session, tenant, account):
    _identifier(db_session, tenant, account, value="ADM-1", type_="admission_id")
    db_session.flush()

    # Queried rather than read off the backref: A2 adds its row through the
    # relationship, so a collection loaded at that moment would not show a row
    # added afterwards by account_id alone.
    by_type = {
        i.identifier_type: i
        for i in AccountIdentifier.query.filter_by(account_id=account.id)
    }
    assert by_type["admission_id"].identifier_value == "ADM-1"
    # And A2's email identifier is there beside it.
    assert by_type["email"].identifier_value == account.email


def test_deleting_the_account_removes_its_identifiers(db_session, tenant, account):
    _identifier(db_session, tenant, account, value="a@x.test")
    db_session.flush()
    identifier_id = account.identifiers[0].id

    db_session.delete(account)
    db_session.flush()

    assert db_session.get(AccountIdentifier, identifier_id) is None


# ---------------------------------------------------------------------------
# Identifier uniqueness
# ---------------------------------------------------------------------------

def test_one_normalized_value_per_tenant_per_type(db_session, tenant, account):
    other = make_user(db_session, tenant, password=PASSWORD)
    _identifier(db_session, tenant, account, value="Shared@x.test")
    db_session.flush()

    _identifier(db_session, tenant, other, value="shared@x.test")
    with pytest.raises(IntegrityError) as refused:
        db_session.flush()

    assert "uq_account_identifiers_live" in str(refused.value)


def test_the_same_value_may_exist_in_another_tenant(db_session, tenant, account):
    """A household phone will legitimately appear in two schools, and an
    admission number is unique only inside one."""
    elsewhere = make_tenant(db_session, subdomain_prefix="p0b-other")
    guest = make_user(db_session, elsewhere, password=PASSWORD)

    _identifier(db_session, tenant, account, value="shared@x.test")
    _identifier(db_session, elsewhere, guest, value="shared@x.test")
    db_session.flush()

    assert (
        AccountIdentifier.query.filter_by(
            identifier_value_normalized="shared@x.test"
        ).count()
        == 2
    )


def test_the_same_value_may_be_used_by_two_different_types(
    db_session, tenant, account
):
    """The scope includes the type: `ADM2026001` as an admission number and as
    an employee code are different identifiers."""
    _identifier(db_session, tenant, account, value="ADM2026001", type_="admission_id")
    _identifier(
        db_session, tenant, account, value="ADM2026001", type_="employee_code"
    )
    db_session.flush()

    assert (
        AccountIdentifier.query.filter_by(
            account_id=account.id, identifier_value_normalized="adm2026001"
        ).count()
        == 2
    )


def test_a_retired_identifier_frees_its_value(db_session, tenant, account):
    """The reason the index is partial. `uq_users_email_tenant` is not, which
    is why a closed account's email can never be reused."""
    first = _identifier(db_session, tenant, account, value="reuse@x.test")
    db_session.flush()
    first.deleted_at = utc_now()
    db_session.flush()

    successor = make_user(db_session, tenant, password=PASSWORD)
    _identifier(db_session, tenant, successor, value="reuse@x.test")
    db_session.flush()

    assert (
        AccountIdentifier.query.filter_by(
            identifier_value_normalized="reuse@x.test", deleted_at=None
        ).count()
        == 1
    )


def test_an_account_holds_one_primary_per_type(db_session, tenant, account):
    _identifier(
        db_session, tenant, account, value="ADM-1", type_="admission_id",
        is_primary=True,
    )
    db_session.flush()

    _identifier(
        db_session, tenant, account, value="ADM-2", type_="admission_id",
        is_primary=True,
    )
    with pytest.raises(IntegrityError) as refused:
        db_session.flush()

    assert "uq_account_identifiers_primary" in str(refused.value)


def test_an_account_may_hold_several_non_primary_identifiers(
    db_session, tenant, account
):
    _identifier(
        db_session, tenant, account, value="ADM-1", type_="admission_id",
        is_primary=True,
    )
    _identifier(db_session, tenant, account, value="ADM-2", type_="admission_id")
    _identifier(db_session, tenant, account, value="ADM-3", type_="admission_id")
    db_session.flush()

    admission = AccountIdentifier.query.filter_by(
        account_id=account.id, identifier_type="admission_id"
    ).all()
    assert len(admission) == 3
    assert sum(1 for i in admission if i.is_primary) == 1


# ---------------------------------------------------------------------------
# The credential row
# ---------------------------------------------------------------------------

def test_a_credential_can_be_created_and_reads_back(db_session, tenant, account):
    row = _credential(
        db_session, tenant, account, must_change=True, is_provisional=True
    )
    db_session.flush()

    stored = db_session.get(AccountCredential, row.id)
    assert stored.account_id == account.id
    assert stored.tenant_id == tenant.id
    assert stored.credential_type == "password"
    assert stored.hash_algorithm == "scrypt:32768:8:1"
    assert stored.must_change is True
    assert stored.is_provisional is True
    assert stored.issued_at is not None
    assert stored.deleted_at is None


def test_one_live_credential_of_each_type_per_account(db_session, tenant, account):
    _credential(db_session, tenant, account)
    db_session.flush()

    _credential(db_session, tenant, account)
    with pytest.raises(IntegrityError) as refused:
        db_session.flush()

    assert "uq_account_credentials_live" in str(refused.value)


def test_an_account_may_hold_a_password_and_a_pin_at_once(
    db_session, tenant, account
):
    """Different credentials satisfying different authentication methods, not
    two copies of one secret."""
    _credential(db_session, tenant, account, type_="password")
    _credential(db_session, tenant, account, type_="pin")
    db_session.flush()

    assert {c.credential_type for c in account.credentials} == {"password", "pin"}


def test_an_unknown_credential_type_is_refused(db_session, tenant, account):
    _credential(db_session, tenant, account, type_="passkey")
    with pytest.raises(IntegrityError) as refused:
        db_session.flush()
    assert "ck_account_credentials_type" in str(refused.value)


def test_a_retired_credential_frees_its_slot(db_session, tenant, account):
    first = _credential(db_session, tenant, account)
    db_session.flush()
    first.deleted_at = utc_now()
    db_session.flush()

    _credential(db_session, tenant, account, secret_hash="scrypt:32768:8:1$new$new")
    db_session.flush()

    assert (
        AccountCredential.query.filter_by(
            account_id=account.id, credential_type="password", deleted_at=None
        ).count()
        == 1
    )
    assert AccountCredential.query.filter_by(account_id=account.id).count() == 2


def test_deleting_the_account_removes_its_credentials(db_session, tenant, account):
    _credential(db_session, tenant, account)
    db_session.flush()
    credential_id = account.credentials[0].id

    db_session.delete(account)
    db_session.flush()

    assert db_session.get(AccountCredential, credential_id) is None


# ---------------------------------------------------------------------------
# Tenant scoping
# ---------------------------------------------------------------------------

def test_both_tables_are_tenant_scoped_models(db_session):
    """Inheriting TenantBaseModel is what applies the ORM scope — there is no
    opt-in flag, so this is the assertion that matters."""
    from core.models import TenantBaseModel

    assert issubclass(AccountIdentifier, TenantBaseModel)
    assert issubclass(AccountCredential, TenantBaseModel)


def test_the_lookup_never_becomes_globally_scoped(db_session, tenant, account):
    """A lookup by normalized value alone spans tenants; the index and every
    future caller lead on tenant_id. Asserted so a later phase cannot quietly
    drop the tenant filter and still pass."""
    elsewhere = make_tenant(db_session, subdomain_prefix="p0b-scope")
    guest = make_user(db_session, elsewhere, password=PASSWORD)
    _identifier(db_session, tenant, account, value="scope@x.test")
    _identifier(db_session, elsewhere, guest, value="scope@x.test")
    db_session.flush()

    unscoped = AccountIdentifier.query.filter_by(
        identifier_type="email", identifier_value_normalized="scope@x.test"
    ).count()
    scoped = AccountIdentifier.query.filter_by(
        tenant_id=tenant.id,
        identifier_type="email",
        identifier_value_normalized="scope@x.test",
    ).count()

    assert unscoped == 2
    assert scoped == 1


# ---------------------------------------------------------------------------
# The backfill, as applied to the real database
# ---------------------------------------------------------------------------

def test_every_account_with_an_email_has_exactly_one_email_identifier(db_session):
    orphans = db_session.execute(
        db.text(
            """
            SELECT count(*) FROM users u
             WHERE u.email IS NOT NULL AND btrim(u.email) <> ''
               AND NOT EXISTS (
                   SELECT 1 FROM account_identifiers i
                    WHERE i.account_id = u.id AND i.identifier_type = 'email'
               )
            """
        )
    ).scalar()
    duplicates = db_session.execute(
        db.text(
            """
            SELECT count(*) FROM (
                SELECT account_id FROM account_identifiers
                 WHERE identifier_type = 'email'
                 GROUP BY account_id HAVING count(*) > 1
            ) x
            """
        )
    ).scalar()

    assert orphans == 0
    assert duplicates == 0


def test_every_account_with_a_hash_has_exactly_one_password_credential(db_session):
    orphans = db_session.execute(
        db.text(
            """
            SELECT count(*) FROM users u
             WHERE u.password_hash IS NOT NULL AND u.password_hash <> ''
               AND NOT EXISTS (
                   SELECT 1 FROM account_credentials c
                    WHERE c.account_id = u.id AND c.credential_type = 'password'
               )
            """
        )
    ).scalar()
    duplicates = db_session.execute(
        db.text(
            """
            SELECT count(*) FROM (
                SELECT account_id FROM account_credentials
                 WHERE credential_type = 'password'
                 GROUP BY account_id HAVING count(*) > 1
            ) x
            """
        )
    ).scalar()

    assert orphans == 0
    assert duplicates == 0


def test_the_backfill_copied_hashes_verbatim(db_session):
    """Not re-hashed, not regenerated, not invalidated."""
    mismatches = db_session.execute(
        db.text(
            """
            SELECT count(*) FROM users u
              JOIN account_credentials c
                ON c.account_id = u.id AND c.credential_type = 'password'
             WHERE c.secret_hash IS DISTINCT FROM u.password_hash
            """
        )
    ).scalar()

    assert mismatches == 0


def test_the_backfill_preserved_verification_and_reset_state(db_session):
    disagreements = db_session.execute(
        db.text(
            """
            SELECT
              (SELECT count(*) FROM users u
                 JOIN account_identifiers i
                   ON i.account_id = u.id AND i.identifier_type = 'email'
                WHERE i.is_verified IS DISTINCT FROM u.email_verified)
            + (SELECT count(*) FROM users u
                 JOIN account_credentials c
                   ON c.account_id = u.id AND c.credential_type = 'password'
                WHERE c.must_change IS DISTINCT FROM u.force_password_reset)
            """
        )
    ).scalar()

    assert disagreements == 0


def test_the_backfill_normalized_every_email(db_session):
    wrong = db_session.execute(
        db.text(
            """
            SELECT count(*) FROM account_identifiers
             WHERE identifier_type = 'email'
               AND identifier_value_normalized
                   IS DISTINCT FROM lower(btrim(identifier_value))
            """
        )
    ).scalar()

    assert wrong == 0


def test_backfill_ids_are_derived_from_the_account(db_session):
    """Deterministic ids are what make the backfill safe to run twice."""
    wrong = db_session.execute(
        db.text(
            """
            SELECT count(*) FROM account_identifiers
             WHERE identifier_type = 'email'
               AND id IS DISTINCT FROM md5('ident:email:' || account_id)::uuid::text
            """
        )
    ).scalar()

    assert wrong == 0


def test_the_migration_created_every_required_index(db_session):
    present = {
        row[0]
        for row in db_session.execute(
            db.text(
                """
                SELECT indexname FROM pg_indexes
                 WHERE tablename IN ('account_identifiers', 'account_credentials')
                """
            )
        )
    }

    assert {
        "uq_account_identifiers_live",
        "idx_account_identifiers_lookup",
        "idx_account_identifiers_account",
        "uq_account_identifiers_primary",
        "uq_account_credentials_live",
    } <= present


def test_the_live_uniqueness_index_is_partial(db_session):
    definition = db_session.execute(
        db.text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE indexname = 'uq_account_identifiers_live'"
        )
    ).scalar()

    assert "UNIQUE INDEX" in definition
    assert "(tenant_id, identifier_type, identifier_value_normalized)" in definition
    assert "WHERE (deleted_at IS NULL)" in definition


# ---------------------------------------------------------------------------
# The boundary: nothing reads these tables yet
# ---------------------------------------------------------------------------

def test_the_legacy_columns_are_untouched(db_session):
    """`users.email` and `users.password_hash` remain NOT NULL and
    authoritative. Email nullability is a later contract phase."""
    columns = {
        row[0]: row[1]
        for row in db_session.execute(
            db.text(
                """
                SELECT column_name, is_nullable FROM information_schema.columns
                 WHERE table_name = 'users'
                   AND column_name IN ('email', 'password_hash',
                                       'email_verified', 'force_password_reset')
                """
            )
        )
    }

    assert columns["email"] == "NO"
    assert columns["password_hash"] == "NO"
    assert columns["email_verified"] == "NO"
    assert columns["force_password_reset"] == "NO"


def test_login_still_resolves_through_the_legacy_column(
    client, db_session, tenant
):
    """The boundary, asserted rather than assumed.

    Since A2 the account *has* an email identifier — so proving login does not
    read it needs a sharper test than "there is no row". The identifier is
    pointed at a different address; if login resolved through identifiers the
    account would become unreachable by its own email, and it does not.

    This test is expected to change in Phase 0d — that is when login starts
    resolving through identifiers, and this is the marker for it.
    """
    from tests.auth._characterization import login, make_account

    account = make_account(db_session, tenant, password=PASSWORD)
    identifier = AccountIdentifier.query.filter_by(
        account_id=account.id, identifier_type="email"
    ).one()
    identifier.identifier_value_normalized = f"diverged-{uuid.uuid4().hex}@x.test"
    db_session.flush()

    response = login(
        client, email=account.email, password=PASSWORD, tenant_id=tenant.id
    )

    assert response.status_code == 200, response.get_json()


def test_no_credential_row_is_needed_to_sign_in(client, db_session, tenant):
    """The other half of the boundary: credentials are still not written on
    account creation, and verification still reads `users.password_hash`."""
    from tests.auth._characterization import login, make_account

    account = make_account(db_session, tenant, password=PASSWORD)
    assert AccountCredential.query.filter_by(account_id=account.id).count() == 0

    response = login(
        client, email=account.email, password=PASSWORD, tenant_id=tenant.id
    )

    assert response.status_code == 200, response.get_json()


def test_password_verification_still_reads_the_user_row(db_session, tenant, account):
    """`check_password` is unchanged and does not consult account_credentials."""
    _credential(
        db_session, tenant, account, secret_hash="not-the-real-hash",
        hash_algorithm="fabricated",
    )
    db_session.flush()

    assert account.check_password(PASSWORD) is True
