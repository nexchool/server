"""Drop allow_teacher_timetable_override from academic_settings.

Revision ID: 036_drop_teacher_tt_override
Revises: 035_device_tokens
Create Date: 2026-04-12
"""

from alembic import op
import sqlalchemy as sa


revision = "036_drop_teacher_tt_override"
down_revision = "035_device_tokens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("academic_settings", "allow_teacher_timetable_override")
    op.drop_column("academic_settings", "attendance_mode")


def downgrade() -> None:
    op.add_column(
        "academic_settings",
        sa.Column(
            "allow_teacher_timetable_override",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "academic_settings",
        sa.Column(
            "attendance_mode",
            sa.String(20),
            nullable=False,
            server_default="daily",
        ),
    )