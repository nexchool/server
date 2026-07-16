"""rename student_documents storage columns to AWS-neutral names

Renames the legacy Cloudinary-named columns on student_documents to reflect the
current S3-backed storage (the service has stored S3 object keys in both columns
since the migration off Cloudinary):

- cloudinary_url        -> file_url
- cloudinary_public_id  -> s3_object_key

Pure column renames; data is preserved. The unique index backing
cloudinary_public_id follows the column automatically in PostgreSQL.

Revision ID: 067_rename_student_document_storage_columns
Revises: 066_payment_idempotency_key
Create Date: 2026-07-16
"""

from alembic import op


revision = "067_rename_student_document_storage_columns"
down_revision = "066_payment_idempotency_key"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "student_documents", "cloudinary_url", new_column_name="file_url"
    )
    op.alter_column(
        "student_documents", "cloudinary_public_id", new_column_name="s3_object_key"
    )


def downgrade():
    op.alter_column(
        "student_documents", "s3_object_key", new_column_name="cloudinary_public_id"
    )
    op.alter_column(
        "student_documents", "file_url", new_column_name="cloudinary_url"
    )
