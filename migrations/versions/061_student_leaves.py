"""student_leaves + attendance.leave_id + academic_settings.student_leave_admin_approval_required

Revision ID: 061_student_leaves
Revises: 060_school_unit_type_campus
Create Date: 2026-05-28
"""

from alembic import op
import sqlalchemy as sa


revision = "061_student_leaves"
down_revision = "060_school_unit_type_campus"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "student_leaves",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("student_id", sa.String(36), sa.ForeignKey("students.id"), nullable=False, index=True),
        sa.Column("class_id", sa.String(36), sa.ForeignKey("classes.id"), nullable=False),
        sa.Column("class_teacher_id", sa.String(36), sa.ForeignKey("teachers.id"), nullable=True),
        sa.Column("leave_type", sa.String(20), nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=False),
        sa.Column("half_day", sa.String(4), nullable=True),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column(
            "attachment_document_id",
            sa.String(36),
            sa.ForeignKey("student_documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column(
            "requires_admin_approval",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "decided_by_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text, nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested_reason", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "leave_type IN ('sick', 'medical', 'family', 'religious', 'other')",
            name="ck_student_leaves_leave_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending_class_teacher', 'pending_admin', 'approved', 'rejected', 'cancelled')",
            name="ck_student_leaves_status",
        ),
        sa.CheckConstraint(
            "half_day IS NULL OR half_day IN ('am', 'pm')",
            name="ck_student_leaves_half_day",
        ),
        sa.CheckConstraint(
            "end_date >= start_date",
            name="ck_student_leaves_date_range",
        ),
    )
    op.create_index(
        "ix_student_leaves_queue_teacher",
        "student_leaves",
        ["tenant_id", "status", "class_id"],
    )
    op.create_index(
        "ix_student_leaves_queue_admin",
        "student_leaves",
        ["tenant_id", "status", "class_teacher_id", "cancel_requested_at"],
    )
    op.create_index(
        "ix_student_leaves_student_status",
        "student_leaves",
        ["student_id", "status"],
    )

    op.add_column(
        "attendance",
        sa.Column(
            "leave_id",
            sa.String(36),
            sa.ForeignKey("student_leaves.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_attendance_leave_id", "attendance", ["leave_id"])

    op.add_column(
        "academic_settings",
        sa.Column(
            "student_leave_admin_approval_required",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade():
    op.drop_column("academic_settings", "student_leave_admin_approval_required")
    op.drop_index("ix_attendance_leave_id", table_name="attendance")
    op.drop_column("attendance", "leave_id")
    op.drop_index("ix_student_leaves_student_status", table_name="student_leaves")
    op.drop_index("ix_student_leaves_queue_admin", table_name="student_leaves")
    op.drop_index("ix_student_leaves_queue_teacher", table_name="student_leaves")
    op.drop_table("student_leaves")
