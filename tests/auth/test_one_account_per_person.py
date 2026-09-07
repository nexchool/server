"""Phase 0a — a person signs in as one account.

The first identity invariant. Two layers, tested as two layers because they
fail differently and one is authoritative:

  * `uq_users_tenant_person_live` — a partial unique index on
    `(tenant_id, person_id) WHERE deleted_at IS NULL`. This is the rule. It
    holds against races, against a seed script, against psql.
  * `person_link.AccountAlreadyExists` — raised by the existing `before_flush`
    hook before the insert is attempted, so a caller reusing somebody else's
    `person_id` is told which person and which account rather than being handed
    an index name.

What the invariant does NOT say is asserted here too, because getting it
wrong is the expensive mistake: it is not about email. Two different people
may share an address. The same human at two schools is two Person rows and
two accounts, and that is a tenant membership, not a duplicate.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from core.school_time import utc_now
from modules.auth.models import User
from modules.auth.person_link import AccountAlreadyExists
from tests.auth._characterization import make_tenant, new_id

PASSWORD = "C0rrectHorse1"


@pytest.fixture
def person(db_session, tenant):
    """A human this school knows, with no account yet."""
    from modules.people.models import Person

    p = Person(
        id=new_id("p-"), tenant_id=tenant.id, full_name="Characterization Human"
    )
    db_session.add(p)
    db_session.flush()
    return p


def _account_for(db_session, tenant, person, *, email=None, **overrides):
    """An account explicitly bound to an existing person — the shape that the
    invariant governs. Accounts whose person is minted by the hook can never
    collide, because the person is new."""
    user = User(
        id=new_id("u-"),
        tenant_id=tenant.id,
        person_id=person.id,
        email=email or f"p0a-{uuid.uuid4().hex[:8]}@test.school",
        name="Characterization User",
        email_verified=True,
        **overrides,
    )
    user.set_password(PASSWORD)
    db_session.add(user)
    return user


# ---------------------------------------------------------------------------
# 1 — one live account is allowed
# ---------------------------------------------------------------------------

def test_a_person_may_hold_one_account(db_session, tenant, person):
    account = _account_for(db_session, tenant, person)
    db_session.flush()

    assert account.person_id == person.id
    assert (
        User.query.filter_by(person_id=person.id, deleted_at=None).count() == 1
    )


def test_an_account_created_without_a_person_still_gets_one(db_session, tenant):
    """The pre-existing `person_link` behaviour, unchanged: an account that
    names no person has one minted for it, and that person is new — so the new
    invariant can never be tripped by this path."""
    user = User(
        id=new_id("u-"),
        tenant_id=tenant.id,
        email=f"p0a-{uuid.uuid4().hex[:8]}@test.school",
        name="Minted Person",
    )
    user.set_password(PASSWORD)
    db_session.add(user)
    db_session.flush()

    assert user.person_id is not None
    assert user.person.full_name == "Minted Person"


# ---------------------------------------------------------------------------
# 2 — a second live account is refused
# ---------------------------------------------------------------------------

def test_a_second_live_account_for_the_same_person_is_refused(
    db_session, tenant, person
):
    _account_for(db_session, tenant, person)
    db_session.flush()

    _account_for(db_session, tenant, person)
    with pytest.raises(AccountAlreadyExists) as refused:
        db_session.flush()

    assert person.id in str(refused.value)


def test_the_refusal_names_the_account_already_held(db_session, tenant, person):
    first = _account_for(db_session, tenant, person)
    db_session.flush()

    _account_for(db_session, tenant, person)
    with pytest.raises(AccountAlreadyExists) as refused:
        db_session.flush()

    assert first.id in str(refused.value)


def test_two_accounts_for_one_person_in_a_single_flush_are_refused(
    db_session, tenant, person
):
    """Neither row is in the database yet, so only the hook can see this."""
    _account_for(db_session, tenant, person)
    _account_for(db_session, tenant, person)

    with pytest.raises(AccountAlreadyExists):
        db_session.flush()


def test_the_database_refuses_it_even_when_the_hook_is_bypassed(
    db_session, tenant, person
):
    """The index is the authority, not the hook. Inserted with Core SQL so no
    ORM event runs — which is also what a seed script or a psql session does.
    """
    from core.database import db

    _account_for(db_session, tenant, person)
    db_session.flush()

    statement = db.text(
        """
        INSERT INTO users (id, tenant_id, person_id, email, password_hash,
                           email_verified, force_password_reset,
                           is_platform_admin, failed_login_count,
                           is_suspended, created_at, updated_at)
        VALUES (:id, :tenant_id, :person_id, :email, 'h',
                true, false, false, 0, false, now(), now())
        """
    )
    with pytest.raises(IntegrityError) as refused:
        db_session.execute(
            statement,
            {
                "id": new_id("u-"),
                "tenant_id": tenant.id,
                "person_id": person.id,
                "email": f"raw-{uuid.uuid4().hex[:8]}@test.school",
            },
        )

    assert "uq_users_tenant_person_live" in str(refused.value)


# ---------------------------------------------------------------------------
# 3 — the same human in two schools stays two accounts
# ---------------------------------------------------------------------------

def test_person_id_is_not_globally_unique(db_session, tenant):
    """`persons` is tenant-scoped, so one human at two schools is two Person
    rows. Both may hold an account; the invariant is per tenant."""
    from modules.people.models import Person

    other = make_tenant(db_session, subdomain_prefix="p0a-other")
    here = Person(id=new_id("p-"), tenant_id=tenant.id, full_name="Ravi Patel")
    there = Person(id=new_id("p-"), tenant_id=other.id, full_name="Ravi Patel")
    db_session.add_all([here, there])
    db_session.flush()

    _account_for(db_session, tenant, here)
    _account_for(db_session, other, there)
    db_session.flush()

    assert User.query.filter_by(person_id=here.id).count() == 1
    assert User.query.filter_by(person_id=there.id).count() == 1


def test_the_index_is_scoped_to_the_tenant(db_session, tenant):
    """Belt and braces on the same point, at the index level: the same
    person_id string under two tenant_ids does not collide."""
    from core.database import db
    from modules.people.models import Person

    other = make_tenant(db_session, subdomain_prefix="p0a-scope")
    shared_id = new_id("p-")
    db_session.add(
        Person(id=shared_id, tenant_id=tenant.id, full_name="Same Id Here")
    )
    db_session.flush()

    _account_for(
        db_session, tenant, db_session.get(Person, shared_id)
    )
    db_session.flush()

    # A row carrying the identical person_id under a different tenant is not a
    # collision. Inserted raw because a Person row with a duplicate id cannot
    # exist; the point being made is about the index's columns.
    db_session.execute(
        db.text(
            """
            INSERT INTO users (id, tenant_id, person_id, email, password_hash,
                               email_verified, force_password_reset,
                               is_platform_admin, failed_login_count,
                               is_suspended, created_at, updated_at)
            SELECT :id, :tenant_id, :person_id, :email, 'h',
                   true, false, false, 0, false, now(), now()
            """
        ),
        {
            "id": new_id("u-"),
            "tenant_id": other.id,
            "person_id": shared_id,
            "email": f"scope-{uuid.uuid4().hex[:8]}@test.school",
        },
    )


# ---------------------------------------------------------------------------
# 4 — different people are independent
# ---------------------------------------------------------------------------

def test_two_people_may_each_hold_an_account_in_one_school(
    db_session, tenant, person
):
    from modules.people.models import Person

    second = Person(
        id=new_id("p-"), tenant_id=tenant.id, full_name="Another Human"
    )
    db_session.add(second)
    db_session.flush()

    _account_for(db_session, tenant, person)
    _account_for(db_session, tenant, second)
    db_session.flush()

    assert (
        User.query.filter(
            User.person_id.in_([person.id, second.id]), User.deleted_at.is_(None)
        ).count()
        == 2
    )


def test_the_invariant_is_not_about_email(db_session, tenant, person):
    """Two different people may share an address — across tenants, which is
    where `uq_users_email_tenant` already permits it. Phase 0a must not start
    forbidding that."""
    from modules.people.models import Person

    other = make_tenant(db_session, subdomain_prefix="p0a-email")
    elsewhere = Person(
        id=new_id("p-"), tenant_id=other.id, full_name="Different Human"
    )
    db_session.add(elsewhere)
    db_session.flush()

    shared = f"shared-{uuid.uuid4().hex[:8]}@test.school"
    _account_for(db_session, tenant, person, email=shared)
    _account_for(db_session, other, elsewhere, email=shared)
    db_session.flush()

    assert User.query.filter_by(email=shared).count() == 2


# ---------------------------------------------------------------------------
# 5 — soft deletion frees the person
# ---------------------------------------------------------------------------

def test_a_closed_account_does_not_block_a_replacement(
    db_session, tenant, person
):
    """The reason the index is partial. `uq_users_email_tenant` is not, which
    is why a closed account's email can never be reused — this does not repeat
    that."""
    first = _account_for(db_session, tenant, person)
    db_session.flush()

    first.deleted_at = utc_now()
    db_session.flush()

    replacement = _account_for(db_session, tenant, person)
    db_session.flush()

    assert replacement.id != first.id
    assert (
        User.query.filter_by(person_id=person.id, deleted_at=None).count() == 1
    )
    assert User.query.filter_by(person_id=person.id).count() == 2


def test_several_closed_accounts_may_coexist(db_session, tenant, person):
    first = _account_for(db_session, tenant, person)
    db_session.flush()
    first.deleted_at = utc_now()
    db_session.flush()

    second = _account_for(db_session, tenant, person)
    db_session.flush()
    second.deleted_at = utc_now()
    db_session.flush()

    third = _account_for(db_session, tenant, person)
    db_session.flush()

    assert User.query.filter_by(person_id=person.id).count() == 3
    assert third.deleted_at is None


def test_a_replacement_cannot_itself_be_duplicated(db_session, tenant, person):
    first = _account_for(db_session, tenant, person)
    db_session.flush()
    first.deleted_at = utc_now()
    db_session.flush()
    _account_for(db_session, tenant, person)
    db_session.flush()

    _account_for(db_session, tenant, person)
    with pytest.raises(AccountAlreadyExists):
        db_session.flush()


# ---------------------------------------------------------------------------
# 6 — the existing person-link hook still behaves
# ---------------------------------------------------------------------------

def test_the_hook_still_attaches_a_person_to_every_account(db_session, tenant):
    from tests.auth._characterization import make_user

    user = make_user(db_session, tenant, password=PASSWORD)

    assert user.person_id is not None
    assert user.person.tenant_id == tenant.id


def test_the_hook_still_names_a_person_from_the_email(db_session, tenant):
    user = User(
        id=new_id("u-"),
        tenant_id=tenant.id,
        email=f"named-{uuid.uuid4().hex[:8]}@test.school",
    )
    user.set_password(PASSWORD)
    db_session.add(user)
    db_session.flush()

    assert user.person.full_name.startswith("named-")


def test_the_hook_still_gives_a_studentship_its_accounts_person(
    db_session, tenant
):
    """ADR-001: the studentship belongs to the human the account was opened
    for. Unchanged by Phase 0a, and asserted because the guard runs in the
    same hook."""
    from modules.students.models import Student
    from tests.auth._characterization import make_user

    user = make_user(db_session, tenant, password=PASSWORD)
    student = Student(
        id=new_id("s-"),
        tenant_id=tenant.id,
        user_id=user.id,
        admission_number=f"ADM-{uuid.uuid4().hex[:6].upper()}",
    )
    db_session.add(student)
    db_session.flush()

    assert student.person_id == user.person_id


def test_many_accounts_in_one_flush_are_fine_when_each_has_its_own_person(
    db_session, tenant
):
    """What the bulk importers do. The guard must not turn a legitimate batch
    into a false positive."""
    from tests.auth._characterization import make_user

    created = [
        make_user(db_session, tenant, password=PASSWORD) for _ in range(5)
    ]
    db_session.flush()

    assert len({u.person_id for u in created}) == 5


# ---------------------------------------------------------------------------
# The index itself
# ---------------------------------------------------------------------------

def test_the_index_exists_with_the_intended_definition(db_session):
    from core.database import db

    definition = db_session.execute(
        db.text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename = 'users' AND indexname = :name"
        ),
        {"name": "uq_users_tenant_person_live"},
    ).scalar()

    assert definition is not None, "the Phase 0a migration has not been applied"
    assert "UNIQUE INDEX" in definition
    assert "(tenant_id, person_id)" in definition
    assert "WHERE (deleted_at IS NULL)" in definition


def test_the_email_constraint_is_untouched(db_session):
    """Phase 0a adds a rule; it removes none."""
    from core.database import db

    assert db_session.execute(
        db.text(
            "SELECT 1 FROM pg_indexes WHERE tablename = 'users' "
            "AND indexname = 'uq_users_email_tenant'"
        )
    ).scalar() == 1
