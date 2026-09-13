"""Remember the day a school was last reminded about its payment.

The daily reminder job (ADR-023) stamps this so it is safe to re-run: a
school hears from us once a day while a payment is outstanding, however many
times the job fires.
"""

from alembic import op
import sqlalchemy as sa


revision = "140_subscription_payment_reminders"
down_revision = "139_subscription_term_and_payments"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("tenants") as batch_op:
        batch_op.add_column(
            sa.Column("last_payment_reminder_on", sa.Date(), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("tenants") as batch_op:
        batch_op.drop_column("last_payment_reminder_on")
