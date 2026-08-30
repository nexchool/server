"""The examination module's GraphQL fields.

Transport for the roadmap's EX-04 → EX-08: scheduling, the marking register,
mark corrections, and result computation and publication. Everything below
turns arguments into a service call and the answer into a type. There is no
business rule here, and that is load-bearing: the examination services have
been through eight slices of invariants — cycle boundaries, paper dates,
duplicate detection, the derived `class_id`, lifecycle transitions, atomic
fan-out — and a resolver that re-decided any of them would be a second,
weaker copy reachable only by GraphQL.

Authority is not one key. Scheduling answers to `examination.manage`, marking
to the assessment keys, deciding a correction to its own, and publishing to
`examination.publish` — because whoever closes a register is not necessarily
whoever tells the parents. The permission lists below say which is which.

Marksheet *rendering* is not here: a PDF is a download, so it lives in
`marks_import_routes` with the spreadsheet endpoints, under the same feature
gate.
"""

from __future__ import annotations

import datetime as dt
from typing import List, Optional

import strawberry

from graphql_api.errors import ConflictError, NotFoundError, ValidationError
from graphql_api.permissions import (
    IsAuthenticated,
    RequiresTenant,
    requires,
    requires_any,
    requires_feature,
)

from . import services as exam_services
from . import (
    corrections_service,
    marks_service,
    publication_service,
    results_service,
    revision_service,
)
from .graphql.types import (
    ExamPaperNode,
    ExamTypeNode,
    ExaminationNode,
    ExaminationPageNode,
    ExaminationResultsNode,
    MarkCorrectionNode,
    MarkingRegisterNode,
    examination_to_graphql,
    paper_to_graphql,
    correction_to_graphql,
    register_to_graphql,
    results_to_graphql,
)

# The catalogue's own words: `examination.read` is "View examinations" and
# `examination.manage` is "Create, schedule and cancel examinations" — the
# three acts this file exposes. `examination.publish` is deliberately not used
# here; publishing results is a different authority and a later slice.
PERM_READ = "examination.read"
PERM_MANAGE = "examination.manage"

# A school that does not run examinations here should not be able to reach
# any of it — scheduling, marking, correcting, publishing or printing. The
# gate therefore goes in front of every field in the module rather than in
# front of the ones that looked important, and `_GATE` is what makes that
# checkable by reading: a permission list that does not start with it is the
# bug. `examinations` starts off (DEFAULT_OFF_FEATURES), so this is also what
# keeps the module dark on a deploy until a super-admin turns it on.
FEATURE = "examinations"
_GATE = [IsAuthenticated, RequiresTenant, requires_feature(FEATURE)]

_READS = [*_GATE, requires(PERM_READ)]
_WRITES = [*_GATE, requires(PERM_MANAGE)]

# Every examination service answers with a `code`, so nothing here matches on
# English. A code that is not listed is a validation failure, which is the
# safe default: the alternative is reporting a conflict as an unexpected error.
_CONFLICTS = {
    "NAME_TAKEN",
    "PAPER_DUPLICATE",
    "INVALID_TRANSITION",
    "WRONG_STATUS",
    "ALREADY_PUBLISHED",
    "CYCLE_IMMUTABLE",
    "EXAM_TYPE_IMMUTABLE",
    "GRADING_SCHEME_IMMUTABLE",
    "CLASS_MERGED",
    "OFFERING_INACTIVE",
    # Marks entry (EX-05): a closed register and a stale request are both
    # conflicts with the state, not malformed input.
    "PAPER_LOCKED",
    "ALREADY_MARKED",
    # Corrections (EX-07): a decided request and a moved mark are both
    # conflicts with the state somebody is acting on.
    "ALREADY_DECIDED",
    "PAPER_NOT_LOCKED",
    "NO_CHANGE",
    # Results (EX-08): each is a conflict with the state, not bad input.
    "RESULT_PUBLISHED",
    "RESULT_INCOMPLETE",
    "GRADE_UNRESOLVED",
    "RESULT_NOT_PUBLISHED",
    "NOTHING_TO_REVISE",
    "WEIGHTED_CALCULATION_UNSUPPORTED",
}
_NOT_FOUND = {
    "NOT_FOUND",
    "CYCLE_NOT_FOUND",
    "TERM_NOT_FOUND",
    "WINDOW_NOT_FOUND",
    "OFFERING_NOT_FOUND",
    "CLASS_NOT_FOUND",
    "EXAM_TYPE_NOT_FOUND",
    "GRADING_SCHEME_NOT_FOUND",
    "PAPER_NOT_FOUND",
    "MARK_NOT_FOUND",
    "RESULT_MISSING",
}


