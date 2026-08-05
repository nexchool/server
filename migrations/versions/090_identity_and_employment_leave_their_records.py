"""Identity and employment leave the student and teacher records

A student's date of birth belongs to the student, not to their studentship. A
teacher's employee number, designation, department and joining date belong to
their employment, not to the fact that they teach (ADR-001, ADR-005).

Every reader moved first — serializers, filters, sorts, searches, facets, the
class-teacher pickers, the year rollover, global search and the id allocator —
and then every writer. What is left here are the columns nothing asks any more,
so they go.

The uniqueness of an employee number moves with it. It was guaranteed on
``teachers.employee_id``, which only ever covered teachers; an employee number
identifies an employee, so the guarantee now sits on ``staff``.

The student **family** columns deliberately stay. Their read has not moved yet:
where a school recorded the guardian's relationship as "father" the household
holds one adult, and where two students share a household a role lookup can
name a different adult than that student's record did. Showing a parent the
wrong name for a child is not a regression a school can absorb, so those
columns move with the client work that teaches the UI to speak in household
roles.

Revision ID: 090_identity_and_employment_leave_their_records
Revises: 089_authority_leaves_the_account
"""
from alembic import op
import sqlalchemy as sa


revision = "090_identity_and_employment_leave_their_records"
down_revision = "089_authority_leaves_the_account"
branch_labels = None
depends_on = None


# (table, column, type for the downgrade)
_TEACHER_COLUMNS = [
    ("employee_id", sa.String(length=20), False),
    ("designation", sa.String(length=100), True),
    ("department_id", sa.String(length=36), True),
    ("phone", sa.String(length=20), True),
    ("address", sa.Text(), True),
    ("date_of_joining", sa.Date(), True),
    ("status", sa.String(length=20), False),
]

_STUDENT_COLUMNS = [
    ("date_of_birth", sa.Date()),
    ("gender", sa.String(length=10)),
    ("phone", sa.String(length=20)),
    ("address", sa.Text()),
    ("aadhar_number", sa.String(length=20)),
]


_CARRY_STUDENT_IDENTITY = sa.text(
    """
    UPDATE persons p SET
        date_of_birth   = COALESCE(p.date_of_birth,   st.date_of_birth),
        gender          = COALESCE(p.gender,          st.gender),
        phone_number    = COALESCE(p.phone_number,    st.phone),
        address         = COALESCE(p.address,         st.address),
        aadhaar_number  = COALESCE(p.aadhaar_number,  st.aadhar_number)
      FROM students st
     WHERE st.person_id = p.id
    """
)

_CARRY_TEACHER_IDENTITY = sa.text(
    """
    UPDATE persons p SET
        phone_number = COALESCE(p.phone_number, t.phone),
        address      = COALESCE(p.address,      t.address)
      FROM teachers t
      JOIN staff s ON s.id = t.staff_id
     WHERE s.person_id = p.id
    """
)

_CARRY_EMPLOYMENT = sa.text(
    """
    UPDATE staff s SET
        employee_number   = COALESCE(s.employee_number, t.employee_id),
        designation       = COALESCE(s.designation,     t.designation),
        department_id     = COALESCE(s.department_id,   t.department_id),
        employment_status = CASE
            WHEN s.employment_status <> 'working' THEN s.employment_status
            WHEN lower(coalesce(t.status, 'active')) = 'active' THEN s.employment_status
            ELSE 'left' END
      FROM teachers t
     WHERE t.staff_id = s.id
    """
)

_CARRY_JOINING_DATE = sa.text(
    """
    UPDATE staff_employment_periods sep SET joined_on = t.date_of_joining
      FROM teachers t
     WHERE t.staff_id = sep.staff_id
       AND sep.joined_on IS NULL
       AND t.date_of_joining IS NOT NULL
    """
)


