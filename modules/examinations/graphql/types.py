"""What a client sees of an examination.

The scheduling screens render an event, its sittings and its history — so that
is what is here. `created_by_user_id`, `instructions` and `venue` are on the
tables and rendered by nothing yet, so they are not: a field earns its place
when something shows it.

`status` is the stored decision (draft / scheduled / marks_entry / published /
cancelled) and nothing here derives a second one. Whether an examination is
"upcoming" or "over" is a fact about its papers' dates, and ADR-016's rule is
that such facts are computed where they are read rather than stored — a client
that wants a badge composes it from `examDate`.
"""

from __future__ import annotations

import datetime as dt
from typing import List, Optional

import strawberry


@strawberry.type(
    name="ExamType",
    description=(
        "What a school calls a kind of examination — Unit Test, Preliminary, "
        "Board. A row, never an enum: adding one must not be a deploy."
    ),
)
class ExamTypeNode:
    id: strawberry.ID
    name: str
    code: Optional[str] = None
    sequence: int = 0


@strawberry.type(
    name="ExamPaper",
    description=(
        "One sitting: one subject, for one section, on one date. A half yearly "
        "for Grade 10 A with six subjects is six of these."
    ),
)
class ExamPaperNode:
    id: strawberry.ID
    class_id: strawberry.ID = strawberry.field(
        description=(
            "The section sitting this paper. Derived from the offering, never "
            "supplied by a caller, so it cannot disagree with it."
        )
    )
    class_subject_id: strawberry.ID
    subject_name: Optional[str] = None
    class_name: Optional[str] = None
    component_label: Optional[str] = strawberry.field(
        default=None,
        description='"Theory"/"Practical" where a school splits a subject; null where it does not.',
    )
    exam_date: Optional[dt.date] = None
    starts_at: Optional[dt.time] = None
    ends_at: Optional[dt.time] = None
    max_marks: float = 0.0
    pass_marks: Optional[float] = None
    marks_locked: bool = False


@strawberry.type(
    name="ExaminationEvent",
    description="One entry in an examination's history. Append-only.",
)
class ExaminationEventNode:
    id: strawberry.ID
    event_name: str
    occurred_on: dt.date
    note: Optional[str] = None
    actor_user_id: Optional[strawberry.ID] = None


@strawberry.type(
    name="Examination",
    description=(
        "An assessment event a school holds. It declares no classes, grades or "
        "streams — which sections sit it is answered by its papers (ADR-016)."
    ),
)
class ExaminationNode:
    id: strawberry.ID
    name: str
    status: str
    description: Optional[str] = None
    academic_cycle_id: strawberry.ID
    academic_term_id: Optional[strawberry.ID] = None
    exam_type_id: strawberry.ID
    exam_type_name: Optional[str] = None
    grading_scheme_id: Optional[strawberry.ID] = None
    exam_window_id: Optional[strawberry.ID] = None

    # Carried so the sub-field resolvers can stay tenant-scoped without
    # re-reading the request's tenant, which a resolver must never assume.
    tenant_id: strawberry.Private[str] = ""

    @strawberry.field(
        description="Every sitting this examination holds, earliest date first."
    )
    def papers(self, info: strawberry.Info) -> List[ExamPaperNode]:
        from modules.examinations.services import papers_with_labels

        return [
            paper_to_graphql(paper, class_name=class_name, subject_name=subject_name)
            for paper, class_name, subject_name in papers_with_labels(
                str(self.id), self.tenant_id
            )
        ]

    @strawberry.field(
        description=(
            "The sections sitting this examination — derived from its papers, "
            "never declared on the event itself."
        )
    )
    def classes_sitting(self, info: strawberry.Info) -> List[strawberry.ID]:
        from modules.examinations.services import classes_sitting

        return [
            strawberry.ID(class_id)
            for class_id in classes_sitting(str(self.id), self.tenant_id)
        ]

    @strawberry.field(description="What has happened to this examination, in order.")
    def timeline(self, info: strawberry.Info) -> List[ExaminationEventNode]:
        from modules.examinations.services import timeline_for

        return [
            ExaminationEventNode(
                id=strawberry.ID(event.id),
                event_name=event.event_name,
                occurred_on=event.occurred_on,
                note=event.note,
                actor_user_id=(
                    strawberry.ID(event.actor_user_id)
                    if event.actor_user_id else None
                ),
            )
            for event in timeline_for(str(self.id), self.tenant_id)
        ]


