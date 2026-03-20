"""Add fee_invoices, fee_invoice_items, fee_payments, fee_receipts tables.

Revision ID: 021_fee_invoices_receipts
Revises: 020_student_documents
Create Date: 2026-03-14

Fees Invoice + Receipt system. Invoices represent fee dues; payments can be partial;
each payment generates a receipt. Never delete financial records.
"""

from alembic import op
import sqlalchemy as sa

revision = "021_fee_invoices_receipts"
down_revision = "020_student_documents"
branch_labels = None
depends_on = None


def upgrade():
    # fee_invoices
    op.create_table(
        "fee_invoices",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("student_id", sa.String(36), nullable=False),
        sa.Column("invoice_number", sa.String(50), nullable=False),
        sa.Column("academic_year", sa.String(20), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("subtotal", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("total_discount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("total_fine", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fee_invoices_tenant_id", "fee_invoices", ["tenant_id"], unique=False)
    op.create_index("ix_fee_invoices_student_id", "fee_invoices", ["student_id"], unique=False)
    op.create_index("ix_fee_invoices_invoice_number", "fee_invoices", ["invoice_number"], unique=False)
    op.create_index("ix_fee_invoices_status", "fee_invoices", ["status"], unique=False)
    op.create_index("ix_fee_invoices_academic_year", "fee_invoices", ["academic_year"], unique=False)
    op.create_index(
        "ix_fee_invoices_invoice_number_tenant",
        "fee_invoices",
        ["invoice_number", "tenant_id"],
        unique=False,
    )

    # fee_invoice_items
    op.create_table(
        "fee_invoice_items",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("invoice_id", sa.String(36), nullable=False),
        sa.Column("fee_head", sa.String(100), nullable=False),
        sa.Column("period", sa.String(50), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("discount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("fine", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("net_amount", sa.Numeric(12, 2), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invoice_id"], ["fee_invoices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fee_invoice_items_tenant_id", "fee_invoice_items", ["tenant_id"], unique=False)
    op.create_index("ix_fee_invoice_items_invoice_id", "fee_invoice_items", ["invoice_id"], unique=False)

    # fee_payments
    op.create_table(
        "fee_payments",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("invoice_id", sa.String(36), nullable=False),
        sa.Column("student_id", sa.String(36), nullable=False),
        sa.Column("payment_reference", sa.String(100), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("payment_method", sa.String(20), nullable=False),
        sa.Column("payment_gateway", sa.String(50), nullable=True),
        sa.Column("transaction_id", sa.String(100), nullable=True),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("collected_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invoice_id"], ["fee_invoices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["collected_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fee_payments_tenant_id", "fee_payments", ["tenant_id"], unique=False)
    op.create_index("ix_fee_payments_invoice_id", "fee_payments", ["invoice_id"], unique=False)
    op.create_index("ix_fee_payments_student_id", "fee_payments", ["student_id"], unique=False)
    op.create_index("ix_fee_payments_payment_reference", "fee_payments", ["payment_reference"], unique=False)
    op.create_index("ix_fee_payments_transaction_id", "fee_payments", ["transaction_id"], unique=False)

    # fee_receipts
    op.create_table(
        "fee_receipts",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("payment_id", sa.String(36), nullable=False),
        sa.Column("receipt_number", sa.String(50), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.Column("pdf_url", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["payment_id"], ["fee_payments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_id", name="uq_fee_receipts_payment_id"),
    )
    op.create_index("ix_fee_receipts_tenant_id", "fee_receipts", ["tenant_id"], unique=False)
    op.create_index("ix_fee_receipts_payment_id", "fee_receipts", ["payment_id"], unique=True)
    op.create_index("ix_fee_receipts_receipt_number", "fee_receipts", ["receipt_number"], unique=False)


def downgrade():
    op.drop_index("ix_fee_receipts_receipt_number", table_name="fee_receipts")
    op.drop_index("ix_fee_receipts_payment_id", table_name="fee_receipts")
    op.drop_index("ix_fee_receipts_tenant_id", table_name="fee_receipts")
    op.drop_table("fee_receipts")

    op.drop_index("ix_fee_payments_transaction_id", table_name="fee_payments")
    op.drop_index("ix_fee_payments_payment_reference", table_name="fee_payments")
    op.drop_index("ix_fee_payments_student_id", table_name="fee_payments")
    op.drop_index("ix_fee_payments_invoice_id", table_name="fee_payments")
    op.drop_index("ix_fee_payments_tenant_id", table_name="fee_payments")
    op.drop_table("fee_payments")

    op.drop_index("ix_fee_invoice_items_invoice_id", table_name="fee_invoice_items")
    op.drop_index("ix_fee_invoice_items_tenant_id", table_name="fee_invoice_items")
    op.drop_table("fee_invoice_items")

    op.drop_index("ix_fee_invoices_invoice_number_tenant", table_name="fee_invoices")
    op.drop_index("ix_fee_invoices_academic_year", table_name="fee_invoices")
    op.drop_index("ix_fee_invoices_status", table_name="fee_invoices")
    op.drop_index("ix_fee_invoices_invoice_number", table_name="fee_invoices")
    op.drop_index("ix_fee_invoices_student_id", table_name="fee_invoices")
    op.drop_index("ix_fee_invoices_tenant_id", table_name="fee_invoices")
    op.drop_table("fee_invoices")
