"""A school may wear its own colours.

Adds `tenants.theme_seeds`: the two or three brand colours a school picks,
from which the mobile app's whole palette is derived (core/theme.py).

Nullable on purpose, and left null for every existing tenant. Null means the
app uses the palette it ships with, so this migration changes how nothing
looks until somebody sets a theme in the panel.

Revision ID: 123_a_school_may_wear_its_own_colours
Revises: 122_a_bed_status_the_readers_do_not_recognise
"""

import sqlalchemy as sa
from alembic import op

revision = "123_a_school_may_wear_its_own_colours"
down_revision = "122_a_bed_status_the_readers_do_not_recognise"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tenants", sa.Column("theme_seeds", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("tenants", "theme_seeds")
