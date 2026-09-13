"""Seat limits on the tenant: max_active_students, max_employed_teachers.

Migration 043 moved pricing, discounts and feature flags from `plans` onto
each tenant and kept `plans` only until nothing read it. The student and
teacher limits were the last readers. They now live on the tenant too, so an
operator sets them in the panel next to the price, and `plans` /
`tenants.plan_id` can be dropped in a later migration.

Backfills each tenant's limits from its current plan so nothing changes for
an existing school on deploy. Null means no ceiling.
"""

from alembic import op
import sqlalchemy as sa


revision = "137_tenant_seat_limits"
down_revision = "136_every_sub_admin_may_open_the_dashboard"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("tenants") as batch_op:
        batch_op.add_column(sa.Column("max_active_students", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("max_employed_teachers", sa.Integer(), nullable=True))

    op.execute(
        """
        UPDATE tenants t
        SET max_active_students = p.max_students,
            max_employed_teachers = p.max_teachers
        FROM plans p
        WHERE p.id = t.plan_id
        """
    )


def downgrade():
    with op.batch_alter_table("tenants") as batch_op:
        batch_op.drop_column("max_employed_teachers")
        batch_op.drop_column("max_active_students")
