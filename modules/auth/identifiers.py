"""How an identifier is written down, and how it is compared.

An identifier is the string a human presents to say *which account they mean*
— an email address today, an admission number or a mobile number in a later
phase. It is not a secret and it may be publicly known; a credential is what
proves the account, and that lives elsewhere.

Two values are stored for every identifier, and the distinction is the whole
point of this module:

    identifier_value             what the person typed, kept for display
    identifier_value_normalized  what the database compares

A school's office reads the first and would not recognise the second. The
uniqueness index is built on the second, because "Ravi@School.in" and
"ravi@school.in " are one address and must not become two accounts.

Each type's rule arrives with the phase that starts issuing it, so that no rule
is guessed at before there are requirements for it. ``email`` came with the
identifier foundation, ``admission_id`` with student sign-in and ``mobile``
with OTP; ``employee_code`` waits for the phase that issues it.
"""

from __future__ import annotations

#: The identifier types the schema accepts. Kept beside the normalizers so a
#: type cannot be added to one without the other being noticed.
IDENTIFIER_TYPE_EMAIL = "email"
IDENTIFIER_TYPE_ADMISSION_ID = "admission_id"
IDENTIFIER_TYPE_MOBILE = "mobile"
IDENTIFIER_TYPE_EMPLOYEE_CODE = "employee_code"

IDENTIFIER_TYPES = (
    IDENTIFIER_TYPE_EMAIL,
    IDENTIFIER_TYPE_ADMISSION_ID,
    IDENTIFIER_TYPE_MOBILE,
    IDENTIFIER_TYPE_EMPLOYEE_CODE,
)


class UnknownIdentifierType(Exception):
    """No normalization rule has been written for this identifier type yet."""


class InvalidIdentifier(Exception):
    """The value cannot be a canonical identifier of that type."""


def normalize_email(value: str) -> str:
    """Trim, then lowercase.

    Deliberately nothing else. Stripping dots or ``+tag`` suffixes is a rule
    about one mail provider, not about email addresses, and applying it would
    silently merge two addresses a school considers different.
    """
    return (value or "").strip().lower()


def normalize_admission_id(value: str) -> str:
    """Trim, collapse internal whitespace, uppercase.

    Deliberately nothing else — and the restraint is the point. Admission
    numbers follow a tenant-configurable pattern (`shared/id_pattern.py`,
    default ``ADM{YEAR}{SEQ:3}``) and legitimately carry ``/``, ``-`` and
    leading zeros. Stripping punctuation would merge ``2026/001`` and
    ``2026-001`` into one identifier, and stripping leading zeros would merge
    ``001`` and ``1`` — two different children in both cases.

    Case and stray spaces are folded because a number read off a printed slip
    and typed by a nine-year-old is the same number whatever case it arrives
    in, and a trailing space is a typo rather than a distinction.
    """
    return " ".join((value or "").split()).upper()


#: The region a number with no country code is assumed to belong to.
#:
#: Hardcoded, and honestly so: there is no country or dial-code column on
#: `Tenant` to read one from, and every school on the platform today is in
#: India — the same statement `core/school_time.py` makes about the default
#: timezone, and made here for the same reason.
#:
#: It is a *default*, not a restriction. A number that arrives already in
#: international form (`+9715...`) is parsed as written and keeps its own
#: country, so this constant only decides what a bare ten-digit number means.
#: When a tenant one day has a country of its own, this is the one place to
#: read it from instead.
DEFAULT_MOBILE_REGION = "IN"


def normalize_mobile(value: str) -> str:
    """A phone number as E.164 — `+919876543210` — or empty if it is not one.

    E.164 rather than "the digits", because a comparison key that is only
    digits has to answer what `09876543210` and `919876543210` and
    `+919876543210` mean, and every answer to that is a guess. E.164 is the
    one representation where a number has exactly one spelling, so a person
    cannot become two accounts by typing their own number differently, and two
    people cannot become one because their numbers happen to end the same way.

    Deliberately **not** `modules/people/matching.py::normalize_phone`, which
    keeps the last ten digits. That rule is right for finding probable
    duplicate people — it is meant to be generous — and would be wrong here,
    where it would collapse a foreign number onto an Indian one that happens
    to share its final ten digits. A fuzzy match is a suggestion; an
    authentication identifier is a decision.

    Returns `""` for anything that is not a valid, dialable number, so a
    caller that stores the result cannot accidentally mint an identifier for
    "n/a", a landline, or a mistyped digit.
    """
    import phonenumbers

    raw = (value or "").strip()
    if not raw:
        return ""

    try:
        parsed = phonenumbers.parse(raw, DEFAULT_MOBILE_REGION)
    except phonenumbers.NumberParseException:
        return ""

    # `is_valid_number` is the strict check — it knows which prefixes a country
    # actually assigns, so it rejects a ten-digit number that is the right
    # length and no real subscriber.
    if not phonenumbers.is_valid_number(parsed):
        return ""

    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


#: type -> the function that produces its comparison key.
_NORMALIZERS = {
    IDENTIFIER_TYPE_EMAIL: normalize_email,
    IDENTIFIER_TYPE_ADMISSION_ID: normalize_admission_id,
    IDENTIFIER_TYPE_MOBILE: normalize_mobile,
}


def normalize_identifier(identifier_type: str, value: str) -> str:
    """The comparison key for this identifier.

    Raises :class:`UnknownIdentifierType` rather than falling back to some
    default, because a wrong normalization is worse than a missing one: it
    would let two different humans collide on one identifier, or split one
    human's identifier into two.
    """
    normalizer = _NORMALIZERS.get(identifier_type)
    if normalizer is None:
        raise UnknownIdentifierType(
            f"No normalization rule for identifier type {identifier_type!r}. "
            f"Known: {sorted(_NORMALIZERS)}."
        )
    return normalizer(value)
