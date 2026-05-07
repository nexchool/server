"""add medium_id to classes

Adds a nullable FK column classes.medium_id → mediums.id (SET NULL on delete)
with an index for efficient lookups.

Revision ID: 054_add_medium_id_to_classes
Revises: 6ef586ca739c
Create Date: 2026-05-07

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "054_add_medium_id_to_classes"
down_revision = "6ef586ca739c"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "classes",
        sa.Column(
            "medium_id",
            sa.String(length=36),
            nullable=True,
        ),
    )
    op.create_index("ix_classes_medium_id", "classes", ["medium_id"], unique=False)
    op.create_foreign_key(
        "fk_classes_medium_id",
        "classes",
        "mediums",
        ["medium_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_classes_medium_id", "classes", type_="foreignkey")
    op.drop_index("ix_classes_medium_id", table_name="classes")
    op.drop_column("classes", "medium_id")
