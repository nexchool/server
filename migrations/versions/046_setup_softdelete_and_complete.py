"""Soft-delete on master tables + tenant setup completion flag.

Revision ID: 046_setup_softdelete_and_complete
Revises: 045_classes_structural_uniqueness
Create Date: 2026-04-29

Adds:
  - school_units.deleted_at, academic_programmes.deleted_at,
    grades.deleted_at, religions.deleted_at  (all DateTime, nullable, indexed)
  - replaces full unique constraints on (tenant_id, code/name) with
    partial unique indexes scoped to active rows (deleted_at IS NULL)
    so codes / names can be reused after archive
  - tenants.is_setup_complete (boolean, NOT NULL, default false)
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "046_setup_softdelete_and_complete"
down_revision = "045_classes_structural_uniqueness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. tenants.is_setup_complete ────────────────────────────────
    op.add_column(
        "tenants",
        sa.Column(
            "is_setup_complete",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # ── 2. school_units ────────────────────────────────────────────
    op.add_column(
        "school_units",
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_school_units_deleted_at",
        "school_units",
        ["deleted_at"],
    )
    op.drop_constraint(
        "uq_school_units_tenant_code", "school_units", type_="unique"
    )
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX uq_school_units_tenant_code_active "
            "ON school_units (tenant_id, code) WHERE deleted_at IS NULL"
        )
    )

    # ── 3. academic_programmes ─────────────────────────────────────
    op.add_column(
        "academic_programmes",
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_academic_programmes_deleted_at",
        "academic_programmes",
        ["deleted_at"],
    )
    op.drop_constraint(
        "uq_academic_programmes_tenant_code",
        "academic_programmes",
        type_="unique",
    )
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX uq_academic_programmes_tenant_code_active "
            "ON academic_programmes (tenant_id, code) WHERE deleted_at IS NULL"
        )
    )

    # ── 4. grades ──────────────────────────────────────────────────
    op.add_column(
        "grades",
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_grades_deleted_at", "grades", ["deleted_at"])
    op.drop_constraint("uq_grades_tenant_name", "grades", type_="unique")
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX uq_grades_tenant_name_active "
            "ON grades (tenant_id, name) WHERE deleted_at IS NULL"
        )
    )

    # ── 5. religions ───────────────────────────────────────────────
    op.add_column(
        "religions",
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_religions_deleted_at", "religions", ["deleted_at"])
    op.drop_constraint(
        "uq_religions_tenant_name", "religions", type_="unique"
    )
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX uq_religions_tenant_name_active "
            "ON religions (tenant_id, name) WHERE deleted_at IS NULL"
        )
    )


def downgrade() -> None:
    # religions
    op.execute(sa.text("DROP INDEX IF EXISTS uq_religions_tenant_name_active"))
    op.create_unique_constraint(
        "uq_religions_tenant_name", "religions", ["tenant_id", "name"]
    )
    op.drop_index("ix_religions_deleted_at", table_name="religions")
    op.drop_column("religions", "deleted_at")

    # grades
    op.execute(sa.text("DROP INDEX IF EXISTS uq_grades_tenant_name_active"))
    op.create_unique_constraint(
        "uq_grades_tenant_name", "grades", ["tenant_id", "name"]
    )
    op.drop_index("ix_grades_deleted_at", table_name="grades")
    op.drop_column("grades", "deleted_at")

    # academic_programmes
    op.execute(
        sa.text("DROP INDEX IF EXISTS uq_academic_programmes_tenant_code_active")
    )
    op.create_unique_constraint(
        "uq_academic_programmes_tenant_code",
        "academic_programmes",
        ["tenant_id", "code"],
    )
    op.drop_index(
        "ix_academic_programmes_deleted_at", table_name="academic_programmes"
    )
    op.drop_column("academic_programmes", "deleted_at")

    # school_units
    op.execute(sa.text("DROP INDEX IF EXISTS uq_school_units_tenant_code_active"))
    op.create_unique_constraint(
        "uq_school_units_tenant_code", "school_units", ["tenant_id", "code"]
    )
    op.drop_index("ix_school_units_deleted_at", table_name="school_units")
    op.drop_column("school_units", "deleted_at")

    # tenants.is_setup_complete
    op.drop_column("tenants", "is_setup_complete")
