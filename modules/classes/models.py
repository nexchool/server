from core.database import db
from core.models import TenantBaseModel
from datetime import datetime
import uuid

from sqlalchemy import CheckConstraint, Index, text
from core.school_time import utc_now


class Class(TenantBaseModel):
    """
    Class/Section Model

    A specific class division for an academic year, scoped by tenant.

    Multi-school structure:
    - school_unit_id: which campus / sub-school the class belongs to
    - programme_id:   board + medium combo (e.g. CBSE-English, GSEB-Gujarati)
    - grade_id:       master grade (LKG..12); replaces free-text grade naming

    `name` is now an optional display label; identity is (school_unit,
    programme, grade, section, academic_year). The legacy `grade_level`
    smallint is kept for backward compatibility and will be removed once
    callers migrate to `grade_id`.
    """
    __tablename__ = "classes"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # Optional display label, e.g. "Grade 10" or "10 - CBSE English". Identity now lives on the FKs below.
    name = db.Column(db.String(50), nullable=True)
    section = db.Column(db.String(10), nullable=False)  # e.g. "A"
    stream = db.Column(
        db.String(32),
        nullable=True,
        index=True,
        comment="Grade 11-12 stream: Science, Commerce, Arts, Vocational. NULL for Grade 1-10.",
    )
    academic_year_id = db.Column(
        db.String(36),
        db.ForeignKey("academic_years.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    # Multi-school structure — kept nullable in Phase 1 so existing class
    # creation paths keep working until services are migrated. Tighten to
    # NOT NULL in a follow-up migration once all callers populate them.
    school_unit_id = db.Column(
        db.String(36),
        db.ForeignKey("school_units.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    programme_id = db.Column(
        db.String(36),
        db.ForeignKey("academic_programmes.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    grade_id = db.Column(
        db.String(36),
        db.ForeignKey("grades.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    medium_id = db.Column(
        db.String(36),
        db.ForeignKey("mediums.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    department_id = db.Column(
        db.String(36),
        db.ForeignKey("departments.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )

    # Academic year date bounds
    start_date = db.Column(db.Date, nullable=True)  # e.g. 2025-06-01
    end_date = db.Column(db.Date, nullable=True)     # e.g. 2026-03-31

    # Class-teacher CACHE (ADR-014): the owner is class_teacher_assignments;
    # nothing decides from this column. Keys on the teacher since migration
    # 095 — a class teacher is a teacher, not a login (they may have none).
    teacher_id = db.Column(
        db.String(36),
        db.ForeignKey("teachers.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Where this section went when it was merged into another, and when.
    # A merged section is never deleted: its attendance, its marks and its
    # reports stay attached to it, because they happened there. What changes
    # is that nothing new is placed into it (see section_merge.py).
    merged_into_class_id = db.Column(
        db.String(36),
        db.ForeignKey("classes.id", ondelete="SET NULL"),
        nullable=True,
    )
    merged_on = db.Column(db.Date, nullable=True)

    @property
    def is_merged_away(self) -> bool:
        """True when this section's future was moved elsewhere."""
        return self.merged_into_class_id is not None

    @property
    def display_name(self) -> str | None:
        """What a school calls this class — "5 A", "Nursery B".

        The grade first, because that is what names it; `name` only where
        there is no grade, and the legacy standard number only where there is
        neither. The section follows when there is one.

        One rule, on the thing itself, because every screen needs it and
        `name` is nullable: it is empty for every class the structured form
        creates, and each caller that composed its own label got it wrong —
        pages titled "— A", pickers offering a dozen options all reading "-A",
        a subject catalogue naming every class "A".
        """
        label = (
            (self.grade.name if self.grade else None)
            or self.name
            or (f"Grade {self.grade_level}" if self.grade_level is not None else None)
        )
        return " ".join(part for part in (label, self.section) if part) or None

    # DEPRECATED: free-text standard number. Use grade_id instead.
    grade_level = db.Column(db.SmallInteger, nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        # Structural identity: a section is unique within a
        # (tenant, school_unit, programme, grade, academic_year).
        db.UniqueConstraint(
            "tenant_id",
            "school_unit_id",
            "programme_id",
            "grade_id",
            "section",
            "academic_year_id",
            name="uq_classes_unit_programme_grade_section_year",
        ),
        # One teacher can only be class teacher of one class per tenant.
        db.UniqueConstraint(
            "teacher_id", "tenant_id",
            name="uq_classes_teacher_id_tenant",
        ),
        db.CheckConstraint(
            "stream IS NULL OR stream IN "
            "('Science', 'Commerce', 'Arts', 'Vocational')",
            name="ck_classes_stream",
        ),
    )

    # Relationships
    teacher = db.relationship('Teacher', foreign_keys=[teacher_id])
    academic_year_ref = db.relationship(
        "AcademicYear",
        foreign_keys=[academic_year_id],
        lazy=True,
    )
    school_unit = db.relationship(
        "SchoolUnit",
        foreign_keys=[school_unit_id],
        back_populates="class_records",
        lazy=True,
    )
    programme = db.relationship(
        "AcademicProgramme",
        foreign_keys=[programme_id],
        back_populates="class_records",
        lazy=True,
    )
    grade = db.relationship(
        "Grade",
        foreign_keys=[grade_id],
        back_populates="class_records",
        lazy=True,
    )
    medium = db.relationship(
        "Medium",
        foreign_keys=[medium_id],
        lazy=True,
    )
    department_ref = db.relationship("Department", foreign_keys=[department_id])

    def save(self):
        db.session.add(self)
        db.session.commit()

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            # What a school calls this class. `name` is a nullable legacy
            # label, so a client composing "`${name} - ${section}`" printed
            # "null - A" on every row; the rule lives on the model and both
            # transports carry its answer.
            "display_name": self.display_name,
            "section": self.section,
            "stream": self.stream,
            "grade_level": self.grade_level,
            "school_unit_id": self.school_unit_id,
            "school_unit_name": self.school_unit.name if self.school_unit else None,
            "programme_id": self.programme_id,
            "programme_name": self.programme.name if self.programme else None,
            "grade_id": self.grade_id,
            "grade_name": self.grade.name if self.grade else None,
            "grade_sequence": self.grade.sequence if self.grade else None,
            "medium_id": self.medium_id,
            "medium_name": self.medium.name if self.medium else None,
            "department_id": self.department_id,
            "department_name": self.department_ref.name if self.department_ref else None,
            "academic_year": self.academic_year_ref.name if self.academic_year_ref else None,
            "academic_year_id": self.academic_year_id,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            # teacher_id is a teachers.id since migration 095 — the same id
            # every teacher picker and assignment endpoint already speaks.
            "teacher_id": self.teacher_id,
            "teacher_name": (
                self.teacher.staff.person.full_name
                if self.teacher and self.teacher.staff and self.teacher.staff.person
                else None
            ),
            "created_at": self.created_at.isoformat(),
        }

    def __repr__(self):
        label = self.name or (self.grade.name if self.grade else "?")
        year = self.academic_year_ref.name if self.academic_year_ref else None
        return f"<Class {label}-{self.section} ({year})>"


class ClassSubject(TenantBaseModel):
    """
    Subject offering for a class (per academic year via Class.academic_year_id).

    Source of truth for weekly load and subject linkage. New code should use this table.

    DEPRECATED PARALLEL TABLE: subject_load — migrated in 023; kept for legacy routes until phase 2.
    """

    __tablename__ = "class_subjects"
    __table_args__ = (
        CheckConstraint("weekly_periods > 0", name="ck_class_subjects_weekly_periods_positive"),
        Index(
            "uq_class_subjects_active_class_subject",
            "tenant_id",
            "class_id",
            "subject_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND status = 'active'"),
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    class_id = db.Column(db.String(36), db.ForeignKey("classes.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_id = db.Column(db.String(36), db.ForeignKey("subjects.id", ondelete="RESTRICT"), nullable=False, index=True)
    weekly_periods = db.Column(db.SmallInteger, nullable=False)
    is_mandatory = db.Column(db.Boolean, nullable=False, default=True)
    is_elective_bucket = db.Column(db.Boolean, nullable=False, default=False)
    sort_order = db.Column(db.SmallInteger, nullable=True)
    academic_term_id = db.Column(
        db.String(36),
        db.ForeignKey("academic_terms.id", ondelete="SET NULL"),
        nullable=True,
    )
    status = db.Column(db.String(20), nullable=False, default="active")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=utc_now,
    )
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    class_ref = db.relationship(
        "Class",
        backref=db.backref("class_subjects", lazy=True, passive_deletes=True),
    )
    subject_ref = db.relationship("Subject", foreign_keys=[subject_id], lazy=True)
    assigned_teachers = db.relationship(
        "ClassSubjectTeacher",
        back_populates="class_subject",
        lazy=True,
    )


class SubjectLoad(TenantBaseModel):
    """
    DEPRECATED: use ClassSubject (class_subjects) — see migration 023.

    Subject Weekly Period Load per Class.

    Defines how many periods per week a given subject should be scheduled
    for a specific class. Used by the timetable generator as a constraint.
    Unique per (class_id, subject_id, tenant_id).
    """
    __tablename__ = "subject_load"
    __table_args__ = (
        db.UniqueConstraint("class_id", "subject_id", "tenant_id", name="uq_subject_load_class_subject_tenant"),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    class_id = db.Column(db.String(36), db.ForeignKey("classes.id", ondelete="CASCADE"), nullable=False, index=True)
    subject_id = db.Column(db.String(36), db.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False, index=True)
    weekly_periods = db.Column(db.Integer, nullable=False, default=1)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    class_ref = db.relationship(
        "Class",
        backref=db.backref("subject_loads", lazy=True, passive_deletes=True),
    )
    subject_ref = db.relationship("Subject", backref=db.backref("class_loads", lazy=True))

    def save(self):
        db.session.add(self)
        db.session.commit()

    def delete(self):
        db.session.delete(self)
        db.session.commit()

    def to_dict(self):
        return {
            "id": self.id,
            "class_id": self.class_id,
            "subject_id": self.subject_id,
            "subject_name": self.subject_ref.name if self.subject_ref else None,
            "subject_code": self.subject_ref.code if self.subject_ref else None,
            "weekly_periods": self.weekly_periods,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def __repr__(self):
        return f"<SubjectLoad class={self.class_id} subject={self.subject_id} weekly={self.weekly_periods}>"
