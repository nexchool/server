"""Make subject code unique (not subject name).

Revision ID: 039_subject_code_unique
Revises: 038_leave_email_tpl
Create Date: 2026-04-17

- Drops unique constraint uq_subjects_name_tenant (name, tenant_id)
- Keeps/enforces uniqueness via uq_subjects_tenant_code_active on (tenant_id, code)
  when code is set and row is not soft-deleted.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "039_subject_code_unique"
down_revision = "038_leave_email_tpl"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use raw SQL so this is safe to re-run across environments.
    op.execute(sa.text("ALTER TABLE subjects DROP CONSTRAINT IF EXISTS uq_subjects_name_tenant"))
    # Enforce uniqueness on (tenant_id, code) for active (not soft-deleted) rows.
    # Partial unique index lets multiple NULL codes exist and allows reusing codes after archive.
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_subjects_tenant_code_active
            ON subjects (tenant_id, code)
            WHERE code IS NOT NULL AND deleted_at IS NULL
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS uq_subjects_tenant_code_active"))
    op.create_unique_constraint(
        "uq_subjects_name_tenant",
        "subjects",
        ["name", "tenant_id"],
    )

