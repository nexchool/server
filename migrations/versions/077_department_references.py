"""department references on teachers and classes

Adds department_id to teachers and classes, backfills departments from the
existing free-text teachers.department values, then drops that column.

Revision ID: 077_department_references
Revises: 076_departments
Create Date: 2026-07-28
"""

import uuid

from alembic import op
import sqlalchemy as sa

from migrations.department_backfill import distinct_names

revision = "077_department_references"
down_revision = "076_departments"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "teachers", sa.Column("department_id", sa.String(length=36), nullable=True)
    )
    op.add_column(
        "classes", sa.Column("department_id", sa.String(length=36), nullable=True)
    )

    connection = op.get_bind()

    rows = connection.execute(
        sa.text("SELECT tenant_id, department FROM teachers WHERE department IS NOT NULL")
    ).fetchall()

    for (tenant_id, _lowered), original_name in distinct_names(rows).items():
        connection.execute(
            sa.text(
                "INSERT INTO departments "
                "(id, tenant_id, name, type, status, display_order, created_at, updated_at) "
                "VALUES (:id, :tenant_id, :name, 'academic_division', 'active', 0, now(), now())"
            ),
            {"id": str(uuid.uuid4()), "tenant_id": tenant_id, "name": original_name},
        )

    connection.execute(
        sa.text(
            "UPDATE teachers t SET department_id = d.id "
            "FROM departments d "
            "WHERE d.tenant_id = t.tenant_id "
            "  AND d.deleted_at IS NULL "
            "  AND lower(trim(t.department)) = lower(d.name) "
            "  AND t.department IS NOT NULL"
        )
    )

    op.drop_column("teachers", "department")

    op.create_index("ix_teachers_department_id", "teachers", ["department_id"])
    op.create_index("ix_classes_department_id", "classes", ["department_id"])
    op.create_foreign_key(
        "fk_teachers_department_id",
        "teachers",
        "departments",
        ["department_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_classes_department_id",
        "classes",
        "departments",
        ["department_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade():
    op.add_column("teachers", sa.Column("department", sa.String(length=100), nullable=True))

    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE teachers t SET department = d.name "
            "FROM departments d WHERE d.id = t.department_id"
        )
    )

    # Constraints must go before the cleanup DELETE below: fk_teachers_department_id
    # still references these rows and blocks the delete otherwise.
    op.drop_constraint("fk_classes_department_id", "classes", type_="foreignkey")
    op.drop_constraint("fk_teachers_department_id", "teachers", type_="foreignkey")
    op.drop_index("ix_classes_department_id", table_name="classes")
    op.drop_index("ix_teachers_department_id", table_name="teachers")

    # Remove the rows this migration's own backfill created. Without this,
    # a subsequent upgrade() re-runs the backfill and its INSERT collides
    # with the still-present rows on uq_departments_tenant_name_active
    # (case-insensitive), aborting the migration. Safe at this point in the
    # chain: teachers.department_id is the only writer of `departments`
    # rows so far, so every row still linked to a teacher was created here.
    connection.execute(
        sa.text(
            "DELETE FROM departments d "
            "USING teachers t "
            "WHERE t.department_id = d.id"
        )
    )

    op.drop_column("classes", "department_id")
    op.drop_column("teachers", "department_id")
