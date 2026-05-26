"""Drop legacy class uniqueness; add composite indexes for multi-school filtering.

Revision ID: 045_classes_structural_uniqueness
Revises: 044_multi_school_structure
Create Date: 2026-04-29

Phase 1 fixes that go with the multi-school structure:

1. Drop the legacy unique constraint
   `uq_class_section_academic_year_id_tenant` on
   `(name, section, academic_year_id, tenant_id)`. The structural unique
   constraint on `(tenant_id, school_unit_id, programme_id, grade_id,
   section, academic_year_id)` introduced in 044 is now the source of
   truth.

2. Add three composite indexes that match the most common multi-school
   list / filter queries:
       (tenant_id, school_unit_id)
       (tenant_id, programme_id)
       (tenant_id, grade_id)
"""

from __future__ import annotations

from alembic import op


revision = "045_classes_structural_uniqueness"
down_revision = "044_multi_school_structure"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Drop legacy uniqueness — superseded by uq_classes_unit_programme_grade_section_year.
    op.drop_constraint(
        "uq_class_section_academic_year_id_tenant",
        "classes",
        type_="unique",
    )

    # 2. Composite indexes for tenant-scoped filtering.
    op.create_index(
        "ix_classes_tenant_school_unit",
        "classes",
        ["tenant_id", "school_unit_id"],
    )
    op.create_index(
        "ix_classes_tenant_programme",
        "classes",
        ["tenant_id", "programme_id"],
    )
    op.create_index(
        "ix_classes_tenant_grade",
        "classes",
        ["tenant_id", "grade_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_classes_tenant_grade", table_name="classes")
    op.drop_index("ix_classes_tenant_programme", table_name="classes")
    op.drop_index("ix_classes_tenant_school_unit", table_name="classes")

    op.create_unique_constraint(
        "uq_class_section_academic_year_id_tenant",
        "classes",
        ["name", "section", "academic_year_id", "tenant_id"],
    )
