"""Where examination papers and answer sheets are filed.

**No new table.** `documents` already serves any domain through
`(owner_kind, owner_id)` — its registry docstring uses `exam_paper` as the
worked example — so registering two owner kinds is the whole of it (ADR-018).

The owners are chosen so the reference is exact:

* a **question paper** belongs to the `exam_paper` — the Mathematics paper, not
  the whole Half Yearly;
* an **answer sheet** belongs to the `exam_mark` — this student's outcome for
  this paper. That pair is precisely what an answer sheet is about, and keying
  it on the student alone would lose which sitting it came from.

`resolve_tenant` is the price of a polymorphic reference: the store refuses to
write a document whose owner it cannot place in a school.
"""

from __future__ import annotations

from typing import Optional

from modules.documents.registry import OwnerKind, register

EXAM_PAPER = "exam_paper"
EXAM_MARK = "exam_mark"

# Scanned scripts are photographed as often as they are scanned, so the default
# set (pdf + jpeg/png) is right. Question papers are frequently large scans.
_PAPER_MAX_BYTES = 25 * 1024 * 1024


def _paper_tenant(owner_id: str) -> Optional[str]:
    from .models import ExamPaper

    row = ExamPaper.query.filter_by(id=owner_id).first()
    return row.tenant_id if row is not None else None


def _mark_tenant(owner_id: str) -> Optional[str]:
    from .models import ExamMark

    row = ExamMark.query.filter_by(id=owner_id).first()
    return row.tenant_id if row is not None else None


def register_examination_document_kinds() -> None:
    """Attach both owner kinds. Called once from `app.py`."""
    register(
        OwnerKind(
            name=EXAM_PAPER,
            label="Exam paper",
            contexts=("question_paper",),
            resolve_tenant=_paper_tenant,
            max_file_size_bytes=_PAPER_MAX_BYTES,
            description="The question paper for one subject sitting.",
        )
    )
    register(
        OwnerKind(
            name=EXAM_MARK,
            label="Answer sheet",
            contexts=("answer_sheet",),
            resolve_tenant=_mark_tenant,
            max_file_size_bytes=_PAPER_MAX_BYTES,
            description="A student's script for one subject sitting.",
        )
    )