def _raise(result: dict) -> None:
    """Turn a service refusal into the GraphQL error of its kind.

    Two codes travel, and they answer different questions. `extensions.code` is
    the *kind* — not-found, conflict, bad input — which is what a client
    branches on. `extensions.details.code` is the domain's own code, which is
    what tells a school *why*: `DATE_OUTSIDE_CYCLE` and `PAPER_DUPLICATE` are
    both conflicts and want different words on screen.

    Nothing here reads the message. Every examination service returns a code,
    so the classification cannot be broken by rewording a sentence.
    """
    code = result.get("code") or "VALIDATION_ERROR"
    message = result.get("error") or "That could not be done"
    details = {"code": code}
    if code in _NOT_FOUND:
        raise NotFoundError(message, details)
    if code in _CONFLICTS:
        raise ConflictError(message, details)
    raise ValidationError(message, details)


def _unwrap(result: dict, tenant_id: str) -> ExaminationNode:
    if not result.get("success"):
        _raise(result)
    return examination_to_graphql(result["examination"], tenant_id)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@strawberry.input(
    description=(
        "One subject in a subject set, with what it is worth and when it is "
        "sat. The same settings are used for every section chosen."
    )
)
class SubjectSetEntryInput:
    subject_id: strawberry.ID
    max_marks: float
    pass_marks: Optional[float] = None
    component_label: Optional[str] = strawberry.field(
        default=None,
        description='"Theory"/"Practical" where the school splits this subject.',
    )
    exam_date: Optional[dt.date] = None
    starts_at: Optional[dt.time] = None
    ends_at: Optional[dt.time] = None


@strawberry.input(
    description=(
        "One set of subjects, fanned across several sections. Grade 10 A and B "
        "with six subjects produces twelve papers in one pass. The sections "
        "and subjects are named; which offering teaches each pair is resolved "
        "by the server, because a paper's class is derived from its offering."
    )
)
class SubjectSetInput:
    class_ids: List[strawberry.ID]
    subjects: List[SubjectSetEntryInput]


@strawberry.input(description="A new examination, and optionally its sittings.")
class CreateExaminationInput:
    academic_cycle_id: strawberry.ID
    exam_type_id: strawberry.ID
    name: str
    description: Optional[str] = None
    academic_term_id: Optional[strawberry.ID] = None
    grading_scheme_id: Optional[strawberry.ID] = None
    exam_window_id: Optional[strawberry.ID] = None
    subject_set: Optional[SubjectSetInput] = strawberry.field(
        default=None,
        description=(
            "Papers to create with the examination. Created in the same "
            "transaction: if any one is refused, the examination is not "
            "created either."
        ),
    )


@strawberry.input(
    description=(
        "Details that may be corrected. The academic cycle is absent on "
        "purpose — moving an examination between operating periods would "
        "strand every paper, so that is a new examination, not an edit."
    )
)
class UpdateExaminationInput:
    name: Optional[str] = None
    description: Optional[str] = None
    academic_term_id: Optional[strawberry.ID] = None
    exam_window_id: Optional[strawberry.ID] = None
    exam_type_id: Optional[strawberry.ID] = None
    grading_scheme_id: Optional[strawberry.ID] = None


