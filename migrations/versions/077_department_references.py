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

    # ON CONFLICT DO NOTHING: makes the backfill idempotent against rows that
    # already exist (case-insensitively) for this tenant — notably including
    # rows a prior downgrade()/upgrade() cycle left behind, since downgrade()
    # intentionally does not delete departments (see its docstring below).
    # The subsequent UPDATE matches pre-existing rows the same way it
    # matches freshly-inserted ones (lower(trim(name)) equality).
    for (tenant_id, _lowered), original_name in distinct_names(rows).items():
        connection.execute(
            sa.text(
                "INSERT INTO departments "
                "(id, tenant_id, name, type, status, display_order, created_at, updated_at) "
                "VALUES (:id, :tenant_id, :name, 'academic_division', 'active', 0, now(), now()) "
                "ON CONFLICT (tenant_id, lower(name)) WHERE deleted_at IS NULL DO NOTHING"
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
    # Deliberately does NOT delete rows from `departments`. A downgrade runs
    # at a point in *time*, not a point in the revision chain: by the time
    # anyone downgrades past this revision in a real environment, other
    # tasks' code (departments CRUD, Task 4+) may have created or attached
    # departments this migration didn't insert — code, description,
    # display_order, teacher/class assignments made through the API. Those
    # rows belong to revision 076, which downgrade() must not touch.
    # Deleting only "rows referenced by a teacher" is not a safe proxy for
    # "rows this migration inserted" either: it's asymmetric (a department
    # with no teacher survives) and would destroy user-created data the
    # moment any teacher is assigned to it. upgrade()'s backfill INSERT is
    # ON CONFLICT DO NOTHING specifically so it tolerates rows still present
    # from a prior upgrade that a downgrade correctly left alone.
    op.add_column("teachers", sa.Column("department", sa.String(length=100), nullable=True))

    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE teachers t SET department = d.name "
            "FROM departments d WHERE d.id = t.department_id"
        )
    )

    op.drop_constraint("fk_classes_department_id", "classes", type_="foreignkey")
    op.drop_constraint("fk_teachers_department_id", "teachers", type_="foreignkey")
    op.drop_index("ix_classes_department_id", table_name="classes")
    op.drop_index("ix_teachers_department_id", table_name="teachers")
    op.drop_column("classes", "department_id")
    op.drop_column("teachers", "department_id")
