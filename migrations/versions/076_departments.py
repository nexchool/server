"""departments catalogue

Creates the per-tenant `departments` table. Case-insensitive partial unique
indexes on name and code exclude soft-deleted rows so values can be reused
after archiving.

Revision ID: 076_departments
Revises: 075_calendar_admin_fields
Create Date: 2026-07-28
"""

from alembic import op
import sqlalchemy as sa

revision = "076_departments"
down_revision = "075_calendar_admin_fields"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "departments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("display_order", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("type", sa.String(length=32), nullable=False, server_default=sa.text("'academic_division'")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'active'")),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint("status IN ('active','inactive')", name="ck_departments_status"),
    )
    op.create_index("ix_departments_tenant_id", "departments", ["tenant_id"])
    op.execute(
        "CREATE UNIQUE INDEX uq_departments_tenant_name_active "
        "ON departments (tenant_id, lower(name)) WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_departments_tenant_code_active "
        "ON departments (tenant_id, lower(code)) "
        "WHERE deleted_at IS NULL AND code IS NOT NULL"
    )
    op.create_index(
        "idx_departments_tenant_display_order",
        "departments",
        ["tenant_id", "display_order", "name"],
    )


def downgrade():
    op.drop_index("idx_departments_tenant_display_order", table_name="departments")
    op.execute("DROP INDEX IF EXISTS uq_departments_tenant_code_active")
    op.execute("DROP INDEX IF EXISTS uq_departments_tenant_name_active")
    op.drop_index("ix_departments_tenant_id", table_name="departments")
    op.drop_table("departments")
