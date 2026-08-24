"""CLI: seed rich demo/test data on top of a seeded academic foundation.

`scripts/seed_school.py` builds the foundation (units -> programmes -> grades ->
academic year -> subjects -> subject_contexts -> classes -> class_subjects).
This script fills in everything downstream of it so a local tenant behaves like
a school that has actually been running: staff, teaching assignments, the
timetable, leave, students, attendance, fees, transport and hostel.

Usage (from server/, tenant must already have the foundation seeded):
    PYTHONPATH=. python scripts/seed_demo_data.py --stage all
    PYTHONPATH=. python scripts/seed_demo_data.py --stage teachers --tenant default

Stages run in dependency order and each is idempotent on its natural keys, so a
partial run can be repeated. `--stage all` runs every stage in order.

LOCAL/TEST DATA ONLY. Every login it creates shares one well-known password.
"""
from __future__ import annotations

import argparse
import random
import sys
import uuid
from datetime import date, datetime, time, timedelta

from werkzeug.security import generate_password_hash

from app import create_app
from core.database import db
from core.models import Tenant

# Deterministic output: re-running against a fresh DB yields the same school.
SEED = 20260803
TEACHER_PASSWORD = "Teacher@123"
STUDENT_PASSWORD = "Student@123"


def log(msg: str) -> None:
    print(f"  {msg}")


# --------------------------------------------------------------------------- #
# Shared lookup helpers
# --------------------------------------------------------------------------- #
class Ctx:
    """Resolved foundation objects every stage needs."""

    def __init__(self, tenant_id: str):
        from modules.academics.academic_year.models import AcademicYear
        from modules.classes.models import Class
        from modules.subjects.models import Subject

        self.tenant_id = tenant_id
        self.year = (
            AcademicYear.query.filter_by(tenant_id=tenant_id, is_active=True)
            .order_by(AcademicYear.start_date.desc())
            .first()
        )
        if not self.year:
            raise SystemExit("No active academic year — run seed_school.py first.")
        self.classes = (
            Class.query.filter_by(tenant_id=tenant_id, academic_year_id=self.year.id)
            .all()
        )
        if not self.classes:
            raise SystemExit("No classes for the active year — run seed_school.py first.")
        self.subjects = Subject.query.filter_by(tenant_id=tenant_id).all()
        self.subject_by_code = {s.code: s for s in self.subjects}

    @property
    def leave_year(self) -> str:
        """Leave balances key on the Apr-Mar label ("2026-27"), not the AY name."""
        from modules.teachers.constraint_services import get_current_academic_year

        return get_current_academic_year()


def grade_seq(cls) -> int:
    return cls.grade.sequence if cls.grade else 0


def class_label(cls) -> str:
    grade_name = cls.grade.name if cls.grade else (cls.name or "?")
    prog = cls.programme.code if cls.programme else "?"
    return f"{prog} Std {grade_name}-{cls.section}"


# --------------------------------------------------------------------------- #
# Stage 1: departments, staff, teaching assignments
# --------------------------------------------------------------------------- #

# Academic divisions (NOT subject groupings) — see .claude/memory/modules/
# school_structure.md. Each covers a grade band.
# Bands are keyed on a grade's `sequence`, not its name. This school runs
# Nursery/LKG/UKG at sequences 1-3, so Std 1 is sequence 4 and Std 12 is 15.
DEPARTMENTS = [
    ("Pre-Primary", "PRE", "Nursery to UKG", 1, (1, 3)),
    ("Primary", "PRI", "Std 1 to 5", 2, (4, 8)),
    ("Middle School", "MID", "Std 6 to 8", 3, (9, 11)),
    ("Secondary", "SEC", "Std 9 to 10", 4, (12, 13)),
    ("Higher Secondary", "HSC", "Std 11 to 12", 5, (14, 15)),
]

# Every class needs its own primary teacher, and a school needs more teachers
# than it has classes. The hand-written roster below covers a small school; a
# trust running 65 sections is topped up to these totals per band.
TEACHERS_PER_BAND = {"PRE": 12, "PRI": 26, "MID": 16, "SEC": 11, "HSC": 22}

# Subjects a generated teacher of each band is qualified for. Real codes only —
# an expertise entry for a subject the school does not teach is never read.
BAND_SUBJECTS = {
    "PRE": [["ACT", "ART"], ["GUJ", "ACT"], ["ENG", "ART"], ["MATH", "ACT"]],
    "PRI": [["GUJ", "EVS"], ["ENG", "EVS"], ["MATH", "EVS"], ["HIN", "GUJ"],
            ["PE", "ART"]],
    "MID": [["MATH", "SCI"], ["ENG", "SS"], ["GUJ", "SS"], ["SCI", "MATH"],
            ["HIN", "SAN"]],
    "SEC": [["MATH", "SCI"], ["ENG", "SS"], ["SCI", "MATH"], ["GUJ", "HIN"],
            ["SS", "ENG"]],
    "HSC": [["PHY", "MATH"], ["CHEM", "PHY"], ["BIO", "CHEM"], ["ACC", "BST"],
            ["ECO", "STAT"], ["HIST", "POL"], ["ENG", "PSY"], ["GEO", "SOC"]],
}

BAND_DESIGNATIONS = ["Teacher", "Senior Teacher", "Assistant Teacher"]
BAND_QUALIFICATIONS = ["B.Ed", "M.Ed", "M.A, B.Ed", "M.Sc, B.Ed", "B.A, B.Ed"]


def _extend_roster(base: list, rng) -> list:
    """Top the hand-written roster up to a staffing level this school needs.

    Returns `base` plus generated specs in the same 8-tuple shape, so every
    downstream `zip(teachers, roster)` stays aligned.
    """
    roster = list(base)
    have = {}
    for spec in base:
        have[spec[1]] = have.get(spec[1], 0) + 1

    # A teacher's login is derived from their name, so two teachers sharing one
    # would share an account. Middle initials keep them apart, as they do on a
    # real staff list.
    used_names = {spec[0] for spec in base}

    def _unique_name(first: str, surname: str) -> str:
        candidate = f"{first} {surname}"
        for initial in "ABCDEFGHIJKLMNOPRSTVY":
            if candidate not in used_names:
                break
            candidate = f"{first} {initial} {surname}"
        used_names.add(candidate)
        return candidate

    for band, target in TEACHERS_PER_BAND.items():
        subject_sets = BAND_SUBJECTS[band]
        for n in range(target - have.get(band, 0)):
            is_woman = rng.random() < 0.6
            first = rng.choice(GIRL_NAMES if is_woman else BOY_NAMES)
            surname = rng.choice(SURNAMES)
            subjects = subject_sets[n % len(subject_sets)]
            roster.append((
                _unique_name(first, surname),
                band,
                rng.choice(BAND_DESIGNATIONS),
                rng.choice(BAND_QUALIFICATIONS),
                f"{subjects[0].title()} Teaching",
                rng.randint(2, 24),
                subjects,
                "active",
            ))
    return roster

