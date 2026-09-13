"""Subscription term on the tenant, and a record of what a school has paid.

tenants gains:
  subscription_starts_on   date      nullable — when the current term began
  subscription_due_on      date      nullable — when the next payment is due
  grace_days               integer   NOT NULL default 7 — days the school
                                     keeps working after the due date
  auto_suspend_after_grace boolean   NOT NULL default true — whether the
                                     nightly job suspends the school when
                                     grace runs out

A null due date means no term has been set and the school is never suspended
by it, so existing schools change nothing on deploy.

subscription_payments is the operator's paper trail: one row per payment a
school made, never edited, voided with a reason when wrong. See ADR-023.
"""

from alembic import op
import sqlalchemy as sa


revision = "139_subscription_term_and_payments"
down_revision = "138_rooms_come_with_their_beds"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("tenants") as batch_op:
        batch_op.add_column(sa.Column("subscription_starts_on", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("subscription_due_on", sa.Date(), nullable=True))
        batch_op.add_column(
            sa.Column("grace_days", sa.Integer(), nullable=False, server_default="7")
        )
        batch_op.add_column(
            sa.Column(
                "auto_suspend_after_grace",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            )
        )

    op.create_table(
        "subscription_payments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("paid_on", sa.Date(), nullable=False),
        sa.Column("method", sa.String(30), nullable=False),
        sa.Column("reference", sa.String(120), nullable=True),
        sa.Column("covers_from", sa.Date(), nullable=True),
        sa.Column("covers_to", sa.Date(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "recorded_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("void_reason", sa.Text(), nullable=True),
        sa.Column(
            "voided_by_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("amount > 0", name="ck_subscription_payments_amount_positive"),
        sa.CheckConstraint(
            "method IN ('bank_transfer', 'upi', 'cheque', 'cash', 'other')",
            name="ck_subscription_payments_method",
        ),
    )
    op.create_index(
        "idx_subscription_payments_tenant_paid_on",
        "subscription_payments",
        ["tenant_id", "paid_on"],
    )
    op.create_index(
        "ix_subscription_payments_tenant_id", "subscription_payments", ["tenant_id"]
    )


def downgrade():
    op.drop_index("ix_subscription_payments_tenant_id", table_name="subscription_payments")
    op.drop_index(
        "idx_subscription_payments_tenant_paid_on", table_name="subscription_payments"
    )
    op.drop_table("subscription_payments")
    with op.batch_alter_table("tenants") as batch_op:
        batch_op.drop_column("auto_suspend_after_grace")
        batch_op.drop_column("grace_days")
        batch_op.drop_column("subscription_due_on")
        batch_op.drop_column("subscription_starts_on")
