"""A code that lives for five minutes.

Mobile OTP needs somewhere to keep a code while it is in flight — long enough
to check it once, and not a moment longer. That is not a credential: an
`account_credential` is something an account keeps, and its own docstring says
an OTP "is issued, verified and destroyed in flight, and gets no row here."
So this is its own table, and everything in it is shaped by being temporary.

**No secret is stored.** The code is kept as a per-challenge salted hash, and
the phone number as a keyed digest — there is no operator who reads these rows
to recognise a person, so keeping a number in clear would be storing personal
data for no purpose it serves.

Purely additive. One new table; nothing existing is altered, backfilled or
reinterpreted. No identifier is created, no policy row is written, and no
school gains a sign-in method by this migration running — `mobile_otp` is off
for every tenant until somebody turns it on.

Revision ID: 130_a_code_that_lives_for_five_minutes
Revises: 129_whose_wire_a_schools_messages_go_down
"""

import sqlalchemy as sa
from alembic import op

revision = "130_a_code_that_lives_for_five_minutes"
down_revision = "129_whose_wire_a_schools_messages_go_down"
branch_labels = None
depends_on = None

STATUSES = "('created', 'sent', 'failed', 'consumed', 'superseded')"


def upgrade():
    op.create_table(
        "mobile_otp_challenges",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Bound at issue time, so verification cannot be redirected to another
        # account by anything the caller sends.
        sa.Column(
            "account_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "identifier_id",
            sa.String(36),
            sa.ForeignKey("account_identifiers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Keyed digests, never the values. See the module docstring.
        sa.Column("mobile_hash", sa.String(64), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("code_salt", sa.String(32), nullable=False),
        sa.Column(
            "purpose", sa.String(40), nullable=False, server_default="authentication_otp"
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="created"),
        # The limit is stored, not read from config at verification time, so
        # changing the setting cannot give a live challenge more guesses.
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_reference", sa.String(120), nullable=True),
        sa.Column("failure_code", sa.String(40), nullable=True),
        sa.Column(
            "superseded_by_id",
            sa.String(36),
            sa.ForeignKey("mobile_otp_challenges.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("request_ip_hash", sa.String(64), nullable=True),
        sa.Column("client_surface", sa.String(30), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(f"status IN {STATUSES}", name="ck_mobile_otp_status"),
        sa.CheckConstraint("attempts >= 0", name="ck_mobile_otp_attempts"),
        sa.CheckConstraint("max_attempts > 0", name="ck_mobile_otp_max_attempts"),
    )
    # The verification read path: this school, this number, still live.
    op.create_index(
        "idx_mobile_otp_lookup",
        "mobile_otp_challenges",
        ["tenant_id", "mobile_hash", "status", "expires_at"],
    )
    op.create_index(
        "idx_mobile_otp_account", "mobile_otp_challenges", ["tenant_id", "account_id"]
    )


def downgrade():
    op.drop_index("idx_mobile_otp_account", table_name="mobile_otp_challenges")
    op.drop_index("idx_mobile_otp_lookup", table_name="mobile_otp_challenges")
    op.drop_table("mobile_otp_challenges")
