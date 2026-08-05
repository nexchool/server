"""every account belongs to a person

The constrain step of ADR-010 for accounts: `users.person_id` becomes mandatory
now that every account has been backfilled and new accounts are given a Person
as they are created.

Revision ID: 082_account_requires_person
Revises: 081_teacher_academic_participation
Create Date: 2026-08-05
"""

from alembic import op
import sqlalchemy as sa

revision = "082_account_requires_person"
down_revision = "081_teacher_academic_participation"
branch_labels = None
depends_on = None


def upgrade():
    # Fail with an instruction rather than a constraint violation: an operator
    # who has not run the backfill needs to know that, not to read a stack
    # trace about a null value.
    unlinked = (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM users WHERE person_id IS NULL"))
        .scalar()
    )
    if unlinked:
        raise RuntimeError(
            f"{unlinked} account(s) have no person. "
            "Run `python scripts/backfill_people.py` before applying this migration."
        )

    op.alter_column(
        "users", "person_id", existing_type=sa.String(length=36), nullable=False
    )


def downgrade():
    op.alter_column(
        "users", "person_id", existing_type=sa.String(length=36), nullable=True
    )
