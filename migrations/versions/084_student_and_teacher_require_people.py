"""students belong to a person, teachers to an employment

The constrain step of ADR-010 for the two relationships that hang off People:
a student relationship must name the human it belongs to, and teaching must name
the employment it is a participation of (ADR-005).

Every path that creates these rows — the services, both bulk importers and both
seed scripts — now populates them, so the constraint records a rule the code
already keeps. Rows written before that is true are linked here rather than by
a script run out of band, so the chain completes on any database at the
previous revision.

A student's human is the human their account belongs to; migration 082 has
already given every account one. A teacher's employment is a Staff relationship
for that same human, carrying what the teacher record already says about the
job — employee number, designation, department, and whether they still work
here.

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


_STUDENTS_TAKE_THE_PERSON_BEHIND_THEIR_ACCOUNT = sa.text(
    """
    UPDATE students s SET person_id = u.person_id
      FROM users u
     WHERE u.id = s.user_id AND s.person_id IS NULL
    """
)

# Derived from the teacher id so a second run cannot open a second employment
# for the same person. Skipped where the person already works here, because
# employment is created once per person (ADR-001) — someone who already has a
# Staff relationship and starts teaching keeps the one they had.
_EMPLOY_TEACHERS_WHO_ARE_NOT_YET_STAFF = sa.text(
    """
    INSERT INTO staff (id, tenant_id, person_id, employee_number, designation,
                       department_id, employment_status, created_at, updated_at)
    SELECT DISTINCT ON (u.person_id)
           md5('staff:' || t.id)::uuid::text,
           t.tenant_id,
           u.person_id,
           t.employee_id,
           t.designation,
           t.department_id,
           -- v1 recorded only active or not, so a departure arrives without a
           -- reason. 'left' says exactly what is known: they have gone, and
           -- why was never recorded.
           CASE WHEN lower(COALESCE(t.status, 'active')) = 'active'
                THEN 'working' ELSE 'left' END,
           now(), now()
      FROM teachers t
      JOIN users u ON u.id = t.user_id
     WHERE t.staff_id IS NULL
       AND u.person_id IS NOT NULL
       AND NOT EXISTS (
             SELECT 1 FROM staff s
              WHERE s.tenant_id = t.tenant_id AND s.person_id = u.person_id
           )
     ORDER BY u.person_id, t.id
    ON CONFLICT (id) DO NOTHING
    """
)

_TEACHING_POINTS_AT_THE_EMPLOYMENT = sa.text(
    """
    UPDATE teachers t SET staff_id = s.id
      FROM users u, staff s
     WHERE u.id = t.user_id
       AND s.tenant_id = t.tenant_id
       AND s.person_id = u.person_id
       AND t.staff_id IS NULL
    """
)

# One continuous stretch of employment, starting when the teacher record says
# they joined. Someone who later leaves and returns gets a second period; that
# is a business event, not something a backfill can invent.
_OPEN_THE_EMPLOYMENT_PERIOD = sa.text(
    """
    INSERT INTO staff_employment_periods (id, tenant_id, staff_id, joined_on,
                                          created_at, updated_at)
    SELECT md5('period:' || t.staff_id)::uuid::text,
           t.tenant_id, t.staff_id, t.date_of_joining, now(), now()
      FROM teachers t
     WHERE t.staff_id IS NOT NULL
       AND NOT EXISTS (
             SELECT 1 FROM staff_employment_periods p WHERE p.staff_id = t.staff_id
           )
    ON CONFLICT (id) DO NOTHING
    """
)


def _count(connection, statement: str) -> int:
    return connection.execute(sa.text(statement)).scalar()


def upgrade():
    connection = op.get_bind()

    connection.execute(_STUDENTS_TAKE_THE_PERSON_BEHIND_THEIR_ACCOUNT)
    connection.execute(_EMPLOY_TEACHERS_WHO_ARE_NOT_YET_STAFF)
    connection.execute(_TEACHING_POINTS_AT_THE_EMPLOYMENT)
    connection.execute(_OPEN_THE_EMPLOYMENT_PERIOD)

    # Say so rather than assume it: what is left here has no account to take a
    # person from, which a null-value stack trace would not explain.
    unlinked_students = _count(
        connection, "SELECT count(*) FROM students WHERE person_id IS NULL"
    )
    unlinked_teachers = _count(
        connection, "SELECT count(*) FROM teachers WHERE staff_id IS NULL"
    )
    if unlinked_students or unlinked_teachers:
        raise RuntimeError(
            f"{unlinked_students} student(s) still have no person and "
            f"{unlinked_teachers} teacher(s) no employment after the backfill. "
            "Those rows point at an account that does not exist; fix them first."
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