def _subject_set_to_specs(subject_set: SubjectSetInput, tenant_id: str) -> list:
    """Ask the service to expand the set. Refusals surface as they are."""
    expanded = exam_services.expand_subject_set(
        tenant_id,
        class_ids=[str(c) for c in subject_set.class_ids],
        subjects=[
            {
                "subject_id": str(entry.subject_id),
                "max_marks": entry.max_marks,
                "pass_marks": entry.pass_marks,
                "component_label": entry.component_label,
                "exam_date": entry.exam_date,
                "starts_at": entry.starts_at,
                "ends_at": entry.ends_at,
            }
            for entry in subject_set.subjects
        ],
    )
    if not expanded.get("success"):
        _raise(expanded)
    return expanded["papers"]


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


@strawberry.type
class ExaminationQuery:
    @strawberry.field(
        permission_classes=_READS,
        description=(
            "Examinations this school holds, newest first. Filter by cycle or "
            "status; `limit` is capped by the service."
        ),
    )
    def examinations(
        self,
        info: strawberry.Info,
        academic_cycle_id: Optional[strawberry.ID] = None,
        status: Optional[str] = None,
        limit: int = 25,
        offset: int = 0,
    ) -> ExaminationPageNode:
        tenant_id = info.context.tenant_id
        filters = {
            "tenant_id": tenant_id,
            "academic_cycle_id": str(academic_cycle_id) if academic_cycle_id else None,
            "status": status,
        }
        # One row past the page is what answers `hasNextPage`, with no second
        # query — the convention the students list set.
        rows = exam_services.list_examinations(
            **filters, limit=limit + 1, offset=offset
        )
        has_next = len(rows) > limit
        return ExaminationPageNode(
            nodes=[examination_to_graphql(row, tenant_id) for row in rows[:limit]],
            has_next_page=has_next,
            filters=filters,
        )

    @strawberry.field(
        permission_classes=_READS,
        description="One examination, or null if this school has no such thing.",
    )
    def examination(
        self, info: strawberry.Info, id: strawberry.ID
    ) -> Optional[ExaminationNode]:
        tenant_id = info.context.tenant_id
        found = exam_services.get_examination(str(id), tenant_id)
        return examination_to_graphql(found, tenant_id) if found else None

    @strawberry.field(
        permission_classes=_READS,
        description="The kinds of examination this school has defined.",
    )
    def exam_types(self, info: strawberry.Info) -> List[ExamTypeNode]:
        rows = exam_services.list_exam_types(info.context.tenant_id)
        return [
            ExamTypeNode(
                id=strawberry.ID(row.id),
                name=row.name,
                code=row.code,
                sequence=row.sequence,
            )
            for row in rows
        ]


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------


