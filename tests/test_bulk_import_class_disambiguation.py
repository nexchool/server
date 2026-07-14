"""Unit tests for bulk-import class resolution via required branch + programme.

A school running several branches/programmes can have classes that share a grade
label + section (e.g. Main Campus GSEB English "10 A" and Main Campus GSEB
Gujarati "10 A", or the same "10 A" in two branches). The importer resolves the
exact class from the required `branch` + `programme` columns, and must NOT
silently pick one. `_resolve_class_by_branch_programme` is a pure function
(candidate dicts + the branch/programme strings) returning
``(class_id, error_message)``, so these need no DB or Flask.
"""
from __future__ import annotations

import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def _two_programmes_one_branch():
    """Same grade+section+branch, two programmes (multi-medium school)."""
    return [
        {
            "id": "c-eng",
            "programme_name": "GSEB English",
            "programme_code": "GSEB-EN",
            "board": "GSEB",
            "unit_name": "Main Campus",
            "unit_code": "MAIN",
        },
        {
            "id": "c-guj",
            "programme_name": "GSEB Gujarati",
            "programme_code": "GSEB-GU",
            "board": "GSEB",
            "unit_name": "Main Campus",
            "unit_code": "MAIN",
        },
    ]


def _two_branches_one_programme():
    """Same grade+section+programme, two branches (multi-campus school)."""
    return [
        {
            "id": "c-main",
            "programme_name": "CBSE English",
            "programme_code": "CBSE-EN",
            "board": "CBSE",
            "unit_name": "Main Campus",
            "unit_code": "MAIN",
        },
        {
            "id": "c-north",
            "programme_name": "CBSE English",
            "programme_code": "CBSE-EN",
            "board": "CBSE",
            "unit_name": "North Branch",
            "unit_code": "NORTH",
        },
    ]


def test_branch_and_programme_resolve_to_the_right_class():
    from modules.students.bulk_student_import_service import (
        _resolve_class_by_branch_programme,
    )

    cands = _two_programmes_one_branch()
    assert _resolve_class_by_branch_programme(
        "10", "A", "Main Campus", "GSEB English", cands
    ) == ("c-eng", None)
    assert _resolve_class_by_branch_programme(
        "10", "A", "Main Campus", "GSEB Gujarati", cands
    ) == ("c-guj", None)


def test_case_insensitive_branch_and_programme():
    from modules.students.bulk_student_import_service import (
        _resolve_class_by_branch_programme,
    )

    assert _resolve_class_by_branch_programme(
        "10", "A", "main campus", "gseb gujarati", _two_programmes_one_branch()
    ) == ("c-guj", None)


def test_programme_matches_by_code_or_board():
    from modules.students.bulk_student_import_service import (
        _resolve_class_by_branch_programme,
    )

    # programme column may carry the programme code instead of the display name
    assert _resolve_class_by_branch_programme(
        "10", "A", "MAIN", "GSEB-GU", _two_programmes_one_branch()
    ) == ("c-guj", None)


def test_branch_narrows_two_campuses():
    from modules.students.bulk_student_import_service import (
        _resolve_class_by_branch_programme,
    )

    assert _resolve_class_by_branch_programme(
        "10", "A", "North Branch", "CBSE English", _two_branches_one_programme()
    ) == ("c-north", None)


def test_wrong_branch_is_rejected_with_options():
    from modules.students.bulk_student_import_service import (
        _resolve_class_by_branch_programme,
    )

    class_id, err = _resolve_class_by_branch_programme(
        "10", "A", "Ghost Campus", "GSEB English", _two_programmes_one_branch()
    )
    assert class_id is None
    assert err and "Main Campus" in err  # lists the real branch option


def test_wrong_programme_is_rejected_with_options():
    from modules.students.bulk_student_import_service import (
        _resolve_class_by_branch_programme,
    )

    class_id, err = _resolve_class_by_branch_programme(
        "10", "A", "Main Campus", "ICSE", _two_programmes_one_branch()
    )
    assert class_id is None
    assert err and "GSEB English" in err and "GSEB Gujarati" in err


def test_shared_board_stays_ambiguous():
    """Using the shared board (matches both programmes) does not single one out."""
    from modules.students.bulk_student_import_service import (
        _resolve_class_by_branch_programme,
    )

    class_id, err = _resolve_class_by_branch_programme(
        "10", "A", "Main Campus", "GSEB", _two_programmes_one_branch()
    )
    assert class_id is None
    assert err and "matched 2 classes" in err


def test_blank_branch_or_programme_returns_no_error():
    """Blank branch/programme are flagged as "Missing" by the caller, so the
    resolver returns (None, None) and adds no duplicate error."""
    from modules.students.bulk_student_import_service import (
        _resolve_class_by_branch_programme,
    )

    cands = _two_programmes_one_branch()
    assert _resolve_class_by_branch_programme("10", "A", "", "GSEB English", cands) == (
        None,
        None,
    )
    assert _resolve_class_by_branch_programme(
        "10", "A", "Main Campus", None, cands
    ) == (None, None)
