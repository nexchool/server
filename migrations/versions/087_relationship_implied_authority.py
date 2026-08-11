"""authority implied by a business relationship

A student holds no organizational authority. Nobody grants them the right to
see their own attendance — it follows from being a student. This marks the
Authority Profile that a relationship implies, so that access can be derived
rather than assigned account by account (ADR-013).

Marked on the profile rather than matched by name, so that a school renaming
"Student" does not silently remove every student's access.

Revision ID: 087_relationship_implied_authority
Revises: 086_authority_delegation
Create Date: 2026-08-05
"""

from alembic import op
import sqlalchemy as sa

revision = "087_relationship_implied_authority"
down_revision = "086_authority_delegation"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "roles",
        sa.Column("implied_by_relationship", sa.String(length=30), nullable=True),
    )
    op.create_index(
        "ix_roles_implied_by_relationship", "roles", ["implied_by_relationship"]
    )

    # Preserve today's behaviour: the profile every student already holds is the
    # one their relationship now implies.
    op.execute("UPDATE roles SET implied_by_relationship = 'student' WHERE name = 'Student'")


def downgrade():
    op.drop_index("ix_roles_implied_by_relationship", table_name="roles")
    op.drop_column("roles", "implied_by_relationship")
