"""
Class request validation, built from the central validators in core.validation.
Mirrors admin-web/src/components/classes/ClassFormModal.tsx.

Required-field logic (section, academic_year_id, and the name/grade_level
interplay) stays in the route; this covers formats, ranges and lengths.
"""

from __future__ import annotations

from core import validation as v

_CLASS_SPEC = {
    "name": [v.max_length(120, "Name")],
    "section": [v.max_length(40, "Section")],
    "grade_level": [v.integer(min_value=0, max_value=20, label="Grade level")],
    "start_date": [v.is_date("Start date")],
    "end_date": [v.is_date("End date")],
    "stream": [v.max_length(60, "Stream")],
}


def validate_class_payload(data: dict, *, is_update: bool = False) -> dict[str, str] | None:
    """Return a ``{field: message}`` dict of validation errors, or None."""
    return v.run(data, _CLASS_SPEC)
