"""The Examination domain.

An **Examination** is an assessment *event* a school holds — "Half Yearly",
"Unit Test 1", "Preliminary", "JEE Mock 3". An **ExamPaper** is one sitting
inside it: one subject, for one section, on one date. A "Half Yearly" for
Grade 10 A with six subjects is one Examination and six papers.

Three decisions shape everything here, each recorded as an ADR:

**An Examination declares no applicability** (ADR-016). There is no
programme, grade, stream or class on it. Which sections sit an examination is
answered by its papers — a query, not a claim. This is the rule AcademicCycle
already follows, and for the same reason: a header saying "Grade 10" while its
papers name Grade 9 is a contradiction the schema should not be able to hold.

**An Examination belongs to a cycle, not a year** (ADR-017). The cycle is when
the school is open, and a paper's date is checked against it. A term is
optional: a board examination is scheduled by the board, not by the school's
terms.

**Documents are not stored here** (ADR-018). `documents` already serves any
domain through `(owner_kind, owner_id)`; question papers hang off the paper and
answer sheets off the mark.

Deliberately absent, and not an oversight: there is no AssessmentScheme table.
Theory 80 + Practical 20 is **two papers** on the same class subject, which is
what a school actually sits, and a scheme would be a template that stamps those
out — convenience over an existing model rather than a different model.
"""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, Index, text

from core.database import db
from core.models import TenantBaseModel
from core.school_time import utc_now


# --- lifecycle --------------------------------------------------------------
#
# Stored states are decisions somebody makes. Time facts — whether an
# examination is upcoming, running or over — are DERIVED from its papers'
# dates, never stored: a stored "upcoming" is wrong the morning after and
# needs a job to keep it honest.
EXAM_DRAFT = "draft"
EXAM_SCHEDULED = "scheduled"
EXAM_MARKS_ENTRY = "marks_entry"
EXAM_PUBLISHED = "published"
EXAM_CANCELLED = "cancelled"

EXAM_STATUSES = (
    EXAM_DRAFT,
    EXAM_SCHEDULED,
    EXAM_MARKS_ENTRY,
    EXAM_PUBLISHED,
    EXAM_CANCELLED,
)

# --- a student's outcome for one paper --------------------------------------
#
# Absence is a status, never a magic number. A child who did not sit the paper
# has no mark; recording zero would fail them and drag the aggregate, and a
# blank would be indistinguishable from "not entered yet".
MARK_PRESENT = "present"
MARK_ABSENT = "absent"
MARK_EXEMPTED = "exempted"
MARK_MALPRACTICE = "malpractice"

MARK_STATUSES = (MARK_PRESENT, MARK_ABSENT, MARK_EXEMPTED, MARK_MALPRACTICE)

# --- changing a mark that has already been closed ---------------------------
#
# The same three states attendance uses, and for the same reason: the change
# has to exist as a request before it exists as a fact.
CORRECTION_REQUESTED = "requested"
CORRECTION_APPROVED = "approved"
CORRECTION_REJECTED = "rejected"

CORRECTION_STATUSES = (
    CORRECTION_REQUESTED,
    CORRECTION_APPROVED,
    CORRECTION_REJECTED,
)

# --- how a number becomes a grade -------------------------------------------
GRADING_PERCENTAGE = "percentage"
GRADING_LETTER = "letter"
GRADING_GRADE_POINT = "grade_point"
GRADING_PASS_FAIL = "pass_fail"

GRADING_SCHEME_TYPES = (
    GRADING_PERCENTAGE,
    GRADING_LETTER,
    GRADING_GRADE_POINT,
    GRADING_PASS_FAIL,
)


class ExamType(TenantBaseModel):
    """What a school calls its kinds of examination.

    Unit Test, Periodic Test, Half Yearly, Preliminary, Board, Mock, Practical.
    A **table**, not an enum, because these differ by school and by board and
    adding one must never be a deploy — the same rule `streams` follows.

    Nothing branches on the type. It labels and groups; it does not decide.
    """

    __tablename__ = "exam_types"
    __table_args__ = (
        Index(
            "uq_exam_types_tenant_name",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_exam_types_tenant_code",
            "tenant_id",
            "code",
            unique=True,
            postgresql_where=text("code IS NOT NULL AND deleted_at IS NULL"),
        ),
        db.UniqueConstraint("tenant_id", "id", name="uq_exam_types_tenant_id_id"),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(80), nullable=False)
    code = db.Column(db.String(32), nullable=True)
    sequence = db.Column(db.Integer, nullable=False, default=0, index=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "code": self.code,
            "sequence": self.sequence,
        }


