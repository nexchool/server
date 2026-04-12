"""
Academic backbone — normalized offerings, scheduling, and daily attendance sessions.

Source of truth (new code):
- ClassSubject (class_subjects), ClassTeacherAssignment, StudentClassEnrollment
- TimetableVersion + TimetableEntry, BellSchedule + BellSchedulePeriod
- AttendanceSession + AttendanceRecord

Deprecated (backward compatibility; see migration 023 docstring):
- SubjectLoad (subject_load), TimetableSlot (timetable_slots), Attendance (attendance)
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Index, text

from core.database import db
from core.models import TenantBaseModel
from sqlalchemy.dialects.postgresql import JSONB


class AcademicSettings(TenantBaseModel):
    """One row per tenant — current year, defaults, feature flags."""

    __tablename__ = "academic_settings"
    __table_args__ = (db.UniqueConstraint("tenant_id", name="uq_academic_settings_tenant"),)

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    current_academic_year_id = db.Column(
        db.String(36),
        db.ForeignKey("academic_years.id", ondelete="SET NULL"),
        nullable=True,
    )
    default_bell_schedule_id = db.Column(
        db.String(36),
        db.ForeignKey("bell_schedules.id", ondelete="SET NULL"),
        nullable=True,
    )
    allow_admin_attendance_override = db.Column(db.Boolean, nullable=False, default=True)
    default_working_days_json = db.Column(JSONB, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=datetime.utcnow,
    )

    current_academic_year = db.relationship("AcademicYear", foreign_keys=[current_academic_year_id])
    default_bell_schedule = db.relationship("BellSchedule", foreign_keys=[default_bell_schedule_id])


class AcademicTerm(TenantBaseModel):
    __tablename__ = "academic_terms"
    __table_args__ = (
        Index(
            "uq_academic_terms_year_name",
            "tenant_id",
            "academic_year_id",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_academic_terms_year_code",
            "tenant_id",
            "academic_year_id",
            "code",
            unique=True,
            postgresql_where=text("code IS NOT NULL AND deleted_at IS NULL"),
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    academic_year_id = db.Column(
        db.String(36),
        db.ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(32), nullable=True)
    sequence = db.Column(db.SmallInteger, nullable=False, default=1)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=datetime.utcnow,
    )
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    academic_year = db.relationship("AcademicYear", foreign_keys=[academic_year_id])


class BellSchedule(TenantBaseModel):
    __tablename__ = "bell_schedules"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = db.Column(db.String(100), nullable=False)
    academic_year_id = db.Column(
        db.String(36),
        db.ForeignKey("academic_years.id", ondelete="SET NULL"),
        nullable=True,
    )
    day_of_week = db.Column(db.SmallInteger, nullable=True)
    is_default = db.Column(db.Boolean, nullable=False, default=False)
    valid_from = db.Column(db.Date, nullable=True)
    valid_to = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=datetime.utcnow,
    )
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    periods = db.relationship(
        "BellSchedulePeriod",
        back_populates="bell_schedule",
        cascade="all, delete-orphan",
    )


class BellSchedulePeriod(TenantBaseModel):
    __tablename__ = "bell_schedule_periods"
    __table_args__ = (
        db.UniqueConstraint(
            "bell_schedule_id",
            "period_number",
            name="uq_bell_schedule_periods_schedule_number",
        ),
        CheckConstraint("starts_at < ends_at", name="ck_bell_schedule_periods_start_before_end"),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    bell_schedule_id = db.Column(
        db.String(36),
        db.ForeignKey("bell_schedules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_number = db.Column(db.SmallInteger, nullable=False)
    period_kind = db.Column(db.String(20), nullable=False, default="lesson")
    starts_at = db.Column(db.Time, nullable=False)
    ends_at = db.Column(db.Time, nullable=False)
    label = db.Column(db.String(100), nullable=True)
    sort_order = db.Column(db.SmallInteger, nullable=False)

    bell_schedule = db.relationship("BellSchedule", back_populates="periods")


class ClassSubjectTeacher(TenantBaseModel):
    """Teacher assigned to teach a class_subject offering (primary / assistant / guest)."""

    __tablename__ = "class_subject_teachers"
    __table_args__ = (
        Index(
            "uq_cst_primary_active",
            "tenant_id",
            "class_subject_id",
            unique=True,
            postgresql_where=text("role = 'primary' AND is_active = true AND deleted_at IS NULL"),
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    class_subject_id = db.Column(
        db.String(36),
        db.ForeignKey("class_subjects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    teacher_id = db.Column(
        db.String(36),
        db.ForeignKey("teachers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = db.Column(db.String(20), nullable=False, default="primary")
    effective_from = db.Column(db.Date, nullable=True)
    effective_to = db.Column(db.Date, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=datetime.utcnow,
    )
    created_by = db.Column(db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by = db.Column(db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    class_subject = db.relationship("ClassSubject", back_populates="assigned_teachers")
    teacher = db.relationship("Teacher", foreign_keys=[teacher_id])


class ClassTeacherAssignment(TenantBaseModel):
    """
    Authoritative class teacher (and assistants). Primary should usually allow_attendance_marking.

    Replaces relying solely on classes.teacher_id (deprecated pointer; keep for legacy APIs).
    """

    __tablename__ = "class_teacher_assignments"
    __table_args__ = (
        Index(
            "uq_cta_primary_active_class",
            "tenant_id",
            "class_id",
            unique=True,
            postgresql_where=text("role = 'primary' AND is_active = true AND deleted_at IS NULL"),
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    class_id = db.Column(
        db.String(36),
        db.ForeignKey("classes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    teacher_id = db.Column(
        db.String(36),
        db.ForeignKey("teachers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role = db.Column(db.String(20), nullable=False, default="primary")
    allow_attendance_marking = db.Column(db.Boolean, nullable=False, default=False)
    effective_from = db.Column(db.Date, nullable=True)
    effective_to = db.Column(db.Date, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=datetime.utcnow,
    )
    created_by = db.Column(db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by = db.Column(db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    class_ref = db.relationship("Class", foreign_keys=[class_id])
    teacher = db.relationship("Teacher", foreign_keys=[teacher_id])


class StudentClassEnrollment(TenantBaseModel):
    """Enrollment history; is_current marks the active row for reporting."""

    __tablename__ = "student_class_enrollments"
    __table_args__ = (
        Index(
            "uq_sce_current_per_student_year",
            "tenant_id",
            "student_id",
            "academic_year_id",
            unique=True,
            postgresql_where=text("is_current = true"),
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    student_id = db.Column(
        db.String(36),
        db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    class_id = db.Column(
        db.String(36),
        db.ForeignKey("classes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    academic_year_id = db.Column(
        db.String(36),
        db.ForeignKey("academic_years.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    enrollment_status = db.Column(db.String(20), nullable=False, default="active")
    is_current = db.Column(db.Boolean, nullable=False, default=True)
    started_on = db.Column(db.Date, nullable=True)
    ended_on = db.Column(db.Date, nullable=True)
    promoted_from_enrollment_id = db.Column(
        db.String(36),
        db.ForeignKey("student_class_enrollments.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=datetime.utcnow,
    )

    student = db.relationship("Student", foreign_keys=[student_id], passive_deletes=True)
    class_ref = db.relationship("Class", foreign_keys=[class_id])
    academic_year = db.relationship("AcademicYear", foreign_keys=[academic_year_id])


class TimetableVersion(TenantBaseModel):
    __tablename__ = "timetable_versions"
    __table_args__ = (
        Index(
            "uq_timetable_versions_active_per_class",
            "tenant_id",
            "class_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    class_id = db.Column(
        db.String(36),
        db.ForeignKey("classes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bell_schedule_id = db.Column(
        db.String(36),
        db.ForeignKey("bell_schedules.id", ondelete="SET NULL"),
        nullable=True,
    )
    label = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(20), nullable=False, default="draft")
    effective_from = db.Column(db.Date, nullable=True)
    effective_to = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=datetime.utcnow,
    )
    created_by = db.Column(db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    class_ref = db.relationship("Class", foreign_keys=[class_id])
    bell_schedule = db.relationship("BellSchedule", foreign_keys=[bell_schedule_id])
    entries = db.relationship(
        "TimetableEntry",
        back_populates="timetable_version",
        cascade="all, delete-orphan",
    )


class TimetableEntry(TenantBaseModel):
    """Weekly recurring slot — independent from daily attendance."""

    __tablename__ = "timetable_entries"
    __table_args__ = (
        db.UniqueConstraint(
            "timetable_version_id",
            "day_of_week",
            "period_number",
            name="uq_timetable_entries_version_day_period",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    timetable_version_id = db.Column(
        db.String(36),
        db.ForeignKey("timetable_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    class_subject_id = db.Column(
        db.String(36),
        db.ForeignKey("class_subjects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    teacher_id = db.Column(
        db.String(36),
        db.ForeignKey("teachers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    day_of_week = db.Column(db.SmallInteger, nullable=False)
    period_number = db.Column(db.SmallInteger, nullable=False)
    room = db.Column(db.String(50), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    entry_status = db.Column(db.String(20), nullable=False, default="active")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=datetime.utcnow,
    )

    timetable_version = db.relationship("TimetableVersion", back_populates="entries")
    class_subject = db.relationship("ClassSubject", foreign_keys=[class_subject_id])
    teacher = db.relationship("Teacher", foreign_keys=[teacher_id])


class AttendanceSession(TenantBaseModel):
    """One session per class per calendar day — daily attendance, not period-wise."""

    __tablename__ = "attendance_sessions"
    __table_args__ = (
        Index(
            "uq_attendance_session_class_day",
            "tenant_id",
            "class_id",
            "session_date",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    class_id = db.Column(
        db.String(36),
        db.ForeignKey("classes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="draft")
    marked_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assigned_marker_teacher_id = db.Column(
        db.String(36),
        db.ForeignKey("teachers.id", ondelete="SET NULL"),
        nullable=True,
    )
    class_teacher_assignment_id = db.Column(
        db.String(36),
        db.ForeignKey("class_teacher_assignments.id", ondelete="SET NULL"),
        nullable=True,
    )
    attendance_source = db.Column(db.String(20), nullable=False, default="manual")
    taken_by_role = db.Column(db.String(20), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    marked_at = db.Column(db.DateTime(timezone=True), nullable=True)
    finalized_at = db.Column(db.DateTime(timezone=True), nullable=True)
    finalized_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=datetime.utcnow,
    )
    created_by = db.Column(db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_by = db.Column(db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    deleted_at = db.Column(db.DateTime(timezone=True), nullable=True)

    class_ref = db.relationship("Class", foreign_keys=[class_id])
    records = db.relationship(
        "AttendanceRecord",
        back_populates="session",
        cascade="all, delete-orphan",
    )


class AttendanceRecord(TenantBaseModel):
    __tablename__ = "attendance_records"
    __table_args__ = (
        db.UniqueConstraint(
            "attendance_session_id",
            "student_id",
            name="uq_attendance_records_session_student",
        ),
    )

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    attendance_session_id = db.Column(
        db.String(36),
        db.ForeignKey("attendance_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id = db.Column(
        db.String(36),
        db.ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status = db.Column(db.String(20), nullable=False)
    remarks = db.Column(db.Text, nullable=True)
    recorded_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    recorded_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=datetime.utcnow,
    )
    updated_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    session = db.relationship("AttendanceSession", back_populates="records")
    student = db.relationship("Student", foreign_keys=[student_id], passive_deletes=True)
