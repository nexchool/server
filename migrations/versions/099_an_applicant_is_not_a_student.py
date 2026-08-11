"""An applicant is not a student, and a rejected one still happened.

Admission was `create_student`: the only way to record that a child had
applied was to make them a student of the school. So there was nowhere to
put the family who withdrew, the papers that never arrived, or the offer
that went elsewhere — and the canon requires exactly those to remain
visible with no Student relationship created.

`admission_applications` is that record. It holds enough to admit somebody
and nothing that presumes they will be: no Person, no admission number, no
place in a class until the school approves. `student_id` is the link, set
only on approval, so an application can always be read back to the student
it became — or to the fact that it became none.

Revision ID: 099_an_applicant_is_not_a_student
Revises: 098_a_student_has_a_history
"""

import sqlalchemy as sa
from alembic import op

revision = "099_an_applicant_is_not_a_student"
down_revision = "098_a_student_has_a_history"
branch_labels = None
depends_on = None

_STATUSES = ("submitted", "under_review", "approved", "rejected", "withdrawn")


def upgrade():
    op.create_table(
        "admission_applications",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("applicant_name", sa.String(length=120), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("gender", sa.String(length=20), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=True),
        sa.Column("email", sa.String(length=120), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("guardian_name", sa.String(length=120), nullable=False),
        sa.Column("guardian_relationship", sa.String(length=50), nullable=False),
        sa.Column("guardian_phone", sa.String(length=20), nullable=False),
        sa.Column("guardian_email", sa.String(length=120), nullable=True),
        sa.Column("academic_year_id", sa.String(length=36), nullable=False),
        sa.Column("desired_class_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="submitted"),
        sa.Column("submitted_on", sa.Date(), nullable=False),
        sa.Column("decided_on", sa.Date(), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column("decided_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("student_id", sa.String(length=36), nullable=True),
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
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        # RESTRICT: an academic year with applications against it is not an
        # empty year, and deleting it would strand them.
        sa.ForeignKeyConstraint(
            ["academic_year_id"], ["academic_years.id"], ondelete="RESTRICT"
        ),
        # The desired class is a wish; losing it must not lose the application.
        sa.ForeignKeyConstraint(["desired_class_id"], ["classes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in _STATUSES) + ")",
            name="ck_admission_applications_status",
        ),
    )
    op.create_index(
        "ix_admission_applications_tenant_id", "admission_applications", ["tenant_id"]
    )
    op.create_index(
        "ix_admission_applications_academic_year_id",
        "admission_applications",
        ["academic_year_id"],
    )
    op.create_index(
        "ix_admission_applications_student_id", "admission_applications", ["student_id"]
    )
    # The list is read by state far more than any other way.
    op.create_index(
        "ix_admission_applications_status", "admission_applications", ["status"]
    )


def downgrade():
    op.drop_index("ix_admission_applications_status", table_name="admission_applications")
    op.drop_index("ix_admission_applications_student_id", table_name="admission_applications")
    op.drop_index(
        "ix_admission_applications_academic_year_id", table_name="admission_applications"
    )
    op.drop_index("ix_admission_applications_tenant_id", table_name="admission_applications")
    op.drop_table("admission_applications")
