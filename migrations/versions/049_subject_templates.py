"""Subject templates (programme + grade) for bulk class-subject assignment.

Revision ID: 049_subject_templates
Revises: 048_academic_programme_medium_nullable
Create Date: 2026-04-30

Tables:
  - subject_templates: one row per (tenant, programme, grade)
  - subject_template_items: subjects in that template
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "049_subject_templates"
down_revision = "048_academic_programme_medium_nullable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subject_templates",
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
            "default_weekly_periods",
            sa.SmallInteger(),
            nullable=False,
            server_default="5",
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
        sa.UniqueConstraint(
            "tenant_id",
            "programme_id",
            "grade_id",
            name="uq_subject_templates_tenant_programme_grade",
        ),
    )
    op.create_index(
        "ix_subject_templates_tenant_id",
        "subject_templates",
        ["tenant_id"],
    )
    op.create_index(
        "ix_subject_templates_programme_id",
        "subject_templates",
        ["programme_id"],
    )
    op.create_index(
        "ix_subject_templates_grade_id",
        "subject_templates",
        ["grade_id"],
    )

    op.create_table(
        "subject_template_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "template_id",
            sa.String(length=36),
            sa.ForeignKey("subject_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subject_id",
            sa.String(length=36),
            sa.ForeignKey("subjects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "template_id",
            "subject_id",
            name="uq_subject_template_items_template_subject",
        ),
    )
    op.create_index(
        "ix_subject_template_items_template_id",
        "subject_template_items",
        ["template_id"],
    )
    op.create_index(
        "ix_subject_template_items_subject_id",
        "subject_template_items",
        ["subject_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_subject_template_items_subject_id", table_name="subject_template_items")
    op.drop_index("ix_subject_template_items_template_id", table_name="subject_template_items")
    op.drop_table("subject_template_items")
    op.drop_index("ix_subject_templates_grade_id", table_name="subject_templates")
    op.drop_index("ix_subject_templates_programme_id", table_name="subject_templates")
    op.drop_index("ix_subject_templates_tenant_id", table_name="subject_templates")
    op.drop_table("subject_templates")
