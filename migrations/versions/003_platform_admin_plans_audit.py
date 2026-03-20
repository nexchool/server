"""Platform Admin: is_platform_admin on users, plans table, tenants.plan_id FK, audit_logs.

Revision ID: 003_platform_admin
Revises: 002_multi_tenant
Create Date: 2025-02-18

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
import uuid

# revision identifiers, used by Alembic.
revision = "003_platform_admin"
down_revision = "002_multi_tenant"
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add is_platform_admin to users
    op.add_column(
        "users",
        sa.Column("is_platform_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # 2. Create plans table
    op.create_table(
        "plans",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("price_monthly", sa.Numeric(12, 2), nullable=False),
        sa.Column("max_students", sa.Integer(), nullable=False),
        sa.Column("max_teachers", sa.Integer(), nullable=False),
        sa.Column("features_json", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_plans_name"), "plans", ["name"], unique=True)

    # Insert default plan so tenants can be assigned a plan
    op.execute(
        sa.text(
            """
            INSERT INTO plans (id, name, price_monthly, max_students, max_teachers, features_json, created_at, updated_at)
            VALUES (:id, 'Starter', 0, 100, 20, '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        ).bindparams(id=str(uuid.uuid4()))
    )

    # 3. Add FK from tenants.plan_id to plans
    #    (tenants.plan_id already exists from 002 as nullable string; add FK)
    op.create_foreign_key(
        "fk_tenants_plan_id",
        "tenants",
        "plans",
        ["plan_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 4. Create audit_logs table
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=True),
        sa.Column("platform_admin_id", sa.String(36), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("metadata", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["platform_admin_id"], ["users.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(op.f("ix_audit_logs_tenant_id"), "audit_logs", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_audit_logs_platform_admin_id"), "audit_logs", ["platform_admin_id"], unique=False)
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"], unique=False)
    op.create_index(op.f("ix_audit_logs_created_at"), "audit_logs", ["created_at"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_audit_logs_created_at"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_action"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_platform_admin_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_tenant_id"), table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_constraint("fk_tenants_plan_id", "tenants", type_="foreignkey")

    op.drop_index(op.f("ix_plans_name"), table_name="plans")
    op.drop_table("plans")

    op.drop_column("users", "is_platform_admin")
