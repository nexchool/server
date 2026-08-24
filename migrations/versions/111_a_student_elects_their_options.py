"""a student may study something different from the child beside them

`class_subjects` says what a section is taught, and until now that was the
whole answer: every child in the class took all of it. Grade 11 is where it
stops being true — a Science section offers Biology and Computer Science and
each student takes one — and nothing in the schema could say which.

Elections are deviations. A section with no electives writes no rows, so the
ordinary school pays nothing for this. Only the choice itself is recorded.

The row keys on the **enrollment**, not the student: the same child has one
subject set in Grade 10 and another in Grade 11, and may hold an additional
enrollment with its own subjects. Keying on student_id would merge them.

Tenant integrity is declared, not assumed. Both parents gain
`UNIQUE (tenant_id, id)` so composite foreign keys can be declared against
them — the guard migrations 088 and 097 established, and the exit the debt
register names for the FK pairs that can still legally cross tenants.

Revision ID: 111_a_student_elects_their_options
Revises: 110_the_roll_number_belongs_to_the_year
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa

revision = "111_a_student_elects_their_options"
down_revision = "110_the_roll_number_belongs_to_the_year"
branch_labels = None
depends_on = None


def upgrade():
    # Composite-FK targets. Cheap (one index each) and they let the database
    # refuse a cross-tenant election outright rather than trusting a service.
    op.create_unique_constraint(
        "uq_sce_tenant_id_id", "student_class_enrollments", ["tenant_id", "id"]
    )
    op.create_unique_constraint(
        "uq_class_subjects_tenant_id_id", "class_subjects", ["tenant_id", "id"]
    )

    op.create_table(
        "student_subject_elections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("student_class_enrollment_id", sa.String(36), nullable=False),
        sa.Column("class_subject_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="taking"),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("decided_by_user_id", sa.String(36), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"],
            name="fk_sse_tenant_id", ondelete="CASCADE",
        ),
        # Composite: the enrollment must belong to the same school as the row.
        sa.ForeignKeyConstraint(
            ["tenant_id", "student_class_enrollment_id"],
            ["student_class_enrollments.tenant_id", "student_class_enrollments.id"],
            name="fk_sse_enrollment", ondelete="CASCADE",
        ),
        # Composite: so must the subject offering.
        sa.ForeignKeyConstraint(
            ["tenant_id", "class_subject_id"],
            ["class_subjects.tenant_id", "class_subjects.id"],
            name="fk_sse_class_subject", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"], ["users.id"],
            name="fk_sse_decided_by", ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "status IN ('taking', 'dropped', 'exempted')", name="ck_sse_status"
        ),
    )

    op.create_index("idx_sse_tenant_id", "student_subject_elections", ["tenant_id"])
    op.create_index(
        "idx_sse_enrollment",
        "student_subject_elections",
        ["tenant_id", "student_class_enrollment_id"],
    )
    op.create_index(
        "idx_sse_class_subject", "student_subject_elections", ["class_subject_id"]
    )
    op.create_index(
        "idx_sse_deleted_at", "student_subject_elections", ["deleted_at"]
    )
    # One decision per subject per enrollment. Partial, so a withdrawn election
    # does not block a new one — the soft-delete convention the rest of the
    # academic tables follow.
    op.create_index(
        "uq_sse_enrollment_class_subject",
        "student_subject_elections",
        ["tenant_id", "student_class_enrollment_id", "class_subject_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade():
    op.drop_table("student_subject_elections")
    op.drop_constraint(
        "uq_class_subjects_tenant_id_id", "class_subjects", type_="unique"
    )
    op.drop_constraint(
        "uq_sce_tenant_id_id", "student_class_enrollments", type_="unique"
    )
