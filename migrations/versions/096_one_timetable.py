"""One timetable, not two.

`timetable_slots` was superseded by `timetable_versions` + `timetable_entries`
in migration 023, which copied every slot across and declared the new pair the
source of truth. The old table was left behind with its own REST API, its own
generator, its own conflict rules and its own config table — a second
implementation of the same concept, which is the thing this architecture
forbids most explicitly.

Everything the deleted surface did is done by the class timetable API, except
one thing it uniquely had: a signed-in teacher's or student's own week. That
read now assembles itself from timetable entries and bell schedules, so no
client loses a screen.

Dropped here:
- `timetable_slots` and `timetable_config`
- `schedule_overrides.slot_id`, the pointer at the departing table. Every
  override that had one was repointed at its entry by migration 023; any row
  that still names only a slot is carried across first, and the migration
  refuses rather than silently discarding an override it cannot place.

Revision ID: 096_one_timetable
Revises: 095_the_class_teacher_cache_names_the_teacher
"""

import sqlalchemy as sa
from alembic import op

revision = "096_one_timetable"
down_revision = "095_the_class_teacher_cache_names_the_teacher"
branch_labels = None
depends_on = None


# An override still keyed only on a slot: find the entry that replaced that
# slot — same class, day, period — and repoint it. Migration 023 did this for
# everything that existed then; this covers anything written since.
_CARRY_ORPHANED_OVERRIDES = """
UPDATE schedule_overrides o
SET timetable_entry_id = e.id
FROM timetable_slots s
JOIN timetable_versions v
  ON v.class_id = s.class_id AND v.tenant_id = s.tenant_id
JOIN timetable_entries e
  ON e.timetable_version_id = v.id
 AND e.day_of_week = s.day_of_week + 1
 AND e.period_number = s.period_number
WHERE o.slot_id = s.id
  AND o.timetable_entry_id IS NULL
"""

_STILL_STRANDED = """
SELECT COUNT(*) FROM schedule_overrides
WHERE timetable_entry_id IS NULL AND slot_id IS NOT NULL
"""


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text(_CARRY_ORPHANED_OVERRIDES))

    stranded = bind.execute(sa.text(_STILL_STRANDED)).scalar()
    if stranded:
        raise RuntimeError(
            f"{stranded} schedule override(s) point only at a legacy timetable "
            "slot with no matching timetable entry. Repoint or delete them "
            "before dropping the table — dropping now would discard them."
        )

    op.drop_index("uq_schedule_override_slot_date", table_name="schedule_overrides")
    op.drop_index("ix_schedule_overrides_slot_id", table_name="schedule_overrides")
    op.drop_column("schedule_overrides", "slot_id")

    op.drop_table("timetable_slots")
    op.drop_table("timetable_config")


def downgrade():
    # The column and tables come back empty: the slot rows they held are not
    # reconstructable, and the overrides now name entries.
    op.add_column(
        "schedule_overrides", sa.Column("slot_id", sa.String(length=36), nullable=True)
    )
    op.create_index(
        "ix_schedule_overrides_slot_id", "schedule_overrides", ["slot_id"]
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_schedule_override_slot_date
        ON schedule_overrides (slot_id, override_date)
        WHERE slot_id IS NOT NULL
        """
    )

    op.create_table(
        "timetable_config",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column(
            "general_class_duration_minutes", sa.Integer(), nullable=False, server_default="45"
        ),
        sa.Column(
            "first_class_duration_minutes", sa.Integer(), nullable=False, server_default="50"
        ),
        sa.Column(
            "gap_between_classes_minutes", sa.Integer(), nullable=False, server_default="5"
        ),
        sa.Column("periods_per_day", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("school_start_time", sa.Time(), nullable=False),
        sa.Column("breaks_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", name="uq_timetable_config_tenant"),
    )

    op.create_table(
        "timetable_slots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("class_id", sa.String(length=36), nullable=False),
        sa.Column("subject_id", sa.String(length=36), nullable=False),
        sa.Column("teacher_id", sa.String(length=36), nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=False),
        sa.Column("period_number", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("room", sa.String(length=50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["class_id"], ["classes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subject_id"], ["subjects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["teacher_id"], ["teachers.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "class_id", "day_of_week", "period_number", name="uq_class_day_period"
        ),
    )
    op.create_foreign_key(
        "schedule_overrides_slot_id_fkey",
        "schedule_overrides",
        "timetable_slots",
        ["slot_id"],
        ["id"],
        ondelete="CASCADE",
    )
