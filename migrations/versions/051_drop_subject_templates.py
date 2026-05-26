"""Drop subject_templates and subject_template_items.

Revision ID: 051_drop_subject_templates
Revises: 050_subject_contexts
Create Date: 2026-05-02

These tables were superseded by subject_contexts (migration 050). The
backfill in 050 copied every subject_template_items row into subject_contexts,
and no application code reads or writes the template tables anymore.

Downgrade rebuilds the empty tables so the schema can be reverted, but the
original rows are NOT restored — a roll-back would lose any template data
created between 050 and 051. In practice the gap is the deploy window.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "051_drop_subject_templates"
down_revision = "050_subject_contexts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index(
        "ix_subject_template_items_subject_id",
        table_name="subject_template_items",
    )
    op.drop_index(
        "ix_subject_template_items_template_id",
        table_name="subject_template_items",
    )
    op.drop_table("subject_template_items")

    op.drop_index(
        "ix_subject_templates_grade_id", table_name="subject_templates"
    )
    op.drop_index(
        "ix_subject_templates_programme_id", table_name="subject_templates"
    )
    op.drop_index(
        "ix_subject_templates_tenant_id", table_name="subject_templates"
    )
    op.drop_table("subject_templates")


def downgrade() -> None:
    # Rebuild the empty tables. Data is NOT restored.
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