# (name, dept_code, designation, qualification, specialization, experience,
#  [subject codes they can teach], status)
TEACHERS = [
    # --- Primary: generalists, each owns a class and teaches most of its subjects
    ("Ramesh Patel",     "PRI", "Head Teacher",     "M.Ed",        "Primary Pedagogy",     22, ["GUJ", "EVS", "MATH"],        "active"),
    ("Nilamben Shah",    "PRI", "Senior Teacher",   "B.Ed",        "Early Literacy",       15, ["GUJ", "EVS"],                "active"),
    ("Kalpesh Desai",    "PRI", "Teacher",          "B.Ed",        "Primary Mathematics",   9, ["MATH", "EVS"],               "active"),
    ("Hetal Trivedi",    "PRI", "Teacher",          "B.Ed",        "Primary English",       7, ["ENG", "GUJ"],                "active"),
    ("Mehul Joshi",      "PRI", "Teacher",          "B.Ed",        "Environmental Studies", 6, ["EVS", "MATH"],               "active"),
    ("Bhavna Mehta",     "PRI", "Teacher",          "B.Ed",        "Primary English",      11, ["ENG", "EVS"],                "active"),
    ("Dipak Chauhan",    "PRI", "Assistant Teacher","B.A, B.Ed",   "Gujarati Language",     4, ["GUJ", "ART"],                "active"),
    ("Rekha Solanki",    "PRI", "Teacher",          "B.Ed",        "Primary Mathematics",   8, ["MATH", "ENG"],               "active"),
    ("Jignesh Bhatt",    "PRI", "Teacher",          "B.P.Ed",      "Physical Education",   10, ["PE", "ART"],                 "active"),
    ("Payal Rana",       "PRI", "Teacher",          "B.Ed",        "Creative Arts",         5, ["ART", "EVS"],                "active"),
    ("Sanjay Vyas",      "PRI", "Teacher",          "B.Ed",        "Primary Gujarati",     13, ["GUJ", "MATH"],               "active"),
    ("Kiran Modi",       "PRI", "Assistant Teacher","B.Ed",        "Primary English",       3, ["ENG", "ART"],                "active"),
    ("Ashaben Pandya",   "PRI", "Teacher",          "M.A, B.Ed",   "Hindi Language",       12, ["HIN", "GUJ"],                "active"),
    ("Vipul Gohil",      "PRI", "Teacher",          "B.Ed",        "Primary Science",       6, ["EVS", "MATH"],               "inactive"),

    # --- Middle School: catalogue depth, no classes at this grade band yet
    ("Falguni Amin",     "MID", "HOD",              "M.Sc, B.Ed",  "Mathematics",          16, ["MATH", "SCI"],               "active"),
    ("Rajesh Thakkar",   "MID", "Senior Teacher",   "M.A, B.Ed",   "Social Science",       14, ["SST", "GUJ"],                "active"),

    # --- Secondary: subject specialists for Std 9-10
    ("Anil Dave",        "SEC", "HOD",              "M.Sc, B.Ed",  "Physics & Chemistry",  19, ["SCI", "MATH-STD"],           "active"),
    ("Snehal Parikh",    "SEC", "Senior Teacher",   "M.A, B.Ed",   "English Literature",   12, ["ENG-LL", "ENG"],             "active"),
    ("Nitin Raval",      "SEC", "Teacher",          "M.Sc, B.Ed",  "Standard Mathematics", 10, ["MATH-STD", "MATH-BAS"],      "active"),
    ("Meena Kapadia",    "SEC", "Teacher",          "M.A, B.Ed",   "Social Science",        9, ["SST", "HIN"],                "active"),
    ("Paresh Bhavsar",   "SEC", "Teacher",          "M.Sc, B.Ed",  "Biology",               8, ["SCI", "PE"],                 "active"),
    ("Urvashi Nayak",    "SEC", "Teacher",          "M.A",         "Sanskrit",              7, ["SAN", "HIN"],                "active"),
    ("Tushar Limbachiya","SEC", "Assistant Teacher","B.Sc, B.Ed",  "Basic Mathematics",     3, ["MATH-BAS", "SCI"],           "active"),
    ("Hina Qureshi",     "SEC", "Teacher",          "M.A, B.Ed",   "English Literature",    6, ["ENG-LL", "SST"],             "active"),

    # --- Higher Secondary: staffed ahead of the Std 11-12 classes opening
    ("Bharat Chokshi",   "HSC", "HOD",              "M.Sc, M.Phil","Physics",              21, ["SCI", "MATH-STD"],           "active"),
]


def stage_teachers(ctx: Ctx) -> None:
    from modules.academics.backbone.models import ClassSubjectTeacher, ClassTeacherAssignment
    from modules.auth.models import User
    from modules.academics.backbone.models import ClassTeacherAssignment
    from modules.classes.models import ClassSubject, SubjectLoad
    from modules.departments.models import Department
    from modules.mediums.models import Medium
    from modules.people.employment import Staff
    from modules.people.service import (
        employ,
        employment_status_for_legacy_flag,
        fill_blank_identity,
    )
    from modules.rbac.authority_service import grant_authority
    from modules.rbac.models import Role
    from modules.teachers.models import Teacher, TeacherSubject

    tid = ctx.tenant_id
    rng = random.Random(SEED)

    # -- departments ---------------------------------------------------------
    dept_by_code: dict[str, Department] = {}
    for name, code, desc, order, _band in DEPARTMENTS:
        dept = Department.query.filter_by(tenant_id=tid, code=code).first()
        if not dept:
            dept = Department(
                id=str(uuid.uuid4()),
                tenant_id=tid,
                name=name,
                code=code,
                description=desc,
                display_order=order,
                type="academic_division",
                status="active",
            )
            db.session.add(dept)
        dept_by_code[code] = dept
    db.session.flush()
    log(f"departments: {len(dept_by_code)}")

    # -- backfill class.medium_id / department_id ----------------------------
    # bulk_generate_classes sets unit/programme/grade but not these two.
    mediums = {m.name: m for m in Medium.query.filter_by(tenant_id=tid).all()}
    band_for = {}
    for _n, code, _d, _o, (lo, hi) in DEPARTMENTS:
        for seq in range(lo, hi + 1):
            band_for[seq] = code
    for cls in ctx.classes:
        if cls.programme and cls.programme.medium in mediums:
            cls.medium_id = mediums[cls.programme.medium].id
        dept_code = band_for.get(grade_seq(cls))
        if dept_code:
            cls.department_id = dept_by_code[dept_code].id
    db.session.flush()
    log(f"classes backfilled with medium_id + department_id: {len(ctx.classes)}")

    # -- staff users + teacher profiles --------------------------------------
    teacher_role = Role.query.filter_by(tenant_id=tid, name="Teacher").first()
    if not teacher_role:
        raise SystemExit("Teacher role missing — run scripts/seed_rbac.py first.")
    pw_hash = generate_password_hash(TEACHER_PASSWORD)

    teachers: list[Teacher] = []
    roster = _extend_roster(TEACHERS, rng)
    for idx, (name, dept_code, designation, qual, spec, exp, subject_codes, status) in enumerate(
        roster, start=1
    ):
        employee_id = f"EMP{idx:03d}"
        teacher = (
            Teacher.query.join(Staff, Teacher.staff_id == Staff.id)
            .filter(Teacher.tenant_id == tid, Staff.employee_number == employee_id)
            .first()
        )
        if teacher:
            teachers.append(teacher)
            continue

        local = name.lower().replace(" ", ".").replace(",", "")
        email = f"{local}@nexchool.in"
        user = User.query.filter_by(tenant_id=tid, email=email).first()
        if not user:
            user = User(
                id=str(uuid.uuid4()),
                tenant_id=tid,
                email=email,
                name=name,
                password_hash=pw_hash,
                email_verified=True,
            )
            db.session.add(user)
            db.session.flush()

        joined_on = date(2026, 6, 1) - timedelta(days=365 * exp + rng.randint(0, 200))

        # A teacher is an employed person who teaches (ADR-005): employment is
        # the Staff relationship, teaching hangs off it.
        staff = employ(
            tid,
            user.person_id,
            employee_number=employee_id,
            designation=designation,
            department_id=dept_by_code[dept_code].id,
            employment_status=employment_status_for_legacy_flag(status),
            joined_on=joined_on,
        )
        # Authority is held by a current employment (ADR-013): a teacher who
        # has left holds none, which is the point of putting it there.
        if staff.is_employed:
            grant_authority(staff.id, teacher_role.id)

        # How to reach them belongs to the person (ADR-001); the employment
        # facts went to Staff via employ() above.
        fill_blank_identity(
            staff.person,
            {
                "phone_number": f"9{rng.randint(700000000, 899999999)}",
                "address": f"{rng.randint(1, 90)}, "
                           f"{rng.choice(['Shivalik', 'Satyam', 'Ravi', 'Gokul'])} Society, "
                           f"{rng.choice(['Maninagar', 'Naranpura', 'Bopal', 'Vastrapur'])}, Ahmedabad",
            },
        )

        teacher = Teacher(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            user_id=user.id,
            staff_id=staff.id,
            qualification=qual,
            specialization=spec,
            experience_years=exp,
        )
        db.session.add(teacher)
        db.session.flush()
        teachers.append(teacher)

        for code in subject_codes:
            subject = ctx.subject_by_code.get(code)
            if subject:
                db.session.add(
                    TeacherSubject(
                        id=str(uuid.uuid4()),
                        tenant_id=tid,
                        teacher_id=teacher.id,
                        subject_id=subject.id,
                    )
                )
    db.session.commit()
    log(f"teachers: {len(teachers)} (with user logins, roles and subject expertise)")

    # -- expertise index: subject code -> teachers who can teach it -----------
    by_subject: dict[str, list[Teacher]] = {}
    for teacher, (_n, _d, _des, _q, _s, _e, subject_codes, status) in zip(teachers, roster):
        if status != "active":
            continue
        for code in subject_codes:
            by_subject.setdefault(code, []).append(teacher)

    # -- class teachers ------------------------------------------------------
    # One primary class teacher per class, drawn from the matching department so
    # a Std 3 class is owned by a Primary teacher, not a Secondary specialist.
    active_by_dept: dict[str, list[Teacher]] = {}
    for teacher, (_n, dept_code, _des, _q, _s, _e, _sc, status) in zip(teachers, roster):
        if status == "active":
            active_by_dept.setdefault(dept_code, []).append(teacher)

    used: set[str] = set()
    # A total order. Grade+section alone ties whenever two campuses or two
    # programmes run the same section letter, and the tie broke differently on
    # each run — so a re-run handed a class to a teacher who already owned
    # another one, which `uq_classes_teacher_id_tenant` refuses.
    ordered = sorted(
        ctx.classes,
        key=lambda c: (grade_seq(c), c.school_unit_id or "", c.programme.code, c.section),
    )
    primary_of: dict[str, Teacher] = {}
    for cls in ordered:
        dept_code = band_for.get(grade_seq(cls), "PRI")
        pool = [t for t in active_by_dept.get(dept_code, []) if t.id not in used]
        if not pool:  # band exhausted — fall back to any unused active teacher
            # Employment lives on Staff (ADR-005); a Teacher has no status of
            # its own. Only a currently employed teacher can own a class.
            pool = [
                t for t in teachers
                if t.id not in used and t.staff is not None and t.staff.is_employed
            ]
        owner = pool[0]
        used.add(owner.id)
        primary_of[cls.id] = owner

        if not ClassTeacherAssignment.query.filter_by(
            tenant_id=tid, class_id=cls.id, role="primary", is_active=True
        ).first():
            db.session.add(
                ClassTeacherAssignment(
                    id=str(uuid.uuid4()),
                    tenant_id=tid,
                    class_id=cls.id,
                    teacher_id=owner.id,
                    role="primary",
                    allow_attendance_marking=True,
                    effective_from=ctx.year.start_date,
                    is_active=True,
                )
            )
        # Legacy pointer still read by older APIs. FK points at `teachers`,
        # so this is the Teacher id -- not the user id it used to hold.
        cls.teacher_id = owner.id

    # An assistant on the two largest wings, so the assistant role is exercised.
    for cls in ordered[:4]:
        dept_code = band_for.get(grade_seq(cls), "PRI")
        candidates = [
            t for t in active_by_dept.get(dept_code, []) if t.id != primary_of[cls.id].id
        ]
        if not candidates:
            continue
        assistant = candidates[grade_seq(cls) % len(candidates)]
        exists = ClassTeacherAssignment.query.filter_by(
            tenant_id=tid, class_id=cls.id, teacher_id=assistant.id, role="assistant"
        ).first()
        if not exists:
            db.session.add(
                ClassTeacherAssignment(
                    id=str(uuid.uuid4()),
                    tenant_id=tid,
                    class_id=cls.id,
                    teacher_id=assistant.id,
                    role="assistant",
                    allow_attendance_marking=True,
                    effective_from=ctx.year.start_date,
                    is_active=True,
                )
            )
    db.session.commit()
    log(f"class teacher assignments: {len(ordered)} primary + assistants on 4 classes")

    # -- subject teachers per class_subject ----------------------------------
    # Round-robin within the set of teachers who actually list that subject, so
    # load spreads instead of piling onto the first match.
    cursor: dict[str, int] = {}
    cst_created = 0
    load_created = 0

    class_subjects = (
        ClassSubject.query.filter(
            ClassSubject.tenant_id == tid,
            ClassSubject.class_id.in_([c.id for c in ctx.classes]),
            ClassSubject.deleted_at.is_(None),
        ).all()
    )
    subject_by_id = {s.id: s for s in ctx.subjects}

    for cs in sorted(class_subjects, key=lambda x: (x.class_id, x.sort_order or 0)):
        subject = subject_by_id.get(cs.subject_id)
        if not subject:
            continue
        pool = by_subject.get(subject.code) or []
        if not pool:
            # nobody lists this subject — give it to the class teacher
            pool = [primary_of[cs.class_id]]
        i = cursor.get(subject.code, 0)
        teacher = pool[i % len(pool)]
        cursor[subject.code] = i + 1

        if not ClassSubjectTeacher.query.filter_by(
            tenant_id=tid, class_subject_id=cs.id, role="primary", is_active=True
        ).first():
            db.session.add(
                ClassSubjectTeacher(
                    id=str(uuid.uuid4()),
                    tenant_id=tid,
                    class_subject_id=cs.id,
                    teacher_id=teacher.id,
                    role="primary",
                    effective_from=ctx.year.start_date,
                    is_active=True,
                )
            )
            cst_created += 1

        # weekly period load mirrors the offering
        if not SubjectLoad.query.filter_by(
            tenant_id=tid, class_id=cs.class_id, subject_id=cs.subject_id
        ).first():
            db.session.add(
                SubjectLoad(
                    id=str(uuid.uuid4()),
                    tenant_id=tid,
                    class_id=cs.class_id,
                    subject_id=cs.subject_id,
                    weekly_periods=int(cs.weekly_periods or 5),
                )
            )
            load_created += 1

    # Who is responsible for each class, recorded where that is owned.
    ct_rows = 0
    for cls in ordered:
        owner = primary_of[cls.id]
        if ClassTeacherAssignment.query.filter_by(
            tenant_id=tid, class_id=cls.id, teacher_id=owner.id, is_active=True
        ).first():
            continue
        ct_rows += 1
        db.session.add(
            ClassTeacherAssignment(
                id=str(uuid.uuid4()),
                tenant_id=tid,
                class_id=cls.id,
                teacher_id=owner.id,
                role="primary",
                is_active=True,
            )
        )
        # The cache follows the owner. FK points at `teachers`, so this is the
        # Teacher id -- not the user id it used to hold.
        cls.teacher_id = owner.id
        db.session.add(cls)

    db.session.commit()
    log(f"class_subject_teachers: {cst_created} primary assignments")
    log(f"class_teachers rows: {ct_rows} · subject_load rows: {load_created}")


