"""Multi-school / multi-board / multi-medium foundational structure.

Revision ID: 044_multi_school_structure
Revises: 043_per_tenant_subscription
Create Date: 2026-04-29

Phase 1 — schema only:

Adds four new tenant-scoped master tables to support sub-schools (campuses),
board + medium programmes, structured grades, and demographic religions:

  - school_units           (campus / sub-school)
  - academic_programmes    (board + medium combo)
  - grades                 (master grade list, replaces free-text grade)
  - religions              (demographic master)

Extends `classes` with foreign keys into the new structure:

  - classes.school_unit_id   FK -> school_units.id (nullable, RESTRICT)
  - classes.programme_id     FK -> academic_programmes.id (nullable, RESTRICT)
  - classes.grade_id         FK -> grades.id (nullable, RESTRICT)
  - new uniqueness:
        (tenant_id, school_unit_id, programme_id, grade_id, section, academic_year_id)
  - `classes.name` becomes nullable (now a display label; identity lives on the FKs).

The legacy unique constraint on (name, section, academic_year_id, tenant_id)
and the legacy `grade_level` smallint are intentionally retained to keep
existing services and APIs working until they are migrated to the new
structure in a follow-up phase.

The new FKs are nullable in this phase so existing class-creation paths keep
functioning. They will be tightened to NOT NULL once data and services are
migrated.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "044_multi_school_structure"
down_revision = "043_per_tenant_subscription"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. school_units
    # ------------------------------------------------------------------
    op.create_table(
        "school_units",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(length=36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False, server_default="other"),
        sa.Column("dise_no", sa.String(length=64), nullable=True),
        sa.Column("index_no", sa.String(length=64), nullable=True),
        sa.Column("recognition_no", sa.String(length=64), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("logo_url", sa.String(length=500), nullable=True),
        sa.Column("principal_signature_url", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("tenant_id", "code", name="uq_school_units_tenant_code"),
        sa.CheckConstraint(
            "type IN ('nursery','primary','secondary','higher_secondary','other')",
            name="ck_school_units_type",
        ),
        sa.CheckConstraint(
            "status IN ('active','inactive')",
            name="ck_school_units_status",
        ),
    )
    op.create_index("ix_school_units_tenant_id", "school_units", ["tenant_id"])
    op.create_index("ix_school_units_code", "school_units", ["code"])
    op.create_index("ix_school_units_status", "school_units", ["status"])

    # ------------------------------------------------------------------
    # 2. academic_programmes
    # ------------------------------------------------------------------
    op.create_table(
        "academic_programmes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(length=36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("board", sa.String(length=64), nullable=False),
        sa.Column("medium", sa.String(length=64), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "code", name="uq_academic_programmes_tenant_code"
        ),
        sa.CheckConstraint(
            "status IN ('active','inactive')",
            name="ck_academic_programmes_status",
        ),
    )
    op.create_index(
        "ix_academic_programmes_tenant_id", "academic_programmes", ["tenant_id"]
    )
    op.create_index("ix_academic_programmes_code", "academic_programmes", ["code"])
    op.create_index(
        "ix_academic_programmes_status", "academic_programmes", ["status"]
    )

    # ------------------------------------------------------------------
    # 3. grades
    # ------------------------------------------------------------------
    op.create_table(
        "grades",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(length=36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_grades_tenant_name"),
    )
    op.create_index("ix_grades_tenant_id", "grades", ["tenant_id"])
    op.create_index("ix_grades_sequence", "grades", ["sequence"])

    # ------------------------------------------------------------------
    # 4. religions
    # ------------------------------------------------------------------
    op.create_table(
        "religions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(length=36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("tenant_id", "name", name="uq_religions_tenant_name"),
    )
    op.create_index("ix_religions_tenant_id", "religions", ["tenant_id"])

    # ------------------------------------------------------------------
    # 5. classes — extend with the new structural FKs and uniqueness.
    # ------------------------------------------------------------------
    # `name` becomes a display label; identity now lives on the FKs.
    op.alter_column("classes", "name", existing_type=sa.String(length=50), nullable=True)

    op.add_column(
        "classes",
        sa.Column("school_unit_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "classes",
        sa.Column("programme_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "classes",
        sa.Column("grade_id", sa.String(length=36), nullable=True),
    )

    op.create_foreign_key(
        "fk_classes_school_unit_id",
        "classes",
        "school_units",
        ["school_unit_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_classes_programme_id",
        "classes",
        "academic_programmes",
        ["programme_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_classes_grade_id",
        "classes",
        "grades",
        ["grade_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_index("ix_classes_school_unit_id", "classes", ["school_unit_id"])
    op.create_index("ix_classes_programme_id", "classes", ["programme_id"])
    op.create_index("ix_classes_grade_id", "classes", ["grade_id"])

    op.create_unique_constraint(
        "uq_classes_unit_programme_grade_section_year",
        "classes",
        [
            "tenant_id",
            "school_unit_id",
            "programme_id",
            "grade_id",
            "section",
            "academic_year_id",
        ],
    )


def downgrade() -> None:
    # Reverse: drop the new uniqueness, then FKs / columns on classes,
    # then the four new tables.
    op.drop_constraint(
        "uq_classes_unit_programme_grade_section_year", "classes", type_="unique"
    )

    op.drop_index("ix_classes_grade_id", table_name="classes")
    op.drop_index("ix_classes_programme_id", table_name="classes")
    op.drop_index("ix_classes_school_unit_id", table_name="classes")

    op.drop_constraint("fk_classes_grade_id", "classes", type_="foreignkey")
    op.drop_constraint("fk_classes_programme_id", "classes", type_="foreignkey")
    op.drop_constraint("fk_classes_school_unit_id", "classes", type_="foreignkey")

    op.drop_column("classes", "grade_id")
    op.drop_column("classes", "programme_id")
    op.drop_column("classes", "school_unit_id")

    # Restore `name` to NOT NULL. Safe only when no NULLs exist; in a fresh
    # environment this is fine. In an environment with data, populate name
    # before downgrading.
    op.alter_column("classes", "name", existing_type=sa.String(length=50), nullable=False)

    op.drop_index("ix_religions_tenant_id", table_name="religions")
    op.drop_table("religions")

    op.drop_index("ix_grades_sequence", table_name="grades")
    op.drop_index("ix_grades_tenant_id", table_name="grades")
    op.drop_table("grades")

    op.drop_index("ix_academic_programmes_status", table_name="academic_programmes")
    op.drop_index("ix_academic_programmes_code", table_name="academic_programmes")
    op.drop_index(
        "ix_academic_programmes_tenant_id", table_name="academic_programmes"
    )
    op.drop_table("academic_programmes")

    op.drop_index("ix_school_units_status", table_name="school_units")
    op.drop_index("ix_school_units_code", table_name="school_units")
    op.drop_index("ix_school_units_tenant_id", table_name="school_units")
    op.drop_table("school_units")
