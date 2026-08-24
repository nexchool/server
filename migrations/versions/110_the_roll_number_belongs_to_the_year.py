"""a roll number belongs to the placement, not to the child

A roll number is a position in a section for one year. The same student is
17 in Grade 10 and 42 in Grade 11, and a marksheet reprinted after they move
up must still say 17.

`students.roll_number` is a single column, so it could only ever hold the
current one. Reprinting last year's record printed this year's number, and
nothing in the system could tell that it had.

The enrollment already carries the year, the section and the placement, so it
is where the number belongs. `students.roll_number` stays as a cache of the
**primary** enrollment's value — the same arrangement `students.class_id`
has, guarded the same way — because 20-odd readers and both clients read it
and none of them should have to learn a join.

No uniqueness is added. There is none today (checked: no index, no
constraint, back to 001), and schools genuinely differ — some number by
section, some by grade, some not at all. Inventing a rule here would refuse
data a school already has.

Revision ID: 110_the_roll_number_belongs_to_the_year
Revises: 109_an_enrollment_states_its_type
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa

revision = "110_the_roll_number_belongs_to_the_year"
down_revision = "109_an_enrollment_states_its_type"
branch_labels = None
depends_on = None

# Only the academic placement takes the cached value. An additional
# enrollment (a vacation batch, coaching) may carry its own roll number, but
# it has never had one to inherit and inventing one would be fiction.
_BACKFILL = sa.text(
    """
    UPDATE student_class_enrollments e
       SET roll_number = s.roll_number
      FROM students s
     WHERE s.id = e.student_id
       AND s.tenant_id = e.tenant_id
       AND e.enrollment_type = 'primary'
       AND s.roll_number IS NOT NULL
    """
)


def upgrade():
    bind = op.get_bind()

    op.add_column(
        "student_class_enrollments",
        sa.Column("roll_number", sa.Integer(), nullable=True),
    )
    bind.execute(_BACKFILL)

    # Reading a section's register in roll order is the query this column is
    # for, and it is per class.
    op.create_index(
        "idx_sce_class_roll_number",
        "student_class_enrollments",
        ["tenant_id", "class_id", "roll_number"],
    )

    # Say what moved rather than assuming it. A student holding a roll number
    # with no current primary enrollment has nowhere to put it — that is the
    # unplaced student, which is legitimate, so this reports rather than fails.
    stranded = bind.execute(
        sa.text(
            """
            SELECT count(*) FROM students s
             WHERE s.roll_number IS NOT NULL
               AND NOT EXISTS (
                   SELECT 1 FROM student_class_enrollments e
                    WHERE e.student_id = s.id
                      AND e.tenant_id = s.tenant_id
                      AND e.enrollment_type = 'primary'
               )
            """
        )
    ).scalar()
    if stranded:
        print(
            f"[110] {stranded} student(s) hold a roll number but have no primary "
            "enrollment to carry it. Their students.roll_number is unchanged and "
            "will seed the enrollment when they are next placed."
        )


def downgrade():
    # students.roll_number was never stopped being written, so it still holds
    # the current value and nothing is lost by dropping the historical one.
    # The history itself is lost, which is exactly what this migration existed
    # to prevent — hence the note rather than a silent drop.
    op.drop_index("idx_sce_class_roll_number", table_name="student_class_enrollments")
    op.drop_column("student_class_enrollments", "roll_number")