# --------------------------------------------------------------------------- #
# Stage 2: availability, workload rules, bell schedule, timetable
# --------------------------------------------------------------------------- #

# period_number -> (kind, start, end, label). 8 teaching periods + one recess.
BELL_PERIODS = [
    (1, "lesson", time(7, 45),  time(8, 30),  "Period 1"),
    (2, "lesson", time(8, 30),  time(9, 15),  "Period 2"),
    (3, "lesson", time(9, 15),  time(10, 0),  "Period 3"),
    (4, "break",  time(10, 0),  time(10, 20), "Recess"),
    (5, "lesson", time(10, 20), time(11, 5),  "Period 4"),
    (6, "lesson", time(11, 5),  time(11, 50), "Period 5"),
    (7, "lesson", time(11, 50), time(12, 35), "Period 6"),
    (8, "lesson", time(12, 35), time(13, 20), "Period 7"),
    (9, "lesson", time(13, 20), time(14, 5),  "Period 8"),
]
LESSON_PERIODS = [p for p, kind, *_ in BELL_PERIODS if kind == "lesson"]
SCHOOL_DAYS = [1, 2, 3, 4, 5]  # Mon-Fri

# Teachers who are genuinely not available for parts of the week. Anything not
# listed here has no availability row at all, which the model reads as "free".
UNAVAILABILITY = {
    "Ashaben Pandya": [(5, p) for p in LESSON_PERIODS],           # off on Fridays
    "Kiran Modi":     [(d, p) for d in SCHOOL_DAYS for p in (8, 9)],  # leaves after Period 6
    "Urvashi Nayak":  [(1, 1), (1, 2), (3, 1), (3, 2)],           # late start Mon & Wed
    "Dipak Chauhan":  [(2, 9), (4, 9)],
}

# designation -> (max periods/day, max periods/week)
WORKLOAD_BY_DESIGNATION = {
    "HOD": (4, 20),
    "Head Teacher": (4, 18),
    "Senior Teacher": (5, 26),
    "Teacher": (6, 30),
    "Assistant Teacher": (5, 24),
}


