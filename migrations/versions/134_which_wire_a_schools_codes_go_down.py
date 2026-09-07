"""Which wire a school's sign-in codes go down.

Adds one column with a default equal to today's behaviour, so every existing
school keeps sending codes by SMS until an operator chooses otherwise. There
is no data to migrate and nothing to backfill.
"""

from alembic import op
import sqlalchemy as sa

revision = "134_which_wire_a_schools_codes_go_down"
down_revision = "133_an_auth_event_says_who_did_it"
branch_labels = None
depends_on = None


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


def downgrade():
    op.drop_column("tenant_auth_policies", "otp_delivery_channel")
