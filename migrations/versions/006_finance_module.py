"""Finance module: academic_years, fee_structures, fee_components, student_fees, student_fee_items, payments, notifications.

Revision ID: 006_finance_module
Revises: 005_user_login_lockout
Create Date: 2025-02-28

"""
from alembic import op
import sqlalchemy as sa

revision = "006_finance_module"
down_revision = "005_user_login_lockout"
branch_labels = None
depends_on = None


def upgrade():
    # academic_years
    op.create_table(
        "academic_years",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(20), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_academic_years_tenant_id"), "academic_years", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_academic_years_name"), "academic_years", ["name"], unique=False)
    op.create_unique_constraint(
        "uq_academic_years_name_tenant",
        "academic_years",
        ["name", "tenant_id"],
    )

    # fee_structures
    op.create_table(
        "fee_structures",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("academic_year_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("class_id", sa.String(36), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_fee_structures_tenant_id"), "fee_structures", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_fee_structures_academic_year_id"), "fee_structures", ["academic_year_id"], unique=False)
    op.create_index(op.f("ix_fee_structures_class_id"), "fee_structures", ["class_id"], unique=False)
    op.create_index(op.f("ix_fee_structures_name"), "fee_structures", ["name"], unique=False)

    # fee_components
    op.create_table(
        "fee_components",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("fee_structure_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("is_optional", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["fee_structure_id"], ["fee_structures.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_fee_components_tenant_id"), "fee_components", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_fee_components_fee_structure_id"), "fee_components", ["fee_structure_id"], unique=False)

    # student_fees
    op.create_table(
        "student_fees",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("student_id", sa.String(36), nullable=False),
        sa.Column("fee_structure_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("paid_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["fee_structure_id"], ["fee_structures.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_student_fees_tenant_id"), "student_fees", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_student_fees_student_id"), "student_fees", ["student_id"], unique=False)
    op.create_index(op.f("ix_student_fees_fee_structure_id"), "student_fees", ["fee_structure_id"], unique=False)
    op.create_index(op.f("ix_student_fees_status"), "student_fees", ["status"], unique=False)
    op.create_unique_constraint(
        "uq_student_fees_student_structure_tenant",
        "student_fees",
        ["student_id", "fee_structure_id", "tenant_id"],
    )

    # student_fee_items
    op.create_table(
        "student_fee_items",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("student_fee_id", sa.String(36), nullable=False),
        sa.Column("fee_component_id", sa.String(36), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("paid_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["fee_component_id"], ["fee_components.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_fee_id"], ["student_fees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_student_fee_items_tenant_id"), "student_fee_items", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_student_fee_items_student_fee_id"), "student_fee_items", ["student_fee_id"], unique=False)
    op.create_index(op.f("ix_student_fee_items_fee_component_id"), "student_fee_items", ["fee_component_id"], unique=False)
    op.create_unique_constraint(
        "uq_student_fee_items_fee_component_tenant",
        "student_fee_items",
        ["student_fee_id", "fee_component_id", "tenant_id"],
    )

    # payments
    op.create_table(
        "payments",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("student_fee_id", sa.String(36), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("reference_number", sa.String(100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["student_fee_id"], ["student_fees.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_payments_tenant_id"), "payments", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_payments_student_fee_id"), "payments", ["student_fee_id"], unique=False)
    op.create_index(op.f("ix_payments_method"), "payments", ["method"], unique=False)
    op.create_index(op.f("ix_payments_status"), "payments", ["status"], unique=False)
    op.create_index(op.f("ix_payments_reference_number"), "payments", ["reference_number"], unique=False)
    op.create_index(op.f("ix_payments_created_at"), "payments", ["created_at"], unique=False)

    # notifications
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("extra_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notifications_tenant_id"), "notifications", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_notifications_user_id"), "notifications", ["user_id"], unique=False)
    op.create_index(op.f("ix_notifications_type"), "notifications", ["type"], unique=False)
    op.create_index(op.f("ix_notifications_channel"), "notifications", ["channel"], unique=False)
    op.create_index(op.f("ix_notifications_created_at"), "notifications", ["created_at"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_notifications_created_at"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_channel"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_type"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_user_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_tenant_id"), table_name="notifications")
    op.drop_table("notifications")

    op.drop_index(op.f("ix_payments_created_at"), table_name="payments")
    op.drop_index(op.f("ix_payments_reference_number"), table_name="payments")
    op.drop_index(op.f("ix_payments_status"), table_name="payments")
    op.drop_index(op.f("ix_payments_method"), table_name="payments")
    op.drop_index(op.f("ix_payments_student_fee_id"), table_name="payments")
    op.drop_index(op.f("ix_payments_tenant_id"), table_name="payments")
    op.drop_table("payments")

    op.drop_constraint("uq_student_fee_items_fee_component_tenant", "student_fee_items", type_="unique")
    op.drop_index(op.f("ix_student_fee_items_fee_component_id"), table_name="student_fee_items")
    op.drop_index(op.f("ix_student_fee_items_student_fee_id"), table_name="student_fee_items")
    op.drop_index(op.f("ix_student_fee_items_tenant_id"), table_name="student_fee_items")
    op.drop_table("student_fee_items")

    op.drop_constraint("uq_student_fees_student_structure_tenant", "student_fees", type_="unique")
    op.drop_index(op.f("ix_student_fees_status"), table_name="student_fees")
    op.drop_index(op.f("ix_student_fees_fee_structure_id"), table_name="student_fees")
    op.drop_index(op.f("ix_student_fees_student_id"), table_name="student_fees")
    op.drop_index(op.f("ix_student_fees_tenant_id"), table_name="student_fees")
    op.drop_table("student_fees")

    op.drop_index(op.f("ix_fee_components_fee_structure_id"), table_name="fee_components")
    op.drop_index(op.f("ix_fee_components_tenant_id"), table_name="fee_components")
    op.drop_table("fee_components")

    op.drop_index(op.f("ix_fee_structures_name"), table_name="fee_structures")
    op.drop_index(op.f("ix_fee_structures_class_id"), table_name="fee_structures")
    op.drop_index(op.f("ix_fee_structures_academic_year_id"), table_name="fee_structures")
    op.drop_index(op.f("ix_fee_structures_tenant_id"), table_name="fee_structures")
    op.drop_table("fee_structures")

    op.drop_constraint("uq_academic_years_name_tenant", "academic_years", type_="unique")
    op.drop_index(op.f("ix_academic_years_name"), table_name="academic_years")
    op.drop_index(op.f("ix_academic_years_tenant_id"), table_name="academic_years")
    op.drop_table("academic_years")
