"""A parent role nobody could hold.

Every school has been seeded with a `Parent` authority profile since roles
existed, carrying a sensible set of read permissions for a child's attendance,
timetable and results. Nobody has ever held it, and nobody could: authority is
implied from a relationship by matching `roles.implied_by_relationship`, the
catalogue never declared one for `Parent`, and so the implication had nothing
to match on. The role has been sitting in every tenant, complete and
unreachable.

The catalogue now declares it, which fixes new schools. This fixes the ones
that already exist — the same shape as migration 103, which is the precedent
in this repository for "the catalogue changed and existing rows must follow"
(the seeder deliberately only ever *adds* permissions, so it cannot do this).

**This grants nobody anything on its own.** The implication is additionally
gated on the school running separate parent logins (ADR-011), and every school
defaults to shared access, where a household signs in as the student. A school
that has not chosen separate logins sees no difference whatsoever — which is
the whole point of doing it this way rather than by granting roles to people.

Only rows the catalogue owns and only where the column is unset: a role a
school renamed, or one somebody deliberately pointed at something else, is
left alone.

Revision ID: 131_a_parent_role_nobody_could_hold
Revises: 130_a_code_that_lives_for_five_minutes
"""

import sqlalchemy as sa
from alembic import op

revision = "131_a_parent_role_nobody_could_hold"
down_revision = "130_a_code_that_lives_for_five_minutes"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        sa.text(
            """
            UPDATE roles
               SET implied_by_relationship = 'parent'
             WHERE name = 'Parent'
               AND implied_by_relationship IS NULL
            """
        )
    )


def downgrade():
    # Back to unreachable, which is where it was. Scoped the same way, so a
    # value somebody set on purpose after this ran is not taken away.
    op.execute(
        sa.text(
            """
            UPDATE roles
               SET implied_by_relationship = NULL
             WHERE name = 'Parent'
               AND implied_by_relationship = 'parent'
            """
        )
    )
