"""teacher as academic participation of staff

Points each teacher at the Staff relationship that employs them (ADR-005):
employment belongs to the People Domain, teaching to the Academic Domain.
Additive per ADR-010 — `staff_id` is nullable and the employment columns on
`teachers` are left in place until nothing reads them.

Revision ID: 081_teacher_academic_participation
Revises: 080_staff_relationship
Create Date: 2026-08-05
"""

from alembic import op
import sqlalchemy as sa

revision = "081_teacher_academic_participation"
down_revision = "080_staff_relationship"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("teachers", sa.Column("staff_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(
        "fk_teachers_staff_id", "teachers", "staff", ["staff_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_index("ix_teachers_staff_id", "teachers", ["staff_id"])
    # One teaching participation per employment: a staff member teaches or does
    # not, and repeating that fact would let the two records disagree.
    op.execute(
        "CREATE UNIQUE INDEX uq_teachers_staff_id "
        "ON teachers (staff_id) WHERE staff_id IS NOT NULL"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS uq_teachers_staff_id")
    op.drop_index("ix_teachers_staff_id", table_name="teachers")
    op.drop_constraint("fk_teachers_staff_id", "teachers", type_="foreignkey")
    op.drop_column("teachers", "staff_id")