def stage_timetable(ctx: Ctx) -> None:
    from modules.academics.backbone.models import (
        BellSchedule,
        BellSchedulePeriod,
        ClassSubjectTeacher,
        TimetableEntry,
        TimetableVersion,
    )
    from modules.classes.models import ClassSubject
    from modules.teachers.models import Teacher, TeacherAvailability, TeacherWorkloadRule

    tid = ctx.tenant_id
    teachers = Teacher.query.filter_by(tenant_id=tid).all()
    by_name = {t.user.name: t for t in teachers if t.user}

    # -- bell schedule -------------------------------------------------------
    bell = BellSchedule.query.filter_by(
        tenant_id=tid, academic_year_id=ctx.year.id, is_default=True
    ).first()
    if not bell:
        bell = BellSchedule(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            name="Standard Day",
            academic_year_id=ctx.year.id,
            is_default=True,
            valid_from=ctx.year.start_date,
            valid_to=ctx.year.end_date,
        )
        db.session.add(bell)
        db.session.flush()
        for number, kind, starts, ends, label in BELL_PERIODS:
            db.session.add(
                BellSchedulePeriod(
                    id=str(uuid.uuid4()),
                    tenant_id=tid,
                    bell_schedule_id=bell.id,
                    period_number=number,
                    period_kind=kind,
                    starts_at=starts,
                    ends_at=ends,
                    label=label,
                    sort_order=number,
                )
            )
        db.session.flush()
    period_times = {n: (s, e) for n, _k, s, e, _l in BELL_PERIODS}
    log(f"bell schedule: '{bell.name}' with {len(BELL_PERIODS)} periods "
        f"({len(LESSON_PERIODS)} teaching)")

    # -- workload rules ------------------------------------------------------
    caps: dict[str, tuple[int, int]] = {}
    made = 0
    for teacher in teachers:
        per_day, per_week = WORKLOAD_BY_DESIGNATION.get(
            (teacher.staff.designation if teacher.staff else "") or "", (6, 30)
        )
        caps[teacher.id] = (per_day, per_week)
        if not TeacherWorkloadRule.query.filter_by(teacher_id=teacher.id).first():
            db.session.add(
                TeacherWorkloadRule(
                    id=str(uuid.uuid4()),
                    tenant_id=tid,
                    teacher_id=teacher.id,
                    max_periods_per_day=per_day,
                    max_periods_per_week=per_week,
                )
            )
            made += 1
    log(f"workload rules: {made} created (by designation)")

    # -- availability --------------------------------------------------------
    blocked: dict[str, set[tuple[int, int]]] = {}
    rows = 0
    for name, slots in UNAVAILABILITY.items():
        teacher = by_name.get(name)
        if not teacher:
            continue
        blocked[teacher.id] = set(slots)
        for day, period in slots:
            exists = TeacherAvailability.query.filter_by(
                teacher_id=teacher.id, day_of_week=day, period_number=period
            ).first()
            if not exists:
                db.session.add(
                    TeacherAvailability(
                        id=str(uuid.uuid4()),
                        tenant_id=tid,
                        teacher_id=teacher.id,
                        day_of_week=day,
                        period_number=period,
                        available=False,
                    )
                )
                rows += 1
    db.session.commit()
    log(f"teacher availability: {rows} blocked slots across {len(blocked)} teachers")

    # -- who teaches what ----------------------------------------------------
    class_subjects = ClassSubject.query.filter(
        ClassSubject.tenant_id == tid,
        ClassSubject.class_id.in_([c.id for c in ctx.classes]),
        ClassSubject.deleted_at.is_(None),
    ).all()
    teacher_of_cs = {
        cst.class_subject_id: cst.teacher_id
        for cst in ClassSubjectTeacher.query.filter_by(
            tenant_id=tid, role="primary", is_active=True
        ).all()
    }
    cs_by_class: dict[str, list] = {}
    for cs in class_subjects:
        cs_by_class.setdefault(cs.class_id, []).append(cs)

    # -- versions ------------------------------------------------------------
    version_of: dict[str, TimetableVersion] = {}
    for cls in ctx.classes:
        version = TimetableVersion.query.filter_by(
            tenant_id=tid, class_id=cls.id, status="active"
        ).first()
        if not version:
            version = TimetableVersion(
                id=str(uuid.uuid4()),
                tenant_id=tid,
                class_id=cls.id,
                bell_schedule_id=bell.id,
                label=f"{ctx.year.name} — {class_label(cls)}",
                status="active",
                effective_from=ctx.year.start_date,
                effective_to=ctx.year.end_date,
            )
            db.session.add(version)
        version_of[cls.id] = version
    db.session.flush()

    # -- greedy scheduler ----------------------------------------------------
    # Constraints honoured: one subject per class per cell, a teacher is never
    # double-booked, never scheduled into a blocked slot, and never over their
    # per-day / per-week cap. Subjects spread across days before doubling up.
    class_cell: set[tuple[str, int, int]] = set()       # (class_id, day, period)
    teacher_cell: set[tuple[str, int, int]] = set()     # (teacher_id, day, period)
    per_day_count: dict[tuple[str, int], int] = {}      # (teacher_id, day) -> n
    per_week_count: dict[str, int] = {}                 # teacher_id -> n
    subject_day: dict[tuple[str, int, str], int] = {}   # (class_id, day, subject_id)

    existing = TimetableEntry.query.filter(
        TimetableEntry.tenant_id == tid,
        TimetableEntry.timetable_version_id.in_([v.id for v in version_of.values()]),
    ).count()
    if existing:
        log(f"timetable entries already present ({existing}) — skipping scheduler")
        db.session.commit()
        return

    placed = 0

    def try_place(cls, cs, teacher_id, offset: int, allow_double: bool) -> bool:
        """Place one period for this offering, or report that nothing fits."""
        nonlocal placed
        days = SCHOOL_DAYS[offset % len(SCHOOL_DAYS):] + SCHOOL_DAYS[: offset % len(SCHOOL_DAYS)]
        shift = offset % len(LESSON_PERIODS)
        periods = LESSON_PERIODS[shift:] + LESSON_PERIODS[:shift]
        for day in days:
            for period in periods:
                if (cls.id, day, period) in class_cell:
                    continue
                if not allow_double and subject_day.get((cls.id, day, cs.subject_id), 0):
                    continue
                if teacher_id:
                    if (teacher_id, day, period) in teacher_cell:
                        continue
                    if (day, period) in blocked.get(teacher_id, ()):
                        continue
                    max_day, max_week = caps.get(teacher_id, (6, 30))
                    if per_day_count.get((teacher_id, day), 0) >= max_day:
                        continue
                    if per_week_count.get(teacher_id, 0) >= max_week:
                        continue

                db.session.add(
                    TimetableEntry(
                        id=str(uuid.uuid4()),
                        tenant_id=tid,
                        timetable_version_id=version_of[cls.id].id,
                        class_subject_id=cs.id,
                        teacher_id=teacher_id,
                        day_of_week=day,
                        period_number=period,
                        room=f"R{grade_seq(cls):02d}{cls.section}",
                        # "active" is the only status any reader recognises;
                        # seeding "scheduled" hid 90% of the demo timetable
                        # from every dashboard and from /api/schedule/today.
                        entry_status="active",
                    )
                )
                class_cell.add((cls.id, day, period))
                subject_day[(cls.id, day, cs.subject_id)] = (
                    subject_day.get((cls.id, day, cs.subject_id), 0) + 1
                )
                if teacher_id:
                    teacher_cell.add((teacher_id, day, period))
                    per_day_count[(teacher_id, day)] = per_day_count.get((teacher_id, day), 0) + 1
                    per_week_count[teacher_id] = per_week_count.get(teacher_id, 0) + 1
                placed += 1
                return True
        return False

    # Round-robin across every offering rather than finishing one class at a
    # time: filling class-by-class lets the classes scheduled first consume all
    # of a shared teacher's capacity, which left whole subjects on zero periods.
    demand = []
    for cls in ctx.classes:
        for cs in cs_by_class.get(cls.id, []):
            demand.append([cls, cs, teacher_of_cs.get(cs.id), int(cs.weekly_periods or 0), 0])

    for allow_double in (False, True):
        progress = True
        while progress:
            progress = False
            for item in demand:
                cls, cs, teacher_id, need, got = item
                if got >= need:
                    continue
                if try_place(cls, cs, teacher_id, got + grade_seq(cls), allow_double):
                    item[4] += 1
                    progress = True

    shortfall = [
        f"{class_label(cls)} {cs.subject_ref.code if cs.subject_ref else '?'}: {got}/{need}"
        for cls, cs, _t, need, got in demand
        if got < need
    ]

    db.session.commit()
    log(f"timetable: {len(version_of)} active versions, {placed} entries placed")
    if shortfall:
        log(f"unfilled periods ({len(shortfall)}): {'; '.join(shortfall[:6])}"
            + (" …" if len(shortfall) > 6 else ""))


# --------------------------------------------------------------------------- #
# Stage 3: calendar (holidays) — leave working_days depend on these
# --------------------------------------------------------------------------- #

# (name, type, start, end, description). Saturday + Sunday are added separately
# as recurring weekly offs so the calendar matches the Mon-Fri timetable.
HOLIDAYS = [
    ("Independence Day",   "national", date(2026, 8, 15),  date(2026, 8, 15),  None),
    ("Janmashtami",        "regional", date(2026, 9, 4),   date(2026, 9, 4),   None),
    ("Gandhi Jayanti",     "national", date(2026, 10, 2),  date(2026, 10, 2),  None),
    ("Navratri Break",     "vacation", date(2026, 10, 12), date(2026, 10, 16), "Garba holidays"),
    ("Diwali Vacation",    "vacation", date(2026, 11, 5),  date(2026, 11, 20), "Diwali and New Year break"),
    ("Christmas",          "public",   date(2026, 12, 25), date(2026, 12, 25), None),
    ("Uttarayan",          "regional", date(2027, 1, 14),  date(2027, 1, 15),  "Kite festival"),
    ("Republic Day",       "national", date(2027, 1, 26),  date(2027, 1, 26),  None),
    ("Mahashivratri",      "regional", date(2027, 3, 6),   date(2027, 3, 6),   None),
    ("Dhuleti",            "regional", date(2027, 3, 22),  date(2027, 3, 22),  None),
]


def stage_calendar(ctx: Ctx) -> None:
    from modules.academics.calendar.holidays import Holiday

    tid = ctx.tenant_id
    created = 0
    for name, htype, start, end, desc in HOLIDAYS:
        if Holiday.query.filter_by(tenant_id=tid, name=name, start_date=start).first():
            continue
        db.session.add(
            Holiday(
                id=str(uuid.uuid4()),
                tenant_id=tid,
                name=name,
                description=desc,
                holiday_type=htype,
                start_date=start,
                end_date=end,
                is_recurring=False,
                academic_year_id=ctx.year.id,
                applies_to="entire_school",
            )
        )
        created += 1

    # weekly offs: Python weekday numbering, 5=Saturday, 6=Sunday
    for label, dow in (("Saturday Off", 5), ("Sunday Off", 6)):
        if Holiday.query.filter_by(tenant_id=tid, name=label).first():
            continue
        db.session.add(
            Holiday(
                id=str(uuid.uuid4()),
                tenant_id=tid,
                name=label,
                holiday_type="weekly_off",
                is_recurring=True,
                recurring_day_of_week=dow,
                academic_year_id=ctx.year.id,
                applies_to="entire_school",
            )
        )
        created += 1
    db.session.commit()
    log(f"holidays: {created} created ({len(HOLIDAYS)} dated + 2 weekly offs)")