@strawberry.type(
    name="ExaminationPage",
    description=(
        "A page of examinations. Offset-paged and with no cursor, for the "
        "reason classes are: nothing an examination is ordered by is unique, "
        "immutable and meaningful to a school."
    ),
)
class ExaminationPageNode:
    nodes: List[ExaminationNode]
    has_next_page: bool

    filters: strawberry.Private[dict]

    @strawberry.field(
        description=(
            "How many examinations match, ignoring paging. Counted only when "
            "asked for."
        )
    )
    def total_count(self, info: strawberry.Info) -> int:
        from modules.examinations.services import count_examinations

        return count_examinations(**self.filters)


# ---------------------------------------------------------------------------
# Converters
# ---------------------------------------------------------------------------


def paper_to_graphql(paper, *, subject_name=None, class_name=None) -> ExamPaperNode:
    return ExamPaperNode(
        id=strawberry.ID(paper.id),
        class_id=strawberry.ID(paper.class_id),
        class_subject_id=strawberry.ID(paper.class_subject_id),
        subject_name=subject_name,
        class_name=class_name,
        component_label=paper.component_label or None,
        exam_date=paper.exam_date,
        starts_at=paper.starts_at,
        ends_at=paper.ends_at,
        max_marks=float(paper.max_marks),
        pass_marks=(
            float(paper.pass_marks) if paper.pass_marks is not None else None
        ),
        marks_locked=paper.marks_are_locked,
    )


def examination_to_graphql(examination, tenant_id: str) -> ExaminationNode:
    return ExaminationNode(
        id=strawberry.ID(examination.id),
        name=examination.name,
        status=examination.status,
        description=examination.description,
        academic_cycle_id=strawberry.ID(examination.academic_cycle_id),
        academic_term_id=(
            strawberry.ID(examination.academic_term_id)
            if examination.academic_term_id else None
        ),
        exam_type_id=strawberry.ID(examination.exam_type_id),
        grading_scheme_id=(
            strawberry.ID(examination.grading_scheme_id)
            if examination.grading_scheme_id else None
        ),
        exam_window_id=(
            strawberry.ID(examination.exam_window_id)
            if examination.exam_window_id else None
        ),
        tenant_id=tenant_id,
    )


# ---------------------------------------------------------------------------
# Marks entry (EX-05)
# ---------------------------------------------------------------------------


@strawberry.type(
    name="RegisterStudent",
    description=(
        "One line of a paper's register. `status` is null when no mark has "
        "been recorded — the sixth state, which is deliberately neither absent "
        "nor a zero."
    ),
)
class RegisterStudentNode:
    student_id: strawberry.ID
    mark_id: Optional[strawberry.ID] = strawberry.field(
        default=None,
        description="The mark's id, which a correction targets. Null when none exists.",
    )
    admission_number: Optional[str] = None
    full_name: Optional[str] = None
    roll_number: Optional[int] = None
    status: Optional[str] = None
    marks_obtained: Optional[float] = None
    remarks: Optional[str] = None


@strawberry.type(
    name="MarkingProgress",
    description=(
        "How far a register has got. `outstanding` is null on a closed paper: "
        "its cohort is its own marks, so a number there would claim everybody "
        "was marked."
    ),
)
class MarkingProgressNode:
    eligible: int
    recorded: int
    outstanding: Optional[int] = None
    locked: bool = False
    cohort_source: str = "enrollment"


@strawberry.type(
    name="MarkingRegister",
    description="A paper, who sits it, and what each of them has so far.",
)
class MarkingRegisterNode:
    paper: ExamPaperNode
    examination_id: strawberry.ID
    examination_name: str
    examination_status: str
    open_for_marking: bool = strawberry.field(
        description=(
            "Whether marks may be written now — the same guard the write path "
            "applies, so the screen and the server cannot disagree."
        )
    )
    progress: MarkingProgressNode
    students: List[RegisterStudentNode]


