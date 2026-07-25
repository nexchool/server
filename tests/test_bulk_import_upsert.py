"""Unit tests for bulk-import re-import (upsert) behaviour.

A school uploads a sheet, then uploads it again later with more columns filled
in. That second pass must enrich the students already on record rather than
erroring on every row or creating duplicates.

`_validate_and_coerce_row` takes the existing-student index as a plain dict and
`_apply_row_updates` works through getattr/setattr, so neither needs a DB or a
Flask app context.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def _class_map():
    return {
        ("10", "a"): [
            {
                "id": "class-10a",
                "programme_name": "CBSE English",
                "programme_code": "CBSE-EN",
                "board": "CBSE",
                "unit_name": "Main Campus",
                "unit_code": "MAIN",
            }
        ],
        ("9", "b"): [
            {
                "id": "class-9b",
                "programme_name": "CBSE English",
                "programme_code": "CBSE-EN",
                "board": "CBSE",
                "unit_name": "Main Campus",
                "unit_code": "MAIN",
            }
        ],
    }


def _index(*, students=(), non_student_emails=()):
    by_admission, by_email = {}, {}
    for entry in students:
        if entry.get("admission_number"):
            by_admission[entry["admission_number"].lower()] = entry
        if entry.get("email_lower"):
            by_email[entry["email_lower"]] = entry
    return {
        "by_admission": by_admission,
        "by_email": by_email,
        "non_student_emails": set(non_student_emails),
    }


def _existing(admission="ADM-001", email="riya@example.com", class_id="class-10a"):
    return {
        "student_id": "stu-1",
        "user_id": "usr-1",
        "admission_number": admission,
        "class_id": class_id,
        "email_lower": email.lower(),
    }


def _row(**overrides):
    row = {
        "name": "Riya Shah",
        "email": "riya@example.com",
        "branch": "Main Campus",
        "programme": "CBSE English",
        "class_name": "10",
        "section": "A",
    }
    row.update(overrides)
    return row


def _validate(row, index):
    from modules.students.bulk_student_import_service import _validate_and_coerce_row

    return _validate_and_coerce_row(
        row, 2, class_map=_class_map(), index=index, file_emails=set()
    )


def test_new_email_creates_a_student():
    ok, _display, errors, _warnings, coerced = _validate(
        _row(email="new@example.com"), _index()
    )
    assert ok, errors
    assert coerced["_action"] == "create"


def test_matching_email_updates_instead_of_erroring():
    ok, _display, errors, _warnings, coerced = _validate(
        _row(), _index(students=[_existing()])
    )
    assert ok, errors
    assert coerced["_action"] == "update"
    assert coerced["_match"]["student_id"] == "stu-1"


def test_admission_number_takes_precedence_over_email():
    """The sheet's admission number identifies the student even when the row
    carries no email match of its own."""
    ok, _display, errors, _warnings, coerced = _validate(
        _row(admission_number="ADM-001"),
        _index(students=[_existing()]),
    )
    assert ok, errors
    assert coerced["_action"] == "update"


def test_admission_number_with_a_conflicting_email_is_rejected():
    ok, _display, errors, _warnings, _coerced = _validate(
        _row(admission_number="ADM-001", email="someone.else@example.com"),
        _index(students=[_existing()]),
    )
    assert not ok
    assert any("different email" in e for e in errors)


def test_unknown_admission_number_warns_and_creates():
    ok, _display, errors, warnings, coerced = _validate(
        _row(admission_number="ADM-999", email="new@example.com"), _index()
    )
    assert ok, errors
    assert coerced["_action"] == "create"
    assert any("No student found with admission number" in w for w in warnings)


def test_email_belonging_to_a_non_student_account_is_rejected():
    """A teacher's address must not be hijacked into a student record."""
    ok, _display, errors, _warnings, _coerced = _validate(
        _row(email="teacher@example.com"),
        _index(non_student_emails={"teacher@example.com"}),
    )
    assert not ok
    assert any("already in use by another account" in e for e in errors)


def test_duplicate_email_within_the_same_file_is_rejected():
    from modules.students.bulk_student_import_service import _validate_and_coerce_row

    seen = set()
    args = dict(class_map=_class_map(), index=_index(), file_emails=seen)

    ok_first, _d, errs_first, _w, _c = _validate_and_coerce_row(_row(), 2, **args)
    assert ok_first, errs_first

    ok_second, _d, errs_second, _w, _c = _validate_and_coerce_row(_row(), 3, **args)
    assert not ok_second
    assert any("Duplicate email in file" in e for e in errs_second)


def test_a_different_class_warns_but_does_not_move_the_student():
    ok, _display, errors, warnings, coerced = _validate(
        _row(class_name="9", section="B"),
        _index(students=[_existing(class_id="class-10a")]),
    )
    assert ok, errors
    assert coerced["_action"] == "update"
    assert any("was not moved" in w for w in warnings)


# ---- _apply_row_updates ---------------------------------------------------


def _student(**attrs):
    base = {
        "admission_number": "ADM-001",
        "class_id": "class-10a",
        "academic_year_id": "ay-1",
        "phone": "9876543210",
        "blood_group": "O+",
        "father_name": "Existing Father",
        "is_transport_opted": True,
    }
    base.update(attrs)
    return SimpleNamespace(**base)


def _apply(student, coerced):
    from modules.students.bulk_student_import_service import _apply_row_updates

    return _apply_row_updates(student, coerced, academic_year_id="ay-1")


def test_populated_cells_are_written_to_the_existing_student():
    student = _student(blood_group=None)
    coerced = {"admission_number": "ADM-001", "class_id": "class-10a", "blood_group": "B+"}

    changed = _apply(student, coerced)

    assert "blood_group" in changed
    assert student.blood_group == "B+"


def test_blank_cells_never_clear_existing_values():
    """Schools upload partial sheets; an empty cell means "nothing to say",
    not "erase what is on record"."""
    student = _student()
    coerced = {
        "admission_number": "ADM-001",
        "class_id": "class-10a",
        "father_name": "",
        "phone": None,
    }

    changed = _apply(student, coerced)

    assert changed == []
    assert student.father_name == "Existing Father"
    assert student.phone == "9876543210"


def test_a_blank_boolean_cell_does_not_clear_the_flag():
    """is_transport_opted coerces a missing cell to False, which would silently
    switch transport off for every re-imported student."""
    student = _student(is_transport_opted=True)
    coerced = {"admission_number": "ADM-001", "class_id": "class-10a"}

    _apply(student, coerced)

    assert student.is_transport_opted is True


def test_identity_and_placement_fields_are_never_overwritten():
    student = _student()
    coerced = {
        "admission_number": "ADM-OTHER",
        "class_id": "class-9b",
        "blood_group": "AB+",
    }

    changed = _apply(student, coerced)

    assert "admission_number" not in changed
    assert "class_id" not in changed
    assert student.admission_number == "ADM-001"
    assert student.class_id == "class-10a"
