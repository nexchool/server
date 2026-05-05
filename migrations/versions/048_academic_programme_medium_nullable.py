"""Academic programme medium optional (nullable).

Revision ID: 048_academic_programme_medium_nullable
Revises: 047_subscription_and_usage
Create Date: 2026-04-30

Boards like CBSE / ICSE are often single-medium in practice; international
sales also need a language-of-instruction field to be optional. Relax
`academic_programmes.medium` to NULL when not specified.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "048_academic_programme_medium_nullable"
down_revision = "047_subscription_and_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "academic_programmes",
        "medium",
        existing_type=sa.String(length=64),
        nullable=True,
    )


def downgrade() -> None:
    op.execute(
        "UPDATE academic_programmes SET medium = '' WHERE medium IS NULL"
    )
    op.alter_column(
        "academic_programmes",
        "medium",
        existing_type=sa.String(length=64),
        nullable=False,
    )
