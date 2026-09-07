"""A school may be configured for WhatsApp.

Migration 129 created `ck_tenant_integrations_capability` as
`f"capability IN {CAPABILITIES}"` — an f-string that interpolated the *live*
Python constant at the moment 129 ran. `CAPABILITIES` was `('sms',)` then, so
every database that has applied 129 carries a constraint that permits only
`sms`, while `modules/integrations/models.py` builds the same constraint
dynamically from the same constant, which is now `('sms', 'whatsapp')`. Model
and database disagree, and only the database's opinion is enforced at the SQL
level: no school can be stored with a WhatsApp integration until this widens
what Postgres itself will accept.

**Why the replacement is a literal, never `str(tuple(CAPABILITIES))` or any
other read of the live constant.** A migration is a record of one change at
one moment in this database's history — replaying it later is supposed to
reproduce exactly the schema it produced the day it was authored. A migration
body that reads a constant is not recording a moment; it is recording a
*reference* to whatever that constant happens to be when the migration runs,
so its meaning drifts as the code moves on without the migration file ever
changing. That is precisely how 129 went wrong: it did not mean anything
different in code than it does today, and yet the database it produced no
longer matches what the model claims. A literal fixes the meaning at the
moment this file is written, the same way every other historical migration on
this table is a record of a change, not a computation of one.

Existing rows are all `sms` (129's constraint permitted nothing else), so
there is nothing to backfill — this only enlarges what a future row may be.

Revision ID: 135_a_school_may_be_configured_for_whatsapp
Revises: 134_which_wire_a_schools_codes_go_down
"""

from alembic import op

revision = "135_a_school_may_be_configured_for_whatsapp"
down_revision = "134_which_wire_a_schools_codes_go_down"
branch_labels = None
depends_on = None

_CONSTRAINT = "ck_tenant_integrations_capability"


def upgrade():
    op.drop_constraint(_CONSTRAINT, "tenant_integrations", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        "tenant_integrations",
        "capability IN ('sms', 'whatsapp')",
    )


def downgrade():
    op.drop_constraint(_CONSTRAINT, "tenant_integrations", type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        "tenant_integrations",
        "capability IN ('sms')",
    )