def register_to_graphql(register: dict) -> MarkingRegisterNode:
    paper = register["paper"]
    examination = register["examination"]
    progress = register["progress"]
    return MarkingRegisterNode(
        paper=paper_to_graphql(
            paper,
            class_name=register.get("class_name"),
            subject_name=register.get("subject_name"),
        ),
        examination_id=strawberry.ID(examination.id),
        examination_name=examination.name,
        examination_status=examination.status,
        open_for_marking=register["open_for_marking"],
        progress=MarkingProgressNode(
            eligible=progress["eligible"],
            recorded=progress["recorded"],
            outstanding=progress["outstanding"],
            locked=progress["locked"],
            cohort_source=progress["cohort_source"],
        ),
        students=[
            RegisterStudentNode(
                student_id=strawberry.ID(row["student_id"]),
                mark_id=(
                    strawberry.ID(row["mark_id"]) if row.get("mark_id") else None
                ),
                admission_number=row["admission_number"],
                full_name=row["full_name"],
                roll_number=row["roll_number"],
                status=row["status"],
                marks_obtained=row["marks_obtained"],
                remarks=row["remarks"],
            )
            for row in register["students"]
        ],
    )


# ---------------------------------------------------------------------------
# Corrections (EX-07)
# ---------------------------------------------------------------------------


@strawberry.type(
    name="MarkCorrection",
    description=(
        "A request to change a mark on a closed paper, with enough context to "
        "decide on it. `from*` is what the mark said when the request was "
        "raised — kept so a stale request can be refused rather than applied."
    ),
)
class MarkCorrectionNode:
    id: strawberry.ID
    exam_mark_id: strawberry.ID
    status: str

    from_status: str
    to_status: str
    from_marks: Optional[float] = None
    to_marks: Optional[float] = None
    reason: str = ""

    student_id: Optional[strawberry.ID] = None
    admission_number: Optional[str] = None
    full_name: Optional[str] = None

    exam_paper_id: Optional[strawberry.ID] = None
    class_name: Optional[str] = None
    subject_name: Optional[str] = None
    examination_id: Optional[strawberry.ID] = None
    examination_name: Optional[str] = None
    max_marks: Optional[float] = None

    requested_by_user_id: Optional[strawberry.ID] = None
    requested_by_name: Optional[str] = None
    requested_at: Optional[str] = None
    decided_by_user_id: Optional[strawberry.ID] = None
    decided_by_name: Optional[str] = None
    decided_at: Optional[str] = None
    decision_note: Optional[str] = None


def correction_to_graphql(row: dict) -> MarkCorrectionNode:
    """`row` is one entry of `corrections_service.correction_queue`."""
    correction = row["correction"]
    return MarkCorrectionNode(
        id=strawberry.ID(correction.id),
        exam_mark_id=strawberry.ID(correction.exam_mark_id),
        status=correction.status,
        from_status=correction.from_status,
        to_status=correction.to_status,
        from_marks=(
            float(correction.from_marks) if correction.from_marks is not None else None
        ),
        to_marks=(
            float(correction.to_marks) if correction.to_marks is not None else None
        ),
        reason=correction.reason,
        student_id=(
            strawberry.ID(row["student_id"]) if row.get("student_id") else None
        ),
        admission_number=row.get("admission_number"),
        full_name=row.get("full_name"),
        exam_paper_id=(
            strawberry.ID(row["exam_paper_id"]) if row.get("exam_paper_id") else None
        ),
        class_name=row.get("class_name"),
        subject_name=row.get("subject_name"),
        examination_id=(
            strawberry.ID(row["examination_id"]) if row.get("examination_id") else None
        ),
        examination_name=row.get("examination_name"),
        max_marks=row.get("max_marks"),
        requested_by_user_id=(
            strawberry.ID(correction.requested_by_user_id)
            if correction.requested_by_user_id else None
        ),
        requested_by_name=row.get("requested_by_name"),
        requested_at=(
            correction.requested_at.isoformat() if correction.requested_at else None
        ),
        decided_by_user_id=(
            strawberry.ID(correction.decided_by_user_id)
            if correction.decided_by_user_id else None
        ),
        decided_by_name=row.get("decided_by_name"),
        decided_at=(
            correction.decided_at.isoformat() if correction.decided_at else None
        ),
        decision_note=correction.decision_note,
    )


# ---------------------------------------------------------------------------
# Results (EX-08)
# ---------------------------------------------------------------------------


