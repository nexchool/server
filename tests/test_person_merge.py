"""Combining two records that describe one human (ADR-010)."""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from modules.people.merge import (
    MergeRefused,
    merge_people,
    suggest_duplicates,
)
from modules.people.models import (
    FAMILY_ROLE_FATHER,
    Family,
    FamilyMember,
    Person,
    PersonMerge,
)


def _person(db_session, tenant, name, **fields):
    person = Person(tenant_id=tenant.id, full_name=name, **fields)
    db_session.add(person)
    db_session.flush()
    return person


def _account_for(db_session, tenant, person):
    from modules.auth.models import User

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}",
        tenant_id=tenant.id,
        email=f"{suffix}@test.school",
        password_hash="x" * 60,
        name=person.full_name,
        person_id=person.id,
    )
    db_session.add(user)
    db_session.flush()
    return user


def _staff_for(db_session, tenant, person):
    from modules.people.employment import Staff

    staff = Staff(tenant_id=tenant.id, person_id=person.id)
    db_session.add(staff)
    db_session.flush()
    return staff


# ---------------------------------------------------------------------------
# Combining
# ---------------------------------------------------------------------------

def test_merging_repoints_everything_at_the_surviving_person(db_session, tenant):
    kept = _person(db_session, tenant, "Rajesh Patel")
    absorbed = _person(db_session, tenant, "R Patel")
    staff = _staff_for(db_session, tenant, absorbed)

    merge_people(kept.id, absorbed.id, reason="same teacher recorded twice")

    assert staff.person_id == kept.id
    assert absorbed.deleted_at is not None


def test_the_survivor_gains_what_only_the_other_record_held(db_session, tenant):
    kept = _person(db_session, tenant, "Rajesh Patel")
    absorbed = _person(
        db_session,
        tenant,
        "Rajesh Patel",
        phone_number="9876543210",
        occupation="Engineer",
        date_of_birth=date(1980, 3, 4),
    )

    merge_people(kept.id, absorbed.id)

    assert kept.phone_number == "9876543210"
    assert kept.occupation == "Engineer"
    assert kept.date_of_birth == date(1980, 3, 4)


def test_the_survivors_own_details_are_never_overwritten(db_session, tenant):
    kept = _person(db_session, tenant, "Rajesh Patel", phone_number="9811111111")
    absorbed = _person(db_session, tenant, "Rajesh Patel", phone_number="9822222222")

    merge_people(kept.id, absorbed.id)

    assert kept.phone_number == "9811111111"


def test_what_was_combined_is_written_down(db_session, tenant):
    kept = _person(db_session, tenant, "Rajesh Patel")
    absorbed = _person(db_session, tenant, "R Patel", phone_number="9876543210")

    record = merge_people(kept.id, absorbed.id, reason="confirmed by office")

    stored = PersonMerge.query.get(record.id)
    assert stored.kept_person_id == kept.id
    assert stored.absorbed_person_id == absorbed.id
    assert stored.absorbed_person_details["full_name"] == "R Patel"
    assert stored.absorbed_person_details["phone_number"] == "9876543210"
    assert stored.reason == "confirmed by office"


# ---------------------------------------------------------------------------
# Families
# ---------------------------------------------------------------------------

def test_family_participation_follows_the_surviving_person(db_session, tenant):
    kept = _person(db_session, tenant, "Rajesh Patel")
    absorbed = _person(db_session, tenant, "R Patel")
    family = Family(tenant_id=tenant.id)
    db_session.add(family)
    db_session.flush()
    db_session.add(
        FamilyMember(
            tenant_id=tenant.id,
            family_id=family.id,
            person_id=absorbed.id,
            relationship=FAMILY_ROLE_FATHER,
        )
    )
    db_session.flush()

    merge_people(kept.id, absorbed.id)

    members = FamilyMember.query.filter_by(family_id=family.id).all()
    assert [member.person_id for member in members] == [kept.id]


