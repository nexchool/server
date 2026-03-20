"""Teacher constraints: subjects, availability, leaves, workload, subject load.

Revision ID: 015_teacher_constraints
Revises: 014_timetable_module
Create Date: 2026-03-07

Creates:
  - teacher_subjects       (teacher expertise / subject assignment)
  - teacher_availability   (unavailable periods per day)
  - teacher_leaves         (leave requests with approval workflow)
  - teacher_workload_rules (max periods per day / week)
  - subject_load           (weekly period target per class+subject)
"""

from alembic import op
import sqlalchemy as sa

revision = "015_teacher_constraints"
down_revision = "014_timetable_module"
branch_labels = None
depends_on = None


def upgrade():
    # ------------------------------------------------------------------
    # teacher_subjects
    # ------------------------------------------------------------------
    op.create_table(
        "teacher_subjects",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("teacher_id", sa.String(36), nullable=False),
        sa.Column("subject_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_teacher_subjects_tenant_id"), "teacher_subjects", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_teacher_subjects_teacher_id"), "teacher_subjects", ["teacher_id"], unique=False)
    op.create_index(op.f("ix_teacher_subjects_subject_id"), "teacher_subjects", ["subject_id"], unique=False)
    op.create_unique_constraint(
        "uq_teacher_subject_tenant",
        "teacher_subjects",
        ["teacher_id", "subject_id", "tenant_id"],
    )

    # ------------------------------------------------------------------
    # teacher_availability
    # ------------------------------------------------------------------
    op.create_table(
        "teacher_availability",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("teacher_id", sa.String(36), nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=False),
        sa.Column("period_number", sa.Integer(), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_teacher_availability_tenant_id"), "teacher_availability", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_teacher_availability_teacher_id"), "teacher_availability", ["teacher_id"], unique=False)

    # ------------------------------------------------------------------
    # teacher_leaves
    # ------------------------------------------------------------------
    op.create_table(
        "teacher_leaves",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("teacher_id", sa.String(36), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("leave_type", sa.String(50), nullable=False, server_default="casual"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_teacher_leaves_tenant_id"), "teacher_leaves", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_teacher_leaves_teacher_id"), "teacher_leaves", ["teacher_id"], unique=False)

    # ------------------------------------------------------------------
    # teacher_workload_rules
    # ------------------------------------------------------------------
    op.create_table(
        "teacher_workload_rules",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("teacher_id", sa.String(36), nullable=False),
        sa.Column("max_periods_per_day", sa.Integer(), nullable=False, server_default="6"),
        sa.Column("max_periods_per_week", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("teacher_id", name="uq_workload_teacher_id"),
    )
    op.create_index(op.f("ix_teacher_workload_rules_tenant_id"), "teacher_workload_rules", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_teacher_workload_rules_teacher_id"), "teacher_workload_rules", ["teacher_id"], unique=False)

    # ------------------------------------------------------------------
    # subject_load
    # ------------------------------------------------------------------
    op.create_table(
        "subject_load",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("class_id", sa.String(36), nullable=False),
        sa.Column("subject_id", sa.String(36), nullable=False),
        sa.Column("weekly_periods", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_subject_load_tenant_id"), "subject_load", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_subject_load_class_id"), "subject_load", ["class_id"], unique=False)
    op.create_index(op.f("ix_subject_load_subject_id"), "subject_load", ["subject_id"], unique=False)
    op.create_unique_constraint(
        "uq_subject_load_class_subject_tenant",
        "subject_load",
        ["class_id", "subject_id", "tenant_id"],
    )


def downgrade():
    op.drop_constraint("uq_subject_load_class_subject_tenant", "subject_load", type_="unique")
    op.drop_index(op.f("ix_subject_load_subject_id"), table_name="subject_load")
    op.drop_index(op.f("ix_subject_load_class_id"), table_name="subject_load")
    op.drop_index(op.f("ix_subject_load_tenant_id"), table_name="subject_load")
    op.drop_table("subject_load")

    op.drop_index(op.f("ix_teacher_workload_rules_teacher_id"), table_name="teacher_workload_rules")
    op.drop_index(op.f("ix_teacher_workload_rules_tenant_id"), table_name="teacher_workload_rules")
    op.drop_table("teacher_workload_rules")

    op.drop_index(op.f("ix_teacher_leaves_teacher_id"), table_name="teacher_leaves")
    op.drop_index(op.f("ix_teacher_leaves_tenant_id"), table_name="teacher_leaves")
    op.drop_table("teacher_leaves")

    op.drop_index(op.f("ix_teacher_availability_teacher_id"), table_name="teacher_availability")
    op.drop_index(op.f("ix_teacher_availability_tenant_id"), table_name="teacher_availability")
    op.drop_table("teacher_availability")

    op.drop_constraint("uq_teacher_subject_tenant", "teacher_subjects", type_="unique")
    op.drop_index(op.f("ix_teacher_subjects_subject_id"), table_name="teacher_subjects")
    op.drop_index(op.f("ix_teacher_subjects_teacher_id"), table_name="teacher_subjects")
    op.drop_index(op.f("ix_teacher_subjects_tenant_id"), table_name="teacher_subjects")
    op.drop_table("teacher_subjects")
