"""The rules that decide whether two records describe the same human (ADR-010).

The case that matters most is the one that must never merge: a father and a
mother sharing one household phone number.
"""

from __future__ import annotations

import pytest

from modules.people.matching import (
    build_match_key,
    normalize_email,
    normalize_name,
    normalize_phone,
)
from modules.people.models import (
    FAMILY_ROLE_CHILD,
    FAMILY_ROLE_FATHER,
    FAMILY_ROLE_MOTHER,
)

HOUSEHOLD_PHONE = "9876543210"


# ---------------------------------------------------------------------------
# The guard that prevents the damaging mistake
# ---------------------------------------------------------------------------

def test_parents_sharing_a_household_phone_are_never_the_same_person():
    father = build_match_key(FAMILY_ROLE_FATHER, "Rajesh Patel", phone=HOUSEHOLD_PHONE)
    mother = build_match_key(FAMILY_ROLE_MOTHER, "Nita Patel", phone=HOUSEHOLD_PHONE)

    assert father != mother


def test_parents_sharing_a_phone_and_a_name_are_still_not_the_same_person():
    """Even identical names must not merge across roles — the role decides."""
    father = build_match_key(FAMILY_ROLE_FATHER, "A Patel", phone=HOUSEHOLD_PHONE)
    mother = build_match_key(FAMILY_ROLE_MOTHER, "A Patel", phone=HOUSEHOLD_PHONE)

    assert father != mother


# ---------------------------------------------------------------------------
# What does merge
# ---------------------------------------------------------------------------

def test_the_same_parent_of_two_children_is_one_person():
    first = build_match_key(FAMILY_ROLE_FATHER, "Rajesh Patel", phone=HOUSEHOLD_PHONE)
    second = build_match_key(FAMILY_ROLE_FATHER, "Rajesh Patel", phone=HOUSEHOLD_PHONE)

    assert first == second


def test_a_parent_recorded_with_a_country_code_still_matches():
    plain = build_match_key(FAMILY_ROLE_FATHER, "Rajesh Patel", phone=HOUSEHOLD_PHONE)
    with_code = build_match_key(
        FAMILY_ROLE_FATHER, "Rajesh Patel", phone="+91 98765-43210"
    )

    assert plain == with_code


def test_an_honorific_does_not_make_a_different_person():
    plain = build_match_key(FAMILY_ROLE_FATHER, "Rajesh Patel", phone=HOUSEHOLD_PHONE)
    formal = build_match_key(FAMILY_ROLE_FATHER, "Shri Rajesh Patel", phone=HOUSEHOLD_PHONE)

    assert plain == formal


def test_email_can_stand_in_for_a_missing_phone():
    first = build_match_key(
        FAMILY_ROLE_FATHER, "Rajesh Patel", email="rajesh@example.com"
    )
    second = build_match_key(
        FAMILY_ROLE_FATHER, "Rajesh Patel", email="Rajesh@Example.com "
    )

    assert first is not None
    assert first == second


# ---------------------------------------------------------------------------
# What refuses to decide
# ---------------------------------------------------------------------------

def test_a_name_alone_is_never_enough_to_merge():
    assert build_match_key(FAMILY_ROLE_FATHER, "Rajesh Patel") is None


def test_a_contact_alone_is_never_enough_to_merge():
    assert build_match_key(FAMILY_ROLE_FATHER, None, phone=HOUSEHOLD_PHONE) is None


def test_different_names_on_one_phone_do_not_merge():
    first = build_match_key(FAMILY_ROLE_FATHER, "Rajesh Patel", phone=HOUSEHOLD_PHONE)
    second = build_match_key(FAMILY_ROLE_FATHER, "Suresh Patel", phone=HOUSEHOLD_PHONE)

    assert first != second


def test_roles_outside_the_comparable_set_never_merge():
    assert (
        build_match_key(FAMILY_ROLE_CHILD, "Aarav Patel", phone=HOUSEHOLD_PHONE) is None
    )


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "written,expected",
    [
        ("+91 98765 43210", "9876543210"),
        ("098765-43210", "9876543210"),
        ("0091 9876543210", "9876543210"),
        ("9876543210", "9876543210"),
        ("", ""),
        (None, ""),
    ],
)
def test_phone_reduces_to_subscriber_digits(written, expected):
    assert normalize_phone(written) == expected


@pytest.mark.parametrize(
    "written,expected",
    [
        ("  Rajesh   Patel ", "rajesh patel"),
        ("Mr. Rajesh Patel", "rajesh patel"),
        ("SMT. Nita Patel", "nita patel"),
        ("Rajesh-Patel", "rajesh patel"),
        (None, ""),
    ],
)
def test_name_reduces_to_what_is_comparable(written, expected):
    assert normalize_name(written) == expected


def test_email_is_compared_case_insensitively():
    assert normalize_email("  Rajesh@Example.COM ") == "rajesh@example.com"
