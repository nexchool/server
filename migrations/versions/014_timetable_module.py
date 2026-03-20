"""Timetable module: timetable_slots table.

Revision ID: 014_timetable_module
Revises: 013_class_teachers_subject_id
Create Date: 2025-03-06

- Creates timetable_slots table (tenant-scoped)
- Unique: (class_id, day_of_week, period_number)
"""

from alembic import op
import sqlalchemy as sa

revision = "014_timetable_module"
down_revision = "013_class_teachers_subject_id"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "timetable_slots",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("class_id", sa.String(36), nullable=False),
        sa.Column("subject_id", sa.String(36), nullable=False),
        sa.Column("teacher_id", sa.String(36), nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=False),
        sa.Column("period_number", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("room", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_timetable_slots_tenant_id"), "timetable_slots", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_timetable_slots_class_id"), "timetable_slots", ["class_id"], unique=False)
    op.create_index(op.f("ix_timetable_slots_subject_id"), "timetable_slots", ["subject_id"], unique=False)
    op.create_index(op.f("ix_timetable_slots_teacher_id"), "timetable_slots", ["teacher_id"], unique=False)
    op.create_unique_constraint(
        "uq_timetable_slots_class_day_period",
        "timetable_slots",
        ["class_id", "day_of_week", "period_number"],
    )


def downgrade():
    op.drop_constraint("uq_timetable_slots_class_day_period", "timetable_slots", type_="unique")
    op.drop_index(op.f("ix_timetable_slots_teacher_id"), table_name="timetable_slots")
    op.drop_index(op.f("ix_timetable_slots_subject_id"), table_name="timetable_slots")
    op.drop_index(op.f("ix_timetable_slots_class_id"), table_name="timetable_slots")
    op.drop_index(op.f("ix_timetable_slots_tenant_id"), table_name="timetable_slots")
    op.drop_table("timetable_slots")
