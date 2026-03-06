"""Drop classes.academic_year column (deprecated; use academic_year_id)."""

from alembic import op

revision = "009_drop_classes_academic_year"
down_revision = "008_notification_templates"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_column("classes", "academic_year")


def downgrade():
    import sqlalchemy as sa
    op.add_column(
        "classes",
        sa.Column("academic_year", sa.String(20), nullable=True),
    )
