"""Add logo_url, tagline, board_affiliation to tenants.

Revision ID: 022_tenant_school_details
Revises: 021_fee_invoices_receipts
Create Date: 2026-03-17

Adds school branding fields to tenants so they appear in PDF receipts/invoices.
"""

from alembic import op
import sqlalchemy as sa

revision = "022_tenant_school_details"
down_revision = "021_fee_invoices_receipts"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tenants", sa.Column("logo_url", sa.String(500), nullable=True))
    op.add_column("tenants", sa.Column("tagline", sa.String(255), nullable=True))
    op.add_column("tenants", sa.Column("board_affiliation", sa.String(100), nullable=True))


def downgrade():
    op.drop_column("tenants", "board_affiliation")
    op.drop_column("tenants", "tagline")
    op.drop_column("tenants", "logo_url")
