"""a paper's class cannot disagree with the offering it examines

`exam_papers` carries `class_subject_id` and `class_id`, and the offering
already names the class. The second column is a denormalisation — it is what
lets "every paper this section sits" be one index rather than a join — and a
denormalisation that only a service keeps honest is one refactor from drifting.

This makes the database refuse the contradiction instead. `class_subjects`
gains `UNIQUE (id, class_id)`, which is what allows `exam_papers` to declare a
composite foreign key on the pair. After this migration a paper naming Grade
10-A's Mathematics offering while claiming to be Grade 10-B's sitting is not
storable, however the row is written.

The service does not trust `class_id` from a caller at all — it reads it off
the offering — so this constraint should never fire. That is the point: it
guards the paths nobody has written yet.

Revision ID: 116_a_paper_cannot_disagree_with_its_offering
Revises: 115_marks_answer_to_assessment
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa

revision = "116_a_paper_cannot_disagree_with_its_offering"
down_revision = "115_marks_answer_to_assessment"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    # Nothing can violate this yet — EX-00 shipped the tables and no service
    # writes them — but check rather than assume, because a migration that
    # declares a constraint over data it did not inspect is how a deploy fails
    # at 2am instead of here.
    disagreeing = bind.execute(
        sa.text(
            """
            SELECT count(*) FROM exam_papers p
              JOIN class_subjects cs ON cs.id = p.class_subject_id
             WHERE cs.class_id <> p.class_id
            """
        )
    ).scalar()
    if disagreeing:
        raise RuntimeError(
            f"{disagreeing} exam paper(s) name a class that is not the one their "
            "class_subject belongs to. Correct them before the constraint lands: "
            "the offering is authoritative, the column is its cache."
        )

    op.create_unique_constraint(
        "uq_class_subjects_id_class_id", "class_subjects", ["id", "class_id"]
    )
    op.create_foreign_key(
        "fk_exam_papers_offering_matches_class",
        "exam_papers",
        "class_subjects",
        ["class_subject_id", "class_id"],
        ["id", "class_id"],
        ondelete="RESTRICT",
    )


def downgrade():
    op.drop_constraint(
        "fk_exam_papers_offering_matches_class", "exam_papers", type_="foreignkey"
    )
    op.drop_constraint(
        "uq_class_subjects_id_class_id", "class_subjects", type_="unique"
    )