class GradingScheme(TenantBaseModel):
    """How a number becomes a grade.

    A **platform capability**, deliberately not inside the examination module's
    ownership: attendance grades, co-scholastic grades and conduct grades will
    want the same machinery, and a scheme that lived under Examination would
    have to be moved to give it to them.

    Per-board grading needs no scope column here. A CBSE examination and a GSEB
    examination are different Examinations and each names its own scheme, so
    the scoping already exists through the event. That is why this table is
    tenant-wide and stays that way (ADR-019).
    """

    __tablename__ = "grading_schemes"
    __table_args__ = (
        Index(
            "uq_grading_schemes_tenant_name",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        CheckConstraint(
            "scheme_type IN ('percentage', 'letter', 'grade_point', 'pass_fail')",
            name="ck_grading_schemes_type",
        ),
        db.UniqueConstraint(
            "tenant_id", "id", name="uq_grading_schemes_tenant_id_id"
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(120), nullable=False)
    scheme_type = db.Column(db.String(20), nullable=False, default=GRADING_PERCENTAGE)
    # A school that reports marks only still has a scheme — it simply has no
    # bands. Keeping the row means an examination always has something to name.
    is_default = db.Column(db.Boolean, nullable=False, default=False)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)

    bands = db.relationship(
        "GradingBand",
        back_populates="scheme",
        cascade="all, delete-orphan",
        order_by="GradingBand.sequence",
    )

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "scheme_type": self.scheme_type,
            "is_default": self.is_default,
            "bands": [b.to_dict() for b in self.bands],
        }