def holiday_dates(ctx: Ctx) -> set[date]:
    """Dated (non-recurring) holidays, expanded to every day they cover."""
    from modules.academics.calendar.holidays import Holiday

    out: set[date] = set()
    rows = Holiday.query.filter_by(tenant_id=ctx.tenant_id, is_recurring=False).all()
    for row in rows:
        if not row.start_date:
            continue
        end = row.end_date or row.start_date
        day = row.start_date
        while day <= end:
            out.add(day)
            day += timedelta(days=1)
    return out


def working_days_between(start: date, end: date, holidays: set[date]) -> float:
    """Mon-Fri days in the range that are not dated holidays."""
    total = 0
    day = start
    while day <= end:
        if day.weekday() < 5 and day not in holidays:
            total += 1
        day += timedelta(days=1)
    return float(total)


# --------------------------------------------------------------------------- #
# Stage 4: leave policies, balances and requests
# --------------------------------------------------------------------------- #

# (teacher name, leave_type, start, end, status, reason)
LEAVES = [
    # --- approved, already consumed
    ("Ramesh Patel",     "casual",    date(2026, 6, 15), date(2026, 6, 16), "approved", "Family function"),
    ("Nilamben Shah",    "sick",      date(2026, 6, 22), date(2026, 6, 24), "approved", "Viral fever"),
    ("Kalpesh Desai",    "casual",    date(2026, 7, 2),  date(2026, 7, 2),  "approved", "Personal work"),
    ("Hetal Trivedi",    "sick",      date(2026, 7, 8),  date(2026, 7, 9),  "approved", "Dental surgery"),
    ("Anil Dave",        "casual",    date(2026, 7, 13), date(2026, 7, 14), "approved", "Out of town"),
    ("Snehal Parikh",    "emergency", date(2026, 7, 20), date(2026, 7, 20), "approved", "Family emergency"),
    ("Meena Kapadia",    "sick",      date(2026, 7, 23), date(2026, 7, 27), "approved", "Post-operative rest"),
    ("Bhavna Mehta",     "casual",    date(2026, 6, 29), date(2026, 6, 29), "approved", "Personal work"),
    ("Nitin Raval",      "casual",    date(2026, 7, 30), date(2026, 7, 31), "approved", "Wedding in family"),
    ("Rajesh Thakkar",   "unpaid",    date(2026, 7, 6),  date(2026, 7, 10), "approved", "Extended personal leave"),
    ("Urvashi Nayak",    "sick",      date(2026, 6, 18), date(2026, 6, 18), "approved", "Migraine"),
    ("Payal Rana",       "casual",    date(2026, 7, 17), date(2026, 7, 17), "approved", "Personal work"),

    # --- pending, awaiting an admin decision (dated around "today")
    ("Rekha Solanki",    "casual",    date(2026, 8, 10), date(2026, 8, 11), "pending", "Family trip"),
    ("Mehul Joshi",      "sick",      date(2026, 8, 5),  date(2026, 8, 6),  "pending", "Not keeping well"),
    ("Dipak Chauhan",    "casual",    date(2026, 8, 17), date(2026, 8, 17), "pending", "Personal work"),
    ("Paresh Bhavsar",   "emergency", date(2026, 8, 4),  date(2026, 8, 4),  "pending", "Hospital visit"),
    ("Hina Qureshi",     "casual",    date(2026, 8, 20), date(2026, 8, 21), "pending", "Out of station"),
    ("Falguni Amin",     "sick",      date(2026, 8, 12), date(2026, 8, 14), "pending", "Medical rest advised"),

    # --- rejected
    ("Sanjay Vyas",      "casual",    date(2026, 7, 6),  date(2026, 7, 10), "rejected", "Long leave during exams"),
    ("Jignesh Bhatt",    "casual",    date(2026, 8, 3),  date(2026, 8, 7),  "rejected", "Clashes with sports day"),
    ("Tushar Limbachiya","other",     date(2026, 7, 15), date(2026, 7, 15), "rejected", "Insufficient notice"),

    # --- deliberately overlapping requests for one teacher (validation case)
    ("Ashaben Pandya",   "casual",    date(2026, 8, 24), date(2026, 8, 26), "pending", "Personal work"),
    ("Ashaben Pandya",   "sick",      date(2026, 8, 25), date(2026, 8, 27), "pending", "Overlaps the casual request"),
]


def stage_leaves(ctx: Ctx) -> None:
    from modules.teachers.models import (
        DEFAULT_POLICY_SETTINGS,
        LEAVE_TYPES,
        LeavePolicy,
        Teacher,
        TeacherLeave,
        TeacherLeaveBalance,
    )

    tid = ctx.tenant_id
    year_label = ctx.leave_year
    holidays = holiday_dates(ctx)
    rng = random.Random(SEED + 1)

    # -- policies ------------------------------------------------------------
    made = 0
    for leave_type in LEAVE_TYPES:
        if LeavePolicy.query.filter_by(tenant_id=tid, leave_type=leave_type).first():
            continue
        db.session.add(
            LeavePolicy(
                id=str(uuid.uuid4()),
                tenant_id=tid,
                leave_type=leave_type,
                **DEFAULT_POLICY_SETTINGS[leave_type],
            )
        )
        made += 1
    db.session.flush()
    log(f"leave policies: {made} created for {len(LEAVE_TYPES)} types")

    # -- leave requests ------------------------------------------------------
    teachers = Teacher.query.filter_by(tenant_id=tid).all()
    by_name = {t.user.name: t for t in teachers if t.user}
    used: dict[tuple[str, str], float] = {}
    pending: dict[tuple[str, str], float] = {}
    created = 0

    for name, leave_type, start, end, status, reason in LEAVES:
        teacher = by_name.get(name)
        if not teacher:
            continue
        days = working_days_between(start, end, holidays)
        exists = TeacherLeave.query.filter_by(
            tenant_id=tid, teacher_id=teacher.id, start_date=start, leave_type=leave_type
        ).first()
        if not exists:
            db.session.add(
                TeacherLeave(
                    id=str(uuid.uuid4()),
                    tenant_id=tid,
                    teacher_id=teacher.id,
                    start_date=start,
                    end_date=end,
                    leave_type=leave_type,
                    reason=reason,
                    status=status,
                    working_days=days,
                    academic_year=year_label,
                )
            )
            created += 1
        # a rejected request consumes nothing
        if status == "approved":
            used[(teacher.id, leave_type)] = used.get((teacher.id, leave_type), 0.0) + days
        elif status == "pending":
            pending[(teacher.id, leave_type)] = pending.get((teacher.id, leave_type), 0.0) + days
    db.session.flush()
    log(f"teacher leaves: {created} requests "
        f"({sum(1 for l in LEAVES if l[4]=='approved')} approved, "
        f"{sum(1 for l in LEAVES if l[4]=='pending')} pending, "
        f"{sum(1 for l in LEAVES if l[4]=='rejected')} rejected)")

    # -- balances, reconciled against the requests above ---------------------
    balances = 0
    for teacher in teachers:
        for leave_type in LEAVE_TYPES:
            policy = LeavePolicy.query.filter_by(tenant_id=tid, leave_type=leave_type).first()
            existing = TeacherLeaveBalance.query.filter_by(
                tenant_id=tid,
                teacher_id=teacher.id,
                leave_type=leave_type,
                academic_year=year_label,
            ).first()
            if existing:
                continue
            carried = 0
            if policy and policy.is_carry_forward_allowed and rng.random() < 0.4:
                carried = rng.randint(1, max(1, policy.max_carry_forward_days))
            db.session.add(
                TeacherLeaveBalance(
                    id=str(uuid.uuid4()),
                    tenant_id=tid,
                    teacher_id=teacher.id,
                    leave_type=leave_type,
                    academic_year=year_label,
                    allocated_days=policy.total_days if policy else 0,
                    used_days=used.get((teacher.id, leave_type), 0.0),
                    pending_days=pending.get((teacher.id, leave_type), 0.0),
                    carried_forward_days=carried,
                )
            )
            balances += 1
    db.session.commit()
    log(f"leave balances: {balances} rows for {len(teachers)} teachers, year {year_label}")


