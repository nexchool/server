"""An auth event says who did it.

Phase 1c needed to record which operator reset somebody's password and had no
column for it, so the actor was encoded into the event's `user_agent` slot as
`actor:<id>` — honest about being a workaround, and registered as debt 55. This
phase is the one completing the authentication lifecycle, which makes it the
right time: an audit trail that cannot be queried by actor is not an audit
trail an incident review can use.

`SET NULL` rather than cascade: a departed administrator's account may be
removed, and the record that somebody reset a credential must survive the
removal of the person who did it.

Historical rows are migrated where the encoding makes it unambiguous — the
`actor:` prefix is machine-written and nothing else produces it — and the slot
is cleared only for those rows. **No actor is invented.** An event that never
recorded one keeps a null.

Revision ID: 133_an_auth_event_says_who_did_it
Revises: 132_a_refresh_token_that_can_only_be_used_once
"""

import sqlalchemy as sa
from alembic import op

revision = "133_an_auth_event_says_who_did_it"
down_revision = "132_a_refresh_token_that_can_only_be_used_once"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "auth_events",
        sa.Column(
            "actor_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("idx_auth_events_actor", "auth_events", ["tenant_id", "actor_user_id"])

    # Move what the workaround recorded, and only that. The prefix is
    # machine-written; a real user agent never starts with it.
    op.execute(
        sa.text(
            """
            UPDATE auth_events
               SET actor_user_id = substring(user_agent from 7),
                   user_agent = NULL
             WHERE user_agent LIKE 'actor:%'
               AND EXISTS (
                     SELECT 1 FROM users u
                      WHERE u.id = substring(auth_events.user_agent from 7)
                   )
            """
        )
    )


def downgrade():
    # Put the encoding back for the rows that carried it, so a downgrade loses
    # nothing an upgrade recorded.
    op.execute(
        sa.text(
            """
            UPDATE auth_events
               SET user_agent = 'actor:' || actor_user_id
             WHERE actor_user_id IS NOT NULL
               AND user_agent IS NULL
            """
        )
    )
    op.drop_index("idx_auth_events_actor", table_name="auth_events")
    op.drop_column("auth_events", "actor_user_id")
