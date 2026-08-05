"""Deciding whether two records describe the same human (ADR-010).

Only conclusive evidence merges: the same family role, a matching phone or
email, and a matching name. The family-role condition is the one that prevents
the damaging mistake — households routinely share a phone number, so without it
a father and a mother would be fused into a single person.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .models import MERGEABLE_FAMILY_ROLES

# Stripped before comparing names: they describe how someone is addressed, not
# who they are, and schools record them inconsistently.
HONORIFICS = frozenset(
    {
        "mr", "mrs", "ms", "miss", "master",
        "shri", "shree", "sri", "smt", "smt.",
        "dr", "prof", "late",
    }
)

_NON_NAME_CHARACTERS = re.compile(r"[^a-z\s]")
_WHITESPACE = re.compile(r"\s+")

# Indian subscriber numbers are ten digits; anything longer carries a country
# code or trunk prefix that the same person may or may not have been recorded
# with.
SUBSCRIBER_NUMBER_LENGTH = 10


def normalize_name(value: Optional[str]) -> str:
    """Reduce a written name to what is comparable about it."""
    if not value:
        return ""
    lowered = value.strip().lower()
    without_punctuation = _NON_NAME_CHARACTERS.sub(" ", lowered)
    words = [
        word
        for word in _WHITESPACE.split(without_punctuation)
        if word and word not in HONORIFICS
    ]
    return " ".join(words)


def normalize_phone(value: Optional[str]) -> str:
    """Reduce a phone number to its subscriber digits."""
    if not value:
        return ""
    digits = re.sub(r"\D", "", value)
    if len(digits) > SUBSCRIBER_NUMBER_LENGTH:
        return digits[-SUBSCRIBER_NUMBER_LENGTH:]
    return digits


def normalize_email(value: Optional[str]) -> str:
    if not value:
        return ""
    return value.strip().lower()


@dataclass(frozen=True)
class PersonMatchKey:
    """Two records sharing this key describe the same human.

    ``role`` is part of the key by design: it confines every comparison to
    father-with-father and mother-with-mother, so shared household contact
    details can never merge two different people.
    """

    role: str
    contact: str
    name: str


def build_match_key(
    role: str,
    name: Optional[str],
    phone: Optional[str] = None,
    email: Optional[str] = None,
) -> Optional[PersonMatchKey]:
    """Return the key to merge on, or None when the evidence is too weak.

    Returns None when the role is not one we compare, when the name is missing,
    or when there is neither a phone nor an email — a name on its own is never
    enough to declare two people the same.
    """
    if role not in MERGEABLE_FAMILY_ROLES:
        return None

    normalized_name = normalize_name(name)
    if not normalized_name:
        return None

    contact = normalize_phone(phone) or normalize_email(email)
    if not contact:
        return None

    return PersonMatchKey(role=role, contact=contact, name=normalized_name)
