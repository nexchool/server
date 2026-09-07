"""The door records who came through it, and how.

Phase 0d moves sign-in onto a pipeline with one registry of methods and one
place where the gates live. This migration adds only what that needs to
record what it now knows.

**`auth_events`** — until now `modules/auth/` wrote exactly one audit record in
the entire module, the platform admin's god-login entry. Nothing recorded a
successful sign-in, a failed one, or why. Deliberately *not* a
`TenantBaseModel`: a failed attempt that named no school has no tenant to
record, and the platform has to be able to read across schools to notice one
attacker working through several. Identifier values are stored as a sha256
hash — enough to correlate repeated attempts, useless as a mailing list.

**`sessions.login_method` widened to 40** — the column has existed since
migration 001 with a default of `"email"` and nothing has ever written it.
The pipeline writes the strategy key, and `admission_id_password` is 21
characters, so `String(20)` would have truncated silently the first time a
later phase used it.

**`sessions.client_surface`** — which application signed in. Self-declared by
the caller, so telemetry and product policy, never a security boundary.
Defaults to `unknown`, and `unknown` stays permanently valid: a mobile build
that predates the header must keep working.

**`sessions.authenticated_identifier_id`** — *which* identifier authenticated,
not merely which type. "Which address did he sign in with" is the question
support actually asks, and a type cannot answer it.

Existing sessions are left exactly as they are. They keep `login_method =
'email'` because that is what the column said when they were created, and
rewriting history to make a report tidier would be inventing facts. Nobody is
signed out by this migration.

Revision ID: 127_the_door_records_who_came_through_it
Revises: 126_a_school_says_which_ways_in_it_allows
Create Date: 2026-09-04

"""
import sqlalchemy as sa
from alembic import op

revision = "127_the_door_records_who_came_through_it"
down_revision = "126_a_school_says_which_ways_in_it_allows"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auth_events",
        sa.Column("id", sa.String(36), nullable=False),
        # Nullable: an attempt that named no school has no tenant to record.
        sa.Column("tenant_id", sa.String(36), nullable=True),
        # Nullable: a failed attempt has no account.
        sa.Column("account_id", sa.String(36), nullable=True),
        sa.Column("identifier_type", sa.String(30), nullable=True),
        sa.Column("identifier_value_hash", sa.String(64), nullable=True),
        sa.Column("method_key", sa.String(40), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("reason", sa.String(40), nullable=True),
        sa.Column("client_surface", sa.String(30), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("session_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        # SET NULL rather than CASCADE throughout: the record that an attempt
        # happened outlives the account, session or school it was about. That
        # is most of the point of a security log.
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["account_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_auth_events_tenant_id", "auth_events", ["tenant_id"])
    op.create_index("ix_auth_events_account_id", "auth_events", ["account_id"])
    op.create_index("ix_auth_events_event_type", "auth_events", ["event_type"])
    op.create_index("ix_auth_events_created_at", "auth_events", ["created_at"])
    op.create_index(
        "ix_auth_events_identifier_value_hash",
        "auth_events",
        ["identifier_value_hash"],
    )
    op.create_index(
        "idx_auth_events_tenant_created", "auth_events", ["tenant_id", "created_at"]
    )
    op.create_index(
        "idx_auth_events_account_created", "auth_events", ["account_id", "created_at"]
    )
    op.create_index(
        "idx_auth_events_identifier_created",
        "auth_events",
        ["identifier_value_hash", "created_at"],
    )

    op.alter_column(
        "sessions",
        "login_method",
        existing_type=sa.String(20),
        type_=sa.String(40),
        existing_nullable=False,
        existing_server_default="email",
    )
    op.add_column(
        "sessions",
        sa.Column(
            "client_surface",
            sa.String(30),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column(
        "sessions",
        sa.Column("authenticated_identifier_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "fk_sessions_authenticated_identifier_id",
        "sessions",
        "account_identifiers",
        ["authenticated_identifier_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint(
        "fk_sessions_authenticated_identifier_id", "sessions", type_="foreignkey"
    )
    op.drop_column("sessions", "authenticated_identifier_id")
    op.drop_column("sessions", "client_surface")
    op.alter_column(
        "sessions",
        "login_method",
        existing_type=sa.String(40),
        type_=sa.String(20),
        existing_nullable=False,
        existing_server_default="email",
    )
    op.drop_table("auth_events")
