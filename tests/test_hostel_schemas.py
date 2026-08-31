"""Hostel payload validation (modules/hostel/hostel_schemas.py).

Pure ``data -> errors`` tests: no database, no app context.

Regression cover for the reported defect — the Create hostel form accepted any
string as Warden phone, so junk reached the database silently.
"""

from __future__ import annotations

import pytest

from modules.hostel.hostel_schemas import validate_hostel_payload

PHONE_MESSAGE = "Enter a valid 10-digit mobile number"


def _create(**overrides):
    payload = {"name": "Boys Hostel A"}
    payload.update(overrides)
    return payload


# ---- Warden phone: accepted formats --------------------------------------


@pytest.mark.parametrize(
    "phone",
    [
        "9876543210",
        "6012345678",
        "+919876543210",
        "+91 9876543210",
        "+91-9876543210",
    ],
)
def test_accepts_valid_indian_mobile_numbers(phone):
    assert validate_hostel_payload(_create(warden_phone=phone)) is None


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_warden_phone_stays_optional_when_not_filled(blank):
    """The field is optional — absent or blank must not raise an error."""
    assert validate_hostel_payload(_create(warden_phone=blank)) is None


def test_warden_phone_key_may_be_omitted_entirely():
    assert validate_hostel_payload({"name": "Boys Hostel A"}) is None


# ---- Warden phone: rejected formats --------------------------------------


@pytest.mark.parametrize(
    "phone",
    [
        "123",                # too short
        "abcdefghij",         # letters
        "+91 12345",          # country code, too short
        "999999999999999",    # too long
        "1234567890",         # 10 digits, but starts with 1
        "5876543210",         # 10 digits, but starts with 5
        "98765 43210",        # inner whitespace
        "+1 9876543210",      # wrong country code
        "9876543210x",        # trailing junk
    ],
)
def test_rejects_invalid_phone_numbers(phone):
    errors = validate_hostel_payload(_create(warden_phone=phone))
    assert errors == {"warden_phone": PHONE_MESSAGE}


# ---- Other hostel fields --------------------------------------------------


def test_name_is_required_on_create():
    errors = validate_hostel_payload({"name": ""})
    assert errors == {"name": "Hostel name is required"}


def test_over_long_values_are_rejected_before_reaching_the_database():
    errors = validate_hostel_payload(_create(warden_name="x" * 201))
    assert errors == {"warden_name": "Warden name must be 200 characters or fewer"}


def test_reports_every_bad_field_at_once():
    errors = validate_hostel_payload({"name": "", "warden_phone": "123"})
    assert errors == {
        "name": "Hostel name is required",
        "warden_phone": PHONE_MESSAGE,
    }


# ---- Update (PATCH) semantics --------------------------------------------


def test_update_does_not_require_fields_the_client_omitted():
    assert validate_hostel_payload({"address": "North Campus"}, is_update=True) is None


def test_update_still_validates_a_phone_the_client_did_send():
    errors = validate_hostel_payload({"warden_phone": "abcdefghij"}, is_update=True)
    assert errors == {"warden_phone": PHONE_MESSAGE}


def test_update_rejects_blanking_the_required_name():
    """`name` is NOT NULL — a sent-but-empty name must not blank the column."""
    errors = validate_hostel_payload({"name": ""}, is_update=True)
    assert errors == {"name": "Hostel name is required"}


def test_update_rejects_a_non_object_payload():
    assert validate_hostel_payload([], is_update=True) == {"_": "Invalid JSON payload."}
