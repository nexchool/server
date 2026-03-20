"""Notification templates table: category, is_system, tenant override support.

Adds notification_templates for unified email/notification template management.
- tenant_id NULL = global default
- tenant_id NOT NULL = tenant override
- Unique: (tenant_id, type, channel) - partial indexes for NULL handling
"""

from alembic import op
import sqlalchemy as sa

revision = "008_notification_templates"
down_revision = "007_academic_year_id"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notification_templates",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=True),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("subject_template", sa.String(500), nullable=False),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notification_templates_tenant_id"), "notification_templates", ["tenant_id"], unique=False)
    op.create_index(op.f("ix_notification_templates_type"), "notification_templates", ["type"], unique=False)
    op.create_index(op.f("ix_notification_templates_channel"), "notification_templates", ["channel"], unique=False)
    op.create_index(op.f("ix_notification_templates_category"), "notification_templates", ["category"], unique=False)

    # Global templates: one per (type, channel) when tenant_id IS NULL
    op.execute(sa.text(
        "CREATE UNIQUE INDEX uq_notification_templates_global "
        "ON notification_templates (type, channel) WHERE tenant_id IS NULL"
    ))
    # Tenant overrides: one per (tenant_id, type, channel)
    op.execute(sa.text(
        "CREATE UNIQUE INDEX uq_notification_templates_tenant "
        "ON notification_templates (tenant_id, type, channel) WHERE tenant_id IS NOT NULL"
    ))


def downgrade():
    op.drop_index("uq_notification_templates_tenant", table_name="notification_templates")
    op.drop_index("uq_notification_templates_global", table_name="notification_templates")
    op.drop_index(op.f("ix_notification_templates_category"), table_name="notification_templates")
    op.drop_index(op.f("ix_notification_templates_channel"), table_name="notification_templates")
    op.drop_index(op.f("ix_notification_templates_type"), table_name="notification_templates")
    op.drop_index(op.f("ix_notification_templates_tenant_id"), table_name="notification_templates")
    op.drop_table("notification_templates")
