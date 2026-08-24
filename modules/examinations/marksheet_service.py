"""The marksheet a school hands a parent.

**A marksheet, not a report card**, and the name is the decision. Audit §22-D7
left the artefact's scope to the product with a recommendation: *"Build (a)
per-examination first but **name it a marksheet**; calling it a report card is
what causes rework."* This is (a). An annual document aggregating terms is a
different artefact that would *read* results rather than replace them, and
nothing here forecloses it (debt 49).

**Rendered from a frozen version, never from live data.** `ExamResult.snapshot`
already holds everything the document needs — the per-paper breakdown, the
totals, the resolved grading band with its bounds — captured when the result
was computed (ADR-018/ADR-020). So a marksheet is reproducible from the row
alone, and republishing produces a v2 document while v1 stays retrievable and
unchanged **by construction**: they are different rows, and neither is ever
edited.

That is why this stores no file. The audit's EX-09 sketch said "stored as
`exam_documents`", which ADR-018 had already rejected — migration 106
consolidated document storage and its docstring names this exact temptation.
A stored PDF would be a second copy of facts that are already immutable, with
its own staleness question; regenerating from the snapshot cannot drift.

**Official, never current.** The version rendered is the latest *published*
one. A revision that has been calculated but not issued is deliberately not
what a parent receives — that is the whole distinction EX-08 draws between
`official_result` and `current_result`, and rendering `is_current` would hand
somebody a figure nobody has told them.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .models import ExamResult
from .services import _ok, _refuse

# Reading a result is what a marksheet is; it needs no separate key, and
# inventing one would let somebody hold "may print" without "may see".
PERM_READ = "examination.read"


def marksheet_model(
    examination_id: str,
    student_id: str,
    tenant_id: str,
    *,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """Everything the document renders, resolved once and frozen.

    Returns a refusal, or `{"success": True, "marksheet": {...}}` whose payload
    is plain data — no ORM rows — so the renderer cannot reach back into the
    database for a value that has moved since.

    `version` names a specific published version for a reprint; omitted, the
    latest published one is used. An unpublished version is never rendered,
    whichever way it is asked for.
    """
    from modules.people.models import Person
    from modules.students.models import Student

    from .services import _get

    examination = _get(examination_id, tenant_id)
    if examination is None:
        return _refuse("NOT_FOUND", "Examination not found")

    query = ExamResult.query.filter(
        ExamResult.tenant_id == tenant_id,
        ExamResult.examination_id == examination_id,
        ExamResult.student_id == student_id,
        ExamResult.deleted_at.is_(None),
        # The published-only filter is the rule, not an optimisation: an
        # unpublished revision is not the school's word.
        ExamResult.published_at.isnot(None),
    )
    if version is not None:
        query = query.filter(ExamResult.version == version)
    result = query.order_by(ExamResult.version.desc()).first()

    if result is None:
        return _refuse(
            "RESULT_NOT_PUBLISHED",
            (
                "This student has no published result for this examination, so "
                "there is nothing to print. A calculated result becomes "
                "printable when it is published."
            ),
        )

    student = Student.query.filter_by(id=student_id, tenant_id=tenant_id).first()
    person = (
        Person.query.filter_by(id=student.person_id).first()
        if student is not None and student.person_id
        else None
    )

    snapshot = result.snapshot or {}
    grading = snapshot.get("grading") or {}
    aggregate = snapshot.get("aggregate") or {}

    return _ok(marksheet={
        "examination": {
            "id": examination.id,
            "name": examination.name,
        },
        "student": {
            "id": student_id,
            "full_name": person.full_name if person else None,
            "admission_number": student.admission_number if student else None,
        },
        # Which statement this document is. A reprint of v1 after v2 exists
        # must still say v1, or two different documents claim to be the result.
        "result": {
            "version": result.version,
            "published_at": (
                result.published_at.isoformat() if result.published_at else None
            ),
            "revision_reason": result.revision_reason,
            "is_superseded": not result.is_current,
        },
        # Straight from the frozen snapshot. Statuses keep the meanings EX-03A
        # fixed — present/absent/exempted/malpractice/not_yet_entered — and are
        # not reinterpreted at print time.
        "papers": snapshot.get("papers") or [],
        "aggregate": {
            "total_obtained": aggregate.get("total_obtained"),
            "total_max": aggregate.get("total_max"),
            "percentage": aggregate.get("percentage"),
        },
        "grading": {
            "grade_label": grading.get("grade_label"),
            "grade_point": grading.get("grade_point"),
            "min_value": grading.get("min_value"),
            "max_value": grading.get("max_value"),
        },
        "outcome": {
            "is_pass": result.is_pass,
            "complete": snapshot.get("complete"),
        },
        "warnings": snapshot.get("warnings") or [],
    })


def render_marksheet_pdf(marksheet: Dict[str, Any]) -> Optional[bytes]:
    """Turn a frozen render model into a PDF, or None if WeasyPrint is absent.

    Takes data, not ids: the renderer runs no query, so it cannot render a
    value the snapshot does not contain. The finance receipts' import guard is
    reused verbatim — WeasyPrint needs native libraries that are not present on
    every machine, and an ImportError at request time is worse than a clear
    refusal.
    """
    from flask import render_template

    from modules.finance.services.pdf_service import _get_tenant_info, _html_to_pdf

    html = render_template(
        "examinations/marksheet.html",
        school=_get_tenant_info(),
        **marksheet,
    )
    return _html_to_pdf(html)
