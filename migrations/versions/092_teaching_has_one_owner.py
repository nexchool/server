"""Teaching has one owner

`class_teachers` recorded two different things at once: who teaches a subject in
a class, and — as a boolean — who is responsible for the class. Both already had
owners. Subject teaching belongs to `class_subject_teachers`, which hangs off
the subject a class offers and can say from when. Class-teacher responsibility
belongs to `class_teacher_assignments`, which can say the same.

Keeping the third table meant a reader could ask any of them and get a different
answer, and the branch-scope filter had to union all three to work out whose
teacher a teacher was. ADR-014 settles it; this removes the table it settles
against.

Nothing is carried. Every row is already recorded by an owner — verified below
rather than assumed, because "it should already be there" is how data goes
missing.

Revision ID: 092_teaching_has_one_owner
Revises: 091_the_household_knows_who_to_call
"""
from alembic import op
import sqlalchemy as sa


revision = "092_teaching_has_one_owner"
down_revision = "091_the_household_knows_who_to_call"
branch_labels = None
depends_on = None


# A subject-teaching row is covered when the same teacher is recorded against
# the same subject in the same class.
_UNCOVERED_SUBJECT_TEACHING = sa.text(
    """
    SELECT count(*) FROM class_teachers ct
     WHERE ct.subject_id IS NOT NULL
       AND NOT EXISTS (
             SELECT 1
               FROM class_subjects cs
               JOIN class_subject_teachers cst ON cst.class_subject_id = cs.id
              WHERE cs.class_id = ct.class_id
                AND cs.subject_id = ct.subject_id
                AND cst.teacher_id = ct.teacher_id
           )
    """
)

# A class-teacher row is covered when the same teacher is recorded as
# responsible for the same class.
_UNCOVERED_CLASS_TEACHER = sa.text(
    """
    SELECT count(*) FROM class_teachers ct
     WHERE ct.is_class_teacher
       AND NOT EXISTS (
             SELECT 1 FROM class_teacher_assignments a
              WHERE a.class_id = ct.class_id
                AND a.teacher_id = ct.teacher_id
                AND a.deleted_at IS NULL
           )
    """
)


def upgrade():
    bind = op.get_bind()

    if _table_exists(bind, "class_teachers"):
        stranded_subjects = bind.execute(_UNCOVERED_SUBJECT_TEACHING).scalar()
        stranded_class_teachers = bind.execute(_UNCOVERED_CLASS_TEACHER).scalar()

        if stranded_subjects or stranded_class_teachers:
            raise RuntimeError(
                f"{stranded_subjects} subject-teaching row(s) and "
                f"{stranded_class_teachers} class-teacher row(s) in class_teachers "
                "are not recorded by an owner. Copy them into "
                "class_subject_teachers / class_teacher_assignments before "
                "dropping this table, or the assignment is lost."
            )

        op.drop_table("class_teachers")


def _table_exists(bind, name: str) -> bool:
    return bool(
        bind.execute(
            sa.text("SELECT to_regclass(:name)"), {"name": f"public.{name}"}
        ).scalar()
    )


def downgrade():
    """Recreate the table, empty.

    The rows cannot be rebuilt faithfully: `class_teachers` held one subject per
    teacher per class, and the owners hold every subject a teacher takes, so
    reversing would have to choose one and silently discard the rest. An empty
    table restores the shape without inventing the contents.
    """
    op.create_table(
        "class_teachers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("class_id", sa.String(length=36), nullable=False),
        sa.Column("teacher_id", sa.String(length=36), nullable=False),
        sa.Column("subject", sa.String(length=100), nullable=True),
        sa.Column("subject_id", sa.String(length=36), nullable=True),
        sa.Column("is_class_teacher", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"]),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"]),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
