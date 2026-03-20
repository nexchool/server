"""Timetable configuration per school (tenant).

Revision ID: 016_timetable_config
Revises: 015_teacher_constraints
Create Date: 2026-03-09

Creates timetable_config table for school-specific schedule settings:
- Class duration, first class duration, gaps, breaks
"""

from alembic import op
import sqlalchemy as sa

revision = "016_timetable_config"
down_revision = "015_teacher_constraints"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "timetable_config",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("general_class_duration_minutes", sa.Integer(), nullable=False, server_default="45"),
        sa.Column("first_class_duration_minutes", sa.Integer(), nullable=False, server_default="40"),
        sa.Column("gap_between_classes_minutes", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("periods_per_day", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("school_start_time", sa.Time(), nullable=False, server_default=sa.text("'08:00'::time")),
        sa.Column("breaks_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", name="uq_timetable_config_tenant"),
    )
    op.create_index(op.f("ix_timetable_config_tenant_id"), "timetable_config", ["tenant_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_timetable_config_tenant_id"), table_name="timetable_config")
    op.drop_table("timetable_config")
