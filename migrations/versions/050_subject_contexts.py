"""Subject contexts: per-(programme, grade) offerings of a subject.

Revision ID: 050_subject_contexts
Revises: 049_subject_templates
Create Date: 2026-05-02

Tables introduced:
  - mediums: per-tenant lookup for medium of instruction (English, Gujarati, ...)
  - subject_contexts: how a (programme, grade) offers a subject. Replaces the
    role of subject_template_items as the source of truth.

Modifications:
  - class_subjects.subject_context_id: nullable FK pointing back at the
    context that produced the row, for traceability.

Backfill:
  - Insert one subject_contexts row per existing subject_template_items row,
    inheriting default_weekly_periods from its parent template.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "050_subject_contexts"
down_revision = "049_subject_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- mediums ----------------------------------------------------------
    op.create_table(
        "mediums",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(length=36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_by",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_by",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_mediums_tenant_id", "mediums", ["tenant_id"])
    op.create_index(
        "uq_mediums_tenant_name_active",
        "mediums",
        ["tenant_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ---- subject_contexts -------------------------------------------------
    op.create_table(
        "subject_contexts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(length=36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "programme_id",
            sa.String(length=36),
            sa.ForeignKey("academic_programmes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "grade_id",
            sa.String(length=36),
            sa.ForeignKey("grades.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subject_id",
            sa.String(length=36),
            sa.ForeignKey("subjects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(length=160), nullable=True),
        sa.Column("short_code", sa.String(length=32), nullable=True),
        sa.Column(
            "type",
            sa.String(length=16),
            nullable=False,
            server_default="mandatory",
        ),
        sa.Column("role", sa.String(length=32), nullable=True),
        sa.Column(
            "medium_id",
            sa.String(length=36),
            sa.ForeignKey("mediums.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "variant_of_context_id",
            sa.String(length=36),
            sa.ForeignKey("subject_contexts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("elective_group_key", sa.String(length=80), nullable=True),
        sa.Column(
            "default_weekly_periods",
            sa.SmallInteger(),
            nullable=False,
            server_default="5",
        ),
        sa.Column(
            "sort_order",
            sa.SmallInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_by",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_by",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "default_weekly_periods BETWEEN 1 AND 40",
            name="ck_subject_contexts_periods_range",
        ),
        sa.CheckConstraint(
            "type IN ('mandatory','elective')",
            name="ck_subject_contexts_type",
        ),
        sa.CheckConstraint(
            "role IS NULL OR role IN ("
            "'first_language','second_language','third_language',"
            "'core','co_curricular')",
            name="ck_subject_contexts_role",
        ),
        sa.CheckConstraint(
            "variant_of_context_id IS NULL OR variant_of_context_id <> id",
            name="ck_subject_contexts_no_self_variant",
        ),
    )
    op.create_index(
        "ix_subject_contexts_tenant_programme_grade",
        "subject_contexts",
        ["tenant_id", "programme_id", "grade_id"],
    )
    op.create_index(
        "ix_subject_contexts_subject_id",
        "subject_contexts",
        ["subject_id"],
    )
    op.create_index(
        "ix_subject_contexts_elective_group",
        "subject_contexts",
        ["tenant_id", "programme_id", "grade_id", "elective_group_key"],
        postgresql_where=sa.text("elective_group_key IS NOT NULL"),
    )
    # Uniqueness: one offering per (programme, grade, subject, medium, role)
    # among non-deleted rows. NULLs in medium_id / role are coalesced to a
    # sentinel so 'no medium / no role' collisions are still caught.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_subject_contexts_offering_active
        ON subject_contexts (
            tenant_id,
            programme_id,
            grade_id,
            subject_id,
            COALESCE(medium_id, ''),
            COALESCE(role, '')
        )
        WHERE deleted_at IS NULL;
        """
    )

    # ---- class_subjects.subject_context_id --------------------------------
    op.add_column(
        "class_subjects",
        sa.Column("subject_context_id", sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        "fk_class_subjects_subject_context",
        "class_subjects",
        "subject_contexts",
        ["subject_context_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_class_subjects_subject_context_id",
        "class_subjects",
        ["subject_context_id"],
    )

    # ---- backfill from subject_template_items -----------------------------
    # One subject_contexts row per existing template item, carrying its
    # parent template's default_weekly_periods. Skip items whose parent
    # template was deleted (FK guarantees cascade, but be defensive).
    op.execute(
        """
        INSERT INTO subject_contexts (
            id, tenant_id, programme_id, grade_id, subject_id,
            display_name, type, default_weekly_periods, sort_order,
            is_active, created_at, updated_at
        )
        SELECT
            gen_random_uuid()::text,
            t.tenant_id,
            t.programme_id,
            t.grade_id,
            i.subject_id,
            s.name,
            'mandatory',
            COALESCE(t.default_weekly_periods, 5),
            0,
            true,
            now(),
            now()
        FROM subject_template_items i
        JOIN subject_templates t ON t.id = i.template_id
        JOIN subjects s ON s.id = i.subject_id
        WHERE NOT EXISTS (
            SELECT 1 FROM subject_contexts c
            WHERE c.tenant_id = t.tenant_id
              AND c.programme_id = t.programme_id
              AND c.grade_id = t.grade_id
              AND c.subject_id = i.subject_id
              AND c.deleted_at IS NULL
              AND COALESCE(c.medium_id, '') = ''
              AND COALESCE(c.role, '') = ''
        );
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_class_subjects_subject_context_id", table_name="class_subjects"
    )
    op.drop_constraint(
        "fk_class_subjects_subject_context",
        "class_subjects",
        type_="foreignkey",
    )
    op.drop_column("class_subjects", "subject_context_id")

    op.execute("DROP INDEX IF EXISTS uq_subject_contexts_offering_active;")
    op.drop_index(
        "ix_subject_contexts_elective_group", table_name="subject_contexts"
    )
    op.drop_index(
        "ix_subject_contexts_subject_id", table_name="subject_contexts"
    )
    op.drop_index(
        "ix_subject_contexts_tenant_programme_grade",
        table_name="subject_contexts",
    )
    op.drop_table("subject_contexts")

    op.drop_index("uq_mediums_tenant_name_active", table_name="mediums")
    op.drop_index("ix_mediums_tenant_id", table_name="mediums")
    op.drop_table("mediums")
