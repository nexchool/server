"""Add student_documents table.

Revision ID: 020_student_documents
Revises: 019_leave_balance
Create Date: 2026-03-13

Creates student_documents table for storing document metadata (files in Cloudinary).
"""

from alembic import op
import sqlalchemy as sa

revision = "020_student_documents"
down_revision = "019_leave_balance"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "student_documents",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("student_id", sa.String(36), nullable=False),
        sa.Column(
            "document_type",
            sa.Enum(
                "aadhar_card",
                "birth_certificate",
                "leaving_certificate",
                "transfer_certificate",
                "passport",
                "other",
                name="documenttype",
            ),
            nullable=False,
        ),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("cloudinary_url", sa.Text(), nullable=False),
        sa.Column("cloudinary_public_id", sa.String(500), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="fk_student_documents_tenant_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            name="fk_student_documents_student_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"],
            ["users.id"],
            name="fk_student_documents_uploaded_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_student_documents"),
    )
    op.create_index(
        "ix_student_documents_tenant_id",
        "student_documents",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        "ix_student_documents_student_id",
        "student_documents",
        ["student_id"],
        unique=False,
    )
    op.create_index(
        "ix_student_documents_uploaded_by_user_id",
        "student_documents",
        ["uploaded_by_user_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_student_documents_cloudinary_public_id",
        "student_documents",
        ["cloudinary_public_id"],
    )


def downgrade():
    op.drop_constraint(
        "uq_student_documents_cloudinary_public_id",
        "student_documents",
        type_="unique",
    )
    op.drop_index(
        "ix_student_documents_uploaded_by_user_id",
        table_name="student_documents",
    )
    op.drop_index("ix_student_documents_student_id", table_name="student_documents")
    op.drop_index("ix_student_documents_tenant_id", table_name="student_documents")
    op.drop_table("student_documents")
    op.execute("DROP TYPE documenttype")
