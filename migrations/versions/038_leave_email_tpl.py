"""Seed global EMAIL templates for teacher leave lifecycle.

Inserts SYSTEM / EMAIL rows (tenant_id NULL) for:
- TEACHER_LEAVE_REQUEST (to leave managers)
- TEACHER_LEAVE_APPROVED (to teacher)
- TEACHER_LEAVE_REJECTED (to teacher)

Idempotent: skips when a global template already exists for (type, channel).
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "038_leave_email_tpl"
down_revision = "037_payment_method_detail"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from modules.notifications.teacher_leave_email_defaults import (
        teacher_leave_email_template_rows,
    )

    conn = op.get_bind()
    sql = sa.text(
        """
        INSERT INTO notification_templates (
            id, tenant_id, type, channel, category, is_system,
            subject_template, body_template, created_at, updated_at
        )
        SELECT :id, NULL, :ntype, :channel, :category, :is_system,
               :subj, :body, NOW(), NOW()
        WHERE NOT EXISTS (
            SELECT 1 FROM notification_templates nt
            WHERE nt.tenant_id IS NULL
              AND nt.type = :ntype
              AND nt.channel = :channel
        )
        """
    )
    for row in teacher_leave_email_template_rows():
        conn.execute(
            sql,
            {
                "id": str(uuid.uuid4()),
                "ntype": row["type"],
                "channel": row["channel"],
                "category": row["category"],
                "is_system": row["is_system"],
                "subj": row["subject_template"],
                "body": row["body_template"],
            },
        )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM notification_templates
            WHERE tenant_id IS NULL
              AND channel = 'EMAIL'
              AND type IN (
                'TEACHER_LEAVE_REQUEST',
                'TEACHER_LEAVE_APPROVED',
                'TEACHER_LEAVE_REJECTED'
              )
            """
        )
    )
