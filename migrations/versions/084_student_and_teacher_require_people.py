"""students belong to a person, teachers to an employment

The constrain step of ADR-010 for the two relationships that hang off People:
a student relationship must name the human it belongs to, and teaching must name
the employment it is a participation of (ADR-005).

Every path that creates these rows — the services, both bulk importers and both
seed scripts — now populates them, so the constraint records a rule the code
already keeps.

Revision ID: 084_student_and_teacher_require_people
Revises: 083_person_merges
Create Date: 2026-08-05
"""

from alembic import op
import sqlalchemy as sa

revision = "084_student_and_teacher_require_people"
down_revision = "083_person_merges"
branch_labels = None
depends_on = None


def _count(connection, statement: str) -> int:
    return connection.execute(sa.text(statement)).scalar()


def upgrade():
    connection = op.get_bind()

    # Fail with an instruction rather than a constraint violation: an operator
    # who has not run the backfill needs to know that, not to read a stack
    # trace about a null value.
    unlinked_students = _count(
        connection, "SELECT count(*) FROM students WHERE person_id IS NULL"
    )
    unlinked_teachers = _count(
        connection, "SELECT count(*) FROM teachers WHERE staff_id IS NULL"
    )
    if unlinked_students or unlinked_teachers:
        raise RuntimeError(
            f"{unlinked_students} student(s) have no person and "
            f"{unlinked_teachers} teacher(s) have no employment. "
            "Run `python scripts/backfill_people.py` before applying this migration."
        )

    op.alter_column(
        "students", "person_id", existing_type=sa.String(length=36), nullable=False
    )
    op.alter_column(
        "teachers", "staff_id", existing_type=sa.String(length=36), nullable=False
    )


def downgrade():
    op.alter_column(
        "teachers", "staff_id", existing_type=sa.String(length=36), nullable=True
    )
    op.alter_column(
        "students", "person_id", existing_type=sa.String(length=36), nullable=True
    )
