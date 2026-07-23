"""create tenant_onboarding_drafts

Holds the in-progress onboarding config for one tenant while an operator fills
in the panel form. One row per tenant; the row is deleted when the config is
applied.

Revision ID: 070_tenant_onboarding_drafts
Revises: 069_subject_exam_codes
Create Date: 2026-07-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "070_tenant_onboarding_drafts"
down_revision = "069_subject_exam_codes"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tenant_onboarding_drafts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("config", JSONB, nullable=False),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tenant_onboarding_drafts_tenant_id",
        "tenant_onboarding_drafts",
        ["tenant_id"],
        unique=True,
    )


def downgrade():
    op.drop_index(
        "ix_tenant_onboarding_drafts_tenant_id",
        table_name="tenant_onboarding_drafts",
    )
    op.drop_table("tenant_onboarding_drafts")
