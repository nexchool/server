"""Importing a paper's register from a workbook.

Every test builds a real .xlsx in memory and puts it through the same two calls
a screen would: preview, then import. Nothing here mocks the parser — a sheet
that a school would actually upload is the thing under test.
"""

from __future__ import annotations

import uuid
from datetime import date
from io import BytesIO

import pytest
from openpyxl import Workbook

from modules.examinations import marks_import, marks_service, services as exam_services
from modules.examinations.models import (
    MARK_ABSENT,
    MARK_EXEMPTED,
    MARK_PRESENT,
    ExamMark,
)

from tests.test_examination_marks import (  # noqa: F401
    _enroll,
    _new_id,
    _student,
    _teacher_of_maths,
    anyone_may,
    ctx,
    cycles,
    exam_type,
    marking,
    only_teachers_may,
    school,
    year,
)


def _sheet(rows, *, headers=("admission_number", "marks", "status")):
    """A workbook the way a school hands it over."""
    book = Workbook()
    sheet = book.active
    sheet.append(list(headers))
    for row in rows:
        sheet.append(list(row))
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _import(tenant, school, marking, file_bytes, **kwargs):
    return marks_import.import_marks(
        tenant.id, marking["paper"].id, file_bytes,
        actor_user_id=kwargs.pop("actor_user_id", _teacher_of_maths(school)),
        commit=False, **kwargs,
    )


def _preview(tenant, school, marking, file_bytes, **kwargs):
    return marks_import.preview_marks(
        tenant.id, marking["paper"].id, file_bytes,
        actor_user_id=kwargs.pop("actor_user_id", _teacher_of_maths(school)),
        **kwargs,
    )


def _marks(tenant, marking):
    return marks_service.marks_for_paper(marking["paper"].id, tenant.id)


# ---------------------------------------------------------------------------
# Preview writes nothing
# ---------------------------------------------------------------------------

def test_a_valid_preview_writes_nothing(
    ctx, tenant, school, marking, only_teachers_may
):
    result = _preview(tenant, school, marking, _sheet([
        (school["riya"].admission_number, 88, "present"),
        (school["dev"].admission_number, None, "absent"),
    ]))
    assert result["success"] is True, result
    assert result["summary"] == {"valid": 2, "invalid": 0, "total": 2}
    assert all(row["valid"] for row in result["preview"])
    assert _marks(tenant, marking) == []


def test_an_invalid_preview_writes_nothing_and_reports_every_row(
    ctx, tenant, school, marking, only_teachers_may
):
    """A teacher fixing a sheet needs the whole list, not the first problem."""
    result = _preview(tenant, school, marking, _sheet([
        (school["riya"].admission_number, 88, "present"),
        ("NOSUCH", 40, "present"),
        (school["dev"].admission_number, 5000, "present"),
    ]))
    assert result["success"] is True
    assert result["summary"] == {"valid": 1, "invalid": 2, "total": 3}

    errors = [row["errors"] for row in result["preview"]]
    assert errors[0] == []
    assert any("STUDENT_NOT_ELIGIBLE" in e for e in errors[1])
    assert any("MARKS_ABOVE_MAX" in e for e in errors[2])
    assert _marks(tenant, marking) == []


def test_preview_reports_the_excel_row_number(
    ctx, tenant, school, marking, only_teachers_may
):
    """Row 1 is the header, so the first data row is 2 — the number the person
    holding the spreadsheet can see."""
    result = _preview(tenant, school, marking, _sheet([
        (school["riya"].admission_number, 88, "present"),
        ("NOSUCH", 40, "present"),
    ]))
    assert [row["row_number"] for row in result["preview"]] == [2, 3]


# ---------------------------------------------------------------------------
# Import is all or nothing
# ---------------------------------------------------------------------------

def test_a_valid_sheet_imports_every_row(
    ctx, tenant, school, marking, only_teachers_may
):
    result = _import(tenant, school, marking, _sheet([
        (school["riya"].admission_number, 88, "present"),
        (school["dev"].admission_number, None, "absent"),
        (school["meera"].admission_number, 0, "present"),
    ]))
    assert result["success"] is True, result
    assert result["imported"] == 3

    written = {m.student_id: m for m in _marks(tenant, marking)}
    assert len(written) == 3
    assert float(written[school["riya"].id].marks_obtained) == 88.0
    assert written[school["dev"].id].status == MARK_ABSENT
    assert written[school["dev"].id].marks_obtained is None
    # Zero is a mark, and stays one.
    assert float(written[school["meera"].id].marks_obtained) == 0.0
    assert written[school["meera"].id].status == MARK_PRESENT


