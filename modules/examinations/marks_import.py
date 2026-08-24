"""Importing a paper's register from a workbook.

Two calls, the split the student importer already established: `preview_marks`
validates and writes nothing, `import_marks` validates again and writes
everything or nothing.

**One register, one outcome.** This is where it deliberately parts company with
the student importer, which commits per row on purpose — five hundred students
are five hundred independent facts, and landing 497 of them is a good day. A
paper's marks are one register: landing 38 of 40 leaves a teacher unable to
tell which two are missing, and re-uploading the sheet ambiguous. So a single
bad row writes nothing.

**Import creates; it never overwrites.** A row for a student who already has a
mark is refused as `ALREADY_MARKED`. Changing a mark that exists is an update
while the paper is open, and a correction once it is closed — both of which
have somebody's name attached. An importer that silently overwrote would be a
way to move marks with no record of who moved them, which is the thing the
whole locking design exists to prevent.

**No second rulebook.** Every row goes through `_validate_outcome`, the same
function ordinary entry uses, and the write goes through `record_marks`, so
authority (ADR-014), the lock, status semantics, NaN and max_marks are all
enforced once. This module resolves admission numbers and shapes errors; it
decides nothing about what a valid mark is.

The parsing itself is `students/utils/excel_parser.py`, unchanged — the same
`.xlsx`, headers on row 1, normalised to snake_case keys.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

from core.database import db
from modules.students.models import Student
from modules.students.utils.excel_parser import parse_xlsx_to_rows

from .marks_service import (
    _currently_enrolled_ids,
    _paper_of,
    _validate_outcome,
    marker_authority,
    record_marks,
)
from .models import MARK_PRESENT, ExamMark
from .services import _ok, _refuse

# The canonical sheet. Three columns, one of them optional — anything wider is
# ignored rather than refused, because schools export registers with their own
# extra columns and rejecting the file over a "Remarks" heading helps nobody.
COLUMN_ADMISSION_NUMBER = "admission_number"
COLUMN_MARKS = "marks"
COLUMN_STATUS = "status"

REQUIRED_COLUMNS = (COLUMN_ADMISSION_NUMBER,)


def _cohort_index(paper) -> Dict[str, str]:
    """`admission_number → student_id`, for this paper's eligible cohort only.

    Scoped to the cohort rather than the tenant, so a valid admission number
    belonging to another section cannot be marked into this register by typing
    it into the sheet. One query for the whole file.
    """
    student_ids = _currently_enrolled_ids(paper)
    if not student_ids:
        return {}
    rows = (
        db.session.query(Student.admission_number, Student.id)
        .filter(
            Student.tenant_id == paper.tenant_id,
            Student.id.in_(student_ids),
        )
        .all()
    )
    return {str(number).strip(): student_id for number, student_id in rows if number}


def _already_marked_ids(paper) -> set:
    return {
        row[0]
        for row in db.session.query(ExamMark.student_id)
        .filter(
            ExamMark.tenant_id == paper.tenant_id,
            ExamMark.exam_paper_id == paper.id,
            ExamMark.deleted_at.is_(None),
        )
        .all()
    }


def _validate_rows(
    paper, rows: List[Dict[str, Any]], row_numbers: List[int]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Check every row. Returns (preview rows, rows fit to write).

    Every row is checked even after one has failed — a teacher fixing a sheet
    needs the whole list, not the first problem in it.
    """
    index = _cohort_index(paper)
    marked = _already_marked_ids(paper)
    seen: Dict[str, int] = {}

    preview: List[Dict[str, Any]] = []
    writable: List[Dict[str, Any]] = []

    for position, row in enumerate(rows):
        row_number = row_numbers[position] if position < len(row_numbers) else position + 2
        errors: List[str] = []
        warnings: List[str] = []

        raw_number = row.get(COLUMN_ADMISSION_NUMBER)
        admission_number = str(raw_number).strip() if raw_number is not None else ""
        raw_status = row.get(COLUMN_STATUS)
        # The canonical default, taken from `record_marks` rather than invented
        # here: a row with no status is a student who sat the paper.
        status = str(raw_status).strip() if raw_status else MARK_PRESENT
        marks = row.get(COLUMN_MARKS)

        student_id: Optional[str] = None
        if not admission_number:
            errors.append("ADMISSION_NUMBER_REQUIRED: admission number is missing")
        elif admission_number not in index:
            # One code for both cases on purpose: from the sheet's point of
            # view "no such student here" is the fact, and saying which of the
            # two it is would confirm whether an admission number exists in
            # another section to whoever can upload a file.
            errors.append(
                "STUDENT_NOT_ELIGIBLE: no student with this admission number is "
                "in the class this paper is set for"
            )
        else:
            student_id = index[admission_number]
            if admission_number in seen:
                errors.append(
                    f"STUDENT_REPEATED: also on row {seen[admission_number]}"
                )
            else:
                seen[admission_number] = row_number
            if student_id in marked:
                errors.append(
                    "ALREADY_MARKED: this student already has a mark for this "
                    "paper — change it directly, or raise a correction if the "
                    "paper is closed"
                )

        refusal, value = _validate_outcome(status, marks, paper, who="This row")
        if refusal:
            errors.append(f"{refusal['code']}: {refusal['error']}")

        valid = not errors
        preview.append(
            {
                "row_number": row_number,
                "values": {
                    COLUMN_ADMISSION_NUMBER: admission_number or None,
                    COLUMN_STATUS: status,
                    COLUMN_MARKS: marks,
                },
                "errors": errors,
                "warnings": warnings,
                "valid": valid,
            }
        )
        if valid and student_id:
            writable.append(
                {
                    "student_id": student_id,
                    "status": status,
                    "marks_obtained": value,
                }
            )

    return preview, writable