@strawberry.type
class ExaminationMutation:
    @strawberry.mutation(
        permission_classes=_WRITES,
        description=(
            "Open an assessment event, optionally with its sittings. The "
            "examination and every paper are created together or not at all."
        ),
    )
    def create_examination(
        self, info: strawberry.Info, input: CreateExaminationInput
    ) -> ExaminationNode:
        tenant_id = info.context.tenant_id
        papers = (
            _subject_set_to_specs(input.subject_set, tenant_id)
            if input.subject_set else None
        )
        result = exam_services.create_examination(
            tenant_id=tenant_id,
            academic_cycle_id=str(input.academic_cycle_id),
            exam_type_id=str(input.exam_type_id),
            name=input.name,
            description=input.description,
            academic_term_id=(
                str(input.academic_term_id) if input.academic_term_id else None
            ),
            grading_scheme_id=(
                str(input.grading_scheme_id) if input.grading_scheme_id else None
            ),
            exam_window_id=(
                str(input.exam_window_id) if input.exam_window_id else None
            ),
            papers=papers,
            created_by_user_id=getattr(info.context.current_user, "id", None),
        )
        return _unwrap(result, tenant_id)

    @strawberry.mutation(
        permission_classes=_WRITES,
        description=(
            "Fan a subject set across sections onto an existing examination. "
            "Any one paper being refused creates none of them."
        ),
    )
    def add_exam_papers(
        self,
        info: strawberry.Info,
        examination_id: strawberry.ID,
        subject_set: SubjectSetInput,
    ) -> ExaminationNode:
        tenant_id = info.context.tenant_id
        specs = _subject_set_to_specs(subject_set, tenant_id)
        result = exam_services.add_papers(str(examination_id), tenant_id, specs)
        if not result.get("success"):
            _raise(result)
        found = exam_services.get_examination(str(examination_id), tenant_id)
        return examination_to_graphql(found, tenant_id)

    @strawberry.mutation(
        permission_classes=_WRITES,
        description="Correct an examination's details.",
    )
    def update_examination(
        self,
        info: strawberry.Info,
        id: strawberry.ID,
        input: UpdateExaminationInput,
    ) -> ExaminationNode:
        tenant_id = info.context.tenant_id
        # Only what the caller actually sent — an absent field is not an
        # instruction to clear one, and the service reads presence to decide.
        changes = {
            field: value
            for field, value in {
                "name": input.name,
                "description": input.description,
                "academic_term_id": input.academic_term_id,
                "exam_window_id": input.exam_window_id,
                "exam_type_id": input.exam_type_id,
                "grading_scheme_id": input.grading_scheme_id,
            }.items()
            if value is not None
        }
        result = exam_services.update_examination(str(id), tenant_id, changes)
        return _unwrap(result, tenant_id)

    @strawberry.mutation(
        permission_classes=_WRITES,
        description=(
            "Announce the examination. Every paper must have a date by now — a "
            "scheduled examination with an undated paper is one a school "
            "cannot tell anybody about."
        ),
    )
    def schedule_examination(
        self, info: strawberry.Info, id: strawberry.ID
    ) -> ExaminationNode:
        tenant_id = info.context.tenant_id
        result = exam_services.schedule_examination(
            str(id),
            tenant_id,
            actor_user_id=getattr(info.context.current_user, "id", None),
        )
        return _unwrap(result, tenant_id)

    @strawberry.mutation(
        permission_classes=_WRITES,
        description=(
            "The examination will not be held. Not a delete: the papers, any "
            "marks and the row all stay, so a school asked why a September "
            "examination is missing from its results can answer."
        ),
    )
    def cancel_examination(
        self, info: strawberry.Info, id: strawberry.ID, reason: str
    ) -> ExaminationNode:
        tenant_id = info.context.tenant_id
        result = exam_services.cancel_examination(
            str(id),
            tenant_id,
            reason=reason,
            actor_user_id=getattr(info.context.current_user, "id", None),
        )
        return _unwrap(result, tenant_id)


# ---------------------------------------------------------------------------
# Marks entry (EX-05)
# ---------------------------------------------------------------------------
#
# Reading a register and writing to it answer to different keys, and neither is
# `examination.manage`: scheduling an examination and marking one are different
# jobs in a school. The write also has to clear ADR-014 authority — the teacher
# of this subject in this class — which `record_marks` checks and this
# deliberately does not restate.

PERM_MARKS_READ = "assessment.read.class"
PERM_MARKS_ENTER = "assessment.enter"

_MARKS_READS = [
    *_GATE,
    requires_any(PERM_MARKS_READ, "assessment.read.all", "assessment.manage"),
]
_MARKS_WRITES = [*_GATE, requires_any(PERM_MARKS_ENTER, "assessment.manage")]


@strawberry.input(description="One student's outcome, as the register has it.")
class MarkEntryInput:
    student_id: strawberry.ID
    status: str
    marks_obtained: Optional[float] = strawberry.field(
        default=None,
        description=(
            "Required when the status is `present`, and refused otherwise — a "
            "student who did not sit the paper has no mark, and zero would say "
            "they sat it and scored nothing."
        ),
    )
    remarks: Optional[str] = None


