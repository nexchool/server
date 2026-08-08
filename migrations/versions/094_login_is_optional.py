"""A studentship or an employment does not require a login.

ADR-003 separates authentication from identity: a person exists in the
school's records whether or not the school issues them an account. ADR-010
names ``students.user_id`` and ``teachers.user_id`` NOT NULL as the v1 defect
that made this impossible — every admission and every hire was forced to mint
an account, and when no email existed the code minted a *placeholder* login
(`@student.placeholder` / `@teacher.school`) nobody could ever use.

This relaxes both columns. The tenant-scoped unique constraints stay: Postgres
treats NULLs as distinct, so any number of account-less rows coexist while a
real account can still back at most one student and one teacher per tenant.

Revision ID: 094_login_is_optional
Revises: 093_the_school_has_a_clock
"""

import sqlalchemy as sa
from alembic import op

revision = "094_login_is_optional"
down_revision = "093_the_school_has_a_clock"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "students", "user_id", existing_type=sa.String(length=36), nullable=True
    )
    op.alter_column(
        "teachers", "user_id", existing_type=sa.String(length=36), nullable=True
    )


def downgrade():
    # Restore NOT NULL only if the data can satisfy it: an account-less row
    # has no user_id to give (same rule as migration 090's downgrade).
    bind = op.get_bind()
    for table in ("students", "teachers"):
        orphans = bind.execute(
            sa.text(f"SELECT COUNT(*) FROM {table} WHERE user_id IS NULL")
        ).scalar()
        if orphans:
            raise RuntimeError(
                f"{orphans} {table} rows have no account; link or remove them "
                "before restoring NOT NULL."
            )
    op.alter_column(
        "students", "user_id", existing_type=sa.String(length=36), nullable=False
    )
    op.alter_column(
        "teachers", "user_id", existing_type=sa.String(length=36), nullable=False
    )