def upgrade():
    bind = op.get_bind()

    # Carry anything the People model does not already hold. Only the script
    # `backfill_people.py` ever moved these, so an environment that never ran it
    # would lose the data outright — the columns are dropped a few lines below.
    # COALESCE throughout: People is authoritative now, and a value it already
    # holds is a correction someone made after the move.
    bind.execute(_CARRY_STUDENT_IDENTITY)
    bind.execute(_CARRY_TEACHER_IDENTITY)
    bind.execute(_CARRY_EMPLOYMENT)
    bind.execute(_CARRY_JOINING_DATE)

    # Nothing should be left behind, but say so rather than assume it: the
    # employment must already carry what the teacher row is about to lose.
    stranded = bind.execute(
        sa.text(
            """
            SELECT count(*) FROM teachers t
              JOIN staff s ON s.id = t.staff_id
             WHERE t.employee_id IS DISTINCT FROM s.employee_number
            """
        )
    ).scalar()
    if stranded:
        raise RuntimeError(
            f"{stranded} teachers hold an employee number their employment does "
            "not. Reconcile them before dropping the column, or the number is lost."
        )

    # The test suite builds its schema from the models against this same
    # database, so the constraint may already be here.
    if not _already_there(bind, "uq_staff_tenant_employee_number"):
        op.create_unique_constraint(
            "uq_staff_tenant_employee_number", "staff", ["tenant_id", "employee_number"]
        )

    op.execute("ALTER TABLE teachers DROP CONSTRAINT IF EXISTS uq_teachers_employee_id_tenant")
    for column, _type, _required in _TEACHER_COLUMNS:
        op.execute(f"ALTER TABLE teachers DROP COLUMN IF EXISTS {column}")

    for column, _type in _STUDENT_COLUMNS:
        op.execute(f"ALTER TABLE students DROP COLUMN IF EXISTS {column}")


def _already_there(bind, name: str) -> bool:
    """A unique constraint owns an index of the same name; either one blocks us."""
    return bool(
        bind.execute(
            sa.text("SELECT 1 FROM pg_class WHERE relname = :name"), {"name": name}
        ).scalar()
    )


def downgrade():
    for column, type_, required in _TEACHER_COLUMNS:
        op.execute(
            f"ALTER TABLE teachers ADD COLUMN IF NOT EXISTS {column} "
            f"{type_.compile()}"
        )
    op.execute(
        """
        UPDATE teachers t SET
            employee_id     = s.employee_number,
            designation     = s.designation,
            department_id   = s.department_id,
            phone           = p.phone_number,
            address         = p.address,
            status          = CASE WHEN s.employment_status IN (
                                  'working','probation','on_leave',
                                  'notice_period','suspended')
                              THEN 'active' ELSE 'inactive' END,
            date_of_joining = (SELECT min(joined_on)
                                 FROM staff_employment_periods
                                WHERE staff_id = s.id)
          FROM staff s
          JOIN persons p ON p.id = s.person_id
         WHERE s.id = t.staff_id
        """
    )
    op.execute("UPDATE teachers SET status = 'active' WHERE status IS NULL")
    op.alter_column("teachers", "status", nullable=False, server_default="active")

    # NOT NULL comes back only if the data can honestly satisfy it. An
    # employment with no employee number has nothing to give this column, and
    # inventing one would be worse than leaving it nullable.
    missing = op.get_bind().execute(
        sa.text("SELECT count(*) FROM teachers WHERE employee_id IS NULL")
    ).scalar()
    if not missing:
        op.alter_column("teachers", "employee_id", nullable=False)
    if not missing and not _already_there(op.get_bind(), "uq_teachers_employee_id_tenant"):
        op.create_unique_constraint(
            "uq_teachers_employee_id_tenant", "teachers", ["employee_id", "tenant_id"]
        )

    for column, type_ in _STUDENT_COLUMNS:
        op.execute(
            f"ALTER TABLE students ADD COLUMN IF NOT EXISTS {column} "
            f"{type_.compile()}"
        )
    op.execute(
        """
        UPDATE students st SET
            date_of_birth = p.date_of_birth,
            gender        = p.gender,
            phone         = p.phone_number,
            address       = p.address,
            aadhar_number = p.aadhaar_number
          FROM persons p
         WHERE p.id = st.person_id
        """
    )

    op.execute(
        "ALTER TABLE staff DROP CONSTRAINT IF EXISTS uq_staff_tenant_employee_number"
    )
