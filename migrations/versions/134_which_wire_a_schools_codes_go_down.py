"""Which wire a school's sign-in codes go down.

Adds one column with a default equal to today's behaviour, so every existing
school keeps sending codes by SMS until an operator chooses otherwise. There
is no data to migrate and nothing to backfill.

The check constraint matches its two siblings on this table
(`ck_tenant_auth_policies_family_access_mode`,
`ck_tenant_auth_policies_student_credential_policy`): the application
already refuses an unknown channel, but a script or a shell writing to this
table directly does not go through the application, and a status-like column
without a database-level constraint is exactly the shape that lets a bad
value in.
"""

from alembic import op
import sqlalchemy as sa

revision = "134_which_wire_a_schools_codes_go_down"
down_revision = "133_an_auth_event_says_who_did_it"
branch_labels = None
depends_on = None

_CONSTRAINT = "ck_tenant_auth_policies_otp_delivery_channel"


def upgrade():
    op.add_column(
        "tenant_auth_policies",
        sa.Column(
            "otp_delivery_channel",
            sa.String(length=20),
            nullable=False,
            server_default="sms",
        ),
    )
    op.create_check_constraint(
        _CONSTRAINT,
        "tenant_auth_policies",
        "otp_delivery_channel IN ('sms', 'whatsapp')",
    )


def downgrade():
    op.drop_constraint(_CONSTRAINT, "tenant_auth_policies", type_="check")
    op.drop_column("tenant_auth_policies", "otp_delivery_channel")
