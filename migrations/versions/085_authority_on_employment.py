"""authority held by an employment

Records that an employed person holds an Authority Profile (ADR-013). Authority
belongs to the business relationship rather than the account, so that it ends
when the employment ends instead of when somebody remembers to remove it.

Additive: account-held roles remain and permission resolution reads both until
Milestone M4 retires `user_roles`.

Revision ID: 085_authority_on_employment
Revises: 084_student_and_teacher_require_people
Create Date: 2026-08-05
"""

from alembic import op
import sqlalchemy as sa

revision = "085_authority_on_employment"
down_revision = "084_student_and_teacher_require_people"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "staff_authorities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("staff_id", sa.String(length=36), nullable=False),
        sa.Column("role_id", sa.String(length=36), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("granted_by_user_id", sa.String(length=36), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        # The authority exists because the employment does; it goes when it goes.
        sa.ForeignKeyConstraint(["staff_id"], ["staff.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("staff_id", "role_id", name="uq_staff_authorities_staff_role"),
    )
    op.create_index("ix_staff_authorities_tenant_id", "staff_authorities", ["tenant_id"])
    op.create_index("ix_staff_authorities_staff_id", "staff_authorities", ["staff_id"])
    op.create_index("ix_staff_authorities_role_id", "staff_authorities", ["role_id"])


def downgrade():
    op.drop_index("ix_staff_authorities_role_id", table_name="staff_authorities")
    op.drop_index("ix_staff_authorities_staff_id", table_name="staff_authorities")
    op.drop_index("ix_staff_authorities_tenant_id", table_name="staff_authorities")
    op.drop_table("staff_authorities")
