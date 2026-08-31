"""
Hostel request validation, built from the central validators in
core.validation. Mirrors admin-web/src/components/hostel/HostelFormDialog.tsx.
"""

from __future__ import annotations

from typing import Any

from core import validation as v

# Max lengths match the Hostel columns in modules/hostel/models.py, so an
# over-long value is a 422 with a field message rather than a database error.
_HOSTEL_SPEC = {
    "name": [v.required("Hostel name"), v.max_length(200, "Hostel name")],
    "warden_name": [v.max_length(200, "Warden name")],
    "warden_phone": [v.phone("Warden phone")],
}


def validate_hostel_payload(data: Any, *, is_update: bool = False) -> dict[str, str] | None:
    """Return a ``{field: message}`` dict of validation errors, or None.

    ``capacity`` is checked by the caller: it must be a real JSON integer, which
    is a type rule rather than one of the string-format rules modelled here.

    On update the payload is partial, so a field is only checked when the client
    actually sends it — but a key that IS sent still gets the full rule list, so
    ``{"name": ""}`` is rejected rather than blanking a NOT NULL column.
    """
    spec = _HOSTEL_SPEC
    if is_update:
        if not isinstance(data, dict):
            return {"_": "Invalid JSON payload."}
        spec = {field: rules for field, rules in _HOSTEL_SPEC.items() if field in data}
    return v.run(data, spec)
