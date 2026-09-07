"""Invariant A2 — an account's email identifier says what the account says.

The Phase 0c prerequisite. `users.email` remains authoritative and nothing
reads `account_identifiers` yet; what this guarantees is that the identifier is
*already true* when a later phase switches the read over, so that switch needs
no second backfill.

Enforced in `person_link.py`'s `before_flush` for the reason that module was
written: an address is set in a dozen places — admissions, staff onboarding,
two bulk importers, platform admin creation and reset, seed scripts — and
asking each of them to maintain a row is a rule that will be forgotten.
"""

from __future__ import annotations

import uuid

import pytest

from core.school_time import utc_now
from modules.auth.identifiers import normalize_email
from modules.auth.models import AccountIdentifier, User
from tests.auth._characterization import make_tenant, make_user, new_id

PASSWORD = "C0rrectHorse1"


def _email_identifiers(account_id, *, live_only=False):
    query = AccountIdentifier.query.filter_by(
        account_id=account_id, identifier_type="email"
    )
    if live_only:
        query = query.filter(AccountIdentifier.deleted_at.is_(None))
    return query.all()


def _the_identifier(account):
    rows = _email_identifiers(account.id, live_only=True)
    assert len(rows) == 1, f"expected one live email identifier, found {len(rows)}"
    return rows[0]


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------

def test_a_new_account_gets_an_email_identifier(db_session, tenant):
    account = make_user(db_session, tenant, password=PASSWORD)

    identifier = _the_identifier(account)
    assert identifier.identifier_value == account.email
    assert identifier.identifier_value_normalized == normalize_email(account.email)
    assert identifier.tenant_id == tenant.id
    assert identifier.is_primary is True
    assert identifier.deleted_at is None


def test_the_identifier_is_normalized_at_creation(db_session, tenant):
    account = make_user(
        db_session, tenant, password=PASSWORD,
        email=f"  Ravi.Patel-{uuid.uuid4().hex[:6]}@School.IN  ",
    )

    identifier = _the_identifier(account)
    # The raw value is kept exactly as the school entered it...
    assert identifier.identifier_value == account.email
    # ...and the comparison key is canonical.
    assert identifier.identifier_value_normalized == account.email.strip().lower()
    assert identifier.identifier_value_normalized != identifier.identifier_value


def test_verification_state_is_mirrored_not_invented(db_session, tenant):
    verified = make_user(db_session, tenant, password=PASSWORD, email_verified=True)
    unverified = make_user(
        db_session, tenant, password=PASSWORD, email_verified=False
    )

    assert _the_identifier(verified).is_verified is True
    assert _the_identifier(unverified).is_verified is False


def test_an_account_never_gets_two_live_email_identifiers(db_session, tenant):
    account = make_user(db_session, tenant, password=PASSWORD)

    # Touch the account repeatedly; each flush runs the hook again.
    for index in range(3):
        account.name = f"Renamed {index}"
        db_session.flush()

    assert len(_email_identifiers(account.id, live_only=True)) == 1


def test_a_batch_of_accounts_each_get_one(db_session, tenant):
    """What the bulk importers do — one flush, many accounts."""
    accounts = [make_user(db_session, tenant, password=PASSWORD) for _ in range(5)]
    db_session.flush()

    for account in accounts:
        assert len(_email_identifiers(account.id, live_only=True)) == 1


# ---------------------------------------------------------------------------
# Change
# ---------------------------------------------------------------------------

def test_changing_the_address_moves_the_identifier(db_session, tenant):
    account = make_user(db_session, tenant, password=PASSWORD)
    replacement = f"moved-{uuid.uuid4().hex[:8]}@test.school"

    account.email = replacement
    db_session.flush()

    identifier = _the_identifier(account)
    assert identifier.identifier_value == replacement
    assert identifier.identifier_value_normalized == replacement
    assert len(_email_identifiers(account.id)) == 1, "moved, not duplicated"


def test_changing_only_the_casing_keeps_the_key_canonical(db_session, tenant):
    account = make_user(
        db_session, tenant, password=PASSWORD,
        email=f"person-{uuid.uuid4().hex[:6]}@test.school",
    )
    canonical = normalize_email(account.email)

    account.email = f"  {account.email.upper()}  "
    db_session.flush()

    identifier = _the_identifier(account)
    # The raw value follows what was typed...
    assert identifier.identifier_value == account.email
    # ...and the key does not move.
    assert identifier.identifier_value_normalized == canonical


def test_verifying_the_address_verifies_the_identifier(db_session, tenant):
    account = make_user(
        db_session, tenant, password=PASSWORD, email_verified=False
    )
    assert _the_identifier(account).is_verified is False

    account.email_verified = True
    db_session.flush()

    assert _the_identifier(account).is_verified is True


def test_two_accounts_cannot_move_onto_one_address(db_session, tenant):
    """The identifier index refuses it, exactly as `uq_users_email_tenant`
    refuses the column change that would accompany it."""
    from sqlalchemy.exc import IntegrityError

    first = make_user(db_session, tenant, password=PASSWORD)
    second = make_user(db_session, tenant, password=PASSWORD)
    db_session.flush()

    second.email = first.email.upper()
    with pytest.raises(IntegrityError):
        db_session.flush()


# ---------------------------------------------------------------------------
# Closing an account
# ---------------------------------------------------------------------------

def test_closing_the_account_closes_its_identifier(db_session, tenant):
    account = make_user(db_session, tenant, password=PASSWORD)
    db_session.flush()

    account.deleted_at = utc_now()
    db_session.flush()

    assert _email_identifiers(account.id, live_only=True) == []
    assert len(_email_identifiers(account.id)) == 1, "kept, not deleted"