def test_one_bad_row_writes_nothing(
    ctx, tenant, school, marking, only_teachers_may
):
    """Rows 1, 2 and 4 are fine; row 3 is not. A register is one thing."""
    result = _import(tenant, school, marking, _sheet([
        (school["riya"].admission_number, 88, "present"),
        (school["dev"].admission_number, 64, "present"),
        ("NOSUCH", 40, "present"),
        (school["meera"].admission_number, 71, "present"),
    ]))
    assert result["success"] is False
    assert result["code"] == "ROWS_INVALID"
    assert result["summary"] == {"valid": 3, "invalid": 1, "total": 4}
    assert _marks(tenant, marking) == []


def test_a_status_column_may_be_left_out(
    ctx, tenant, school, marking, only_teachers_may
):
    """The canonical default is `present` — the one `record_marks` already
    applies, not a second convention invented here."""
    result = _import(
        tenant, school, marking,
        _sheet(
            [(school["riya"].admission_number, 88)],
            headers=("admission_number", "marks"),
        ),
    )
    assert result["success"] is True, result
    assert _marks(tenant, marking)[0].status == MARK_PRESENT


def test_a_sheet_without_admission_numbers_is_refused(
    ctx, tenant, school, marking, only_teachers_may
):
    result = _import(
        tenant, school, marking,
        _sheet([(88,)], headers=("marks",)),
    )
    assert result["success"] is False
    assert result["code"] == "COLUMNS_MISSING"


def test_an_empty_sheet_is_refused(ctx, tenant, school, marking, only_teachers_may):
    result = _import(tenant, school, marking, _sheet([]))
    assert result["success"] is False
    assert result["code"] == "NO_ROWS"


def test_a_file_that_is_not_a_workbook_is_refused(
    ctx, tenant, school, marking, only_teachers_may
):
    result = _import(tenant, school, marking, b"admission_number,marks\n123,88\n")
    assert result["success"] is False
    assert result["code"] == "FILE_UNREADABLE"


# ---------------------------------------------------------------------------
# Identity and cohort
# ---------------------------------------------------------------------------

def test_an_unknown_admission_number_is_refused(
    ctx, tenant, school, marking, only_teachers_may
):
    result = _import(tenant, school, marking, _sheet([("GHOST-1", 40, "present")]))
    assert result["success"] is False
    assert any(
        "STUDENT_NOT_ELIGIBLE" in e for e in result["preview"][0]["errors"]
    )


def test_a_student_from_another_class_is_refused(
    ctx, tenant, school, marking, only_teachers_may
):
    """A real admission number belonging to another section must not be
    markable into this register by typing it into the sheet."""
    result = _import(
        tenant, school, marking,
        _sheet([(school["outsider"].admission_number, 40, "present")]),
    )
    assert result["success"] is False
    assert any(
        "STUDENT_NOT_ELIGIBLE" in e for e in result["preview"][0]["errors"]
    )
    assert _marks(tenant, marking) == []


def test_the_same_admission_number_twice_is_refused(
    ctx, tenant, school, marking, only_teachers_may
):
    number = school["riya"].admission_number
    result = _import(tenant, school, marking, _sheet([
        (number, 88, "present"),
        (number, 44, "present"),
    ]))
    assert result["success"] is False
    assert any("STUDENT_REPEATED" in e for e in result["preview"][1]["errors"])
    assert _marks(tenant, marking) == []


def test_the_relationship_persisted_is_the_student_id(
    ctx, tenant, school, marking, only_teachers_may
):
    """The admission number is a lookup key and nothing more."""
    _import(tenant, school, marking,
            _sheet([(school["riya"].admission_number, 88, "present")]))
    written = _marks(tenant, marking)[0]
    assert written.student_id == school["riya"].id


# ---------------------------------------------------------------------------
# Import creates; it never overwrites
# ---------------------------------------------------------------------------

