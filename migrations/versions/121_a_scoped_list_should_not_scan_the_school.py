"""A tenant-scoped list should not read every row in the school.

Measured against a 15,000-student tenant, not estimated. Every index below
serves a query the product runs on a page a person opens daily, and each was
a sequential scan first.

**`students.class_id` had no index at all** — not composite, not standalone.
It is the *only* path branch scoping has, because `students` carries no
`school_unit_id`: campus is reached as student → class → unit
(`core/branch_scope.py`). So the multi-campus product — the whole point of the
scale contract — filtered by walking the table, and a campus-scoped student
page measured ~16x slower than the unscoped one.

**`students(admission_number, tenant_id)` exists but is the wrong way round.**
A btree leads on its first column, so it can answer "which tenant owns
admission number X" and cannot answer "this tenant's students, in admission
order" — which is the default sort of the default list. Hence the pair here
with `tenant_id` first. The old index is left alone; it is small and something
may still lead on admission number.

`persons(tenant_id, full_name)` earns its place on **search**, not on sort:
a name prefix match went 46,497-row sequential scan → index scan (~1.0 ms), and
reading persons in name order is now 0.2 ms. Measured honestly, it does *not*
help the student list *sorted* by name — with the filter on `students` the
planner still hash-joins and top-N sorts (~8 ms at 15,000 students, which is
acceptable). Making that one use an index needs a different query shape, not
another index, and is deliberately not attempted here.

Plain `CREATE INDEX`, not `CONCURRENTLY`: these tables are thousands of rows,
migrations run on container boot, and the lock is momentary. `attendance` is
the one that grows without bound (one row per student per day — ~3.3M a year
at contract scale); if it is already large when this runs, build its two
indexes by hand with `CONCURRENTLY` first and this migration will skip them.

`IF NOT EXISTS` throughout, in both directions: the test suite `create_all()`s
against the same database as dev, so this has to be safe to meet twice.

Revision ID: 121_a_scoped_list_should_not_scan_the_school
Revises: 120_a_retired_feature_key_is_not_an_answer
Create Date: 2026-08-30

"""
from alembic import op

revision = "121_a_scoped_list_should_not_scan_the_school"
down_revision = "120_a_retired_feature_key_is_not_an_answer"
branch_labels = None
depends_on = None


#: (name, table, column list) — every one serves a named query.
INDEXES = [
    # Branch scope: student -> class -> school_unit. The only path there is.
    ("idx_students_tenant_id_class_id", "students", "tenant_id, class_id"),
    # The default student list's default sort.
    ("idx_students_tenant_id_admission_number", "students", "tenant_id, admission_number"),
    # The same list ordered by roll number.
    ("idx_students_tenant_id_roll_number", "students", "tenant_id, roll_number"),
    # Name sort and name search both join persons and ordered by this.
    ("idx_persons_tenant_id_full_name", "persons", "tenant_id, full_name"),
    # A child's attendance history: newest first, one student.
    ("idx_attendance_tenant_id_student_id_date", "attendance", "tenant_id, student_id, date DESC"),
    # The attendance list and the count that pages it. The existing composite
    # leads on `date` with tenant_id last, so it cannot serve a tenant filter.
    ("idx_attendance_tenant_id_date_class_id", "attendance", "tenant_id, date DESC, class_id"),
]


def upgrade():
    for name, table, columns in INDEXES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns})")


def downgrade():
    for name, _table, _columns in reversed(INDEXES):
        op.execute(f"DROP INDEX IF EXISTS {name}")
