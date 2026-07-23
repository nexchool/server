"""add template_board_code to academic_programmes

Records which board template a programme's curriculum came from, so subjects and
offerings can be re-derived at any time rather than only at onboarding. Nullable
because programmes created before this migration have no recorded source, and
because a school may define a programme with no template behind it.

Length 30 matches subject_template_groups.board_code.

Revision ID: 071_programme_template_board_code
Revises: 070_tenant_onboarding_drafts
Create Date: 2026-07-20
"""

from alembic import op
import sqlalchemy as sa


revision = "071_programme_template_board_code"
down_revision = "070_tenant_onboarding_drafts"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "academic_programmes",
        sa.Column("template_board_code", sa.String(length=30), nullable=True),
    )


def downgrade():
    op.drop_column("academic_programmes", "template_board_code")