class GradingBand(TenantBaseModel):
    """One boundary inside a scheme: 90-100 is an A+.

    Bounds are inclusive at both ends and stored as NUMERIC, so 89.995 is a
    school's problem to define rather than a float's to lose. Nothing here is
    hard-coded: A1/A2/B1 and Distinction/First Class/Pass are the same table
    with different rows.
    """

    __tablename__ = "grading_bands"
    __table_args__ = (
        Index("idx_grading_bands_scheme", "tenant_id", "grading_scheme_id"),
        CheckConstraint(
            "min_value <= max_value", name="ck_grading_bands_bounds_ordered"
        ),
        db.ForeignKeyConstraint(
            ["tenant_id", "grading_scheme_id"],
            ["grading_schemes.tenant_id", "grading_schemes.id"],
            name="fk_grading_bands_scheme",
            ondelete="CASCADE",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    grading_scheme_id = db.Column(db.String(36), nullable=False, index=True)
    label = db.Column(db.String(40), nullable=False)
    min_value = db.Column(db.Numeric(6, 2), nullable=False)
    max_value = db.Column(db.Numeric(6, 2), nullable=False)
    # For schemes that carry one. NULL where a school grades without points.
    grade_point = db.Column(db.Numeric(4, 2), nullable=True)
    is_pass = db.Column(db.Boolean, nullable=False, default=True)
    sequence = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    scheme = db.relationship("GradingScheme", back_populates="bands")

    def to_dict(self):
        return {
            "id": self.id,
            "label": self.label,
            "min_value": float(self.min_value),
            "max_value": float(self.max_value),
            "grade_point": float(self.grade_point) if self.grade_point is not None else None,
            "is_pass": self.is_pass,
            "sequence": self.sequence,
        }


class Examination(TenantBaseModel):
    """An assessment event the school holds.

    Belongs to an **AcademicCycle** — when the school is actually open — and
    optionally to a term. It declares no classes, grades or streams: its papers
    do (ADR-016).
    """

    __tablename__ = "examinations"
    __table_args__ = (
        # Named within its cycle. Two "Unit Test 1"s in one cycle are a picker
        # with two identical entries; the same name in the GSEB cycle and the
        # CBSE cycle is two different examinations.
        Index(
            "uq_examinations_cycle_name",
            "tenant_id",
            "academic_cycle_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("idx_examinations_cycle", "tenant_id", "academic_cycle_id"),
        Index("idx_examinations_status", "tenant_id", "status"),
        CheckConstraint(
            "status IN ('draft', 'scheduled', 'marks_entry', 'published', 'cancelled')",
            name="ck_examinations_status",
        ),
        db.UniqueConstraint("tenant_id", "id", name="uq_examinations_tenant_id_id"),
        db.ForeignKeyConstraint(
            ["tenant_id", "academic_cycle_id"],
            ["academic_cycles.tenant_id", "academic_cycles.id"],
            name="fk_examinations_cycle",
            ondelete="RESTRICT",
        ),
        db.ForeignKeyConstraint(
            ["tenant_id", "exam_type_id"],
            ["exam_types.tenant_id", "exam_types.id"],
            name="fk_examinations_exam_type",
            ondelete="RESTRICT",
        ),
        db.ForeignKeyConstraint(
            ["tenant_id", "grading_scheme_id"],
            ["grading_schemes.tenant_id", "grading_schemes.id"],
            name="fk_examinations_grading_scheme",
            ondelete="RESTRICT",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    academic_cycle_id = db.Column(db.String(36), nullable=False)
    # Optional on purpose: a board examination is scheduled by the board, and a
    # surprise unit test belongs to no term a school planned (ADR-017).
    academic_term_id = db.Column(
        db.String(36),
        db.ForeignKey("academic_terms.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    exam_type_id = db.Column(db.String(36), nullable=False)
    # Optional: a school that reports marks only names no scheme.
    grading_scheme_id = db.Column(db.String(36), nullable=True)

    name = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default=EXAM_DRAFT)

    # The calendar reservation this event sits in, where the school made one.
    # `exam_windows` is the calendar's booking of time and stays exactly what
    # it was; this is a reference, not a replacement (ADR-017).
    exam_window_id = db.Column(
        db.String(36),
        db.ForeignKey("exam_windows.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_by_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)

    papers = db.relationship(
        "ExamPaper", back_populates="examination", cascade="all, delete-orphan"
    )

    def to_dict(self):
        return {
            "id": self.id,
            "academic_cycle_id": self.academic_cycle_id,
            "academic_term_id": self.academic_term_id,
            "exam_type_id": self.exam_type_id,
            "grading_scheme_id": self.grading_scheme_id,
            "exam_window_id": self.exam_window_id,
            "name": self.name,
            "description": self.description,
            "status": self.status,
        }


class ExamPaper(TenantBaseModel):
    """One sitting: one subject, one section, one date.

    This is the grain a school actually schedules and a student actually sits.
    A "Half Yearly" for Grade 10 A with six subjects is six of these.

    **Theory and practical are two papers**, not one paper with parts. They are
    sat on different days, often in different rooms and marked by different
    people, and `component_label` says which is which so a result can add them
    back up.
    """

    __tablename__ = "exam_papers"
    __table_args__ = (
        # One paper per (examination, class subject, component). A school with
        # theory and practical has two rows; a second "Theory" for the same
        # offering is a duplicate.
        Index(
            "uq_exam_papers_offering_component",
            "tenant_id",
            "examination_id",
            "class_subject_id",
            "component_label",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("idx_exam_papers_examination", "tenant_id", "examination_id"),
        Index("idx_exam_papers_class", "tenant_id", "class_id"),
        Index("idx_exam_papers_date", "tenant_id", "exam_date"),
        CheckConstraint("max_marks > 0", name="ck_exam_papers_max_marks_positive"),
        CheckConstraint(
            "pass_marks IS NULL OR (pass_marks >= 0 AND pass_marks <= max_marks)",
            name="ck_exam_papers_pass_within_max",
        ),
        CheckConstraint(
            "ends_at IS NULL OR starts_at IS NULL OR starts_at < ends_at",
            name="ck_exam_papers_times_ordered",
        ),
        db.UniqueConstraint("tenant_id", "id", name="uq_exam_papers_tenant_id_id"),
        db.ForeignKeyConstraint(
            ["tenant_id", "examination_id"],
            ["examinations.tenant_id", "examinations.id"],
            name="fk_exam_papers_examination",
            ondelete="CASCADE",
        ),
        db.ForeignKeyConstraint(
            ["tenant_id", "class_subject_id"],
            ["class_subjects.tenant_id", "class_subjects.id"],
            name="fk_exam_papers_class_subject",
            ondelete="RESTRICT",
        ),
        # The denormalised `class_id` cannot contradict the offering it sits
        # beside (migration 116). The service never accepts a class from a
        # caller — it reads it off the offering — so this guards the paths
        # nobody has written yet.
        db.ForeignKeyConstraint(
            ["class_subject_id", "class_id"],
            ["class_subjects.id", "class_subjects.class_id"],
            name="fk_exam_papers_offering_matches_class",
            ondelete="RESTRICT",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    examination_id = db.Column(db.String(36), nullable=False)
    # The offering being examined — which already names the class and the
    # subject, and carries whether it is mandatory or elective. Denormalising
    # `class_id` beside it is what lets "every paper this section sits" be one
    # index rather than a join; the service keeps them in step.
    class_subject_id = db.Column(db.String(36), nullable=False)
    class_id = db.Column(
        db.String(36),
        db.ForeignKey("classes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    # "" for a single-sitting subject, "Theory"/"Practical"/"Internal" where a
    # school splits one. Empty rather than NULL so the unique index above bites
    # — Postgres treats every NULL as distinct.
    component_label = db.Column(
        db.String(40), nullable=False, default="", server_default=text("''")
    )

    exam_date = db.Column(db.Date, nullable=True)
    starts_at = db.Column(db.Time, nullable=True)
    ends_at = db.Column(db.Time, nullable=True)
    venue = db.Column(db.String(120), nullable=True)

    max_marks = db.Column(db.Numeric(6, 2), nullable=False)
    pass_marks = db.Column(db.Numeric(6, 2), nullable=True)
    # What this sitting is worth in the subject's total, where a school
    # weights. NULL means "its marks, as they are".
    weight = db.Column(db.Numeric(6, 2), nullable=True)

    instructions = db.Column(db.Text, nullable=True)

    # When the school closed this paper for marking. The examination's
    # `marks_entry` status is the outer boundary; this is the finer one, at the
    # grain a school actually finishes — the same shape attendance uses to
    # finalise one register at a time (migration 117).
    marks_locked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    marks_locked_by_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)

    examination = db.relationship("Examination", back_populates="papers")

    @property
    def marks_are_locked(self) -> bool:
        return self.marks_locked_at is not None

    def to_dict(self):
        return {
            "id": self.id,
            "examination_id": self.examination_id,
            "class_subject_id": self.class_subject_id,
            "class_id": self.class_id,
            "component_label": self.component_label or None,
            "exam_date": self.exam_date.isoformat() if self.exam_date else None,
            "max_marks": float(self.max_marks),
            "pass_marks": float(self.pass_marks) if self.pass_marks is not None else None,
        }


class ExamMark(TenantBaseModel):
    """What one student got for one paper — or why they got nothing.

    `marks_obtained` is NULL unless the student was present, enforced by a
    CHECK. An absent child is not a zero, and the two must never be the same
    row.
    """

    __tablename__ = "exam_marks"
    __table_args__ = (
        Index(
            "uq_exam_marks_paper_student",
            "tenant_id",
            "exam_paper_id",
            "student_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("idx_exam_marks_student", "tenant_id", "student_id"),
        CheckConstraint(
            "status IN ('present', 'absent', 'exempted', 'malpractice')",
            name="ck_exam_marks_status",
        ),
        # The rule that makes absence expressible: a mark exists only for
        # somebody who sat the paper.
        CheckConstraint(
            "(status = 'present' AND marks_obtained IS NOT NULL) OR "
            "(status <> 'present' AND marks_obtained IS NULL)",
            name="ck_exam_marks_present_has_marks",
        ),
        CheckConstraint(
            "marks_obtained IS NULL OR marks_obtained >= 0",
            name="ck_exam_marks_not_negative",
        ),
        db.UniqueConstraint("tenant_id", "id", name="uq_exam_marks_tenant_id_id"),
        db.ForeignKeyConstraint(
            ["tenant_id", "exam_paper_id"],
            ["exam_papers.tenant_id", "exam_papers.id"],
            name="fk_exam_marks_paper",
            ondelete="CASCADE",
        ),
        db.ForeignKeyConstraint(
            ["tenant_id", "student_id"],
            ["students.tenant_id", "students.id"],
            name="fk_exam_marks_student",
            ondelete="CASCADE",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    exam_paper_id = db.Column(db.String(36), nullable=False)
    student_id = db.Column(db.String(36), nullable=False)

    status = db.Column(db.String(20), nullable=False, default=MARK_PRESENT)
    marks_obtained = db.Column(db.Numeric(6, 2), nullable=True)
    remarks = db.Column(db.Text, nullable=True)

    entered_by_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    entered_at = db.Column(db.DateTime(timezone=True), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "exam_paper_id": self.exam_paper_id,
            "student_id": self.student_id,
            "status": self.status,
            "marks_obtained": (
                float(self.marks_obtained) if self.marks_obtained is not None else None
            ),
            "remarks": self.remarks,
        }


class ExamResult(TenantBaseModel):
    """A student's outcome for one examination, frozen at the moment it was published.

    **A snapshot, not a view.** The totals, the percentage and the grade are
    stored rather than recomputed, because a published result is a statement
    the school made on a date: a grading scheme edited in December must not
    change what a parent was told in August.

    **Revised, never edited.** A correction inserts version N+1 and leaves N
    where it is. `is_current` names the one in force, and the partial unique
    index below allows exactly one per student per examination.
    """

    __tablename__ = "exam_results"
    __table_args__ = (
        Index(
            "uq_exam_results_current",
            "tenant_id",
            "examination_id",
            "student_id",
            unique=True,
            postgresql_where=text("is_current = true AND deleted_at IS NULL"),
        ),
        Index(
            "uq_exam_results_version",
            "tenant_id",
            "examination_id",
            "student_id",
            "version",
            unique=True,
        ),
        Index("idx_exam_results_student", "tenant_id", "student_id"),
        CheckConstraint("version >= 1", name="ck_exam_results_version_positive"),
        db.ForeignKeyConstraint(
            ["tenant_id", "examination_id"],
            ["examinations.tenant_id", "examinations.id"],
            name="fk_exam_results_examination",
            ondelete="CASCADE",
        ),
        db.ForeignKeyConstraint(
            ["tenant_id", "student_id"],
            ["students.tenant_id", "students.id"],
            name="fk_exam_results_student",
            ondelete="CASCADE",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    examination_id = db.Column(db.String(36), nullable=False)
    student_id = db.Column(db.String(36), nullable=False)
    version = db.Column(db.Integer, nullable=False, default=1)
    is_current = db.Column(db.Boolean, nullable=False, default=True)

    # Frozen figures. Nullable because a result may be published for a student
    # who sat nothing, and because a school reporting grades only has no total.
    total_max = db.Column(db.Numeric(8, 2), nullable=True)
    total_obtained = db.Column(db.Numeric(8, 2), nullable=True)
    percentage = db.Column(db.Numeric(6, 3), nullable=True)
    grade_label = db.Column(db.String(40), nullable=True)
    is_pass = db.Column(db.Boolean, nullable=True)
    # The context the figures were computed in, kept so a reprint reads what it
    # read then even if the section was renamed or the child moved on.
    snapshot = db.Column(db.JSON, nullable=True)

    published_at = db.Column(db.DateTime(timezone=True), nullable=True)
    published_by_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revision_reason = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "examination_id": self.examination_id,
            "student_id": self.student_id,
            "version": self.version,
            "is_current": self.is_current,
            "total_max": float(self.total_max) if self.total_max is not None else None,
            "total_obtained": (
                float(self.total_obtained) if self.total_obtained is not None else None
            ),
            "percentage": float(self.percentage) if self.percentage is not None else None,
            "grade_label": self.grade_label,
            "is_pass": self.is_pass,
            "published_at": self.published_at.isoformat() if self.published_at else None,
        }


class ExaminationLifecycleEvent(TenantBaseModel):
    """What happened to an examination, in the order it happened.

    Append-only, the shape `student_lifecycle_events` and
    `staff_lifecycle_events` already use: a correction is a new event, never an
    edit to an old one.
    """

    __tablename__ = "examination_lifecycle_events"
    __table_args__ = (
        Index("idx_exam_lifecycle_examination", "tenant_id", "examination_id"),
        db.ForeignKeyConstraint(
            ["tenant_id", "examination_id"],
            ["examinations.tenant_id", "examinations.id"],
            name="fk_exam_lifecycle_examination",
            ondelete="CASCADE",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    examination_id = db.Column(db.String(36), nullable=False)
    # Named from docs/architecture/business-events.md, not invented in code.
    event_name = db.Column(db.String(60), nullable=False)
    occurred_on = db.Column(db.Date, nullable=False)
    note = db.Column(db.Text, nullable=True)
    actor_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)


class ExamMarkCorrection(TenantBaseModel):
    """A request to change a mark on a paper that has already been closed.

    The shape `attendance_corrections` established, for the same reason: once a
    register is closed, a change to it must not be the only evidence that it
    happened. So the request is written first, states what it is changing
    *from*, carries a reason, names who asked, and waits for someone who runs
    assessment to decide.

    **Never edited.** Approved and rejected are both terminal; a further change
    is another request. That is what makes a marksheet queried a year later
    answerable — what it said, what it says, who moved it and why.

    `from_status` / `from_marks` are not decoration. They are what makes a
    stale request refusable: if the mark moved between asking and deciding, the
    approval would otherwise write a number computed against a value nobody is
    looking at any more.
    """

    __tablename__ = "exam_mark_corrections"
    __table_args__ = (
        Index("idx_exam_mark_corrections_mark", "tenant_id", "exam_mark_id"),
        # The queue a reviewer opens; only the undecided ones are ever listed.
        Index(
            "idx_exam_mark_corrections_pending",
            "tenant_id",
            "status",
            postgresql_where=text("status = 'requested'"),
        ),
        CheckConstraint(
            "status IN ('requested', 'approved', 'rejected')",
            name="ck_exam_mark_corrections_status",
        ),
        # Both ends of the change obey the rule the mark itself obeys, so a
        # correction cannot describe a state a mark could not hold.
        CheckConstraint(
            "(from_status = 'present' AND from_marks IS NOT NULL) OR "
            "(from_status <> 'present' AND from_marks IS NULL)",
            name="ck_exam_mark_corrections_from_consistent",
        ),
        CheckConstraint(
            "(to_status = 'present' AND to_marks IS NOT NULL) OR "
            "(to_status <> 'present' AND to_marks IS NULL)",
            name="ck_exam_mark_corrections_to_consistent",
        ),
        CheckConstraint(
            "(from_marks IS NULL OR from_marks >= 0) AND "
            "(to_marks IS NULL OR to_marks >= 0)",
            name="ck_exam_mark_corrections_not_negative",
        ),
        db.ForeignKeyConstraint(
            ["tenant_id", "exam_mark_id"],
            ["exam_marks.tenant_id", "exam_marks.id"],
            name="fk_exam_mark_corrections_mark",
            ondelete="CASCADE",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    exam_mark_id = db.Column(db.String(36), nullable=False)

    from_status = db.Column(db.String(20), nullable=False)
    to_status = db.Column(db.String(20), nullable=False)
    from_marks = db.Column(db.Numeric(6, 2), nullable=True)
    to_marks = db.Column(db.Numeric(6, 2), nullable=True)

    # Required. A correction without a reason is an edit with extra steps.
    reason = db.Column(db.Text, nullable=False)

    status = db.Column(
        db.String(20), nullable=False, default=CORRECTION_REQUESTED, index=True
    )
    requested_by_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    requested_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now
    )
    decided_by_user_id = db.Column(
        db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at = db.Column(db.DateTime(timezone=True), nullable=True)
    decision_note = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    @property
    def is_decided(self) -> bool:
        return self.status != CORRECTION_REQUESTED

    def to_dict(self):
        return {
            "id": self.id,
            "exam_mark_id": self.exam_mark_id,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "from_marks": (
                float(self.from_marks) if self.from_marks is not None else None
            ),
            "to_marks": float(self.to_marks) if self.to_marks is not None else None,
            "reason": self.reason,
            "status": self.status,
            "requested_by_user_id": self.requested_by_user_id,
            "requested_at": (
                self.requested_at.isoformat() if self.requested_at else None
            ),
            "decided_by_user_id": self.decided_by_user_id,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "decision_note": self.decision_note,
        }

    def __repr__(self):
        return (
            f"<ExamMarkCorrection {self.from_status}->{self.to_status} {self.status}>"
        )