@strawberry.type
class MarksQuery:
    @strawberry.field(
        permission_classes=_MARKS_READS,
        description=(
            "A paper's register: who sits it, what each of them has so far, "
            "and whether it is still open for marking."
        ),
    )
    def marking_register(
        self, info: strawberry.Info, exam_paper_id: strawberry.ID
    ) -> Optional[MarkingRegisterNode]:
        tenant_id = info.context.tenant_id
        register = marks_service.marking_register(str(exam_paper_id), tenant_id)
        if register is None:
            return None
        return register_to_graphql(register)


@strawberry.type
class MarksMutation:
    @strawberry.mutation(
        permission_classes=_MARKS_WRITES,
        description=(
            "Record a register's worth of marks. **All or nothing** — one "
            "refused row writes none of them, so a teacher is never left "
            "unable to tell which half landed."
        ),
    )
    def record_marks(
        self,
        info: strawberry.Info,
        exam_paper_id: strawberry.ID,
        rows: List[MarkEntryInput],
    ) -> MarkingRegisterNode:
        tenant_id = info.context.tenant_id
        result = marks_service.record_marks(
            tenant_id=tenant_id,
            exam_paper_id=str(exam_paper_id),
            rows=[
                {
                    "student_id": str(row.student_id),
                    "status": row.status,
                    "marks_obtained": row.marks_obtained,
                    **({"remarks": row.remarks} if row.remarks is not None else {}),
                }
                for row in rows
            ],
            actor_user_id=getattr(info.context.current_user, "id", None),
        )
        if not result.get("success"):
            _raise(result)
        # The authoritative register, re-read — so a screen never has to guess
        # what its own write produced.
        register = marks_service.marking_register(str(exam_paper_id), tenant_id)
        return register_to_graphql(register)


# ---------------------------------------------------------------------------
# Corrections (EX-07)
# ---------------------------------------------------------------------------
#
# Asking and deciding are different acts with different keys, which is the
# split `corrections_service` already enforces: `assessment.update` plus
# ADR-014 standing to raise one, `assessment.manage` to decide it. Neither is
# restated here — the guards below only stop a field running at all.

PERM_CORRECT_REQUEST = "assessment.update"
PERM_CORRECT_DECIDE = "assessment.manage"

_CORRECTION_REQUEST = [
    *_GATE,
    requires_any(PERM_CORRECT_REQUEST, PERM_CORRECT_DECIDE),
]
_CORRECTION_DECIDE = [*_GATE, requires(PERM_CORRECT_DECIDE)]


@strawberry.type
class CorrectionQuery:
    @strawberry.field(
        permission_classes=_CORRECTION_DECIDE,
        description=(
            "Corrections awaiting a decision, newest first. Pass a `status` to "
            "read the decided ones instead — the history is kept."
        ),
    )
    def mark_corrections(
        self, info: strawberry.Info, status: Optional[str] = "requested"
    ) -> List[MarkCorrectionNode]:
        rows = corrections_service.correction_queue(
            info.context.tenant_id, status=status
        )
        return [correction_to_graphql(row) for row in rows]

    @strawberry.field(
        permission_classes=_CORRECTION_REQUEST,
        description="Every correction ever raised against one mark, oldest first.",
    )
    def corrections_for_mark(
        self, info: strawberry.Info, exam_mark_id: strawberry.ID
    ) -> List[MarkCorrectionNode]:
        tenant_id = info.context.tenant_id
        rows = [
            row
            for row in corrections_service.correction_queue(tenant_id, status=None)
            if row["correction"].exam_mark_id == str(exam_mark_id)
        ]
        return [correction_to_graphql(row) for row in reversed(rows)]


