"""two streams at one grade may offer the same subject

Migration 108 gave `subject_contexts` its stream, but left the uniqueness rule
behind: `uq_subject_contexts_offering_active` still keys on

    (tenant_id, programme_id, grade_id, subject_id, medium_id, role)

so a (programme, grade) can hold exactly one row per subject however many
streams it runs. Physics is safe — only Science teaches it. English is safe the
other way, offered to everyone as one stream-agnostic row. The rule breaks on
the subjects in between, and every board has them: Mathematics is taught in
Science and in Commerce but not in Arts; Economics in Commerce and Arts but not
in Science; Computer Education in Science and Commerce.

Those cannot be written as one stream-agnostic row without also offering them
to the stream that does not take them — an Arts section listing Mathematics —
and cannot be written as one row per stream while this index stands.

Adding `stream_id` to the key allows the row per stream. It does not require
one: NULL still means "every stream here", so a school with no streams keeps
the curriculum it had and the index keeps refusing a genuine duplicate.

Revision ID: 119_two_streams_may_share_a_subject
Revises: 118_a_closed_mark_changes_by_request
Create Date: 2026-08-17
"""

from alembic import op

revision = "119_two_streams_may_share_a_subject"
down_revision = "118_a_closed_mark_changes_by_request"
branch_labels = None
depends_on = None

INDEX = "uq_subject_contexts_offering_active"


def upgrade():
    op.drop_index(INDEX, table_name="subject_contexts")
    op.execute(
        f"""
        CREATE UNIQUE INDEX {INDEX} ON subject_contexts (
            tenant_id, programme_id, grade_id, subject_id,
            COALESCE(medium_id, ''),
            COALESCE(role, ''),
            COALESCE(stream_id, '')
        ) WHERE deleted_at IS NULL
        """
    )


def downgrade():
    # Reversible only while no (programme, grade, subject) is offered to more
    # than one stream — which is the state this migration exists to leave. The
    # index creation fails loudly on such a row rather than dropping data.
    op.drop_index(INDEX, table_name="subject_contexts")
    op.execute(
        f"""
        CREATE UNIQUE INDEX {INDEX} ON subject_contexts (
            tenant_id, programme_id, grade_id, subject_id,
            COALESCE(medium_id, ''),
            COALESCE(role, '')
        ) WHERE deleted_at IS NULL
        """
    )
