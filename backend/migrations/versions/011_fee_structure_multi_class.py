"""Fee structure multi-class: fee_structure_classes junction, drop class_id.

Revision ID: 011_fee_structure_multi_class
Revises: 010_classes_unique_teacher
Create Date: 2025-03-01

- Creates fee_structure_classes junction (fee_structure can apply to multiple classes)
- Migrates existing class_id data to junction
- Drops class_id from fee_structures
- Unique: (academic_year_id, class_id, tenant_id) - no two structures can have same class in same year
"""

from alembic import op
import sqlalchemy as sa

revision = "011_fee_structure_multi_class"
down_revision = "010_classes_unique_teacher"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "fee_structure_classes",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("fee_structure_id", sa.String(36), nullable=False),
        sa.Column("class_id", sa.String(36), nullable=False),
        sa.Column("academic_year_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["academic_year_id"], ["academic_years.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["fee_structure_id"], ["fee_structures.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_fee_structure_classes_tenant_id"),
        "fee_structure_classes",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_fee_structure_classes_fee_structure_id"),
        "fee_structure_classes",
        ["fee_structure_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_fee_structure_classes_class_id"),
        "fee_structure_classes",
        ["class_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_fee_structure_classes_year_class_tenant",
        "fee_structure_classes",
        ["academic_year_id", "class_id", "tenant_id"],
    )

    # Migrate existing class_id from fee_structures
    op.execute("""
        INSERT INTO fee_structure_classes (id, tenant_id, fee_structure_id, class_id, academic_year_id, created_at)
        SELECT
            gen_random_uuid()::text,
            fs.tenant_id,
            fs.id,
            fs.class_id,
            fs.academic_year_id,
            NOW()
        FROM fee_structures fs
        WHERE fs.class_id IS NOT NULL
    """)

    # Drop class_id from fee_structures
    op.drop_index(op.f("ix_fee_structures_class_id"), table_name="fee_structures")
    op.drop_constraint("fee_structures_class_id_fkey", "fee_structures", type_="foreignkey")
    op.drop_column("fee_structures", "class_id")


def downgrade():
    op.add_column(
        "fee_structures",
        sa.Column("class_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "fee_structures_class_id_fkey",
        "fee_structures",
        "classes",
        ["class_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_fee_structures_class_id"), "fee_structures", ["class_id"], unique=False)

    op.execute("""
        UPDATE fee_structures fs
        SET class_id = fsc.class_id
        FROM (
            SELECT fee_structure_id, class_id,
                   ROW_NUMBER() OVER (PARTITION BY fee_structure_id ORDER BY created_at) AS rn
            FROM fee_structure_classes
        ) fsc
        WHERE fs.id = fsc.fee_structure_id AND fsc.rn = 1
    """)

    op.drop_constraint("uq_fee_structure_classes_year_class_tenant", "fee_structure_classes", type_="unique")
    op.drop_index(op.f("ix_fee_structure_classes_class_id"), table_name="fee_structure_classes")
    op.drop_index(op.f("ix_fee_structure_classes_fee_structure_id"), table_name="fee_structure_classes")
    op.drop_index(op.f("ix_fee_structure_classes_tenant_id"), table_name="fee_structure_classes")
    op.drop_table("fee_structure_classes")