def _one_correction(correction_id: str, tenant_id: str) -> MarkCorrectionNode:
    """Re-read through the queue so a mutation answers with the same shape the
    list does, context included."""
    rows = corrections_service.correction_queue(tenant_id, status=None)
    row = next(r for r in rows if r["correction"].id == correction_id)
    return correction_to_graphql(row)


@strawberry.type
class CorrectionMutation:
    @strawberry.mutation(
        permission_classes=_CORRECTION_REQUEST,
        description=(
            "Ask for a closed mark to be changed. Writes the request only — "
            "nothing about the mark moves until somebody decides."
        ),
    )
    def request_mark_correction(
        self,
        info: strawberry.Info,
        exam_mark_id: strawberry.ID,
        to_status: str,
        reason: str,
        to_marks: Optional[float] = None,
    ) -> MarkCorrectionNode:
        tenant_id = info.context.tenant_id
        result = corrections_service.request_correction(
            tenant_id,
            str(exam_mark_id),
            to_status=to_status,
            to_marks=to_marks,
            reason=reason,
            requested_by_user_id=getattr(info.context.current_user, "id", None),
        )
        if not result.get("success"):
            _raise(result)
        return _one_correction(result["correction"].id, tenant_id)

    @strawberry.mutation(
        permission_classes=_CORRECTION_DECIDE,
        description="Agree to the change, and make it — both, or neither.",
    )
    def approve_mark_correction(
        self,
        info: strawberry.Info,
        correction_id: strawberry.ID,
        note: Optional[str] = None,
    ) -> MarkCorrectionNode:
        tenant_id = info.context.tenant_id
        result = corrections_service.approve_correction(
            tenant_id,
            str(correction_id),
            decided_by_user_id=getattr(info.context.current_user, "id", None),
            note=note,
        )
        if not result.get("success"):
            _raise(result)
        return _one_correction(str(correction_id), tenant_id)

    @strawberry.mutation(
        permission_classes=_CORRECTION_DECIDE,
        description="Decline the change. The mark stands, and the request is kept.",
    )
    def reject_mark_correction(
        self,
        info: strawberry.Info,
        correction_id: strawberry.ID,
        note: Optional[str] = None,
    ) -> MarkCorrectionNode:
        tenant_id = info.context.tenant_id
        result = corrections_service.reject_correction(
            tenant_id,
            str(correction_id),
            decided_by_user_id=getattr(info.context.current_user, "id", None),
            note=note,
        )
        if not result.get("success"):
            _raise(result)
        return _one_correction(str(correction_id), tenant_id)


# ---------------------------------------------------------------------------
# Results (EX-08)
# ---------------------------------------------------------------------------
#
# Reading results answers to `examination.read`; every act that changes what a
# school has said — calculating, publishing, revising, republishing — answers
# to `examination.publish`, which the catalogue defines as "Publish and revise
# examination results". `assessment.manage` runs marking and deliberately does
# not reach any of this.
#
# Calculation is the one exception worth stating: `calculate_results` checks
# `assessment.manage` itself (ADR-020), so the field requires *both* rather
# than widening either.

PERM_RESULT_READ = "assessment.read.class"
PERM_RESULT_PUBLISH = "examination.publish"

# **Two keys, both required** — the guards evaluate in order and short-circuit,
# so listing them is an AND.
#
# `examination.read` says you may know this examination exists. It does *not*
# say you may read its marks: it is held by the **Student and Parent profiles**
# (the Student one implied by the relationship, so every pupil holds it
# automatically), and this field returns every child's name, total, percentage
# and grade. Under ADR-011 a household shares the pupil's login, so guarding a
# whole-cohort mark sheet with that key alone showed every parent every child's
# results.
#
# The second key is the tier `markingRegister` already uses. Keeping the first
# as well preserves the layering an earlier decision made deliberately: running
# assessment is not, on its own, permission to open an examination.
_RESULT_READS = [
    *_GATE,
    requires(PERM_READ),
    requires_any(PERM_RESULT_READ, "assessment.read.all", "assessment.manage"),
]
_RESULT_WRITES = [*_GATE, requires(PERM_RESULT_PUBLISH)]


