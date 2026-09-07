"""A refresh token that can only be used once.

The old design kept the token in a plain column on `sessions`, verbatim and
without a unique constraint, and minted it as a JWT whose payload was
`{sub, type, iat, exp}`. Timestamps are whole seconds, so **two sign-ins by one
account inside one second produced byte-identical tokens** — characterized in
Phase −1 and left in place deliberately since. Two live sessions could share
one token; `logout` resolved it with `.first()` and revoked an arbitrary one,
and the token kept working afterwards.

This replaces that with an opaque random token, stored only as a sha256 digest,
unique, single-use and rotated on every refresh, with consumed generations kept
so that replaying one is *detectable* rather than merely ineffective.

**Existing sessions are ended by this migration, and that is deliberate.**
Carrying them over is not safely possible: the values in `sessions.refresh_token`
are exactly the ones known to collide, so there is no way to tell a legitimate
token from a duplicate of somebody else's, and hashing them forward would carry
that ambiguity into the new unique index — where the second row would fail to
insert and the failure would be silent about which human lost their session.
Everyone signs in again once. Nobody loses an account, a credential, an
identifier or any data.

`sessions.refresh_token` is left in place and stops being written. Dropping a
column is a contraction, and this is the expanding half.

Revision ID: 132_a_refresh_token_that_can_only_be_used_once
Revises: 131_a_parent_role_nobody_could_hold
"""

import sqlalchemy as sa
from alembic import op

revision = "132_a_refresh_token_that_can_only_be_used_once"
down_revision = "131_a_parent_role_nobody_could_hold"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The family. Every generation shares it, so detecting reuse of one
        # can end all of them.
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Unique — the guarantee the old column could not make.
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "generation", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        # Kept, not deleted: a row that is gone cannot tell you it was replayed.
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "replaced_by_id",
            sa.String(36),
            sa.ForeignKey("refresh_tokens.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("generation > 0", name="ck_refresh_tokens_generation"),
    )
    op.create_index("idx_refresh_tokens_session", "refresh_tokens", ["tenant_id", "session_id"])
    op.create_index("ix_refresh_tokens_session_id", "refresh_tokens", ["session_id"])
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_tenant_id", "refresh_tokens", ["tenant_id"])

    # Every session that could be resumed with an old-format token is ended.
    # Not a data loss: a session is a convenience, and the alternative is
    # honouring tokens we know may be shared between two people.
    op.execute(
        sa.text(
            """
            UPDATE sessions
               SET revoked = true,
                   revoked_at = now(),
                   refresh_token = NULL
             WHERE revoked = false
            """
        )
    )


def downgrade():
    # The sessions revoked above are not un-revoked: their tokens were
    # discarded on the way up and cannot be reconstructed, and inventing new
    # ones would be worse than asking for a sign-in.
    op.drop_index("ix_refresh_tokens_tenant_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_index("ix_refresh_tokens_session_id", table_name="refresh_tokens")
    op.drop_index("idx_refresh_tokens_session", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
