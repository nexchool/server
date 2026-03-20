"""Schedule overrides for daily substitutions, activity replacements, and cancellations.

Revision ID: 017_schedule_overrides
Revises: 016_timetable_config
Create Date: 2026-03-09

Creates schedule_overrides table to store per-day slot overrides:
  - substitute: Assign a different teacher temporarily
  - activity: Replace class with an activity (sports, assembly, etc.)
  - cancelled: Class cancelled for the day
"""

from alembic import op
import sqlalchemy as sa

revision = "017_schedule_overrides"
down_revision = "016_timetable_config"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "schedule_overrides",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("slot_id", sa.String(36), nullable=False),
        sa.Column("override_date", sa.Date(), nullable=False),
        sa.Column(
            "override_type",
            sa.String(20),
            nullable=False,
            server_default="substitute",
        ),  # substitute | activity | cancelled
        sa.Column("substitute_teacher_id", sa.String(36), nullable=True),
        sa.Column("activity_label", sa.String(100), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["slot_id"], ["timetable_slots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["substitute_teacher_id"], ["teachers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slot_id", "override_date", name="uq_schedule_override_slot_date"),
    )
    op.create_index(op.f("ix_schedule_overrides_tenant_id"), "schedule_overrides", ["tenant_id"])
    op.create_index(op.f("ix_schedule_overrides_slot_id"), "schedule_overrides", ["slot_id"])
    op.create_index(op.f("ix_schedule_overrides_override_date"), "schedule_overrides", ["override_date"])


def downgrade():
    op.drop_index(op.f("ix_schedule_overrides_override_date"), table_name="schedule_overrides")
    op.drop_index(op.f("ix_schedule_overrides_slot_id"), table_name="schedule_overrides")
    op.drop_index(op.f("ix_schedule_overrides_tenant_id"), table_name="schedule_overrides")
    op.drop_table("schedule_overrides")
