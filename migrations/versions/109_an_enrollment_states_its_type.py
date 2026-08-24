"""an enrollment says whether it is the student's class or something extra

A child in Grade 11 Science may also attend a 40-day vacation batch, a JEE
coaching programme and a hostel programme. All four are a Class in this model —
each has its own campus, teachers, subjects, timetable and attendance — and the
only thing stopping a student holding all four was one partial index:

    UNIQUE (tenant, student, academic_year) WHERE is_current

Re-scoping that index to the academic cycle was the obvious move and is the
wrong one. `students.class_id` is a single column with 55 readers on the server
and 694 across the clients, and `test_caches_follow_their_owner` sweeps every
student asserting it equals their current enrollment. Multi-valuing the concept
would break all of that to model something schools do not mean: a child's
*class* is their regular section. Coaching is not their class.

So an enrollment states its type instead. `primary` is the academic placement
and remains the sole owner of `students.class_id`; `additional` is everything
else and touches no cache. The index gains one clause, and every existing row
backfills to `primary` — so on the day this lands nothing behaves differently.

Revision ID: 109_an_enrollment_states_its_type
Revises: 108_a_subject_context_may_name_a_stream
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa

revision = "109_an_enrollment_states_its_type"
down_revision = "108_a_subject_context_may_name_a_stream"
branch_labels = None
depends_on = None

_INDEX = "uq_sce_current_per_student_year"
_TYPES = ("primary", "additional")


def upgrade():
    op.add_column(
        "student_class_enrollments",
        sa.Column(
            "enrollment_type",
            sa.String(20),
            nullable=False,
            server_default="primary",
        ),
    )
    # Everything that exists is a student's academic placement — the only kind
    # the system could express until now.
    op.execute(
        "UPDATE student_class_enrollments SET enrollment_type = 'primary' "
        "WHERE enrollment_type IS NULL"
    )
    op.create_check_constraint(
        "ck_sce_enrollment_type",
        "student_class_enrollments",
        "enrollment_type IN ('primary', 'additional')",
    )

    # The rule the canon states — one current academic placement per student
    # per year — now says which kind of enrollment it is about. Additional
    # enrollments are deliberately unconstrained: a school may run a vacation
    # batch and a coaching programme at once, and nothing about that is a
    # conflict.
    op.drop_index(_INDEX, table_name="student_class_enrollments")
    op.create_index(
        _INDEX,
        "student_class_enrollments",
        ["tenant_id", "student_id", "academic_year_id"],
        unique=True,
        postgresql_where=sa.text("is_current = true AND enrollment_type = 'primary'"),
    )
    op.create_index(
        "idx_sce_type",
        "student_class_enrollments",
        ["tenant_id", "student_id", "enrollment_type"],
    )


def downgrade():
    bind = op.get_bind()

    # Winding back re-imposes one-placement-per-year, so anything additional
    # would violate it. Say so rather than silently dropping a child's
    # coaching record.
    extra = bind.execute(
        sa.text(
            "SELECT count(*) FROM student_class_enrollments "
            "WHERE enrollment_type = 'additional' AND is_current = true"
        )
    ).scalar()
    if extra:
        raise RuntimeError(
            f"{extra} current additional enrollment(s) exist. Reverting would "
            "re-impose one placement per student per year and there is no "
            "correct row to drop. Close them first, or restore from a backup."
        )

    op.drop_index("idx_sce_type", table_name="student_class_enrollments")
    op.drop_index(_INDEX, table_name="student_class_enrollments")
    op.create_index(
        _INDEX,
        "student_class_enrollments",
        ["tenant_id", "student_id", "academic_year_id"],
        unique=True,
        postgresql_where=sa.text("is_current = true"),
    )
    op.drop_constraint(
        "ck_sce_enrollment_type", "student_class_enrollments", type_="check"
    )
    op.drop_column("student_class_enrollments", "enrollment_type")