@strawberry.type(
    name="ExamResultVersion",
    description=(
        "One version of a student's result. A version is a statement the school "
        "made: `publishedAt` says whether it was ever issued, and a published "
        "one never changes again."
    ),
)
class ExamResultVersionNode:
    id: strawberry.ID
    version: int
    is_current: bool
    published_at: Optional[str] = None
    published_by_user_id: Optional[strawberry.ID] = None
    revision_reason: Optional[str] = None
    total_max: Optional[float] = None
    total_obtained: Optional[float] = None
    percentage: Optional[float] = None
    grade_label: Optional[str] = None
    is_pass: Optional[bool] = None
    complete: bool = False
    warnings: List[str] = strawberry.field(default_factory=list)


@strawberry.type(
    name="StudentResult",
    description=(
        "A student's result state. `official` is the version the school has "
        "actually issued; `current` is the one being worked on. They differ "
        "while a revision is pending, and collapsing them would show a parent "
        "a figure nobody has told them (ADR-020)."
    ),
)
class StudentResultNode:
    student_id: strawberry.ID
    admission_number: Optional[str] = None
    full_name: Optional[str] = None
    has_result: bool = False
    revision_pending: bool = False
    official: Optional[ExamResultVersionNode] = None
    current: Optional[ExamResultVersionNode] = None
    versions: List[ExamResultVersionNode] = strawberry.field(default_factory=list)


@strawberry.type(
    name="ResultReadinessBlock",
    description="One student standing between this examination and publication.",
)
class ResultReadinessBlockNode:
    student_id: strawberry.ID
    code: str


@strawberry.type(
    name="ExaminationResults",
    description="Every student's result state for one examination.",
)
class ExaminationResultsNode:
    examination_id: strawberry.ID
    examination_name: str
    examination_status: str
    ready_to_publish: bool = False
    cohort: int = 0
    calculated: int = 0
    published: int = 0
    revision_pending: int = 0
    blocked: List[ResultReadinessBlockNode] = strawberry.field(default_factory=list)
    students: List[StudentResultNode] = strawberry.field(default_factory=list)


def _version_to_graphql(row) -> Optional[ExamResultVersionNode]:
    if row is None:
        return None
    snapshot = row.snapshot or {}
    return ExamResultVersionNode(
        id=strawberry.ID(row.id),
        version=row.version,
        is_current=row.is_current,
        published_at=row.published_at.isoformat() if row.published_at else None,
        published_by_user_id=(
            strawberry.ID(row.published_by_user_id)
            if row.published_by_user_id else None
        ),
        revision_reason=row.revision_reason,
        total_max=float(row.total_max) if row.total_max is not None else None,
        total_obtained=(
            float(row.total_obtained) if row.total_obtained is not None else None
        ),
        percentage=float(row.percentage) if row.percentage is not None else None,
        grade_label=row.grade_label,
        is_pass=row.is_pass,
        complete=bool(snapshot.get("complete")),
        warnings=list(snapshot.get("warnings") or []),
    )


def results_to_graphql(board: dict, readiness: dict) -> ExaminationResultsNode:
    examination = board["examination"]
    students = board["students"]
    return ExaminationResultsNode(
        examination_id=strawberry.ID(examination.id),
        examination_name=examination.name,
        examination_status=examination.status,
        ready_to_publish=bool(readiness.get("ready")),
        cohort=readiness.get("cohort", 0),
        calculated=sum(1 for row in students if row["has_result"]),
        published=sum(1 for row in students if row["official"] is not None),
        revision_pending=sum(1 for row in students if row["revision_pending"]),
        blocked=[
            ResultReadinessBlockNode(
                student_id=strawberry.ID(block["student_id"]), code=block["code"]
            )
            for block in readiness.get("blocked", [])
        ],
        students=[
            StudentResultNode(
                student_id=strawberry.ID(row["student_id"]),
                admission_number=row["admission_number"],
                full_name=row["full_name"],
                has_result=row["has_result"],
                revision_pending=row["revision_pending"],
                official=_version_to_graphql(row["official"]),
                current=_version_to_graphql(row["current"]),
                versions=[_version_to_graphql(v) for v in row["versions"]],
            )
            for row in students
        ],
    )