def test_a_student_who_already_has_a_mark_is_refused(
    ctx, tenant, school, marking, only_teachers_may
):
    """Changing an existing mark has somebody's name attached — an importer
    that overwrote would be a way to move marks with no record of who did."""
    marks_service.record_mark(
        tenant_id=tenant.id, exam_paper_id=marking["paper"].id,
        student_id=school["riya"].id, status=MARK_PRESENT, marks_obtained=61,
        actor_user_id=_teacher_of_maths(school), commit=False,
    )

    result = _import(tenant, school, marking, _sheet([
        (school["riya"].admission_number, 88, "present"),
        (school["dev"].admission_number, 70, "present"),
    ]))
    assert result["success"] is False
    assert any("ALREADY_MARKED" in e for e in result["preview"][0]["errors"])

    # And the good row did not land either — one register, one outcome.
    remaining = _marks(tenant, marking)
    assert len(remaining) == 1
    assert float(remaining[0].marks_obtained) == 61.0


# ---------------------------------------------------------------------------
# The gates ordinary entry applies
# ---------------------------------------------------------------------------

def test_a_locked_paper_cannot_be_imported_into(
    ctx, tenant, school, marking, only_teachers_may
):
    """Import is not a way around the lock. A closed register changes by
    correction."""
    marks_service.lock_paper(
        marking["paper"].id, tenant.id,
        actor_user_id=school["head"]["user"].id, commit=False,
    )
    result = _import(tenant, school, marking,
                     _sheet([(school["riya"].admission_number, 88, "present")]))
    assert result["success"] is False
    assert result["code"] == "PAPER_LOCKED"
    assert _marks(tenant, marking) == []


def test_import_is_not_an_authority_bypass(
    ctx, tenant, school, marking, only_teachers_may
):
    """The Science teacher may not import into the Maths register."""
    result = _import(
        tenant, school, marking,
        _sheet([(school["riya"].admission_number, 88, "present")]),
        actor_user_id=school["science_teacher"]["user"].id,
    )
    assert result["success"] is False
    assert result["code"] == "NOT_THE_MARKER"
    assert _marks(tenant, marking) == []


def test_import_needs_the_enter_permission(
    ctx, monkeypatch, tenant, school, marking
):
    import modules.rbac.services as rbac

    monkeypatch.setattr(rbac, "has_permission", lambda user_id, name: False)
    result = _import(tenant, school, marking,
                     _sheet([(school["riya"].admission_number, 88, "present")]))
    assert result["success"] is False
    assert result["code"] == "FORBIDDEN"


def test_preview_is_gated_too(ctx, tenant, school, marking, only_teachers_may):
    """Otherwise the preview is a way to read a register you may not mark."""
    result = _preview(
        tenant, school, marking,
        _sheet([(school["riya"].admission_number, 88, "present")]),
        actor_user_id=school["science_teacher"]["user"].id,
    )
    assert result["success"] is False
    assert result["code"] == "NOT_THE_MARKER"


def test_another_schools_paper_cannot_be_imported_into(
    ctx, db_session, tenant, school, marking, only_teachers_may
):
    from core.models import BILLING_CYCLE_YEARLY, TENANT_STATUS_ACTIVE, Tenant

    other = Tenant(
        id=_new_id("t-"), name="Other", subdomain=f"o-{uuid.uuid4().hex}",
        status=TENANT_STATUS_ACTIVE, billing_cycle=BILLING_CYCLE_YEARLY,
    )
    db_session.add(other)
    db_session.flush()

    result = marks_import.import_marks(
        other.id, marking["paper"].id,
        _sheet([(school["riya"].admission_number, 88, "present")]),
        actor_user_id=_teacher_of_maths(school), commit=False,
    )
    assert result["success"] is False
    assert result["code"] == "PAPER_NOT_FOUND"
    assert _marks(tenant, marking) == []