def test_the_identifier_index_frees_a_closed_accounts_address(db_session, tenant):
    """EXISTING BEHAVIOUR, and the difference between the two constraints.

    The identifier index is partial, so a closed account's row stops competing
    for the address. `uq_users_email_tenant` is **not** partial, so the account
    row itself still cannot be recreated with that address — which is why
    `create_student`, `create_teacher` and `create_sub_admin` each pass
    `include_deleted=True` to their duplicate guards.

    Both halves are asserted so a later phase can see exactly what the contract
    phase has to change.
    """
    from sqlalchemy.exc import IntegrityError

    first = make_user(db_session, tenant, password=PASSWORD)
    address = first.email
    db_session.flush()
    first.deleted_at = utc_now()
    db_session.flush()

    # The identifier no longer holds the value.
    assert AccountIdentifier.query.filter_by(
        tenant_id=tenant.id,
        identifier_type="email",
        identifier_value_normalized=address,
        deleted_at=None,
    ).count() == 0

    # The legacy column constraint still does.
    with pytest.raises(IntegrityError) as refused:
        make_user(db_session, tenant, password=PASSWORD, email=address)
    assert "uq_users_email_tenant" in str(refused.value)


# ---------------------------------------------------------------------------
# Tenant scope
# ---------------------------------------------------------------------------

def test_the_same_address_in_two_schools_gets_two_identifiers(db_session, tenant):
    elsewhere = make_tenant(db_session, subdomain_prefix="a2-other")
    address = f"shared-{uuid.uuid4().hex[:8]}@test.school"

    here = make_user(db_session, tenant, password=PASSWORD, email=address)
    there = make_user(db_session, elsewhere, password=PASSWORD, email=address)
    db_session.flush()

    assert _the_identifier(here).tenant_id == tenant.id
    assert _the_identifier(there).tenant_id == elsewhere.id


# ---------------------------------------------------------------------------
# The provisioning paths, through their real services
# ---------------------------------------------------------------------------

@pytest.fixture
def academic_year(db_session, tenant):
    from datetime import date

    from modules.academics.academic_year.models import AcademicYear

    year = AcademicYear(
        id=new_id("ay-"),
        tenant_id=tenant.id,
        name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 6, 1),
        end_date=date(2027, 3, 31),
        is_active=True,
    )
    db_session.add(year)
    db_session.flush()
    return year


def test_creating_a_student_through_the_service_yields_an_identifier(
    flask_app, db_session, tenant, academic_year
):
    """`create_student` reads the tenant from the request context rather than
    taking it as an argument, so the service is exercised the way a route
    does."""
    from flask import g

    from modules.students.services import create_student

    with flask_app.test_request_context():
        g.tenant_id = tenant.id
        result = create_student(
            name="Identifier Student",
            academic_year_id=academic_year.id,
            guardian_name="Guardian Name",
            guardian_relationship="father",
            guardian_phone="9876500001",
            email=f"student-{uuid.uuid4().hex[:8]}@test.school",
            date_of_birth="2012-04-01",
        )

    assert result.get("success") is True, result
    account_id = result["student"]["user_id"]
    assert account_id is not None
    assert len(_email_identifiers(account_id, live_only=True)) == 1


def test_a_student_created_without_an_email_has_no_account_and_no_identifier(
    flask_app, db_session, tenant, academic_year
):
    """ADR-003 is untouched: no email means no account, so there is nothing to
    give an identifier to. A2 does not invent one."""
    from flask import g

    from modules.students.services import create_student

    with flask_app.test_request_context():
        g.tenant_id = tenant.id
        result = create_student(
            name="Account-less Student",
            academic_year_id=academic_year.id,
            guardian_name="Guardian Name",
            guardian_relationship="mother",
            guardian_phone="9876500002",
            email=None,
        )

    assert result.get("success") is True, result
    assert result["student"]["user_id"] is None


def test_the_platform_admin_creation_path_yields_an_identifier(db_session):
    """A path that neither creates a student nor a teacher, and that sets the
    address itself — the shape most likely to be forgotten."""
    from modules.platform.services import create_tenant

    result = create_tenant(
        name="A2 Check School",
        subdomain=f"a2-check-{uuid.uuid4().hex[:10]}",
        contact_email=None,
        phone=None,
        address=None,
        admin_email=f"a2-admin-{uuid.uuid4().hex[:8]}@test.school",
        admin_name="A2 Admin",
        platform_admin_id=None,
    )

    assert result.get("success") is True, result
    admin = User.query.filter_by(
        tenant_id=result["tenant"]["id"]
    ).filter(User.email.like("a2-admin-%")).one()
    assert len(_email_identifiers(admin.id, live_only=True)) == 1


def test_the_backfilled_population_still_holds_the_invariant(db_session):
    """Every account in the database, migration-backfilled or hook-created,
    has exactly one live email identifier carrying its normalized address."""
    from core.database import db

    broken = db_session.execute(
        db.text(
            """
            SELECT count(*) FROM users u
             WHERE u.deleted_at IS NULL
               AND u.email IS NOT NULL AND btrim(u.email) <> ''
               AND (
                   SELECT count(*) FROM account_identifiers i
                    WHERE i.account_id = u.id
                      AND i.identifier_type = 'email'
                      AND i.deleted_at IS NULL
                      AND i.identifier_value_normalized = lower(btrim(u.email))
               ) <> 1
            """
        )
    ).scalar()

    assert broken == 0
