"""a subject offering may name the stream it belongs to

`subject_contexts` answers "how does this (programme, grade) offer this
subject" — display name, board paper code, mandatory or elective, which
language slot. It is the strongest curriculum model in the codebase and it was
missing one dimension: the stream.

Without it Grade 11 Science and Grade 11 Commerce resolve to the same subject
set, because both are (programme, grade). Their examinations would too.

Nullable, and NULL means "every stream at this (programme, grade)". That is
what every existing row means, so the backfill is the absence of one: a school
with no streams keeps exactly the curriculum it had, and a school that adds
Science-only Physics adds a row that names Science.

Revision ID: 108_a_subject_context_may_name_a_stream
Revises: 107_a_stream_is_a_domain_entity
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa

revision = "108_a_subject_context_may_name_a_stream"
down_revision = "107_a_stream_is_a_domain_entity"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "subject_contexts", sa.Column("stream_id", sa.String(36), nullable=True)
    )
    op.create_foreign_key(
        "fk_subject_contexts_stream_id",
        "subject_contexts",
        "streams",
        ["stream_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "idx_subject_contexts_stream_id", "subject_contexts", ["stream_id"]
    )
    # Reading a grade's curriculum for one stream is the query examinations
    # will run per paper, so it gets an index rather than a sequential scan
    # per subject.
    op.create_index(
        "idx_subject_contexts_programme_grade_stream",
        "subject_contexts",
        ["tenant_id", "programme_id", "grade_id", "stream_id"],
    )


def downgrade():
    op.drop_index(
        "idx_subject_contexts_programme_grade_stream", table_name="subject_contexts"
    )
    op.drop_index("idx_subject_contexts_stream_id", table_name="subject_contexts")
    op.drop_constraint(
        "fk_subject_contexts_stream_id", "subject_contexts", type_="foreignkey"
    )
    op.drop_column("subject_contexts", "stream_id")
