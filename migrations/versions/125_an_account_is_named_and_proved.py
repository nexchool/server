"""An account is named by identifiers and proved by credentials.

`users` answers both questions today. The account is found by `email` and
proved by `password_hash`, both NOT NULL — which is why a student with no
email address has no account at all (ADR-003 makes that deliberate, and the
bulk importer contradicts it by demanding one), and why there is nowhere to
put a second way of signing in.

This migration lays the storage that separates the two questions, and copies
what `users` already holds into it. **Nothing reads these tables yet.** Login
resolves through `User.get_user_by_email` and verifies against
`users.password_hash` exactly as before; the legacy columns stay authoritative
and NOT NULL. Expand only — a later phase migrates the read paths, and a later
one still relaxes the columns.

**Deterministic ids, not generated ones.** `md5('ident:email:' || u.id)` gives
each row an id derived from the account it describes, so running the backfill
twice cannot produce a second identifier for the same account — the same
device migration 082 used to make the person backfill re-runnable, and the
reason this migration is safe to meet on a database that has already seen it.

**The normalized value is `lower(btrim(email))`,** matching
`modules/auth/identifiers.py::normalize_email`. Audited before writing: no
tenant holds two live accounts whose addresses differ only by case, so the
partial unique index below applies to data already conforming to it.

**`hash_algorithm` is read out of the hash, not assumed.** A werkzeug hash
carries its method in the first `$`-separated field (`scrypt:32768:8:1`,
`pbkdf2:sha256:600000`). Rows whose hash carries no `$` — the development
database has 15,600 fixture accounts whose `password_hash` is the literal
string `x` — are recorded as `unknown` rather than being given an algorithm
they do not have. The hash is copied verbatim either way; this migration
judges no password, invalidates none, and re-hashes none.

Revision ID: 125_an_account_is_named_and_proved
Revises: 124_a_person_signs_in_as_one_account
Create Date: 2026-09-04

"""
import sqlalchemy as sa
from alembic import op

revision = "125_an_account_is_named_and_proved"
down_revision = "124_a_person_signs_in_as_one_account"
branch_labels = None
depends_on = None


# Every account with an address gets one primary email identifier, carrying
# the verification state the account already records.
_EMAIL_IDENTIFIER_FOR_EVERY_ACCOUNT = sa.text(
    """
    INSERT INTO account_identifiers (
        id, tenant_id, account_id, identifier_type,
        identifier_value, identifier_value_normalized,
        is_verified, verified_at, is_primary,
        created_at, updated_at, deleted_at
    )
    SELECT md5('ident:email:' || u.id)::uuid::text,
           u.tenant_id,
           u.id,
           'email',
           u.email,
           lower(btrim(u.email)),
           u.email_verified,
           -- The account records *whether* it was verified, never when. An
           -- invented timestamp would be a fact nobody stated, so the account's
           -- own last update is used and only where it claims verification.
           CASE WHEN u.email_verified THEN u.updated_at END,
           true,
           now(), now(),
           -- A closed account's identifier is closed too, or it would hold the
           -- address against the live account that replaces it.
           u.deleted_at
      FROM users u
     WHERE u.email IS NOT NULL
       AND btrim(u.email) <> ''
    ON CONFLICT DO NOTHING
    """
)

# Every account with a hash gets one password credential holding it verbatim.
_PASSWORD_CREDENTIAL_FOR_EVERY_ACCOUNT = sa.text(
    """
    INSERT INTO account_credentials (
        id, tenant_id, account_id, credential_type,
        secret_hash, hash_algorithm,
        must_change, is_provisional,
        issued_at, created_at, updated_at, deleted_at
    )
    SELECT md5('cred:password:' || u.id)::uuid::text,
           u.tenant_id,
           u.id,
           'password',
           u.password_hash,
           CASE
               WHEN position('$' in u.password_hash) > 0
                   THEN split_part(u.password_hash, '$', 1)
               ELSE 'unknown'
           END,
           u.force_password_reset,
           -- Provisional is a fact about who chose the secret, and `users`
           -- does not record it. The forced-change flag is the only evidence
           -- there is that somebody else did, so it is what is carried over.
           u.force_password_reset,
           u.created_at,
           now(), now(),
           u.deleted_at
      FROM users u
     WHERE u.password_hash IS NOT NULL
       AND u.password_hash <> ''
    ON CONFLICT DO NOTHING
    """
)


def upgrade():
    op.create_table(
        "account_identifiers",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("account_id", sa.String(36), nullable=False),
        sa.Column("identifier_type", sa.String(30), nullable=False),
        sa.Column("identifier_value", sa.Text(), nullable=False),
        sa.Column("identifier_value_normalized", sa.Text(), nullable=False),
        sa.Column(
            "is_verified", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_primary", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("issued_by_user_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["issued_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "identifier_type IN ('email', 'admission_id', 'mobile', 'employee_code')",
            name="ck_account_identifiers_type",
        ),
    )
    op.create_index(
        "ix_account_identifiers_tenant_id", "account_identifiers", ["tenant_id"]
    )
    op.create_index(
        "ix_account_identifiers_account_id", "account_identifiers", ["account_id"]
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_account_identifiers_live
            ON account_identifiers (tenant_id, identifier_type,
                                    identifier_value_normalized)
         WHERE deleted_at IS NULL
        """
    )
    op.create_index(
        "idx_account_identifiers_lookup",
        "account_identifiers",
        ["tenant_id", "identifier_type", "identifier_value_normalized"],
    )
    op.create_index(
        "idx_account_identifiers_account",
        "account_identifiers",
        ["account_id", "identifier_type"],
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_account_identifiers_primary
            ON account_identifiers (account_id, identifier_type)
         WHERE is_primary AND deleted_at IS NULL
        """
    )

    op.create_table(
        "account_credentials",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("account_id", sa.String(36), nullable=False),
        sa.Column("credential_type", sa.String(20), nullable=False),
        sa.Column("secret_hash", sa.Text(), nullable=False),
        sa.Column("hash_algorithm", sa.String(40), nullable=False),
        sa.Column(
            "must_change", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "is_provisional", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("issued_by_user_id", sa.String(36), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["issued_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "credential_type IN ('password', 'pin')",
            name="ck_account_credentials_type",
        ),
    )
    op.create_index(
        "ix_account_credentials_tenant_id", "account_credentials", ["tenant_id"]
    )
    op.create_index(
        "ix_account_credentials_account_id", "account_credentials", ["account_id"]
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_account_credentials_live
            ON account_credentials (account_id, credential_type)
         WHERE deleted_at IS NULL
        """
    )

    op.execute(_EMAIL_IDENTIFIER_FOR_EVERY_ACCOUNT)
    op.execute(_PASSWORD_CREDENTIAL_FOR_EVERY_ACCOUNT)


def downgrade():
    # The tables carry nothing `users` does not still hold, so dropping them
    # loses no fact. That is only true while the legacy columns remain
    # authoritative — it stops being true in the contract phase, which is why
    # that phase is a separate one.
    op.drop_table("account_credentials")
    op.drop_table("account_identifiers")