# --------------------------------------------------------------------------- #
# Stage 5: students and enrollments
# --------------------------------------------------------------------------- #
BOY_NAMES = [
    "Aarav", "Vivaan", "Aditya", "Vihaan", "Arjun", "Reyansh", "Krish", "Ishaan",
    "Dhruv", "Kabir", "Harsh", "Yash", "Jay", "Parth", "Rudra", "Manan", "Devansh",
    "Meet", "Naman", "Tirth", "Smit", "Jainil", "Hetav", "Rishi", "Aryan",
]
GIRL_NAMES = [
    "Aanya", "Diya", "Saanvi", "Aadhya", "Kiara", "Myra", "Anvi", "Riya", "Isha",
    "Khushi", "Nidhi", "Palak", "Shreya", "Vandana", "Krisha", "Jiya", "Heer",
    "Mahi", "Trisha", "Vanshika", "Aarohi", "Dhruvi", "Freya", "Netra", "Siya",
]
SURNAMES = [
    "Patel", "Shah", "Desai", "Trivedi", "Joshi", "Mehta", "Chauhan", "Solanki",
    "Bhatt", "Rana", "Vyas", "Modi", "Pandya", "Gohil", "Amin", "Thakkar", "Dave",
    "Parikh", "Raval", "Kapadia", "Bhavsar", "Nayak", "Jani", "Purohit", "Vaghela",
]
BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"]
RELIGIONS = ["Hindu", "Muslim", "Jain", "Christian", "Sikh"]
CATEGORIES = ["General", "OBC", "SC", "ST", "EWS"]
AREAS = ["Maninagar", "Naranpura", "Bopal", "Vastrapur", "Satellite", "Chandkheda", "Nikol"]
OCCUPATIONS = ["Business", "Service", "Doctor", "Engineer", "Teacher", "Farmer", "Shopkeeper"]

# Most students are active; the rest give the status filters something to show.
STATUS_MIX = (
    ["active"] * 92 + ["inactive"] * 2 + ["transferred"] * 3
    + ["leaving"] * 2 + ["suspended"] * 1
)


def stage_students(ctx: Ctx) -> None:
    from modules.academics.backbone.models import StudentClassEnrollment
    from modules.auth.models import User
    from modules.people.service import fill_blank_identity, record_family_member
    from modules.rbac.models import Role
    from modules.students.models import Student

    tid = ctx.tenant_id
    rng = random.Random(SEED + 2)

    student_role = Role.query.filter_by(tenant_id=tid, name="Student").first()
    if not student_role:
        raise SystemExit("Student role missing — run scripts/seed_rbac.py first.")
    pw_hash = generate_password_hash(STUDENT_PASSWORD)

    if Student.query.filter_by(tenant_id=tid).count():
        log("students already present — skipping")
        return

    # Section strengths a Gujarat trust of this size actually runs. Primary is
    # the fullest part of the school; Std 11-12 sections are small because each
    # stream splits the year group three ways.
    #
    # Grade sequence runs 1..15 here: Nursery/LKG/UKG are 1-3, Std 1-12 are
    # 4-15. Across the 65 sections this school opens it totals about 2,000.
    def strength(cls) -> int:
        seq = grade_seq(cls)
        if seq <= 3:                    # pre-primary
            return rng.randint(26, 34)
        if seq <= 11:                   # Std 1-8
            return rng.randint(33, 39)
        if seq <= 13:                   # Std 9-10
            return rng.randint(31, 37)
        return rng.randint(17, 23)      # Std 11-12, split by stream

    admission_no = 1
    total = 0
    ordered = sorted(ctx.classes, key=lambda c: (grade_seq(c), c.programme.code, c.section))

    for cls in ordered:
        count = strength(cls)
        # A Std N student is typically 5+N years old at the start of the year.
        birth_year = ctx.year.start_date.year - (grade_seq(cls) + 5)
        for roll in range(1, count + 1):
            is_boy = rng.random() < 0.52
            first = rng.choice(BOY_NAMES if is_boy else GIRL_NAMES)
            surname = rng.choice(SURNAMES)
            father = f"{rng.choice(BOY_NAMES)} {surname}"
            mother = f"{rng.choice(GIRL_NAMES)} {surname}"
            name = f"{first} {father.split()[0]} {surname}"  # given + father's + family
            email = f"{first.lower()}.{surname.lower()}{admission_no}@student.nexchool.in"
            area = rng.choice(AREAS)
            address = f"{rng.randint(1, 120)}, {rng.choice(['Shreeji', 'Umiya', 'Krishna', 'Swaminarayan'])} Residency, {area}, Ahmedabad"

            user = User(
                id=str(uuid.uuid4()),
                tenant_id=tid,
                email=email,
                name=name,
                password_hash=pw_hash,
                email_verified=True,
            )
            db.session.add(user)
            db.session.flush()

            status = rng.choice(STATUS_MIX)
            student = Student(
                id=str(uuid.uuid4()),
                tenant_id=tid,
                user_id=user.id,
                person_id=user.person_id,
                admission_number=f"NDS/2026/{admission_no:04d}",
                roll_number=roll,
                class_id=cls.id,
                academic_year=ctx.year.name,
                academic_year_id=ctx.year.id,
                blood_group=rng.choice(BLOOD_GROUPS),
                religion=rng.choice(RELIGIONS),
                category=rng.choice(CATEGORIES),
                nationality="Indian",
                mother_tongue="Gujarati" if cls.programme.code == "GSEB-GUJ" else "Gujarati",
                place_of_birth="Ahmedabad",
                father_name=father,
                father_phone=f"9{rng.randint(700000000, 899999999)}",
                father_occupation=rng.choice(OCCUPATIONS),
                father_annual_income=rng.randrange(180000, 1800000, 10000),
                mother_name=mother,
                mother_phone=f"9{rng.randint(700000000, 899999999)}",
                mother_occupation=rng.choice(["Homemaker"] + OCCUPATIONS),
                guardian_name=father,
                guardian_relationship="Father",
                guardian_phone=f"9{rng.randint(700000000, 899999999)}",
                guardian_email=f"{surname.lower()}.family{admission_no}@example.com",
                guardian_occupation=rng.choice(OCCUPATIONS),
                guardian_address=address,
                current_address=address,
                current_city="Ahmedabad",
                current_state="Gujarat",
                current_pincode=f"38{rng.randint(1000, 9999)}",
                permanent_address=address,
                permanent_city="Ahmedabad",
                permanent_state="Gujarat",
                permanent_pincode=f"38{rng.randint(1000, 9999)}",
                is_same_as_permanent_address=True,
                emergency_contact_name=mother,
                emergency_contact_relationship="Mother",
                emergency_contact_phone=f"9{rng.randint(700000000, 899999999)}",
                admission_date=date(ctx.year.start_date.year - (grade_seq(cls) - 1), 6, rng.randint(1, 20)),
                student_status=status,
                is_transport_opted=rng.random() < 0.35,
                house_name=rng.choice(["Ruby", "Emerald", "Sapphire", "Topaz"]),
            )
            # Who this student is belongs to their Person (ADR-001).
            fill_blank_identity(
                user.person,
                {
                    "date_of_birth": date(birth_year, rng.randint(1, 12), rng.randint(1, 28)),
                    "gender": "male" if is_boy else "female",
                    "phone_number": f"9{rng.randint(700000000, 899999999)}",
                    "address": address,
                },
            )

            # Admission records the household, not just the columns beside it.
            for member_name, relation, member_phone, is_contact in (
                (father, "father", f"9{rng.randint(700000000, 899999999)}", True),
                (mother, "mother", f"9{rng.randint(700000000, 899999999)}", False),
            ):
                record_family_member(
                    tid,
                    user.person_id,
                    name=member_name,
                    relationship=relation,
                    phone=member_phone,
                    is_primary_contact=is_contact,
                )

            db.session.add(student)
            db.session.flush()

            db.session.add(
                StudentClassEnrollment(
                    id=str(uuid.uuid4()),
                    tenant_id=tid,
                    student_id=student.id,
                    class_id=cls.id,
                    academic_year_id=ctx.year.id,
                    enrollment_status="active" if status == "active" else "transferred",
                    is_current=True,
                    started_on=ctx.year.start_date,
                )
            )
            admission_no += 1
            total += 1
        db.session.commit()
        log(f"{class_label(cls)}: {count} students")

    log(f"students: {total} across {len(ordered)} classes (with logins + enrollments)")


# --------------------------------------------------------------------------- #
# Stage 6: attendance — sessions marked by the class teacher who owns the class
# --------------------------------------------------------------------------- #
ATTENDANCE_WEEKS = 6  # school days before "today" to generate


