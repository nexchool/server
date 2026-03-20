"""Timeline refactor: add academic_year_id to students and classes, tenant-scoped backfill.

IMPORTANT: Take a database backup before running this migration.

    pg_dump -U <user> -d <database> -F c -f backup_pre_007.dump

Or use your hosting provider's backup feature.

Backfill logic (all tenant-scoped):
1. Seed academic_years from Classes first (academic_year NOT NULL).
2. Map Students via class_id -> class.academic_year_id when possible.
3. Fallback to student.academic_year string only if needed.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
import uuid

revision = "007_academic_year_id"
down_revision = "006_finance_module"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # 1. Add academic_year_id to students (nullable)
    op.add_column(
        "students",
        sa.Column("academic_year_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "fk_students_academic_year_id",
        "students",
        "academic_years",
        ["academic_year_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_students_academic_year_id"),
        "students",
        ["academic_year_id"],
        unique=False,
    )

    # 2. Add academic_year_id to classes (nullable)
    op.add_column(
        "classes",
        sa.Column("academic_year_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "fk_classes_academic_year_id",
        "classes",
        "academic_years",
        ["academic_year_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_classes_academic_year_id"),
        "classes",
        ["academic_year_id"],
        unique=False,
    )

    # 3. Tenant-scoped backfill
    # Get all tenant_ids
    tenant_ids_result = conn.execute(
        text("SELECT id FROM tenants")
    )
    tenant_ids = [row[0] for row in tenant_ids_result]

    for tenant_id in tenant_ids:
        # 3a. Seed academic_years from Classes (academic_year NOT NULL)
        # Get distinct academic_year strings from classes for this tenant (trimmed)
        distinct_years = conn.execute(
            text("""
                SELECT DISTINCT TRIM(academic_year) FROM classes
                WHERE tenant_id = :tenant_id AND academic_year IS NOT NULL AND TRIM(academic_year) != ''
            """),
            {"tenant_id": tenant_id},
        )
        year_strings = [row[0] for row in distinct_years if row[0]]

        # For each year string, ensure academic_years row exists (by name + tenant)
        for year_name in year_strings:
            existing = conn.execute(
                text("""
                    SELECT id FROM academic_years
                    WHERE tenant_id = :tenant_id AND name = :name
                """),
                {"tenant_id": tenant_id, "name": year_name},
            ).fetchone()

            if not existing:
                # Create with placeholder dates (start = first day of first year, end = last day of second year)
                try:
                    parts = year_name.split("-")
                    y1, y2 = int(parts[0]), int(parts[1]) if len(parts) > 1 else int(parts[0]) + 1
                except (ValueError, IndexError):
                    raise ValueError(
                        f"Invalid academic_year format for tenant {tenant_id}: '{year_name}'. "
                        "Expected format 'YYYY-YYYY'. Fix data before running migration."
                    )
                ay_id = str(uuid.uuid4())
                conn.execute(
                    text("""
                        INSERT INTO academic_years (id, tenant_id, name, start_date, end_date, is_active, created_at, updated_at)
                        VALUES (:id, :tenant_id, :name, :start_date, :end_date, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """),
                    {
                        "id": ay_id,
                        "tenant_id": tenant_id,
                        "name": year_name,
                        "start_date": f"{y1}-06-01",
                        "end_date": f"{y2}-05-31",
                    },
                )

        # Build name -> id map for this tenant
        name_to_id = {}
        mapping = conn.execute(
            text("SELECT id, name FROM academic_years WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        )
        for row in mapping:
            name_to_id[row[1]] = row[0]

        # 3b. Backfill classes: set academic_year_id from academic_year string
        for year_name, ay_id in name_to_id.items():
            conn.execute(
                text("""
                    UPDATE classes SET academic_year_id = :ay_id
                    WHERE tenant_id = :tenant_id AND TRIM(academic_year) = :year_name
                """),
                {"ay_id": ay_id, "tenant_id": tenant_id, "year_name": year_name},
            )

        # 3c. Backfill students:
        # First: use class_id -> get class's academic_year_id
        conn.execute(
            text("""
                UPDATE students s
                SET academic_year_id = c.academic_year_id
                FROM classes c
                WHERE s.class_id = c.id AND s.tenant_id = :tenant_id
                  AND c.academic_year_id IS NOT NULL
                  AND s.academic_year_id IS NULL
            """),
            {"tenant_id": tenant_id},
        )

        # Fallback: use student.academic_year string
        for year_name, ay_id in name_to_id.items():
            conn.execute(
                text("""
                    UPDATE students SET academic_year_id = :ay_id
                    WHERE tenant_id = :tenant_id AND TRIM(academic_year) = :year_name
                      AND academic_year_id IS NULL
                """),
                {"ay_id": ay_id, "tenant_id": tenant_id, "year_name": year_name},
            )

    # 4. Validate no duplicates before adding unique constraint
    duplicates = conn.execute(
        text("""
            SELECT name, section, academic_year_id, tenant_id, COUNT(*)
            FROM classes
            GROUP BY name, section, academic_year_id, tenant_id
            HAVING COUNT(*) > 1
        """),
    ).fetchall()

    if duplicates:
        raise ValueError(
            "Duplicate classes detected after academic_year_id backfill. "
            "Resolve duplicates before proceeding with unique constraint migration."
        )

    # 5. Add new unique constraint on classes (name, section, academic_year_id, tenant_id)
    op.create_unique_constraint(
        "uq_class_section_academic_year_id_tenant",
        "classes",
        ["name", "section", "academic_year_id", "tenant_id"],
    )

    # 6. Drop old unique constraint (name, section, academic_year, tenant_id)
    op.drop_constraint(
        "uq_class_section_year_tenant",
        "classes",
        type_="unique",
    )

    # 7. Make academic_year_id NOT NULL on classes
    op.alter_column(
        "classes",
        "academic_year_id",
        existing_type=sa.String(36),
        nullable=False,
    )


def downgrade():
    # Reverse order
    op.alter_column(
        "classes",
        "academic_year_id",
        existing_type=sa.String(36),
        nullable=True,
    )
    op.create_unique_constraint(
        "uq_class_section_year_tenant",
        "classes",
        ["name", "section", "academic_year", "tenant_id"],
    )
    op.drop_constraint(
        "uq_class_section_academic_year_id_tenant",
        "classes",
        type_="unique",
    )
    op.drop_index(op.f("ix_classes_academic_year_id"), table_name="classes")
    op.drop_constraint("fk_classes_academic_year_id", "classes", type_="foreignkey")
    op.drop_column("classes", "academic_year_id")
    op.drop_index(op.f("ix_students_academic_year_id"), table_name="students")
    op.drop_constraint("fk_students_academic_year_id", "students", type_="foreignkey")
    op.drop_column("students", "academic_year_id")
