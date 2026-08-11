"""An account always belongs to a person.

Accounts are created from a dozen places. Rather than trusting each of them to
remember, the People domain creates the person as the account is saved — the
same approach the platform already takes with tenant scoping.
"""

from __future__ import annotations

import uuid

from modules.people.models import Person


def _new_account(db_session, tenant, **overrides):
    from modules.auth.models import User

    suffix = uuid.uuid4().hex[:8]
    fields = {
        "id": f"u-{suffix}",
        "tenant_id": tenant.id,
        "email": f"{suffix}@test.school",
        "password_hash": "x" * 60,
        "name": "Meera Shah",
    }
    fields.update(overrides)
    user = User(**fields)
    db_session.add(user)
    db_session.flush()
    return user


def test_saving_an_account_creates_the_person_behind_it(db_session, tenant):
    user = _new_account(db_session, tenant)

    assert user.person_id is not None
    assert user.person.full_name == "Meera Shah"
    assert user.person.tenant_id == tenant.id


def test_the_person_takes_the_email_from_the_account(db_session, tenant):
    user = _new_account(db_session, tenant)

    assert user.person.email == user.email


def test_an_account_without_a_name_still_names_the_person(db_session, tenant):
    user = _new_account(db_session, tenant, name=None, email="principal@test.school")

    assert user.person.full_name == "principal"


def test_a_person_supplied_by_the_caller_is_left_alone(db_session, tenant):
    """Callers that know who the human is are not second-guessed."""
    person = Person(tenant_id=tenant.id, full_name="Known Already")
    db_session.add(person)
    db_session.flush()

    user = _new_account(db_session, tenant, person_id=person.id)

    assert user.person_id == person.id
    assert user.person.full_name == "Known Already"


def test_two_accounts_are_two_people(db_session, tenant):
    first = _new_account(db_session, tenant)
    second = _new_account(db_session, tenant)

    assert first.person_id != second.person_id
