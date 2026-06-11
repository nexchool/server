"""Unit tests for bulk-import class disambiguation (multi-medium / multi-board).

A school running several programmes can have classes that share a display
name + section (e.g. GSEB English "10 A" and GSEB Gujarati "10 A"). The importer
must NOT silently pick one — it resolves only when unambiguous or when a
medium/programme hint singles out exactly one class. `_disambiguate_class` is a
pure function (candidate dicts + the raw row), so these need no DB or Flask.
"""
from __future__ import annotations

import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def _candidates():
    return [
        {"id": "c-eng", "programme_name": "GSEB English", "board": "GSEB"},
        {"id": "c-guj", "programme_name": "GSEB Gujarati", "board": "GSEB"},
    ]


def test_ambiguous_without_hint_is_rejected_not_guessed():
    """With two matching classes and no hint, the row is flagged with both
    options rather than silently assigned to an arbitrary one."""
    from modules.students.bulk_student_import_service import _disambiguate_class

    errors: list[str] = []
    result = _disambiguate_class("10 A", "A", _candidates(), {}, errors)
    assert result is None
    assert len(errors) == 1
    assert "matches 2 classes" in errors[0]
    assert "GSEB English" in errors[0] and "GSEB Gujarati" in errors[0]


def test_medium_hint_resolves_to_the_right_class():
    """A `medium` column narrows the candidates to exactly one (correctly)."""
    from modules.students.bulk_student_import_service import _disambiguate_class

    errors: list[str] = []
    assert (
        _disambiguate_class("10 A", "A", _candidates(), {"medium": "English"}, errors)
        == "c-eng"
    )
    assert (
        _disambiguate_class("10 A", "A", _candidates(), {"medium": "Gujarati"}, errors)
        == "c-guj"
    )
    assert errors == []


def test_programme_hint_resolves_by_full_name_case_insensitive():
    """A `programme` column matches the full programme name, case-insensitively."""
    from modules.students.bulk_student_import_service import _disambiguate_class

    errors: list[str] = []
    assert (
        _disambiguate_class(
            "10 A", "A", _candidates(), {"programme": "gseb gujarati"}, errors
        )
        == "c-guj"
    )
    assert errors == []


def test_hint_matching_none_is_rejected():
    """A hint that matches no candidate is an error, not a guess."""
    from modules.students.bulk_student_import_service import _disambiguate_class

    errors: list[str] = []
    result = _disambiguate_class("10 A", "A", _candidates(), {"medium": "Hindi"}, errors)
    assert result is None
    assert "did not match exactly one" in errors[0]


def test_hint_matching_every_candidate_stays_ambiguous():
    """A hint matching all candidates (e.g. the board they share) does not
    resolve — it must single out exactly one."""
    from modules.students.bulk_student_import_service import _disambiguate_class

    errors: list[str] = []
    result = _disambiguate_class("10 A", "A", _candidates(), {"board": "GSEB"}, errors)
    assert result is None
    assert len(errors) == 1
