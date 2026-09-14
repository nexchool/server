"""student_leaves: record the class teacher's decision separately

`decided_by_id` is a single column, so when a leave passes through the
principal the class teacher's approval is overwritten and the school loses the
record of who first agreed. Two nullable columns rather than a decisions child
table: the chain is two steps by design, and a general table would be more
machinery than the decision warrants.

No backfill — existing rows carry exactly one decision, already correctly
recorded in `decided_by_id`.

Revision ID: 142_student_leave_approval_trail
Revises: 141_hostel_master_record_details
"""

import sqlalchemy as sa
from alembic import op

revision = "142_student_leave_approval_trail"
down_revision = "141_hostel_master_record_details"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "student_leaves",
        sa.Column("class_teacher_decided_by_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "student_leaves",
        sa.Column("class_teacher_decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_student_leaves_class_teacher_decided_by",
        "student_leaves",
        "users",
        ["class_teacher_decided_by_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint(
        "fk_student_leaves_class_teacher_decided_by",
        "student_leaves",
        type_="foreignkey",
    )
    op.drop_column("student_leaves", "class_teacher_decided_at")
    op.drop_column("student_leaves", "class_teacher_decided_by_id")