# ---------------------------------------------------------------------------
# The same rulebook as manual entry
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "marks,status,code",
    [
        ("nan", "present", "MARKS_INVALID"),
        ("NaN", "present", "MARKS_INVALID"),
        ("inf", "present", "MARKS_INVALID"),
        ("-inf", "present", "MARKS_INVALID"),
        (-1, "present", "MARKS_INVALID"),
        (101, "present", "MARKS_ABOVE_MAX"),
        (None, "present", "MARKS_REQUIRED"),
        (40, "absent", "MARKS_NOT_ALLOWED"),
        (40, "maybe", "STATUS_INVALID"),
    ],
    ids=["nan", "NaN", "inf", "-inf", "negative", "above-max", "no-mark",
         "absent-with-mark", "bad-status"],
)
def test_a_row_obeys_exactly_the_manual_entry_rules(
    ctx, tenant, school, marking, only_teachers_may, marks, status, code
):
    result = _import(
        tenant, school, marking,
        _sheet([(school["riya"].admission_number, marks, status)]),
    )
    assert result["success"] is False, f"{marks!r}/{status} was accepted"
    assert any(code in e for e in result["preview"][0]["errors"])
    assert _marks(tenant, marking) == []


def test_an_exempted_row_imports_without_a_mark(
    ctx, tenant, school, marking, only_teachers_may
):
    result = _import(
        tenant, school, marking,
        _sheet([(school["riya"].admission_number, None, MARK_EXEMPTED)]),
    )
    assert result["success"] is True, result
    written = _marks(tenant, marking)[0]
    assert written.status == MARK_EXEMPTED
    assert written.marks_obtained is None


def test_a_mark_arriving_as_text_is_stored_as_a_number(
    ctx, tenant, school, marking, only_teachers_may
):
    result = _import(
        tenant, school, marking,
        _sheet([(school["riya"].admission_number, "88", "present")]),
    )
    assert result["success"] is True, result
    assert float(_marks(tenant, marking)[0].marks_obtained) == 88.0


# ---------------------------------------------------------------------------
# EX-02A.1 boundaries hold
# ---------------------------------------------------------------------------

def test_importing_does_not_reopen_the_configuration(
    ctx, tenant, school, marking, exam_type, only_teachers_may
):
    """Marks are marks however they arrived: the first imported one freezes the
    examination's meaning exactly as a typed one does."""
    assert _import(
        tenant, school, marking,
        _sheet([(school["riya"].admission_number, 88, "present")]),
    )["success"] is True

    result = exam_services.update_examination(
        marking["examination"].id, tenant.id,
        {"exam_type_id": exam_type.id}, commit=False,
    )
    # Same type resent is a no-op; a different one is refused.
    assert result["success"] is True

    from modules.examinations.models import ExamType

    other_type = ExamType(
        id=_new_id("et-"), tenant_id=tenant.id,
        name=f"Board-{uuid.uuid4().hex[:5]}", sequence=5,
    )
    from core.database import db

    db.session.add(other_type)
    db.session.flush()

    refused = exam_services.update_examination(
        marking["examination"].id, tenant.id,
        {"exam_type_id": other_type.id}, commit=False,
    )
    assert refused["success"] is False
    assert refused["code"] == "EXAM_TYPE_IMMUTABLE"


def test_a_batch_students_additional_enrollment_is_importable(
    ctx, db_session, tenant, cycles, exam_type, school, only_teachers_may
):
    """The cohort an import resolves against is the same one marking uses, so
    an `additional` enrollment counts (EX-02A)."""
    created = exam_services.create_examination(
        tenant_id=tenant.id, academic_cycle_id=cycles["batch"].id,
        exam_type_id=exam_type.id, name=f"JEE Mock-{uuid.uuid4().hex[:5]}",
        papers=[{"class_subject_id": school["jee_physics"].id,
                 "max_marks": 300, "exam_date": date(2026, 5, 20)}],
        commit=False,
    )
    assert created["success"] is True, created
    examination = created["examination"]
    exam_services.schedule_examination(examination.id, tenant.id, commit=False)
    exam_services.open_marks_entry(examination.id, tenant.id, commit=False)
    paper = exam_services.papers_for(examination.id, tenant.id)[0]

    result = marks_import.import_marks(
        tenant.id, paper.id,
        _sheet([(school["meera"].admission_number, 250, "present")]),
        actor_user_id=school["head"]["user"].id, commit=False,
    )
    assert result["success"] is True, result
    assert ExamMark.query.filter_by(exam_paper_id=paper.id).count() == 1
