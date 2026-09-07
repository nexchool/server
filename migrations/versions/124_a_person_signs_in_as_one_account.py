"""A person signs in as one account.

The first invariant of the identity work: within one school, a human has at
most one live account. Everything the identity architecture goes on to add —
several identifiers on an account, several credentials, a parent login for
somebody who is already a teacher — assumes there is one account to attach
them to. Without this, "give this student an admission-number login" quietly
becomes "give this student a second account", because `record_person()`
constructs a new Person every time it is called and nothing compared them.

**Partial on `deleted_at IS NULL`, and that is the point.** `users` already
carries `uq_users_email_tenant`, which does *not* exclude soft-deleted rows —
which is why `create_student`, `create_teacher` and `create_sub_admin` all
pass `include_deleted=True` to their duplicate guards, and why a closed
account's email can never be reused. This index does not repeat that: a
person whose account was closed must be able to receive a new one.

**Tenant-scoped, not global.** `persons` is itself tenant-scoped, so the same
human at two schools is two Person rows and two accounts. That is what a
tenant membership is, not a duplicate. And this says nothing whatever about
email: two different people may share an address, which
`uq_users_email_tenant` already permits across tenants and this must not
start forbidding.

Audited before writing, against the 15,944 accounts in the development
database: no `(tenant_id, person_id)` pair had more than one row, live or
soft-deleted. The index is created against data already conforming to it.

`IF NOT EXISTS` in both directions: the test suite `create_all()`s against the
same database, so this has to be safe to meet twice.

Revision ID: 124_a_person_signs_in_as_one_account
Revises: 123_a_school_may_wear_its_own_colours
Create Date: 2026-09-04

"""
from alembic import op

revision = "124_a_person_signs_in_as_one_account"
down_revision = "123_a_school_may_wear_its_own_colours"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_users_tenant_person_live"


def upgrade():
    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_NAME}
            ON users (tenant_id, person_id)
         WHERE deleted_at IS NULL
        """
    )


def downgrade():
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
