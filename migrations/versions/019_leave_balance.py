"""Leave Policy and Teacher Leave Balance tables.

Revision ID: 019_leave_balance
Revises: 018_holidays
Create Date: 2026-03-12

Creates:
  - leave_policies           (per-tenant leave type configuration)
  - teacher_leave_balances   (per-teacher per-type annual balance tracker)

Alters:
  - teacher_leaves           (adds working_days + academic_year columns)
"""

from alembic import op
import sqlalchemy as sa

revision = "019_leave_balance"
down_revision = "018_holidays"
branch_labels = None
depends_on = None


def upgrade():
    # ------------------------------------------------------------------
    # leave_policies
    # ------------------------------------------------------------------
    op.create_table(
        "leave_policies",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("leave_type", sa.String(50), nullable=False),
        sa.Column("total_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_unlimited", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_carry_forward_allowed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("max_carry_forward_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("allow_negative", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("requires_reason", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_leave_policies_tenant_id"), "leave_policies", ["tenant_id"], unique=False)
    op.create_unique_constraint(
        "uq_leave_policy_tenant_type",
        "leave_policies",
        ["tenant_id", "leave_type"],
    )

    # ------------------------------------------------------------------
    # teacher_leave_balances
    # ------------------------------------------------------------------
    op.create_table(
        "teacher_leave_balances",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("teacher_id", sa.String(36), nullable=False),
        sa.Column("leave_type", sa.String(50), nullable=False),
        sa.Column("academic_year", sa.String(10), nullable=False),
        sa.Column("allocated_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("used_days", sa.Float(), nullable=False, server_default="0"),
        sa.Column("pending_days", sa.Float(), nullable=False, server_default="0"),
        sa.Column("carried_forward_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("last_adjusted_by", sa.String(36), nullable=True),
        sa.Column("last_adjusted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_teacher_leave_balances_tenant_id"), "teacher_leave_balances", ["tenant_id"], unique=False
    )
    op.create_index(
        op.f("ix_teacher_leave_balances_teacher_id"), "teacher_leave_balances", ["teacher_id"], unique=False
    )
    op.create_unique_constraint(
        "uq_leave_balance_teacher_type_year",
        "teacher_leave_balances",
        ["teacher_id", "leave_type", "academic_year", "tenant_id"],
    )

    # ------------------------------------------------------------------
    # teacher_leaves — add working_days and academic_year columns
    # ------------------------------------------------------------------
    op.add_column(
        "teacher_leaves",
        sa.Column("working_days", sa.Float(), nullable=True),
    )
    op.add_column(
        "teacher_leaves",
        sa.Column("academic_year", sa.String(10), nullable=True),
    )


def downgrade():
    op.drop_column("teacher_leaves", "academic_year")
    op.drop_column("teacher_leaves", "working_days")

    op.drop_constraint("uq_leave_balance_teacher_type_year", "teacher_leave_balances", type_="unique")
    op.drop_index(op.f("ix_teacher_leave_balances_teacher_id"), table_name="teacher_leave_balances")
    op.drop_index(op.f("ix_teacher_leave_balances_tenant_id"), table_name="teacher_leave_balances")
    op.drop_table("teacher_leave_balances")

    op.drop_constraint("uq_leave_policy_tenant_type", "leave_policies", type_="unique")
    op.drop_index(op.f("ix_leave_policies_tenant_id"), table_name="leave_policies")
    op.drop_table("leave_policies")
