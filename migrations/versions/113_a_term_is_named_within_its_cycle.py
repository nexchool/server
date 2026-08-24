"""a term is named within its cycle, not across the whole year

Migration 112 gave terms a cycle and left their uniqueness where it was:

    uq_academic_terms_year_name  (tenant, academic_year_id, name)
    uq_academic_terms_year_code  (tenant, academic_year_id, code)

Which means a trust running two boards under 2026-27 could not do this:

    2026-27
      ├── GSEB Cycle → Term 1, Term 2
      └── CBSE Cycle → Term 1, Term 2

The second "Term 1" was refused. That is the rule this migration moves: a term
is a subdivision of a cycle, so its name is unique within that cycle.

Nothing is loosened for a school with one cycle — one cycle per year makes the
new indexes exactly the old ones. What changes is only what a second cycle is
allowed to be called.

The name is still unique *somewhere*: two "Term 1"s inside one cycle remain
refused, because that is a picker with two identical entries.

Revision ID: 113_a_term_is_named_within_its_cycle
Revises: 112_the_cycle_is_the_operating_period
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa

revision = "113_a_term_is_named_within_its_cycle"
down_revision = "112_the_cycle_is_the_operating_period"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    # A year with two cycles cannot exist yet — 112 made exactly one per year —
    # so nothing can currently violate the narrower rule. Checked rather than
    # assumed, because a migration that silently drops a constraint on data it
    # did not inspect is how duplicates arrive.
    clashing = bind.execute(
        sa.text(
            """
            SELECT count(*) FROM (
                SELECT tenant_id, academic_cycle_id, name
                  FROM academic_terms
                 WHERE deleted_at IS NULL
                 GROUP BY tenant_id, academic_cycle_id, name
                HAVING count(*) > 1
            ) duplicates
            """
        )
    ).scalar()
    if clashing:
        raise RuntimeError(
            f"{clashing} cycle(s) already hold two terms of the same name. "
            "Rename or soft-delete them before the uniqueness moves, or the "
            "narrower index cannot be created."
        )

    op.drop_index("uq_academic_terms_year_name", table_name="academic_terms")
    op.drop_index("uq_academic_terms_year_code", table_name="academic_terms")

    op.create_index(
        "uq_academic_terms_cycle_name",
        "academic_terms",
        ["tenant_id", "academic_cycle_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_academic_terms_cycle_code",
        "academic_terms",
        ["tenant_id", "academic_cycle_id", "code"],
        unique=True,
        postgresql_where=sa.text("code IS NOT NULL AND deleted_at IS NULL"),
    )


def downgrade():
    bind = op.get_bind()

    # Winding back re-imposes the year-wide rule, which a school that has taken
    # up two cycles will violate. Say so rather than fail on index creation
    # with a message about a duplicate key.
    clashing = bind.execute(
        sa.text(
            """
            SELECT count(*) FROM (
                SELECT tenant_id, academic_year_id, name
                  FROM academic_terms
                 WHERE deleted_at IS NULL
                 GROUP BY tenant_id, academic_year_id, name
                HAVING count(*) > 1
            ) duplicates
            """
        )
    ).scalar()
    if clashing:
        raise RuntimeError(
            f"{clashing} year(s) hold terms of the same name in different "
            "cycles — which is what this migration exists to allow. Reverting "
            "would have no correct row to drop. Restore from a backup instead."
        )

    op.drop_index("uq_academic_terms_cycle_code", table_name="academic_terms")
    op.drop_index("uq_academic_terms_cycle_name", table_name="academic_terms")
    op.create_index(
        "uq_academic_terms_year_name",
        "academic_terms",
        ["tenant_id", "academic_year_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_academic_terms_year_code",
        "academic_terms",
        ["tenant_id", "academic_year_id", "code"],
        unique=True,
        postgresql_where=sa.text("code IS NOT NULL AND deleted_at IS NULL"),
    )
