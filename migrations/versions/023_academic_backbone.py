"""Academic backbone: class_subjects, timetable versions, daily attendance sessions, bell schedules, etc.

Revision ID: 023_academic_backbone
Revises: 022_tenant_school_details

PHASE 1 (this migration):
- Extends academic_years, subjects
- Adds academic_settings, academic_terms, class_subjects (copy from subject_load), class_subject_teachers,
  class_teacher_assignments, student_class_enrollments, bell_schedules, bell_schedule_periods,
  timetable_versions, timetable_entries, attendance_sessions, attendance_records
- Migrates timetable_slots -> timetable_versions + timetable_entries; backfills schedule_overrides.timetable_entry_id
- Migrates attendance -> attendance_sessions + attendance_records

DEPRECATED (keep for backward compatibility; remove in phase 2 cleanup):
- subject_load table — use class_subjects as source of truth for new code
- timetable_slots table — use timetable_entries + timetable_versions for new code
- attendance table — use attendance_sessions + attendance_records for new code
- schedule_overrides.slot_id — prefer timetable_entry_id when set

NEW SOURCE OF TRUTH:
- class_subjects, class_teacher_assignments, student_class_enrollments,
  timetable_versions + timetable_entries, attendance_sessions + attendance_records
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB

revision = "023_academic_backbone"
down_revision = "022_tenant_school_details"
branch_labels = None
depends_on = None


def _utcnow():
    return datetime.now(timezone.utc)


def upgrade():
    conn = op.get_bind()

    # --- 1. academic_years: calendar_code (tenant_id already exists from 006) ---
    op.add_column(
        "academic_years",
        sa.Column("calendar_code", sa.String(32), nullable=True),
    )

    # --- 2. subjects: new columns ---
    op.add_column("subjects", sa.Column("subject_type", sa.String(20), nullable=False, server_default="core"))
    op.add_column("subjects", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("subjects", sa.Column("default_grading_scale_id", sa.String(36), nullable=True))
    op.add_column("subjects", sa.Column("metadata_json", JSONB, nullable=True))
    op.add_column("subjects", sa.Column("created_by", sa.String(36), nullable=True))
    op.add_column("subjects", sa.Column("updated_by", sa.String(36), nullable=True))
    op.add_column(
        "subjects",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key("fk_subjects_created_by", "subjects", "users", ["created_by"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_subjects_updated_by", "subjects", "users", ["updated_by"], ["id"], ondelete="SET NULL")
    op.create_index("ix_subjects_tenant_active", "subjects", ["tenant_id", "is_active"])
    op.create_index("ix_subjects_tenant_type", "subjects", ["tenant_id", "subject_type"])
    op.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_subjects_tenant_code_active
            ON subjects (tenant_id, code)
            WHERE code IS NOT NULL AND deleted_at IS NULL
            """
        )
    )

    # --- 3. bell_schedules ---
    op.create_table(
        "bell_schedules",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("academic_year_id", sa.String(36), nullable=True),
        sa.Column("day_of_week", sa.SmallInteger(), nullable=True),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bell_schedules_tenant_id", "bell_schedules", ["tenant_id"])
    # NOTE: Enforce at most one default bell schedule per (tenant, year, day) in application
    # layer; partial unique here is ambiguous when day_of_week / academic_year_id are NULL.

    # --- 4. bell_schedule_periods ---
    op.create_table(
        "bell_schedule_periods",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("bell_schedule_id", sa.String(36), nullable=False),
        sa.Column("period_number", sa.SmallInteger(), nullable=False),
        sa.Column("period_kind", sa.String(20), nullable=False, server_default="lesson"),
        sa.Column("starts_at", sa.Time(), nullable=False),
        sa.Column("ends_at", sa.Time(), nullable=False),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["bell_schedule_id"], ["bell_schedules.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bell_schedule_id", "period_number", name="uq_bell_schedule_periods_schedule_number"),
        sa.CheckConstraint("starts_at < ends_at", name="ck_bell_schedule_periods_start_before_end"),
    )
    op.create_index("ix_bell_schedule_periods_tenant_id", "bell_schedule_periods", ["tenant_id"])
    op.create_index("ix_bell_schedule_periods_schedule_id", "bell_schedule_periods", ["bell_schedule_id"])

    # --- 5. academic_settings (one row per tenant) ---
    op.create_table(
        "academic_settings",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("current_academic_year_id", sa.String(36), nullable=True),
        sa.Column("default_bell_schedule_id", sa.String(36), nullable=True),
        sa.Column("attendance_mode", sa.String(20), nullable=False, server_default="daily"),
        sa.Column("allow_teacher_timetable_override", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("allow_admin_attendance_override", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("default_working_days_json", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["current_academic_year_id"], ["academic_years.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["default_bell_schedule_id"], ["bell_schedules.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", name="uq_academic_settings_tenant"),
    )

    # Seed academic_settings for each tenant (idempotent pattern: one row per tenant)
    tenant_rows = conn.execute(text("SELECT id FROM tenants")).fetchall()
    for (tid,) in tenant_rows:
        conn.execute(
            text(
                """
                INSERT INTO academic_settings (id, tenant_id, created_at, updated_at)
                VALUES (:id, :tid, now(), now())
                """
            ),
            {"id": str(uuid.uuid4()), "tid": tid},
        )

    # --- 6. academic_terms ---
    op.create_table(
        "academic_terms",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("academic_year_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("code", sa.String(32), nullable=True),
        sa.Column("sequence", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_academic_terms_tenant_year", "academic_terms", ["tenant_id", "academic_year_id"])
    op.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_academic_terms_year_name
            ON academic_terms (tenant_id, academic_year_id, name)
            WHERE deleted_at IS NULL
            """
        )
    )
    op.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_academic_terms_year_code
            ON academic_terms (tenant_id, academic_year_id, code)
            WHERE code IS NOT NULL AND deleted_at IS NULL
            """
        )
    )

    # --- 7. class_subjects ---
    op.create_table(
        "class_subjects",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("class_id", sa.String(36), nullable=False),
        sa.Column("subject_id", sa.String(36), nullable=False),
        sa.Column("weekly_periods", sa.SmallInteger(), nullable=False),
        sa.Column("is_mandatory", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_elective_bucket", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("sort_order", sa.SmallInteger(), nullable=True),
        sa.Column("academic_term_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["academic_term_id"], ["academic_terms.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("weekly_periods > 0", name="ck_class_subjects_weekly_periods_positive"),
    )
    op.create_index("ix_class_subjects_tenant_class", "class_subjects", ["tenant_id", "class_id"])
    op.create_index("ix_class_subjects_tenant_subject", "class_subjects", ["tenant_id", "subject_id"])
    op.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_class_subjects_active_class_subject
            ON class_subjects (tenant_id, class_id, subject_id)
            WHERE deleted_at IS NULL AND status = 'active'
            """
        )
    )

    # Copy subject_load -> class_subjects
    sl_rows = conn.execute(
        text(
            """
            SELECT id, tenant_id, class_id, subject_id, weekly_periods, created_at, updated_at
            FROM subject_load
            """
        )
    ).fetchall()
    for row in sl_rows:
        old_id, tenant_id, class_id, subject_id, weekly_periods, created_at, updated_at = row
        new_id = str(uuid.uuid4())
        conn.execute(
            text(
                """
                INSERT INTO class_subjects (
                    id, tenant_id, class_id, subject_id, weekly_periods,
                    is_mandatory, is_elective_bucket, sort_order, academic_term_id, status,
                    created_at, updated_at, deleted_at
                ) VALUES (
                    :id, :tenant_id, :class_id, :subject_id, :weekly_periods,
                    true, false, null, null, 'active',
                    :created_at, :updated_at, null
                )
                """
            ),
            {
                "id": new_id,
                "tenant_id": tenant_id,
                "class_id": class_id,
                "subject_id": subject_id,
                "weekly_periods": int(weekly_periods),
                "created_at": created_at or _utcnow(),
                "updated_at": updated_at or _utcnow(),
            },
        )

    # Ensure class_subjects rows for (class_id, subject_id) appearing in timetable_slots but not in subject_load
    orphan_slots = conn.execute(
        text(
            """
            SELECT DISTINCT ts.tenant_id, ts.class_id, ts.subject_id
            FROM timetable_slots ts
            WHERE NOT EXISTS (
                SELECT 1 FROM class_subjects cs
                WHERE cs.class_id = ts.class_id AND cs.subject_id = ts.subject_id
                AND cs.tenant_id = ts.tenant_id AND cs.deleted_at IS NULL AND cs.status = 'active'
            )
            """
        )
    ).fetchall()
    for tenant_id, class_id, subject_id in orphan_slots:
        conn.execute(
            text(
                """
                INSERT INTO class_subjects (
                    id, tenant_id, class_id, subject_id, weekly_periods,
                    is_mandatory, is_elective_bucket, sort_order, academic_term_id, status,
                    created_at, updated_at, deleted_at
                ) VALUES (
                    :id, :tenant_id, :class_id, :subject_id, 1,
                    true, false, null, null, 'active',
                    now(), now(), null
                )
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "tenant_id": tenant_id,
                "class_id": class_id,
                "subject_id": subject_id,
            },
        )

    # --- 8. class_subject_teachers ---
    op.create_table(
        "class_subject_teachers",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("class_subject_id", sa.String(36), nullable=False),
        sa.Column("teacher_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="primary"),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["class_subject_id"], ["class_subjects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cst_tenant_cs", "class_subject_teachers", ["tenant_id", "class_subject_id"])
    op.create_index("ix_cst_teacher", "class_subject_teachers", ["teacher_id"])
    op.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_cst_primary_active
            ON class_subject_teachers (tenant_id, class_subject_id)
            WHERE role = 'primary' AND is_active = true AND deleted_at IS NULL
            """
        )
    )

    # Backfill from class_teachers where subject_id is set
    ct_rows = conn.execute(
        text(
            """
            SELECT ct.tenant_id, ct.teacher_id, ct.class_id, ct.subject_id
            FROM class_teachers ct
            WHERE ct.subject_id IS NOT NULL
            """
        )
    ).fetchall()
    for tenant_id, teacher_id, class_id, subject_id in ct_rows:
        cs = conn.execute(
            text(
                """
                SELECT id FROM class_subjects
                WHERE tenant_id = :tid AND class_id = :cid AND subject_id = :sid
                AND deleted_at IS NULL AND status = 'active'
                LIMIT 1
                """
            ),
            {"tid": tenant_id, "cid": class_id, "sid": subject_id},
        ).fetchone()
        if not cs:
            continue
        class_subject_id = cs[0]
        exists = conn.execute(
            text(
                """
                SELECT 1 FROM class_subject_teachers
                WHERE class_subject_id = :csid AND role = 'primary' AND deleted_at IS NULL
                LIMIT 1
                """
            ),
            {"csid": class_subject_id},
        ).fetchone()
        if exists:
            continue
        conn.execute(
            text(
                """
                INSERT INTO class_subject_teachers (
                    id, tenant_id, class_subject_id, teacher_id, role,
                    effective_from, effective_to, is_active, created_at, updated_at, deleted_at
                ) VALUES (
                    :id, :tid, :csid, :teid, 'primary', null, null, true, now(), now(), null
                )
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "tid": tenant_id,
                "csid": class_subject_id,
                "teid": teacher_id,
            },
        )

    # --- 9. class_teacher_assignments ---
    op.create_table(
        "class_teacher_assignments",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("class_id", sa.String(36), nullable=False),
        sa.Column("teacher_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="primary"),
        sa.Column("allow_attendance_marking", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_cta_tenant_class", "class_teacher_assignments", ["tenant_id", "class_id"])
    op.create_index("ix_cta_teacher", "class_teacher_assignments", ["teacher_id"])
    op.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_cta_primary_active_class
            ON class_teacher_assignments (tenant_id, class_id)
            WHERE role = 'primary' AND is_active = true AND deleted_at IS NULL
            """
        )
    )

    # Backfill from classes.teacher_id (users.id -> teachers.id)
    cls_rows = conn.execute(
        text(
            """
            SELECT c.id, c.tenant_id, c.teacher_id
            FROM classes c
            WHERE c.teacher_id IS NOT NULL
            """
        )
    ).fetchall()
    covered_classes = set()
    for class_id, tenant_id, user_teacher_id in cls_rows:
        trow = conn.execute(
            text("SELECT id FROM teachers WHERE user_id = :uid AND tenant_id = :tid LIMIT 1"),
            {"uid": user_teacher_id, "tid": tenant_id},
        ).fetchone()
        if not trow:
            continue
        teacher_pk = trow[0]
        conn.execute(
            text(
                """
                INSERT INTO class_teacher_assignments (
                    id, tenant_id, class_id, teacher_id, role, allow_attendance_marking,
                    effective_from, effective_to, is_active, created_at, updated_at, deleted_at
                ) VALUES (
                    :id, :tid, :cid, :teid, 'primary', true,
                    null, null, true, now(), now(), null
                )
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "tid": tenant_id,
                "cid": class_id,
                "teid": teacher_pk,
            },
        )
        covered_classes.add(class_id)

    # Backfill from class_teachers.is_class_teacher where class not covered
    ct_ct = conn.execute(
        text(
            """
            SELECT ct.tenant_id, ct.class_id, ct.teacher_id
            FROM class_teachers ct
            WHERE ct.is_class_teacher = true
            """
        )
    ).fetchall()
    for tenant_id, class_id, teacher_id in ct_ct:
        if class_id in covered_classes:
            continue
        exists = conn.execute(
            text(
                "SELECT 1 FROM class_teacher_assignments WHERE class_id = :cid AND tenant_id = :tid "
                "AND role = 'primary' AND is_active = true AND deleted_at IS NULL LIMIT 1"
            ),
            {"cid": class_id, "tid": tenant_id},
        ).fetchone()
        if exists:
            covered_classes.add(class_id)
            continue
        conn.execute(
            text(
                """
                INSERT INTO class_teacher_assignments (
                    id, tenant_id, class_id, teacher_id, role, allow_attendance_marking,
                    effective_from, effective_to, is_active, created_at, updated_at, deleted_at
                ) VALUES (
                    :id, :tid, :cid, :teid, 'primary', true,
                    null, null, true, now(), now(), null
                )
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "tid": tenant_id,
                "cid": class_id,
                "teid": teacher_id,
            },
        )
        covered_classes.add(class_id)

    # --- 10. student_class_enrollments ---
    op.create_table(
        "student_class_enrollments",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("student_id", sa.String(36), nullable=False),
        sa.Column("class_id", sa.String(36), nullable=False),
        sa.Column("academic_year_id", sa.String(36), nullable=False),
        sa.Column("enrollment_status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("started_on", sa.Date(), nullable=True),
        sa.Column("ended_on", sa.Date(), nullable=True),
        sa.Column("promoted_from_enrollment_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["promoted_from_enrollment_id"], ["student_class_enrollments.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sce_tenant_student", "student_class_enrollments", ["tenant_id", "student_id"])
    op.create_index("ix_sce_class", "student_class_enrollments", ["class_id"])
    op.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_sce_current_per_student_year
            ON student_class_enrollments (tenant_id, student_id, academic_year_id)
            WHERE is_current = true
            """
        )
    )

    st_rows = conn.execute(
        text(
            """
            SELECT s.id, s.tenant_id, s.class_id, c.academic_year_id
            FROM students s
            INNER JOIN classes c ON c.id = s.class_id
            WHERE s.class_id IS NOT NULL AND c.academic_year_id IS NOT NULL
            """
        )
    ).fetchall()
    for student_id, tenant_id, class_id, academic_year_id in st_rows:
        conn.execute(
            text(
                """
                INSERT INTO student_class_enrollments (
                    id, tenant_id, student_id, class_id, academic_year_id,
                    enrollment_status, is_current, started_on, ended_on, promoted_from_enrollment_id,
                    created_at, updated_at
                ) VALUES (
                    :id, :tid, :sid, :cid, :ayid,
                    'active', true, null, null, null,
                    now(), now()
                )
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "tid": tenant_id,
                "sid": student_id,
                "cid": class_id,
                "ayid": academic_year_id,
            },
        )

    # --- 11. timetable_versions ---
    op.create_table(
        "timetable_versions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("class_id", sa.String(36), nullable=False),
        sa.Column("bell_schedule_id", sa.String(36), nullable=True),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["bell_schedule_id"], ["bell_schedules.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ttv_tenant_class", "timetable_versions", ["tenant_id", "class_id"])
    op.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_timetable_versions_active_per_class
            ON timetable_versions (tenant_id, class_id)
            WHERE status = 'active'
            """
        )
    )

    # One active version per class that has timetable_slots
    distinct_classes = conn.execute(
        text("SELECT DISTINCT class_id, tenant_id FROM timetable_slots")
    ).fetchall()
    class_to_version = {}
    for class_id, tenant_id in distinct_classes:
        vid = str(uuid.uuid4())
        conn.execute(
            text(
                """
                INSERT INTO timetable_versions (
                    id, tenant_id, class_id, bell_schedule_id, label, status,
                    effective_from, effective_to, created_at, updated_at, created_by
                ) VALUES (
                    :id, :tid, :cid, null, 'Migrated v1', 'active',
                    null, null, now(), now(), null
                )
                """
            ),
            {"id": vid, "tid": tenant_id, "cid": class_id},
        )
        class_to_version[class_id] = vid

    # --- 12. timetable_entries ---
    op.create_table(
        "timetable_entries",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("timetable_version_id", sa.String(36), nullable=False),
        sa.Column("class_subject_id", sa.String(36), nullable=False),
        sa.Column("teacher_id", sa.String(36), nullable=True),
        sa.Column("day_of_week", sa.SmallInteger(), nullable=False),
        sa.Column("period_number", sa.SmallInteger(), nullable=False),
        sa.Column("room", sa.String(50), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("entry_status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["timetable_version_id"], ["timetable_versions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["class_subject_id"], ["class_subjects.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "timetable_version_id",
            "day_of_week",
            "period_number",
            name="uq_timetable_entries_version_day_period",
        ),
    )
    op.create_index("ix_te_tenant_version", "timetable_entries", ["tenant_id", "timetable_version_id"])
    op.create_index("ix_te_teacher", "timetable_entries", ["teacher_id"])

    slot_to_entry = {}
    slot_rows = conn.execute(
        text(
            """
            SELECT ts.id, ts.tenant_id, ts.class_id, ts.subject_id, ts.teacher_id,
                   ts.day_of_week, ts.period_number, ts.room, ts.created_at, ts.updated_at
            FROM timetable_slots ts
            """
        )
    ).fetchall()
    for (
        slot_id,
        tenant_id,
        class_id,
        subject_id,
        teacher_id,
        dow,
        period,
        room,
        created_at,
        updated_at,
    ) in slot_rows:
        vid = class_to_version.get(class_id)
        if not vid:
            continue
        cs = conn.execute(
            text(
                """
                SELECT id FROM class_subjects
                WHERE tenant_id = :tid AND class_id = :cid AND subject_id = :sid
                AND deleted_at IS NULL AND status = 'active'
                LIMIT 1
                """
            ),
            {"tid": tenant_id, "cid": class_id, "sid": subject_id},
        ).fetchone()
        if not cs:
            continue
        class_subject_id = cs[0]
        eid = str(uuid.uuid4())
        conn.execute(
            text(
                """
                INSERT INTO timetable_entries (
                    id, tenant_id, timetable_version_id, class_subject_id, teacher_id,
                    day_of_week, period_number, room, notes, entry_status, created_at, updated_at
                ) VALUES (
                    :id, :tid, :vid, :csid, :teid,
                    :dow, :period, :room, null, 'active', :created_at, :updated_at
                )
                """
            ),
            {
                "id": eid,
                "tid": tenant_id,
                "vid": vid,
                "csid": class_subject_id,
                "teid": teacher_id,
                "dow": int(dow),
                "period": int(period),
                "room": room,
                "created_at": created_at or _utcnow(),
                "updated_at": updated_at or _utcnow(),
            },
        )
        slot_to_entry[slot_id] = eid

    # --- 13. schedule_overrides: add timetable_entry_id, override_scope; relax slot_id ---
    op.add_column("schedule_overrides", sa.Column("override_scope", sa.String(20), nullable=True))
    op.add_column(
        "schedule_overrides",
        sa.Column("timetable_entry_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "fk_schedule_overrides_timetable_entry",
        "schedule_overrides",
        "timetable_entries",
        ["timetable_entry_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_schedule_overrides_timetable_entry_id", "schedule_overrides", ["timetable_entry_id"])

    for slot_id, entry_id in slot_to_entry.items():
        conn.execute(
            text("UPDATE schedule_overrides SET timetable_entry_id = :eid WHERE slot_id = :sid"),
            {"eid": entry_id, "sid": slot_id},
        )

    op.drop_constraint("uq_schedule_override_slot_date", "schedule_overrides", type_="unique")
    op.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_schedule_override_slot_date
            ON schedule_overrides (slot_id, override_date)
            WHERE slot_id IS NOT NULL
            """
        )
    )
    op.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_schedule_override_entry_date
            ON schedule_overrides (timetable_entry_id, override_date)
            WHERE timetable_entry_id IS NOT NULL
            """
        )
    )

    # New overrides may reference only timetable_entry_id; legacy rows keep slot_id populated.
    op.alter_column(
        "schedule_overrides",
        "slot_id",
        existing_type=sa.String(36),
        nullable=True,
    )

    # --- 14. attendance_sessions ---
    op.create_table(
        "attendance_sessions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("class_id", sa.String(36), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("marked_by_user_id", sa.String(36), nullable=True),
        sa.Column("assigned_marker_teacher_id", sa.String(36), nullable=True),
        sa.Column("class_teacher_assignment_id", sa.String(36), nullable=True),
        sa.Column("attendance_source", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("taken_by_role", sa.String(20), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("marked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_by_user_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("updated_by", sa.String(36), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["marked_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assigned_marker_teacher_id"], ["teachers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["class_teacher_assignment_id"], ["class_teacher_assignments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["finalized_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_att_sess_tenant_class_date", "attendance_sessions", ["tenant_id", "class_id", "session_date"])
    op.create_index("ix_att_sess_date", "attendance_sessions", ["session_date"])
    op.execute(
        text(
            """
            CREATE UNIQUE INDEX uq_attendance_session_class_day
            ON attendance_sessions (tenant_id, class_id, session_date)
            WHERE deleted_at IS NULL
            """
        )
    )

    # --- 15. attendance_records ---
    op.create_table(
        "attendance_records",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("attendance_session_id", sa.String(36), nullable=False),
        sa.Column("student_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("recorded_by_user_id", sa.String(36), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_by_user_id", sa.String(36), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["attendance_session_id"], ["attendance_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recorded_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attendance_session_id", "student_id", name="uq_attendance_records_session_student"),
    )
    op.create_index("ix_ar_tenant_student", "attendance_records", ["tenant_id", "student_id"])

    # Migrate attendance -> sessions + records
    groups = conn.execute(
        text(
            """
            SELECT DISTINCT ON (tenant_id, class_id, date)
                tenant_id, class_id, date, marked_by
            FROM attendance
            ORDER BY tenant_id, class_id, date, updated_at DESC NULLS LAST
            """
        )
    ).fetchall()

    session_map = {}  # (tenant_id, class_id, date) -> session_id
    for tenant_id, class_id, att_date, marked_by in groups:
        cta = conn.execute(
            text(
                """
                SELECT id FROM class_teacher_assignments
                WHERE tenant_id = :tid AND class_id = :cid AND role = 'primary'
                AND is_active = true AND deleted_at IS NULL
                LIMIT 1
                """
            ),
            {"tid": tenant_id, "cid": class_id},
        ).fetchone()
        cta_id = cta[0] if cta else None
        sid = str(uuid.uuid4())
        conn.execute(
            text(
                """
                INSERT INTO attendance_sessions (
                    id, tenant_id, class_id, session_date, status,
                    marked_by_user_id, assigned_marker_teacher_id, class_teacher_assignment_id,
                    attendance_source, taken_by_role, notes, marked_at, finalized_at, finalized_by_user_id,
                    created_at, updated_at, created_by, updated_by, deleted_at
                ) VALUES (
                    :id, :tid, :cid, :sdate, 'finalized',
                    :mb, null, :cta,
                    'manual', null, null, now(), now(), :mb,
                    now(), now(), null, null, null
                )
                """
            ),
            {
                "id": sid,
                "tid": tenant_id,
                "cid": class_id,
                "sdate": att_date,
                "mb": marked_by,
                "cta": cta_id,
            },
        )
        session_map[(tenant_id, class_id, att_date)] = sid

    att_rows = conn.execute(
        text(
            """
            SELECT tenant_id, class_id, date, student_id, status, remarks, marked_by, created_at, updated_at
            FROM attendance
            """
        )
    ).fetchall()
    for tenant_id, class_id, att_date, student_id, status, remarks, marked_by, created_at, updated_at in att_rows:
        sk = (tenant_id, class_id, att_date)
        session_id = session_map.get(sk)
        if not session_id:
            continue
        conn.execute(
            text(
                """
                INSERT INTO attendance_records (
                    id, tenant_id, attendance_session_id, student_id, status, remarks,
                    recorded_by_user_id, recorded_at, updated_at, updated_by_user_id
                ) VALUES (
                    :id, :tid, :asid, :sid, :st, :rm,
                    :rb, :ca, :ua, null
                )
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "tid": tenant_id,
                "asid": session_id,
                "sid": student_id,
                "st": status,
                "rm": remarks,
                "rb": marked_by,
                "ca": created_at or _utcnow(),
                "ua": updated_at or _utcnow(),
            },
        )


def downgrade():
    op.drop_table("attendance_records")
    op.drop_table("attendance_sessions")

    op.drop_index("uq_schedule_override_entry_date", table_name="schedule_overrides")
    op.drop_index("uq_schedule_override_slot_date", table_name="schedule_overrides")
    op.drop_constraint("fk_schedule_overrides_timetable_entry", "schedule_overrides", type_="foreignkey")
    op.drop_index("ix_schedule_overrides_timetable_entry_id", table_name="schedule_overrides")
    op.drop_column("schedule_overrides", "timetable_entry_id")
    op.drop_column("schedule_overrides", "override_scope")
    op.alter_column(
        "schedule_overrides",
        "slot_id",
        existing_type=sa.String(36),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_schedule_override_slot_date",
        "schedule_overrides",
        ["slot_id", "override_date"],
    )

    op.drop_table("timetable_entries")
    op.drop_table("timetable_versions")

    op.drop_table("student_class_enrollments")

    op.drop_index("uq_cta_primary_active_class", table_name="class_teacher_assignments")
    op.drop_table("class_teacher_assignments")

    op.drop_index("uq_cst_primary_active", table_name="class_subject_teachers")
    op.drop_table("class_subject_teachers")

    op.drop_index("uq_class_subjects_active_class_subject", table_name="class_subjects")
    op.drop_table("class_subjects")

    op.drop_index("uq_academic_terms_year_code", table_name="academic_terms")
    op.drop_index("uq_academic_terms_year_name", table_name="academic_terms")
    op.drop_table("academic_terms")

    op.drop_table("academic_settings")

    op.drop_table("bell_schedule_periods")
    op.drop_table("bell_schedules")

    op.drop_constraint("fk_subjects_updated_by", "subjects", type_="foreignkey")
    op.drop_constraint("fk_subjects_created_by", "subjects", type_="foreignkey")
    op.drop_index("uq_subjects_tenant_code_active", table_name="subjects")
    op.drop_index("ix_subjects_tenant_type", table_name="subjects")
    op.drop_index("ix_subjects_tenant_active", table_name="subjects")
    op.drop_column("subjects", "deleted_at")
    op.drop_column("subjects", "updated_by")
    op.drop_column("subjects", "created_by")
    op.drop_column("subjects", "metadata_json")
    op.drop_column("subjects", "default_grading_scale_id")
    op.drop_column("subjects", "is_active")
    op.drop_column("subjects", "subject_type")

    op.drop_column("academic_years", "calendar_code")