def _read(paper_id: str, tenant_id: str, actor_user_id: str, file_bytes: bytes):
    """Everything both calls need: the paper, its guards, and the parsed rows."""
    paper, examination, refusal = _paper_of(paper_id, tenant_id)
    if refusal:
        return None, refusal

    # The same two gates ordinary entry applies, checked here so a locked paper
    # is refused before a file is parsed rather than after.
    from .marks_service import _paper_open_for_marking

    refusal = _paper_open_for_marking(paper, examination)
    if refusal:
        return None, refusal

    refusal = marker_authority(paper, actor_user_id)
    if refusal:
        return None, refusal

    try:
        header_keys, rows, row_numbers = parse_xlsx_to_rows(file_bytes)
    except ValueError as err:
        return None, _refuse("FILE_UNREADABLE", str(err))

    missing = [c for c in REQUIRED_COLUMNS if c not in header_keys]
    if missing:
        return None, _refuse(
            "COLUMNS_MISSING",
            f"The sheet needs a column for {', '.join(missing)}",
        )
    if not rows:
        return None, _refuse("NO_ROWS", "The sheet has no rows to import")

    return (paper, rows, row_numbers), None


def preview_marks(
    tenant_id: str, exam_paper_id: str, file_bytes: bytes, *, actor_user_id: str
) -> Dict[str, Any]:
    """Check a sheet and report on it. **Writes nothing.**"""
    loaded, refusal = _read(exam_paper_id, tenant_id, actor_user_id, file_bytes)
    if refusal:
        return refusal
    paper, rows, row_numbers = loaded

    preview, writable = _validate_rows(paper, rows, row_numbers)
    invalid = len(preview) - len(writable)
    return _ok(
        preview=preview,
        summary={
            "valid": len(writable),
            "invalid": invalid,
            "total": len(preview),
        },
    )


def import_marks(
    tenant_id: str, exam_paper_id: str, file_bytes: bytes, *, actor_user_id: str,
    commit: bool = True,
) -> Dict[str, Any]:
    """Write a sheet's marks — all of them, or none of them."""
    loaded, refusal = _read(exam_paper_id, tenant_id, actor_user_id, file_bytes)
    if refusal:
        return refusal
    paper, rows, row_numbers = loaded

    preview, writable = _validate_rows(paper, rows, row_numbers)
    invalid = len(preview) - len(writable)
    if invalid:
        # Deliberately nothing written, and the whole list returned: a register
        # is one thing, and a teacher fixing a sheet needs every problem in it.
        return {
            "success": False,
            "code": "ROWS_INVALID",
            "error": (
                f"{invalid} of {len(preview)} rows could not be imported, so "
                "none were. Fix them and upload the sheet again."
            ),
            "preview": preview,
            "summary": {
                "valid": len(writable),
                "invalid": invalid,
                "total": len(preview),
            },
        }

    # One call, so the write obeys exactly the rules manual entry does — and
    # `record_marks` is already all-or-nothing inside its own savepoint.
    result = record_marks(
        tenant_id=tenant_id,
        exam_paper_id=paper.id,
        rows=writable,
        actor_user_id=actor_user_id,
        commit=commit,
    )
    if not result["success"]:
        return result
    return _ok(
        imported=result["created"],
        summary={"valid": len(writable), "invalid": 0, "total": len(preview)},
    )


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------


def marks_template(
    tenant_id: str, exam_paper_id: str, *, actor_user_id: str
) -> Dict[str, Any]:
    """A workbook pre-filled with this paper's register, for a teacher to fill in.

    Pre-filled because the alternative is a teacher copying forty admission
    numbers by hand, and a mistyped one is a row the import refuses for a
    reason that reads like the student does not exist.

    **The template is not authoritative.** It carries no marks, creates
    nothing, and every value that comes back is validated by preview and
    import exactly as if it had been typed. A stale template is simply a sheet
    whose rows no longer match, which the same validation catches.

    Answers to the same authority as the import itself — a workbook listing a
    class's children is not something to hand to anyone who asks.
    """
    from openpyxl import Workbook

    from .marks_service import marking_register

    paper, examination, refusal = _paper_of(exam_paper_id, tenant_id)
    if refusal:
        return refusal
    refusal = marker_authority(paper, actor_user_id)
    if refusal:
        return refusal

    register = marking_register(exam_paper_id, tenant_id)
    if register is None:
        return _refuse("PAPER_NOT_FOUND", "Exam paper not found")

    book = Workbook()
    sheet = book.active
    sheet.title = "Marks"
    sheet.append([COLUMN_ADMISSION_NUMBER, COLUMN_MARKS, COLUMN_STATUS])
    for row in register["students"]:
        # Admission number only. A name column would be read back and ignored,
        # and a marks column pre-filled from existing marks would invite a
        # teacher to re-upload them — which the importer refuses as
        # ALREADY_MARKED.
        sheet.append([row["admission_number"], None, None])

    buffer = BytesIO()
    book.save(buffer)
    return _ok(
        filename=f"marks-{paper.id}.xlsx",
        content=buffer.getvalue(),
        students=len(register["students"]),
    )
