"""Generate a production-scale tenant, so performance is measured not guessed.

    python scripts/seed_scale_fixture.py --size large
    python scripts/seed_scale_fixture.py --size medium --measure
    python scripts/seed_scale_fixture.py --drop

Generation is additive, so **--drop before changing size**. Running `medium`
over an existing `large` leaves the large rows in place and measures those,
which is a quietly wrong answer rather than a loud one.

Why this exists
---------------

A demo tenant of a few hundred students hides the problems that matter. Every
performance finding worth having on this project came from data at real size,
and two of them had been dismissed on demo-sized measurements first:

- the teachers list was called "constant queries" after measuring five teachers;
  at twenty-five it was one query per row.
- the bus operational warning was called "bounded by the fleet" after measuring
  four buses; a twenty-campus trust runs eighty.

Realistic distributions, not just realistic counts
--------------------------------------------------

Row counts alone are not enough. The duplicate scan looked catastrophic on the
first attempt at this fixture — 199 seconds — because every generated name
normalised to the same word and landed in one bucket. With ordinary name
variety it is about a second.

So this generates names from a pool of forty given names and twenty-five
surnames, roughly the collision rate a real trust sees, and gives a share of
parents the placeholder phone number that migrated school data is full of.
Both shapes exist because both change the answer.

Safe by construction
--------------------

Everything lives under one tenant whose id is fixed and obviously synthetic,
so `--drop` removes it entirely and nothing else is touched. It refuses to run
against a database whose URL does not look local.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import event, text  # noqa: E402

from app import create_app  # noqa: E402
from core.database import db  # noqa: E402

TENANT_ID = "scale-fixture"
TENANT_SUBDOMAIN = "scale-fixture"

SIZES = {
    "small": {"students": 500, "classes": 20, "campuses": 2, "teachers": 40, "riders": 150},
    "medium": {"students": 5_000, "classes": 120, "campuses": 8, "teachers": 220, "riders": 1_400},
    "large": {"students": 15_000, "classes": 300, "campuses": 20, "teachers": 600, "riders": 4_000},
}

GIVEN_NAMES = 40
SURNAMES = 25

# Migrated school data is full of one office number standing in for a parent's.
# It creates a single enormous match bucket, which is the shape that makes
# duplicate detection quadratic. A fifth is representative.
PLACEHOLDER_PHONE_SHARE = 5


def _guard_the_database() -> None:
    url = os.environ.get("DATABASE_URL", "")
    if not any(host in url for host in ("localhost", "127.0.0.1", "postgres:")):
        raise SystemExit(
            "Refusing to run: DATABASE_URL does not look local.\n"
            f"  {url or '(unset)'}\n"
            "This writes tens of thousands of rows and is for engineering use only."
        )


def _sql(statement: str, **params) -> None:
    db.session.execute(text(statement), params or None)


def drop() -> None:
    """Remove the fixture tenant and everything under it."""
    tables = [
        row[0]
        for row in db.session.execute(
            text(
                """
                SELECT table_name FROM information_schema.columns
                 WHERE column_name = 'tenant_id' AND table_schema = 'public'
                 GROUP BY table_name ORDER BY table_name
                """
            )
        )
    ]

    # Ordered by trial: some foreign keys between child tables do not cascade,
    # so guessing an order is worse than retrying.
    remaining = [t for t in tables if t != "tenants"]
    for _ in range(12):
        blocked = []
        for table in remaining:
            try:
                with db.session.begin_nested():
                    _sql(f'DELETE FROM "{table}" WHERE tenant_id = :t', t=TENANT_ID)
            except Exception:
                blocked.append(table)
        if not blocked or len(blocked) == len(remaining):
            remaining = blocked
            break
        remaining = blocked

    _sql("DELETE FROM tenants WHERE id = :t", t=TENANT_ID)
    db.session.commit()
    print(f"removed the {TENANT_SUBDOMAIN} tenant")


def generate(size: str) -> None:
    shape = SIZES[size]
    students = shape["students"]
    classes = shape["classes"]
    campuses = shape["campuses"]
    teachers = shape["teachers"]
    riders = shape["riders"]

    print(f"generating {size}: {students:,} students, {teachers} teachers, "
          f"{riders:,} riders, {classes} classes, {campuses} campuses")

    _sql(
        """
        INSERT INTO tenants (id, name, subdomain, status, billing_cycle, created_at, updated_at)
        VALUES (:t, 'Scale Fixture Trust', :s, 'active', 'yearly', now(), now())
        ON CONFLICT (id) DO NOTHING
        """,
        t=TENANT_ID, s=TENANT_SUBDOMAIN,
    )

    _sql(
        """
        INSERT INTO school_units (id, tenant_id, name, code, status, created_at, updated_at)
        SELECT 'su-sf-'||g, :t, 'Campus '||g, 'SF'||g, 'active', now(), now()
          FROM generate_series(1, :n) g ON CONFLICT (id) DO NOTHING
        """,
        t=TENANT_ID, n=campuses,
    )
    _sql(
        """
        INSERT INTO academic_years (id, tenant_id, name, start_date, end_date, created_at, updated_at)
        VALUES ('ay-sf', :t, '2026-2027', '2026-06-01', '2027-03-31', now(), now())
        ON CONFLICT (id) DO NOTHING
        """,
        t=TENANT_ID,
    )
    _sql(
        """
        INSERT INTO classes (id, tenant_id, name, section, academic_year_id, school_unit_id, created_at, updated_at)
        SELECT 'cl-sf-'||g, :t, 'Grade '||((g % 12)+1), chr(65 + (g % 4)),
               'ay-sf', 'su-sf-'||((g % :campuses)+1), now(), now()
          FROM generate_series(1, :n) g ON CONFLICT (id) DO NOTHING
        """,
        t=TENANT_ID, n=classes, campuses=campuses,
    )

    # Children, with names drawn from a realistic pool so match buckets behave
    # the way a real tenant's do.
    _sql(
        f"""
        INSERT INTO persons (id, tenant_id, full_name, date_of_birth, gender,
                             phone_number, created_at, updated_at)
        SELECT 'p-sf-stu-'||g, :t, {_name_expression("'p-sf-stu-'||g")},
               (date '2010-01-01' + (g % 3000)),
               CASE WHEN g % 2 = 0 THEN 'male' ELSE 'female' END,
               '9'||lpad((700000000 + g)::text, 9, '0'), now(), now()
          FROM generate_series(1, :n) g ON CONFLICT (id) DO NOTHING
        """,
        t=TENANT_ID, n=students,
    )
    _sql(
        """
        INSERT INTO users (id, tenant_id, email, password_hash, person_id, created_at, updated_at)
        SELECT 'u-sf-stu-'||g, :t, 'sf-student'||g||'@scale.test', 'x', 'p-sf-stu-'||g, now(), now()
          FROM generate_series(1, :n) g ON CONFLICT (id) DO NOTHING
        """,
        t=TENANT_ID, n=students,
    )
    _sql(
        """
        INSERT INTO students (id, tenant_id, user_id, person_id, admission_number,
                              class_id, academic_year_id, created_at, updated_at)
        SELECT 's-sf-'||g, :t, 'u-sf-stu-'||g, 'p-sf-stu-'||g,
               'ADM/'||lpad(g::text, 6, '0'), 'cl-sf-'||((g % :classes)+1), 'ay-sf', now(), now()
          FROM generate_series(1, :n) g ON CONFLICT (id) DO NOTHING
        """,
        t=TENANT_ID, n=students, classes=classes,
    )
    # The enrollment owns the placement; students.class_id above is its cache.
    _sql(
        """
        INSERT INTO student_class_enrollments (id, tenant_id, student_id, class_id,
                                               academic_year_id, enrollment_status,
                                               is_current, created_at, updated_at)
        SELECT 'e-sf-'||g, :t, 's-sf-'||g, 'cl-sf-'||((g % :classes)+1), 'ay-sf',
               'active', true, now(), now()
          FROM generate_series(1, :n) g ON CONFLICT (id) DO NOTHING
        """,
        t=TENANT_ID, n=students, classes=classes,
    )

    _generate_households(students)
    _generate_staff(teachers, classes)
    _generate_transport(riders, classes)

    db.session.commit()
    db.session.execute(text("ANALYZE"))
    print("done")


def _name_expression(seed: str) -> str:
    """A name from a realistic pool, deterministic per row.

    Forty given names against twenty-five surnames is about the collision rate
    a real trust sees. Uniform unique names would make duplicate detection look
    free; a single repeated name would make it look impossible. Neither is true.
    """
    return (
        f"(ARRAY['Aarav','Vivaan','Aditya','Vihaan','Arjun','Sai','Reyansh','Krishna',"
        f"'Ishaan','Rudra','Kiara','Ananya','Diya','Saanvi','Aadhya','Myra','Anika',"
        f"'Navya','Riya','Prisha','Rohan','Kabir','Dhruv','Om','Yash','Tanvi','Meera',"
        f"'Isha','Nisha','Pooja','Amit','Rajesh','Suresh','Mahesh','Nikhil','Sunita',"
        f"'Kavita','Rekha','Neha','Priya'])"
        f"[1 + (('x'||substr(md5({seed}),1,8))::bit(32)::int & 2147483647) % {GIVEN_NAMES}]"
        f" || ' ' || "
        f"(ARRAY['Patel','Shah','Mehta','Desai','Joshi','Trivedi','Raval','Vyas',"
        f"'Parikh','Amin','Solanki','Thakor','Chavda','Parmar','Bhatt','Dave',"
        f"'Purohit','Gandhi','Modi','Soni','Panchal','Rathod','Makwana','Chauhan',"
        f"'Sharma'])"
        f"[1 + (('x'||substr(md5({seed}||'s'),1,8))::bit(32)::int & 2147483647) % {SURNAMES}]"
    )


def _generate_households(students: int) -> None:
    _sql(
        """
        INSERT INTO families (id, tenant_id, created_at, updated_at)
        SELECT 'f-sf-'||g, :t, now(), now() FROM generate_series(1, :n) g
        ON CONFLICT (id) DO NOTHING
        """,
        t=TENANT_ID, n=students,
    )
    _sql(
        f"""
        INSERT INTO persons (id, tenant_id, full_name, phone_number, occupation,
                             created_at, updated_at)
        SELECT 'p-sf-par-'||g||'-'||r, :t,
               {_name_expression("'p-sf-par-'||g||'-'||r")},
               CASE WHEN (g % {PLACEHOLDER_PHONE_SHARE}) = 0
                    THEN '0000000000'
                    ELSE '9'||lpad((800000000 + g*2 + r)::text, 9, '0') END,
               CASE r WHEN 1 THEN 'Engineer' ELSE 'Teacher' END, now(), now()
          FROM generate_series(1, :n) g, generate_series(1, 2) r
        ON CONFLICT (id) DO NOTHING
        """,
        t=TENANT_ID, n=students,
    )
    _sql(
        """
        INSERT INTO family_members (id, tenant_id, family_id, person_id, relationship,
                                    is_primary_contact, created_at, updated_at)
        SELECT 'fm-sf-c-'||g, :t, 'f-sf-'||g, 'p-sf-stu-'||g, 'child', false, now(), now()
          FROM generate_series(1, :n) g ON CONFLICT (id) DO NOTHING
        """,
        t=TENANT_ID, n=students,
    )
    _sql(
        """
        INSERT INTO family_members (id, tenant_id, family_id, person_id, relationship,
                                    is_primary_contact, created_at, updated_at)
        SELECT 'fm-sf-p-'||g||'-'||r, :t, 'f-sf-'||g, 'p-sf-par-'||g||'-'||r,
               CASE r WHEN 1 THEN 'father' ELSE 'mother' END, (r = 1), now(), now()
          FROM generate_series(1, :n) g, generate_series(1, 2) r
        ON CONFLICT (id) DO NOTHING
        """,
        t=TENANT_ID, n=students,
    )


def _generate_staff(teachers: int, classes: int) -> None:
    _sql(
        f"""
        INSERT INTO persons (id, tenant_id, full_name, phone_number, address, created_at, updated_at)
        SELECT 'p-sf-tea-'||g, :t, {_name_expression("'p-sf-tea-'||g")},
               '9'||lpad((600000000 + g)::text, 9, '0'), g||' Staff Colony', now(), now()
          FROM generate_series(1, :n) g ON CONFLICT (id) DO NOTHING
        """,
        t=TENANT_ID, n=teachers,
    )
    _sql(
        """
        INSERT INTO users (id, tenant_id, email, password_hash, person_id, created_at, updated_at)
        SELECT 'u-sf-tea-'||g, :t, 'sf-teacher'||g||'@scale.test', 'x', 'p-sf-tea-'||g, now(), now()
          FROM generate_series(1, :n) g ON CONFLICT (id) DO NOTHING
        """,
        t=TENANT_ID, n=teachers,
    )
    _sql(
        """
        INSERT INTO staff (id, tenant_id, person_id, employee_number, designation,
                           employment_status, created_at, updated_at)
        SELECT 'st-sf-'||g, :t, 'p-sf-tea-'||g, 'SF'||lpad(g::text, 5, '0'),
               CASE WHEN g % 10 = 0 THEN 'Head Teacher' ELSE 'Teacher' END,
               'working', now(), now()
          FROM generate_series(1, :n) g ON CONFLICT (id) DO NOTHING
        """,
        t=TENANT_ID, n=teachers,
    )
    _sql(
        """
        INSERT INTO staff_employment_periods (id, tenant_id, staff_id, joined_on, created_at, updated_at)
        SELECT 'sep-sf-'||g, :t, 'st-sf-'||g, date '2015-06-01' + (g % 2000), now(), now()
          FROM generate_series(1, :n) g ON CONFLICT (id) DO NOTHING
        """,
        t=TENANT_ID, n=teachers,
    )
    _sql(
        """
        INSERT INTO teachers (id, tenant_id, user_id, staff_id, qualification, created_at, updated_at)
        SELECT 't-sf-'||g, :t, 'u-sf-tea-'||g, 'st-sf-'||g, 'M.Ed', now(), now()
          FROM generate_series(1, :n) g ON CONFLICT (id) DO NOTHING
        """,
        t=TENANT_ID, n=teachers,
    )
    # One class teacher per class, which is what the owner's unique index allows.
    _sql(
        """
        INSERT INTO class_teacher_assignments (id, tenant_id, class_id, teacher_id,
                                               role, is_active, created_at, updated_at)
        SELECT 'cta-sf-'||g, :t, 'cl-sf-'||g, 't-sf-'||((g % :teachers)+1),
               'primary', true, now(), now()
          FROM generate_series(1, :classes) g ON CONFLICT (id) DO NOTHING
        """,
        t=TENANT_ID, classes=classes, teachers=teachers,
    )
    # The cache follows the owner.
    _sql(
        """
        UPDATE classes c SET teacher_id = u.id
          FROM class_teacher_assignments a
          JOIN teachers te ON te.id = a.teacher_id
          JOIN users u ON u.id = te.user_id
         WHERE a.class_id = c.id AND c.tenant_id = :t AND a.is_active
        """,
        t=TENANT_ID,
    )


def _generate_transport(riders: int, classes: int) -> None:
    fleet = max(4, riders // 50)
    _sql(
        """
        INSERT INTO transport_buses (id, tenant_id, bus_number, capacity, status, created_at, updated_at)
        SELECT 'bus-sf-'||g, :t, 'SF-'||lpad(g::text, 3, '0'), 50, 'active', now(), now()
          FROM generate_series(1, :n) g ON CONFLICT (id) DO NOTHING
        """,
        t=TENANT_ID, n=fleet,
    )
    _sql(
        """
        INSERT INTO transport_routes (id, tenant_id, name, status, created_at, updated_at)
        SELECT 'rt-sf-'||g, :t, 'Route '||g, 'active', now(), now()
          FROM generate_series(1, :n) g ON CONFLICT (id) DO NOTHING
        """,
        t=TENANT_ID, n=fleet,
    )
    _sql(
        """
        INSERT INTO transport_enrollments (id, tenant_id, student_id, academic_year_id,
                                           bus_id, route_id, start_date, monthly_fee,
                                           status, created_at, updated_at)
        SELECT 'te-sf-'||g, :t, 's-sf-'||g, 'ay-sf',
               'bus-sf-'||((g % :fleet)+1), 'rt-sf-'||((g % :fleet)+1),
               '2026-06-01', 900, 'active', now(), now()
          FROM generate_series(1, :n) g ON CONFLICT (id) DO NOTHING
        """,
        t=TENANT_ID, n=riders, fleet=fleet,
    )


def measure() -> None:
    """Time the list endpoints against the fixture and report queries per call."""
    from flask import g

    from modules.people.merge import suggest_duplicates
    from modules.students.services import list_students
    from modules.teachers.services import list_teachers
    from modules.transport.services import dashboard_stats, list_buses, list_enrollments

    cases = [
        ("students page of 20", lambda: list_students(page=1, per_page=20)),
        ("students page of 100", lambda: list_students(page=1, per_page=100)),
        ("teachers page of 100", lambda: list_teachers(page=1, per_page=100)),
        ("transport enrollments paged", lambda: list_enrollments(page=1, per_page=20)),
        ("transport buses", lambda: list_buses()),
        ("transport dashboard", lambda: dashboard_stats()),
        ("duplicate suggestions", lambda: suggest_duplicates(TENANT_ID)),
    ]

    print(f"\n{'endpoint':<30} {'rows':>6} {'queries':>8} {'ms':>8}")
    print("-" * 56)
    with current_app.test_request_context("/"):
        g.tenant_id = TENANT_ID
        for label, call in cases:
            statements = []
            listener = lambda conn, cur, stmt, *a: statements.append(stmt)  # noqa: E731
            event.listen(db.engine, "before_cursor_execute", listener)
            started = time.perf_counter()
            try:
                result = call()
            finally:
                event.remove(db.engine, "before_cursor_execute", listener)
            elapsed = (time.perf_counter() - started) * 1000
            rows = (
                len(result)
                if isinstance(result, list)
                else len(result.get("items", [])) if isinstance(result, dict) else 0
            )
            print(f"{label:<30} {rows:>6} {len(statements):>8} {elapsed:>8.0f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", choices=sorted(SIZES), default="large")
    parser.add_argument("--drop", action="store_true", help="remove the fixture tenant")
    parser.add_argument("--measure", action="store_true", help="time the list endpoints")
    args = parser.parse_args()

    _guard_the_database()
    app = create_app()
    from flask import current_app  # noqa: E402  (needs an app to exist)

    with app.app_context():
        if args.drop:
            drop()
        else:
            generate(args.size)
        if args.measure:
            measure()
