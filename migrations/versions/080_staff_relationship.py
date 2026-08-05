"""staff relationship and employment periods

Adds the People-domain Staff relationship (ADR-001) and links the existing
student rows to their Person. Additive per ADR-010: `students.person_id` is
nullable here and the v1 identity columns are left alone, so this is safe to
apply before the backfill runs.

Revision ID: 080_staff_relationship
Revises: 079_people_domain
Create Date: 2026-08-05
"""

from alembic import op
import sqlalchemy as sa

revision = "080_staff_relationship"
down_revision = "079_people_domain"
branch_labels = None
depends_on = None

EMPLOYMENT_STATUSES = (
    "'working','probation','on_leave','notice_period','suspended',"
    "'resigned','retired','terminated','left'"
)


def upgrade():
    op.create_table(
        "staff",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("person_id", sa.String(length=36), nullable=False),
        sa.Column("employee_number", sa.String(length=50), nullable=True),
        sa.Column("designation", sa.Text(), nullable=True),
        sa.Column("department_id", sa.String(length=36), nullable=True),
        sa.Column(
            "employment_status",
            sa.String(length=30),
            nullable=False,
            server_default=sa.text("'working'"),
        ),
        sa.Column("employment_type", sa.String(length=30), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="SET NULL"),
        # One employment relationship per human per organization; returning to
        # work opens a new period rather than a second relationship.
        sa.UniqueConstraint("tenant_id", "person_id", name="uq_staff_tenant_person"),
        sa.CheckConstraint(
            f"employment_status IN ({EMPLOYMENT_STATUSES})",
            name="ck_staff_employment_status",
        ),
    )
    op.create_index("ix_staff_tenant_id", "staff", ["tenant_id"])
    op.create_index("ix_staff_person_id", "staff", ["person_id"])
    op.create_index("ix_staff_department_id", "staff", ["department_id"])
    # Employee numbers are unique where a school records them, and reusable
    # after a record is archived.
    op.execute(
        "CREATE UNIQUE INDEX uq_staff_tenant_employee_number "
        "ON staff (tenant_id, employee_number) "
        "WHERE employee_number IS NOT NULL AND deleted_at IS NULL"
    )

    op.create_table(
        "staff_employment_periods",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("staff_id", sa.String(length=36), nullable=False),
        sa.Column("joined_on", sa.Date(), nullable=True),
        sa.Column("left_on", sa.Date(), nullable=True),
        sa.Column("end_reason", sa.String(length=30), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["staff_id"], ["staff.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_staff_employment_periods_tenant_id", "staff_employment_periods", ["tenant_id"])
    op.create_index("ix_staff_employment_periods_staff_id", "staff_employment_periods", ["staff_id"])

    # The v1 students table already is the Student relationship; it only needs
    # to point at the human. Its identity columns are dropped in a later
    # cleanup migration, once nothing reads them.
    op.add_column("students", sa.Column("person_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(
        "fk_students_person_id", "students", "persons", ["person_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_index("ix_students_person_id", "students", ["person_id"])


def downgrade():
    op.drop_index("ix_students_person_id", table_name="students")
    op.drop_constraint("fk_students_person_id", "students", type_="foreignkey")
    op.drop_column("students", "person_id")

    op.drop_index("ix_staff_employment_periods_staff_id", table_name="staff_employment_periods")
    op.drop_index("ix_staff_employment_periods_tenant_id", table_name="staff_employment_periods")
    op.drop_table("staff_employment_periods")

    op.execute("DROP INDEX IF EXISTS uq_staff_tenant_employee_number")
    op.drop_index("ix_staff_department_id", table_name="staff")
    op.drop_index("ix_staff_person_id", table_name="staff")
    op.drop_index("ix_staff_tenant_id", table_name="staff")
    op.drop_table("staff")