def stage_attendance(ctx: Ctx) -> None:
    from modules.academics.backbone.models import (
        AttendanceRecord,
        AttendanceSession,
        ClassTeacherAssignment,
    )
    from modules.attendance.models import Attendance
    from modules.students.models import Student

    tid = ctx.tenant_id
    rng = random.Random(SEED + 3)
    holidays = holiday_dates(ctx)

    if AttendanceSession.query.filter_by(tenant_id=tid).count():
        log("attendance already present — skipping")
        return

    # School days from the start of the year, capped to the last N weeks so the
    # dataset stays small but recent enough to show up in "this month" views.
    today = date(2026, 8, 3)
    days: list[date] = []
    cursor = today
    while len(days) < ATTENDANCE_WEEKS * 5 and cursor > ctx.year.start_date:
        if cursor.weekday() < 5 and cursor not in holidays:
            days.append(cursor)
        cursor -= timedelta(days=1)
    days.reverse()

    markers = {
        cta.class_id: cta
        for cta in ClassTeacherAssignment.query.filter_by(
            tenant_id=tid, role="primary", is_active=True
        ).all()
    }
    students_by_class: dict[str, list[Student]] = {}
    for student in Student.query.filter_by(tenant_id=tid, student_status="active").all():
        students_by_class.setdefault(student.class_id, []).append(student)

    sessions = records = 0
    for cls in ctx.classes:
        roster = students_by_class.get(cls.id, [])
        cta = markers.get(cls.id)
        if not roster or not cta:
            continue
        marker_user_id = cta.teacher.user_id if cta.teacher else None

        for day in days:
            # the most recent day stays in draft so both states are represented
            is_draft = day == days[-1]
            session = AttendanceSession(
                id=str(uuid.uuid4()),
                tenant_id=tid,
                class_id=cls.id,
                session_date=day,
                status="draft" if is_draft else "finalized",
                marked_by_user_id=marker_user_id,
                assigned_marker_teacher_id=cta.teacher_id,
                class_teacher_assignment_id=cta.id,
                attendance_source="manual",
                taken_by_role="class_teacher",
                marked_at=datetime.combine(day, time(8, 0)),
                finalized_at=None if is_draft else datetime.combine(day, time(8, 15)),
                finalized_by_user_id=None if is_draft else marker_user_id,
            )
            db.session.add(session)
            db.session.flush()
            sessions += 1

            for student in roster:
                roll = rng.random()
                if roll < 0.90:
                    status = "present"
                elif roll < 0.97:
                    status = "absent"
                else:
                    status = "late"
                db.session.add(
                    AttendanceRecord(
                        id=str(uuid.uuid4()),
                        tenant_id=tid,
                        attendance_session_id=session.id,
                        student_id=student.id,
                        status=status,
                        recorded_by_user_id=marker_user_id,
                    )
                )
                # legacy per-day table still read by older reports
                db.session.add(
                    Attendance(
                        id=str(uuid.uuid4()),
                        tenant_id=tid,
                        date=day,
                        class_id=cls.id,
                        student_id=student.id,
                        status=status,
                        marked_by=marker_user_id,
                    )
                )
                records += 1
        db.session.commit()
    log(f"attendance: {sessions} sessions over {len(days)} school days, {records} records")


# --------------------------------------------------------------------------- #
# Stage 7: fees
# --------------------------------------------------------------------------- #
# grade band -> (structure name, [(component, amount)])
FEE_PLANS = [
    ((1, 2), "Primary Fees (Std 1-2)", [
        ("Tuition Fee", 12000), ("Term Fee", 2500), ("Activity Fee", 1500),
        ("Exam Fee", 800),
    ]),
    ((3, 5), "Primary Fees (Std 3-5)", [
        ("Tuition Fee", 15000), ("Term Fee", 3000), ("Activity Fee", 2000),
        ("Exam Fee", 1000), ("Computer Lab Fee", 1200),
    ]),
    ((9, 10), "Secondary Fees (Std 9-10)", [
        ("Tuition Fee", 24000), ("Term Fee", 4000), ("Laboratory Fee", 3000),
        ("Exam Fee", 1800), ("Library Fee", 900),
    ]),
]


def stage_fees(ctx: Ctx) -> None:
    from modules.fees.models import FeeInvoice, FeeInvoiceItem, FeePayment, FeeReceipt
    from modules.finance.models import (
        FeeComponent,
        FeeStructure,
        FeeStructureClass,
        StudentFee,
        StudentFeeItem,
    )
    from modules.students.models import Student

    tid = ctx.tenant_id
    rng = random.Random(SEED + 4)

    if FeeStructure.query.filter_by(tenant_id=tid).count():
        log("fee structures already present — skipping")
        return

    due = date(2026, 7, 15)
    structures = []
    for (lo, hi), name, components in FEE_PLANS:
        structure = FeeStructure(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            academic_year_id=ctx.year.id,
            name=name,
            due_date=due,
        )
        db.session.add(structure)
        db.session.flush()
        made = []
        for order, (comp_name, amount) in enumerate(components, start=1):
            comp = FeeComponent(
                id=str(uuid.uuid4()),
                tenant_id=tid,
                fee_structure_id=structure.id,
                name=comp_name,
                amount=amount,
                is_optional=False,
                sort_order=order,
            )
            db.session.add(comp)
            made.append(comp)
        for cls in ctx.classes:
            if lo <= grade_seq(cls) <= hi:
                db.session.add(
                    FeeStructureClass(
                        id=str(uuid.uuid4()),
                        tenant_id=tid,
                        fee_structure_id=structure.id,
                        class_id=cls.id,
                        academic_year_id=ctx.year.id,
                    )
                )
        structures.append(((lo, hi), structure, made))
    db.session.flush()
    log(f"fee structures: {len(structures)} with components, mapped to classes")

    structure_for = {}
    for (lo, hi), structure, comps in structures:
        for cls in ctx.classes:
            if lo <= grade_seq(cls) <= hi:
                structure_for[cls.id] = (structure, comps)

    students = Student.query.filter_by(tenant_id=tid).all()
    invoices = payments = 0
    seq = 1
    for student in students:
        found = structure_for.get(student.class_id)
        if not found:
            continue
        structure, comps = found
        total = sum(int(c.amount) for c in comps)

        # payment mix: fully paid / part-paid / untouched
        draw = rng.random()
        if draw < 0.55:
            paid = total
            fee_status, invoice_status = "paid", "paid"
        elif draw < 0.80:
            paid = int(total * rng.choice([0.3, 0.5, 0.6]))
            fee_status, invoice_status = "partial", "partially_paid"
        else:
            paid = 0
            fee_status, invoice_status = "unpaid", "issued"

        student_fee = StudentFee(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            student_id=student.id,
            fee_structure_id=structure.id,
            status=fee_status,
            total_amount=total,
            paid_amount=paid,
            due_date=due,
        )
        db.session.add(student_fee)
        db.session.flush()

        remaining = paid
        for comp in comps:
            comp_paid = min(remaining, int(comp.amount))
            remaining -= comp_paid
            db.session.add(
                StudentFeeItem(
                    id=str(uuid.uuid4()),
                    tenant_id=tid,
                    student_fee_id=student_fee.id,
                    fee_component_id=comp.id,
                    amount=comp.amount,
                    paid_amount=comp_paid,
                )
            )

        invoice = FeeInvoice(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            student_id=student.id,
            invoice_number=f"INV/2026/{seq:04d}",
            academic_year=ctx.year.name,
            issue_date=date(2026, 6, 20),
            due_date=due,
            subtotal=total,
            total_discount=0,
            total_fine=0,
            total_amount=total,
            status=invoice_status,
        )
        db.session.add(invoice)
        db.session.flush()
        invoices += 1
        for comp in comps:
            db.session.add(
                FeeInvoiceItem(
                    id=str(uuid.uuid4()),
                    tenant_id=tid,
                    invoice_id=invoice.id,
                    fee_head=comp.name,
                    period=ctx.year.name,
                    amount=comp.amount,
                    discount=0,
                    fine=0,
                    net_amount=comp.amount,
                )
            )

        if paid:
            method = rng.choice(["cash", "upi", "bank_transfer", "cheque"])
            payment = FeePayment(
                id=str(uuid.uuid4()),
                tenant_id=tid,
                invoice_id=invoice.id,
                student_id=student.id,
                payment_reference=f"PAY{seq:05d}",
                amount=paid,
                payment_method=method,
                transaction_id=f"TXN{rng.randint(10**9, 10**10 - 1)}" if method != "cash" else None,
                payment_date=date(2026, 7, rng.randint(1, 14)),
            )
            db.session.add(payment)
            db.session.flush()
            db.session.add(
                FeeReceipt(
                    id=str(uuid.uuid4()),
                    tenant_id=tid,
                    payment_id=payment.id,
                    receipt_number=f"RCPT/2026/{seq:04d}",
                )
            )
            payments += 1
        seq += 1
        if seq % 50 == 0:
            db.session.commit()
    db.session.commit()
    log(f"fees: {invoices} invoices, {payments} payments with receipts")


# --------------------------------------------------------------------------- #
# Stage 8: transport
# --------------------------------------------------------------------------- #
ROUTES = [
    ("Route 1 — Maninagar", "School Gate", "Maninagar Cross Road", 900,
     ["Maninagar Cross Road", "Rambaug", "Krishnanagar", "Khokhra Circle"]),
    ("Route 2 — Naranpura", "School Gate", "Naranpura Char Rasta", 850,
     ["Naranpura Char Rasta", "Vijay Cross Road", "Akhbarnagar"]),
    ("Route 3 — Bopal", "School Gate", "Bopal Circle", 1100,
     ["Bopal Circle", "South Bopal", "Ghuma", "Shela"]),
    ("Route 4 — Chandkheda", "School Gate", "Chandkheda Gam", 1000,
     ["Chandkheda Gam", "New CG Road", "Motera Stadium"]),
]
DRIVERS = [
    ("Bharatbhai Solanki", "GJ01-DL-334521"),
    ("Rajubhai Thakor", "GJ01-DL-887410"),
    ("Kanubhai Parmar", "GJ01-DL-556093"),
    ("Vinodbhai Chavda", "GJ01-DL-221876"),
]


