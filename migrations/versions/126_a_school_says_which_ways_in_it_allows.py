"""A school says which ways in it allows.

Which authentication methods a school permits, for which of its people, on
which application — stored where it can be constrained, queried per rule and
audited. Configuration only: **nothing reads these tables in this phase.**
Login resolves and verifies exactly as it did before, and the pipeline that
consumes this arrives later.

**Not in `tenants.feature_flags`, and the reason is written into that file.**
`update_tenant_feature_flags` merges and never prunes, so keys outlive the
modules that named them — `RETIRED_FEATURE_KEYS` lists six still stored as
`true` on live tenants, and one of them switched a module on in production
because a stored value beat its default. Authentication policy is the last
thing that should inherit a stale answer, and a JSON bag cannot say who
enabled a method or when.

**Absence means denied.** An enabled row permits a method; no row refuses it.
That is the opposite of the feature-flag convention and is chosen on purpose.

**The seed is exactly today's behaviour.** Every existing school gets
email-and-password enabled for students, staff and parents on every surface,
plus shared family access (ADR-011's default) and a forced first-login change.
So installing this migration is observably a no-op: nobody gains a way in and,
more to the point, nobody loses one.

Deterministic ids, following migration 082's device: the policy row is keyed by
tenant, and each seeded rule's id is derived from what it says, so running this
twice cannot produce a second copy of the same rule.

Revision ID: 126_a_school_says_which_ways_in_it_allows
Revises: 125_an_account_is_named_and_proved
Create Date: 2026-09-04

"""
import sqlalchemy as sa
from alembic import op

revision = "126_a_school_says_which_ways_in_it_allows"
down_revision = "125_an_account_is_named_and_proved"
branch_labels = None
depends_on = None

SUBJECT_KINDS = ("student", "staff", "parent")
DEFAULT_METHOD = "email_password"
SURFACE_ANY = "any"

_POLICY_FOR_EVERY_TENANT = sa.text(
    """
    INSERT INTO tenant_auth_policies (
        tenant_id, family_access_mode, student_credential_policy,
        created_at, updated_at
    )
    SELECT t.id, 'shared_with_student', 'force_change_on_first_login',
           now(), now()
      FROM tenants t
    ON CONFLICT (tenant_id) DO NOTHING
    """
)

_DEFAULT_RULE = sa.text(
    """
    INSERT INTO tenant_auth_policy_rules (
        id, tenant_id, subject_kind, surface, method_key,
        is_enabled, enabled_at, notes, created_at, updated_at
    )
    SELECT md5('authrule:' || t.id || ':' || :subject_kind || ':'
               || :surface || ':' || :method_key)::uuid::text,
           t.id, :subject_kind, :surface, :method_key,
           true, now(),
           'Seeded default: the school''s behaviour before authentication '
           'policy existed.',
           now(), now()
      FROM tenants t
    ON CONFLICT ON CONSTRAINT uq_tenant_auth_policy_rules DO NOTHING
    """
)


def upgrade():
    op.create_table(
        "tenant_auth_policies",
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column(
            "family_access_mode",
            sa.String(30),
            nullable=False,
            server_default="shared_with_student",
        ),
        sa.Column(
            "student_credential_policy",
            sa.String(40),
            nullable=False,
            server_default="force_change_on_first_login",
        ),
        sa.Column("updated_by_user_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # One policy per school, said by the primary key rather than by a
        # separate constraint.
        sa.PrimaryKeyConstraint("tenant_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "family_access_mode IN ('shared_with_student', 'separate_parent_login')",
            name="ck_tenant_auth_policies_family_access_mode",
        ),
        sa.CheckConstraint(
            "student_credential_policy IN "
            "('force_change_on_first_login', 'no_forced_change')",
            name="ck_tenant_auth_policies_student_credential_policy",
        ),
    )

    op.create_table(
        "tenant_auth_policy_rules",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("subject_kind", sa.String(20), nullable=False),
        sa.Column("surface", sa.String(30), nullable=False, server_default="any"),
        sa.Column("method_key", sa.String(40), nullable=False),
        sa.Column(
            "is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("enabled_by_user_id", sa.String(36), nullable=True),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["enabled_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "subject_kind IN ('student', 'staff', 'parent')",
            name="ck_tenant_auth_policy_rules_subject_kind",
        ),
        # One answer per question: two rows disagreeing about the same
        # (school, kind, surface, method) would make the policy unreadable.
        sa.UniqueConstraint(
            "tenant_id",
            "subject_kind",
            "surface",
            "method_key",
            name="uq_tenant_auth_policy_rules",
        ),
    )
    op.create_index(
        "ix_tenant_auth_policy_rules_tenant_id",
        "tenant_auth_policy_rules",
        ["tenant_id"],
    )
    op.create_index(
        "idx_tenant_auth_policy_rules_lookup",
        "tenant_auth_policy_rules",
        ["tenant_id", "subject_kind"],
    )

    connection = op.get_bind()
    connection.execute(_POLICY_FOR_EVERY_TENANT)
    for subject_kind in SUBJECT_KINDS:
        connection.execute(
            _DEFAULT_RULE,
            {
                "subject_kind": subject_kind,
                "surface": SURFACE_ANY,
                "method_key": DEFAULT_METHOD,
            },
        )


def downgrade():
    # Configuration only, and equal to the product's behaviour without it, so
    # dropping these loses no fact about any account.
    op.drop_table("tenant_auth_policy_rules")
    op.drop_table("tenant_auth_policies")
