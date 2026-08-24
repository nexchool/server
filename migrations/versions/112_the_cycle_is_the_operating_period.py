"""a year is what a school reports under; a cycle is when it actually runs

`academic_years` carries one pair of dates for the whole tenant, so a trust
running GSEB June-to-April and CBSE April-to-March had to pick one and be wrong
about the other. Terms and calendars hung off the year, so they were wrong in
the same way.

A cycle is that missing period. Every existing year gets exactly one, named
after it and carrying its dates, so a school with one cycle behaves precisely
as it did — which is the point: this migration must be invisible until somebody
opens a second cycle.

**Ownership moves; the year column stays.** Classes, terms and calendars each
gain `academic_cycle_id`, and each declares a composite foreign key
`(academic_year_id, academic_cycle_id) → academic_cycles(academic_year_id, id)`.
That is what makes keeping both safe: the database refuses a row whose cycle
belongs to a different year than its own year column, so the retained
denormalisation cannot drift from the new owner. Fifteen readers keep working
untouched, and none of them can be lied to.

Ids are derived from the year they describe (`md5('cycle:' || year)`), never
`gen_random_uuid()` — length is then guaranteed and a re-run cannot duplicate.

Revision ID: 112_the_cycle_is_the_operating_period
Revises: 111_a_student_elects_their_options
Create Date: 2026-08-12
"""

from alembic import op
import sqlalchemy as sa

revision = "112_the_cycle_is_the_operating_period"
down_revision = "111_a_student_elects_their_options"
branch_labels = None
depends_on = None

_DEFAULT_CYCLES = sa.text(
    """
    INSERT INTO academic_cycles (
        id, tenant_id, academic_year_id, name, start_date, end_date,
        cycle_kind, created_at, updated_at
    )
    SELECT md5('cycle:' || y.id)::uuid::text,
           y.tenant_id, y.id, y.name, y.start_date, y.end_date,
           'main', now(), now()
      FROM academic_years y
    ON CONFLICT DO NOTHING
    """
)

# Every row inherits the one cycle its year now has. Written as a join on the
# year rather than the derived id, so a cycle created by hand before this ran
# is still found.
_BACKFILL = """
    UPDATE {table} t
       SET academic_cycle_id = c.id
      FROM academic_cycles c
     WHERE c.academic_year_id = t.academic_year_id
       AND c.tenant_id = t.tenant_id
       AND c.cycle_kind = 'main'
       AND t.academic_cycle_id IS NULL
"""


def _carry(bind, table: str) -> None:
    bind.execute(sa.text(_BACKFILL.format(table=table)))
    stranded = bind.execute(
        sa.text(
            f"SELECT count(*) FROM {table} WHERE academic_cycle_id IS NULL"
        )
    ).scalar()
    if stranded:
        raise RuntimeError(
            f"{stranded} row(s) in {table} could not be given a cycle. Every "
            "academic year should have received a main cycle above; check for "
            f"{table} rows whose academic_year_id names a year that does not "
            "exist or belongs to another tenant."
        )


def upgrade():
    bind = op.get_bind()

    op.create_table(
        "academic_cycles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("academic_year_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("start_date", sa.Date, nullable=False),
        sa.Column("end_date", sa.Date, nullable=False),
        sa.Column(
            "cycle_kind", sa.String(20), nullable=False, server_default="main"
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"],
            name="fk_academic_cycles_tenant", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["academic_year_id"], ["academic_years.id"],
            name="fk_academic_cycles_year", ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "cycle_kind IN ('main', 'short_course')", name="ck_academic_cycles_kind"
        ),
        sa.CheckConstraint(
            "start_date <= end_date", name="ck_academic_cycles_dates_ordered"
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_academic_cycles_tenant_id_id"),
        sa.UniqueConstraint(
            "academic_year_id", "id", name="uq_academic_cycles_year_id_id"
        ),
    )
    op.create_index("idx_academic_cycles_tenant", "academic_cycles", ["tenant_id"])
    op.create_index(
        "idx_academic_cycles_year", "academic_cycles", ["tenant_id", "academic_year_id"]
    )
    op.create_index(
        "idx_academic_cycles_dates",
        "academic_cycles",
        ["tenant_id", "start_date", "end_date"],
    )
    op.create_index("idx_academic_cycles_deleted_at", "academic_cycles", ["deleted_at"])
    op.create_index(
        "uq_academic_cycles_year_name",
        "academic_cycles",
        ["tenant_id", "academic_year_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    bind.execute(_DEFAULT_CYCLES)

    # --- the three owners -------------------------------------------------
    for table, fk_name in (
        ("classes", "fk_classes_academic_cycle"),
        ("academic_terms", "fk_academic_terms_academic_cycle"),
        ("academic_calendars", "fk_academic_calendars_academic_cycle"),
    ):
        op.add_column(
            table, sa.Column("academic_cycle_id", sa.String(36), nullable=True)
        )
        _carry(bind, table)
        op.alter_column(table, "academic_cycle_id", nullable=False)
        # The composite is the whole point: a row's cycle must belong to the
        # row's year, enforced by the database rather than by every writer.
        op.create_foreign_key(
            fk_name,
            table,
            "academic_cycles",
            ["academic_year_id", "academic_cycle_id"],
            ["academic_year_id", "id"],
            ondelete="RESTRICT",
        )
        op.create_index(
            f"idx_{table}_academic_cycle_id", table, ["academic_cycle_id"]
        )

    # A calendar belongs to a cycle now, not to a year. With one cycle per year
    # this is the same rule it already had.
    op.drop_constraint(
        "uq_academic_calendars_tenant_year", "academic_calendars", type_="unique"
    )
    op.create_unique_constraint(
        "uq_academic_calendars_tenant_cycle",
        "academic_calendars",
        ["tenant_id", "academic_cycle_id"],
    )


def downgrade():
    op.drop_constraint(
        "uq_academic_calendars_tenant_cycle", "academic_calendars", type_="unique"
    )
    op.create_unique_constraint(
        "uq_academic_calendars_tenant_year",
        "academic_calendars",
        ["tenant_id", "academic_year_id"],
    )

    for table, fk_name in (
        ("academic_calendars", "fk_academic_calendars_academic_cycle"),
        ("academic_terms", "fk_academic_terms_academic_cycle"),
        ("classes", "fk_classes_academic_cycle"),
    ):
        op.drop_index(f"idx_{table}_academic_cycle_id", table_name=table)
        op.drop_constraint(fk_name, table, type_="foreignkey")
        op.drop_column(table, "academic_cycle_id")

    op.drop_table("academic_cycles")