def _board(examination_id: str, tenant_id: str) -> ExaminationResultsNode:
    board = results_service.result_board(examination_id, tenant_id)
    if board is None:
        raise NotFoundError("Examination not found", {"code": "NOT_FOUND"})
    readiness = publication_service.publication_readiness(examination_id, tenant_id)
    return results_to_graphql(board, readiness)


@strawberry.type
class ResultQuery:
    @strawberry.field(
        permission_classes=_RESULT_READS,
        description=(
            "Every student's result state for one examination — what is "
            "calculated, what is official, and what is waiting on a revision."
        ),
    )
    def examination_results(
        self, info: strawberry.Info, examination_id: strawberry.ID
    ) -> Optional[ExaminationResultsNode]:
        board = results_service.result_board(
            str(examination_id), info.context.tenant_id
        )
        if board is None:
            return None
        readiness = publication_service.publication_readiness(
            str(examination_id), info.context.tenant_id
        )
        return results_to_graphql(board, readiness)


@strawberry.type
class ResultMutation:
    @strawberry.mutation(
        permission_classes=_RESULT_WRITES,
        description=(
            "Compute every student's result for this examination. All or "
            "nothing: one refusal calculates nobody."
        ),
    )
    def calculate_examination_results(
        self, info: strawberry.Info, examination_id: strawberry.ID
    ) -> ExaminationResultsNode:
        tenant_id = info.context.tenant_id
        result = results_service.calculate_results(
            str(examination_id),
            tenant_id=tenant_id,
            actor_user_id=getattr(info.context.current_user, "id", None),
        )
        if not result.get("success"):
            _raise(result)
        return _board(str(examination_id), tenant_id)

    @strawberry.mutation(
        permission_classes=_RESULT_WRITES,
        description=(
            "Make this examination's results the school's word. Refuses unless "
            "every student in the cohort has a complete, gradeable result."
        ),
    )
    def publish_examination_results(
        self, info: strawberry.Info, examination_id: strawberry.ID
    ) -> ExaminationResultsNode:
        tenant_id = info.context.tenant_id
        result = publication_service.publish_results(
            str(examination_id),
            tenant_id,
            actor_user_id=getattr(info.context.current_user, "id", None),
        )
        if not result.get("success"):
            _raise(result)
        return _board(str(examination_id), tenant_id)

    @strawberry.mutation(
        permission_classes=_RESULT_WRITES,
        description=(
            "Recompute one student's published result into a new, unpublished "
            "version. The published one is untouched and stays official until "
            "the revision is published in its own right."
        ),
    )
    def revise_student_result(
        self,
        info: strawberry.Info,
        examination_id: strawberry.ID,
        student_id: strawberry.ID,
        reason: str,
    ) -> ExaminationResultsNode:
        tenant_id = info.context.tenant_id
        result = revision_service.revise_result(
            str(examination_id),
            str(student_id),
            tenant_id,
            reason=reason,
            actor_user_id=getattr(info.context.current_user, "id", None),
        )
        if not result.get("success"):
            _raise(result)
        return _board(str(examination_id), tenant_id)

    @strawberry.mutation(
        permission_classes=_RESULT_WRITES,
        description="Issue the revised result — a separate decision from making it.",
    )
    def publish_student_revision(
        self,
        info: strawberry.Info,
        examination_id: strawberry.ID,
        student_id: strawberry.ID,
    ) -> ExaminationResultsNode:
        tenant_id = info.context.tenant_id
        result = revision_service.publish_revision(
            str(examination_id),
            str(student_id),
            tenant_id,
            actor_user_id=getattr(info.context.current_user, "id", None),
        )
        if not result.get("success"):
            _raise(result)
        return _board(str(examination_id), tenant_id)
