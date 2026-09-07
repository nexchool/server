"""Whose wire a school's messages go down.

Migration 128 recorded what a school *buys* — a service, from a vendor, at a
price. This records what actually happens at the moment of sending: which
provider carries this school's SMS, with what settings, and whether it is
switched on.

They are deliberately two tables. `tenant_services` is a commercial record and
outlives a routing change; a school can be signed up to two vendors while only
one carries traffic. Putting an endpoint or a credential reference on a
billing row would make a billing model responsible for how an HTTP call is
made.

**No credential is stored here.** `credential_references` holds the *names* of
environment variables, never their values — so a database dump contains no
provider secrets, and an API response that forgot to redact one has nothing to
reveal.

Additive. One new table, nothing altered, nothing backfilled. Every school
starts with no integrations, which is what it has today, and every row that
does appear starts `disabled` — configuring a provider must not start sending
anything on its own.

Revision ID: 129_whose_wire_a_schools_messages_go_down
Revises: 128_what_a_school_pays_for_and_what_it_costs_us
"""

import sqlalchemy as sa
from alembic import op

revision = "129_whose_wire_a_schools_messages_go_down"
down_revision = "128_what_a_school_pays_for_and_what_it_costs_us"
branch_labels = None
depends_on = None

CAPABILITIES = "('sms')"
STATUSES = "('disabled', 'enabled', 'failed')"


def upgrade():
    op.create_table(
        "tenant_integrations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # What it does, not who does it.
        sa.Column("capability", sa.String(40), nullable=False),
        # Matches `service_providers.key`, so an operator reading a bill and an
        # operator reading a log see the same vendor name.
        sa.Column("provider_key", sa.String(60), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="disabled"),
        # Non-secret settings: a sender id, a route. Safe to return and to log.
        sa.Column("configuration", sa.JSON(), nullable=False, server_default="{}"),
        # Purpose → environment variable NAME. Never a value.
        sa.Column(
            "credential_references", sa.JSON(), nullable=False, server_default="{}"
        ),
        sa.Column("status_detail", sa.Text(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "enabled_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
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
        # One provider per capability per school. Selection has to be
        # unambiguous, and an index guarantees that better than a query that
        # remembers to order deterministically.
        sa.UniqueConstraint(
            "tenant_id", "capability", name="uq_tenant_integrations_capability"
        ),
        sa.CheckConstraint(
            f"capability IN {CAPABILITIES}", name="ck_tenant_integrations_capability"
        ),
        sa.CheckConstraint(
            f"status IN {STATUSES}", name="ck_tenant_integrations_status"
        ),
    )
    op.create_index(
        "idx_tenant_integrations_tenant_id", "tenant_integrations", ["tenant_id"]
    )


def downgrade():
    op.drop_index("idx_tenant_integrations_tenant_id", table_name="tenant_integrations")
    op.drop_table("tenant_integrations")