def test_a_person_does_not_end_up_in_the_same_family_twice(db_session, tenant):
    kept = _person(db_session, tenant, "Rajesh Patel")
    absorbed = _person(db_session, tenant, "R Patel")
    family = Family(tenant_id=tenant.id)
    db_session.add(family)
    db_session.flush()
    for person in (kept, absorbed):
        db_session.add(
            FamilyMember(
                tenant_id=tenant.id,
                family_id=family.id,
                person_id=person.id,
                relationship=FAMILY_ROLE_FATHER,
            )
        )
    db_session.flush()

    merge_people(kept.id, absorbed.id)

    members = FamilyMember.query.filter_by(family_id=family.id).all()
    assert len(members) == 1


# ---------------------------------------------------------------------------
# When a merge would hide a problem instead of solving one
# ---------------------------------------------------------------------------

def test_two_accounts_are_not_silently_reduced_to_one(db_session, tenant):
    kept = _person(db_session, tenant, "Rajesh Patel")
    absorbed = _person(db_session, tenant, "R Patel")
    _account_for(db_session, tenant, kept)
    _account_for(db_session, tenant, absorbed)

    with pytest.raises(MergeRefused, match="an account"):
        merge_people(kept.id, absorbed.id)


def test_two_employments_are_not_silently_reduced_to_one(db_session, tenant):
    kept = _person(db_session, tenant, "Rajesh Patel")
    absorbed = _person(db_session, tenant, "R Patel")
    _staff_for(db_session, tenant, kept)
    _staff_for(db_session, tenant, absorbed)

    with pytest.raises(MergeRefused, match="an employment record"):
        merge_people(kept.id, absorbed.id)


def test_a_person_cannot_be_merged_into_themselves(db_session, tenant):
    person = _person(db_session, tenant, "Rajesh Patel")

    with pytest.raises(MergeRefused):
        merge_people(person.id, person.id)


def test_people_from_different_organizations_are_not_one_human(db_session, tenant):
    from core.models import Tenant, TENANT_STATUS_ACTIVE, BILLING_CYCLE_YEARLY

    other = Tenant(
        id=f"t-{uuid.uuid4().hex[:12]}",
        name="Other School",
        subdomain=f"other-{uuid.uuid4().hex[:6]}",
        status=TENANT_STATUS_ACTIVE,
        billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(other)
    db_session.flush()

    kept = _person(db_session, tenant, "Rajesh Patel")
    elsewhere = Person(tenant_id=other.id, full_name="Rajesh Patel")
    db_session.add(elsewhere)
    db_session.flush()

    with pytest.raises(MergeRefused, match="different organizations"):
        merge_people(kept.id, elsewhere.id)


def test_merging_an_already_merged_person_is_refused(db_session, tenant):
    kept = _person(db_session, tenant, "Rajesh Patel")
    absorbed = _person(db_session, tenant, "R Patel")
    merge_people(kept.id, absorbed.id)

    with pytest.raises(MergeRefused, match="already been merged"):
        merge_people(kept.id, absorbed.id)


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------

def test_a_shared_phone_is_raised_as_a_question_not_a_merge(db_session, tenant):
    _person(db_session, tenant, "Rajesh Patel", phone_number="9876543210")
    _person(db_session, tenant, "Nita Patel", phone_number="9876543210")

    suggestions = suggest_duplicates(tenant.id)

    assert len(suggestions) == 1
    assert suggestions[0].reason == "same phone, different name"


def test_the_same_name_on_one_phone_is_reported_as_a_likely_duplicate(db_session, tenant):
    _person(db_session, tenant, "Rajesh Patel", phone_number="9876543210")
    _person(db_session, tenant, "Mr. Rajesh Patel", phone_number="+91 98765 43210")

    suggestions = suggest_duplicates(tenant.id)

    assert suggestions[0].reason == "same phone and name"


def test_a_merged_person_stops_being_suggested(db_session, tenant):
    kept = _person(db_session, tenant, "Rajesh Patel", phone_number="9876543210")
    absorbed = _person(db_session, tenant, "Rajesh Patel", phone_number="9876543210")

    assert suggest_duplicates(tenant.id)

    merge_people(kept.id, absorbed.id)

    assert suggest_duplicates(tenant.id) == []
