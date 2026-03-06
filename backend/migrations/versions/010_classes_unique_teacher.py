"""Ensure one teacher can only be class teacher of one class per tenant."""

from alembic import op
from sqlalchemy import text

revision = "010_classes_unique_teacher"
down_revision = "009_drop_classes_academic_year"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    # Clear duplicate teacher assignments: keep first class per (teacher_id, tenant_id), null the rest
    conn.execute(text("""
        UPDATE classes c1
        SET teacher_id = NULL
        FROM (
            SELECT id, teacher_id, tenant_id,
                   ROW_NUMBER() OVER (PARTITION BY teacher_id, tenant_id ORDER BY created_at) AS rn
            FROM classes
            WHERE teacher_id IS NOT NULL
        ) ranked
        WHERE c1.id = ranked.id AND ranked.rn > 1
    """))
    # Add unique (teacher_id, tenant_id) - allows multiple NULL teacher_id; one teacher = one class
    op.create_unique_constraint(
        "uq_classes_teacher_id_tenant",
        "classes",
        ["teacher_id", "tenant_id"],
    )


def downgrade():
    op.drop_constraint(
        "uq_classes_teacher_id_tenant",
        "classes",
        type_="unique",
    )