def add_minutes(base: time, minutes: int) -> time:
    return (datetime.combine(date(2026, 1, 1), base) + timedelta(minutes=minutes)).time()


def stage_transport(ctx: Ctx) -> None:
    from modules.students.models import Student
    from modules.transport.models import (
        TransportBus,
        TransportBusAssignment,
        TransportDriver,
        TransportEnrollment,
        TransportFeePlan,
        TransportRoute,
        TransportRouteStop,
        TransportStop,
    )

    tid = ctx.tenant_id
    rng = random.Random(SEED + 5)

    if TransportRoute.query.filter_by(tenant_id=tid).count():
        log("transport already present — skipping")
        return

    route_rows = []
    for index, (name, start, end, fee, stops) in enumerate(ROUTES):
        route = TransportRoute(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            name=name,
            start_point=start,
            end_point=end,
            pickup_time=add_minutes(time(6, 45), index * 5),
            drop_time=add_minutes(time(14, 30), index * 5),
            status="active",
            default_fee=fee,
            fee_cycle="monthly",
            is_reverse_enabled=True,
        )
        db.session.add(route)
        db.session.flush()

        stop_rows = []
        for order, stop_name in enumerate(stops, start=1):
            stop = TransportStop(
                id=str(uuid.uuid4()),
                tenant_id=tid,
                route_id=route.id,
                name=stop_name,
                sequence_order=order,
                pickup_time=add_minutes(time(6, 45), index * 5 + order * 4),
                drop_time=add_minutes(time(14, 30), index * 5 + order * 4),
                is_active=True,
                area=stop_name.split()[0],
            )
            db.session.add(stop)
            db.session.flush()
            db.session.add(
                TransportRouteStop(
                    id=str(uuid.uuid4()),
                    tenant_id=tid,
                    route_id=route.id,
                    stop_id=stop.id,
                    sequence_order=order,
                    pickup_time=stop.pickup_time,
                    drop_time=stop.drop_time,
                )
            )
            stop_rows.append(stop)

        bus = TransportBus(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            bus_number=f"BUS-{index + 1:02d}",
            vehicle_number=f"GJ01 {rng.choice('ABCHJ')}{rng.choice('ABCHJ')} {rng.randint(1000, 9999)}",
            capacity=rng.choice([32, 40, 45]),
            status="active",
        )
        driver_name, licence = DRIVERS[index]
        driver = TransportDriver(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            name=driver_name,
            phone=f"9{rng.randint(700000000, 899999999)}",
            license_number=licence,
            status="active",
        )
        db.session.add_all([bus, driver])
        db.session.flush()
        db.session.add(
            TransportBusAssignment(
                id=str(uuid.uuid4()),
                tenant_id=tid,
                bus_id=bus.id,
                driver_id=driver.id,
                route_id=route.id,
                effective_from=ctx.year.start_date,
                status="active",
            )
        )
        db.session.add(
            TransportFeePlan(
                id=str(uuid.uuid4()),
                tenant_id=tid,
                route_id=route.id,
                amount=fee,
                academic_year_id=ctx.year.id,
                fee_cycle="monthly",
            )
        )
        route_rows.append((route, bus, stop_rows, fee))
    db.session.flush()

    enrolled = 0
    for student in Student.query.filter_by(tenant_id=tid, is_transport_opted=True).all():
        route, bus, stops, fee = route_rows[rng.randrange(len(route_rows))]
        stop = stops[rng.randrange(len(stops))]
        db.session.add(
            TransportEnrollment(
                id=str(uuid.uuid4()),
                tenant_id=tid,
                student_id=student.id,
                bus_id=bus.id,
                route_id=route.id,
                pickup_point=stop.name,
                drop_point=stop.name,
                pickup_stop_id=stop.id,
                drop_stop_id=stop.id,
                monthly_fee=fee,
                status="active",
                start_date=ctx.year.start_date,
                academic_year_id=ctx.year.id,
                fee_cycle="monthly",
            )
        )
        enrolled += 1
    db.session.commit()
    log(f"transport: {len(ROUTES)} routes, buses, drivers · {enrolled} student enrollments")


# --------------------------------------------------------------------------- #
# Stage 9: hostel
# --------------------------------------------------------------------------- #
def stage_hostel(ctx: Ctx) -> None:
    from modules.hostel.models import Hostel, HostelAllocation, HostelBed, HostelRoom
    from modules.students.models import Student

    tid = ctx.tenant_id
    rng = random.Random(SEED + 6)

    if Hostel.query.filter_by(tenant_id=tid).count():
        log("hostel already present — skipping")
        return

    hostels = []
    for name, warden, floors, rooms_per_floor, beds in [
        ("Boys Hostel — Sardar Bhavan", "Mahesh Chaudhary", ["Ground", "First"], 6, 4),
        ("Girls Hostel — Gargi Bhavan", "Nita Pandya", ["Ground", "First"], 5, 4),
    ]:
        capacity = len(floors) * rooms_per_floor * beds
        hostel = Hostel(
            id=str(uuid.uuid4()),
            tenant_id=tid,
            name=name,
            warden_name=warden,
            warden_phone=f"9{rng.randint(700000000, 899999999)}",
            address="Nexchool Demo School Campus, Ahmedabad",
            capacity=capacity,
            status="active",
        )
        db.session.add(hostel)
        db.session.flush()

        free_beds = []
        for floor in floors:
            for number in range(1, rooms_per_floor + 1):
                room = HostelRoom(
                    id=str(uuid.uuid4()),
                    tenant_id=tid,
                    hostel_id=hostel.id,
                    room_number=f"{floor[0]}{number:02d}",
                    floor=floor,
                    capacity=beds,
                    status="active",
                )
                db.session.add(room)
                db.session.flush()
                for bed_no in range(1, beds + 1):
                    bed = HostelBed(
                        id=str(uuid.uuid4()),
                        tenant_id=tid,
                        room_id=room.id,
                        bed_number=f"{room.room_number}-{bed_no}",
                        is_allocated=False,
                        status="available",
                    )
                    db.session.add(bed)
                    db.session.flush()
                    free_beds.append((room, bed))
        hostels.append((hostel, free_beds))
    db.session.flush()

    # Outstation students are the ones who would actually board.
    candidates = [
        s for s in Student.query.filter_by(tenant_id=tid, student_status="active").all()
        if grade_seq_of_student(ctx, s) >= 3
    ]
    rng.shuffle(candidates)
    allocated = 0
    for student in candidates:
        hostel, free_beds = hostels[0] if student.person.gender == "male" else hostels[1]
        if not free_beds:
            continue
        if rng.random() > 0.22:  # only a minority board
            continue
        room, bed = free_beds.pop()
        bed.is_allocated = True
        bed.allocated_to_student_id = student.id
        bed.status = "occupied"
        student.is_commuting_from_outstation = True
        student.commute_location = rng.choice(["Rajkot", "Bhavnagar", "Palanpur", "Godhra", "Junagadh"])
        db.session.add(
            HostelAllocation(
                id=str(uuid.uuid4()),
                tenant_id=tid,
                student_id=student.id,
                hostel_id=hostel.id,
                room_id=room.id,
                bed_id=bed.id,
                academic_year_id=ctx.year.id,
                check_in_at=datetime.combine(ctx.year.start_date, time(9, 0)),
                status="active",
            )
        )
        allocated += 1
    db.session.commit()
    log(f"hostel: 2 hostels, {sum(len(b) for _h, b in hostels) + allocated} beds · "
        f"{allocated} students allocated")


def grade_seq_of_student(ctx: Ctx, student) -> int:
    for cls in ctx.classes:
        if cls.id == student.class_id:
            return grade_seq(cls)
    return 0


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
STAGES = {
    "teachers": stage_teachers,
    "timetable": stage_timetable,
    "calendar": stage_calendar,
    "leaves": stage_leaves,
    "students": stage_students,
    "attendance": stage_attendance,
    "fees": stage_fees,
    "transport": stage_transport,
    "hostel": stage_hostel,
}
STAGE_ORDER = [
    "teachers", "timetable", "calendar", "leaves", "students",
    "attendance", "fees", "transport", "hostel",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        default="all",
        help=f"Stage to run: all | {' | '.join(STAGE_ORDER)}",
    )
    parser.add_argument("--tenant", default="default", help="Tenant subdomain")
    args = parser.parse_args()

    if args.stage != "all" and args.stage not in STAGES:
        raise SystemExit(f"Unknown stage '{args.stage}'. Choose: all, {', '.join(STAGE_ORDER)}")

    app = create_app()
    with app.app_context():
        tenant = Tenant.query.filter_by(subdomain=args.tenant).first()
        if not tenant:
            raise SystemExit(f"Tenant '{args.tenant}' not found.")
        ctx = Ctx(tenant.id)
        print(f"\nSeeding demo data — tenant '{args.tenant}', year {ctx.year.name}")

        to_run = STAGE_ORDER if args.stage == "all" else [args.stage]
        for name in to_run:
            print(f"\n[{name}]")
            STAGES[name](ctx)
    print("\nDone.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
