"""drop the stale `examinations` flag migration 043 left behind

Migration 043 seeded every tenant's `feature_flags` from the feature list of
the day, and that list carried an `examinations` key — a module name written
down before the module existed. The key was later dropped from
`OPTIONAL_FEATURES`, but the stored `true` stayed: `update_tenant_feature_flags`
merges rather than prunes, deliberately, because the same column doubles as a
per-tenant settings bag and pruning would delete a school's `login_variant`.

Harmless while nothing read the key. Not harmless now. The examination module
ships in `DEFAULT_OFF_FEATURES`, where a *missing* key means off — and a stored
value beats a default, so every tenant that went through 043 would switch the
module on the moment it was deployed. Which is precisely what defaulting it off
was for.

Deleting the key rather than setting it false, because false would be just as
much of an invented answer as true. No super-admin ever chose either: the key
was never in `FEATURE_LABELS` and never returned by `list_feature_catalog`, so
it appeared on no screen and nobody could have clicked it. Removing it lets the
default govern until somebody actually decides, and their decision then writes
a real answer.

Only `examinations` is touched. The other keys 043 left — `library`,
`inventory`, `reports`, `finance`, `holiday_management`, `schedule_management` —
are retired modules that nothing reads, and the live ones say `true` for
features that default to `true` anyway. This migration is about the one key
whose stale value changes behaviour.

Revision ID: 120_a_retired_feature_key_is_not_an_answer
Revises: 119_two_streams_may_share_a_subject
Create Date: 2026-08-25
"""

from alembic import op

revision = "120_a_retired_feature_key_is_not_an_answer"
down_revision = "119_two_streams_may_share_a_subject"
branch_labels = None
depends_on = None


def upgrade():
    # `-` removes a key from jsonb. The column is json, so it is cast both
    # ways; a tenant whose map does not hold the key is left alone by the WHERE.
    op.execute(
        """
        UPDATE tenants
           SET feature_flags = ((feature_flags::jsonb) - 'examinations')::json
         WHERE feature_flags::jsonb ? 'examinations'
        """
    )


def downgrade():
    # Restoring `true` would re-enable the module for every tenant, which is
    # the bug this migration exists to undo. Downgrading writes the value the
    # default already implies, so behaviour is unchanged in either direction
    # and nothing is silently switched on by going backwards.
    op.execute(
        """
        UPDATE tenants
           SET feature_flags = jsonb_set(
                 feature_flags::jsonb, '{examinations}', 'false'::jsonb, true
               )::json
         WHERE NOT (feature_flags::jsonb ? 'examinations')
        """
    )
