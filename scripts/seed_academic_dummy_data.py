"""
Development-only seed: reset tenant academic data and insert realistic dummy data
for the academic backbone + timetable v2.

Uses only the new backbone (no legacy timetable_slots / SubjectLoad seeding).

Usage (from repo ``server/`` with PYTHONPATH including the server root):
    PYTHONPATH=. python scripts/seed_academic_dummy_data.py

With Docker Compose (from ``school-erp-infra/docker``, stack running):
    docker compose -f docker-compose.local.yml exec api python scripts/seed_academic_dummy_data.py

Requires: migrations applied, default tenant, RBAC roles (Admin, Teacher, Student).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time

from app import create_app
from core.database import db
from core.models import Tenant
from modules.academics.academic_year.models import AcademicYear
from modules.academics.backbone.models import (
    AcademicSettings,
    AcademicTerm,
    AttendanceRecord,
    AttendanceSession,
    BellSchedule,
    BellSchedulePeriod,
    ClassSubjectTeacher,
    ClassTeacherAssignment,
    StudentClassEnrollment,
    TimetableEntry,
    TimetableVersion,
)
from modules.attendance.models import Attendance as LegacyAttendance
from modules.auth.models import Session, User
from modules.classes.models import Class, ClassSubject, ClassTeacher, SubjectLoad
from modules.fees.models import FeeInvoice, FeeInvoiceItem, FeePayment, FeeReceipt
from modules.finance.models import (
    FeeComponent,
    FeeStructure,
    FeeStructureClass,
    Payment,
    StudentFee,
    StudentFeeItem,
)
from modules.notifications.models import Notification
from modules.rbac.models import Role, UserRole
from modules.schedule.models import ScheduleOverride
from modules.students.models import Student, StudentDocument
from modules.subjects.models import Subject
from modules.teachers.models import Teacher
from modules.timetable.models import TimetableSlot


def _get_default_tenant_id() -> str:
    t = Tenant.query.filter_by(subdomain="default").first()
    if not t:
        raise RuntimeError('No tenant with subdomain "default". Run migrations / tenant seed first.')
    return t.id


def _clear_tenant_academic_data(tenant_id: str) -> None:
    """Delete tenant academic data in FK-safe order. Keeps platform admins and non-academic config."""

    settings = AcademicSettings.query.filter_by(tenant_id=tenant_id).first()
    if settings:
        settings.current_academic_year_id = None
        settings.default_bell_schedule_id = None
        settings.default_working_days_json = None

    user_ids_to_remove: set[str] = set()
    for row in db.session.query(Student.user_id).filter(Student.tenant_id == tenant_id).all():
        user_ids_to_remove.add(row[0])
    for row in db.session.query(Teacher.user_id).filter(Teacher.tenant_id == tenant_id).all():
        user_ids_to_remove.add(row[0])
    for row in (
        db.session.query(Class.teacher_id)
        .filter(Class.tenant_id == tenant_id, Class.teacher_id.isnot(None))
        .all()
    ):
        user_ids_to_remove.add(row[0])
    seed_admin = User.query.filter_by(tenant_id=tenant_id, email="admin@nexchool.in").first()
    if seed_admin:
        user_ids_to_remove.add(seed_admin.id)

    ScheduleOverride.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    AttendanceRecord.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    AttendanceSession.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    TimetableEntry.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    TimetableVersion.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    TimetableSlot.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)

    ClassSubjectTeacher.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    ClassSubject.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    StudentClassEnrollment.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    ClassTeacherAssignment.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    SubjectLoad.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    ClassTeacher.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    LegacyAttendance.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)

    Payment.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    StudentFeeItem.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    StudentFee.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    FeeStructureClass.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    FeeComponent.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    FeeStructure.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)

    FeeReceipt.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    FeePayment.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    FeeInvoiceItem.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    FeeInvoice.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)

    StudentDocument.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)

    # students.class_id → classes.id (RESTRICT): remove students before classes
    Student.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    Class.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    Teacher.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)

    BellSchedulePeriod.query.filter(
        BellSchedulePeriod.tenant_id == tenant_id,
    ).delete(synchronize_session=False)
    BellSchedule.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)

    AcademicTerm.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)
    AcademicYear.query.filter_by(tenant_id=tenant_id).delete(synchronize_session=False)

    if user_ids_to_remove:
        ids = [
            u.id
            for u in User.query.filter(User.id.in_(user_ids_to_remove)).all()
            if not u.is_platform_admin
        ]
        if ids:
            Session.query.filter(Session.user_id.in_(ids)).delete(synchronize_session=False)
            Notification.query.filter(Notification.user_id.in_(ids)).delete(synchronize_session=False)
            UserRole.query.filter(UserRole.user_id.in_(ids)).delete(synchronize_session=False)
            User.query.filter(User.id.in_(ids)).delete(synchronize_session=False)

    db.session.flush()


def _ensure_subject(tenant_id: str, name: str, code: str) -> Subject:
    s = Subject.query.filter_by(tenant_id=tenant_id, name=name).first()
    if s:
        return s
    s = Subject(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=name,
        code=code,
        subject_type="core",
        is_active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.session.add(s)
    db.session.flush()
    return s


def _user(tenant_id: str, email: str, name: str, password: str) -> User:
    u = User(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        email=email,
        name=name,
        email_verified=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    u.set_password(password)
    db.session.add(u)
    db.session.flush()
    return u


def _assign_role(tenant_id: str, user_id: str, role_name: str) -> None:
    role = Role.query.filter_by(tenant_id=tenant_id, name=role_name).first()
    if not role:
        raise RuntimeError(f'Role "{role_name}" not found for tenant. Run seed_rbac first.')
    db.session.add(
        UserRole(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            role_id=role.id,
            created_at=datetime.utcnow(),
        )
    )


def run_seed() -> None:
    tenant_id = _get_default_tenant_id()
    password = "password123"

    _clear_tenant_academic_data(tenant_id)

    ay = AcademicYear(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name="2025-2026",
        start_date=date(2025, 6, 1),
        end_date=date(2026, 3, 31),
        is_active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.session.add(ay)
    db.session.flush()

    admin = _user(tenant_id, "admin@nexchool.in", "Sahil Patel", password)
    _assign_role(tenant_id, admin.id, "Admin")

    teacher_specs = [
        ("Ramesh Patel", "ramesh.patel@nexchool.in"),
        ("Jignesh Shah", "jignesh.shah@nexchool.in"),
        ("Kalpesh Desai", "kalpesh.desai@nexchool.in"),
        ("Mehul Trivedi", "mehul.trivedi@nexchool.in"),
        ("Hardik Joshi", "hardik.joshi@nexchool.in"),
    ]
    teachers: list[tuple[User, Teacher]] = []
    for i, (tname, temail) in enumerate(teacher_specs, start=1):
        u = _user(tenant_id, temail, tname, password)
        _assign_role(tenant_id, u.id, "Teacher")
        t = Teacher(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id=u.id,
            employee_id=f"EMP{i:03d}",
            designation="Teacher",
            status="active",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.session.add(t)
        db.session.flush()
        teachers.append((u, t))

    t_by_email = {u.email: (u, t) for u, t in teachers}

    student_rows = [
        ("Meet", "Patel"),
        ("Dhruv", "Shah"),
        ("Yash", "Desai"),
        ("Harsh", "Patel"),
        ("Krish", "Mehta"),
        ("Dev", "Patel"),
        ("Parth", "Shah"),
        ("Nisarg", "Desai"),
        ("Jay", "Patel"),
        ("Om", "Shah"),
        ("Aryan", "Patel"),
        ("Tirth", "Mehta"),
        ("Vraj", "Shah"),
        ("Mihir", "Patel"),
        ("Kunal", "Desai"),
        ("Darsh", "Shah"),
        ("Prince", "Patel"),
        ("Rutvik", "Desai"),
        ("Chirag", "Patel"),
        ("Smit", "Shah"),
    ]
    students: list[tuple[User, Student]] = []
    for idx, (first, last) in enumerate(student_rows, start=1):
        email = f"{first.lower()}.{last.lower()}@nexchool.in"
        u = _user(tenant_id, email, f"{first} {last}", password)
        _assign_role(tenant_id, u.id, "Student")
        st = Student(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id=u.id,
            admission_number=f"ADM{idx:03d}",
            roll_number=idx,
            academic_year="2025-2026",
            academic_year_id=ay.id,
            class_id=None,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.session.add(st)
        db.session.flush()
        students.append((u, st))

    # Class teachers: Ramesh -> A, Jignesh -> B (users.id on Class.teacher_id)
    u_ramesh, t_ramesh = t_by_email["ramesh.patel@nexchool.in"]
    u_jignesh, t_jignesh = t_by_email["jignesh.shah@nexchool.in"]

    class_a = Class(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name="Grade 10",
        section="A",
        academic_year_id=ay.id,
        start_date=ay.start_date,
        end_date=ay.end_date,
        teacher_id=u_ramesh.id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    class_b = Class(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name="Grade 10",
        section="B",
        academic_year_id=ay.id,
        start_date=ay.start_date,
        end_date=ay.end_date,
        teacher_id=u_jignesh.id,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.session.add_all([class_a, class_b])
    db.session.flush()

    db.session.add(
        ClassTeacherAssignment(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            class_id=class_a.id,
            teacher_id=t_ramesh.id,
            role="primary",
            allow_attendance_marking=True,
            is_active=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
    )
    db.session.add(
        ClassTeacherAssignment(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            class_id=class_b.id,
            teacher_id=t_jignesh.id,
            role="primary",
            allow_attendance_marking=True,
            is_active=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
    )

    for u, st in students[:10]:
        st.class_id = class_a.id
        db.session.add(
            StudentClassEnrollment(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                student_id=st.id,
                class_id=class_a.id,
                academic_year_id=ay.id,
                enrollment_status="active",
                is_current=True,
                started_on=ay.start_date,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
        )
    for u, st in students[10:]:
        st.class_id = class_b.id
        db.session.add(
            StudentClassEnrollment(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                student_id=st.id,
                class_id=class_b.id,
                academic_year_id=ay.id,
                enrollment_status="active",
                is_current=True,
                started_on=ay.start_date,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
        )

    subject_defs = [
        ("Mathematics", "MATH", 6),
        ("Science", "SCI", 5),
        ("English", "ENG", 5),
        ("Social Studies", "SOC", 4),
        ("Gujarati", "GUJ", 4),
        ("Computer", "CS", 3),
    ]
    subjects = [(n, _ensure_subject(tenant_id, n, c), w) for n, c, w in subject_defs]

    # Subject key -> teacher (Mehul teaches English + Computer on both classes for conflicts)
    key_to_teacher = {
        "Mathematics": t_by_email["ramesh.patel@nexchool.in"][1],
        "Science": t_by_email["jignesh.shah@nexchool.in"][1],
        "English": t_by_email["mehul.trivedi@nexchool.in"][1],
        "Social Studies": t_by_email["kalpesh.desai@nexchool.in"][1],
        "Gujarati": t_by_email["hardik.joshi@nexchool.in"][1],
        "Computer": t_by_email["mehul.trivedi@nexchool.in"][1],
    }

    def add_class_subjects_and_teachers(klass: Class) -> int:
        count = 0
        for sort_idx, (name, subj, weekly) in enumerate(subjects, start=1):
            cs = ClassSubject(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                class_id=klass.id,
                subject_id=subj.id,
                weekly_periods=weekly,
                is_mandatory=True,
                sort_order=sort_idx,
                status="active",
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.session.add(cs)
            db.session.flush()
            cst = ClassSubjectTeacher(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                class_subject_id=cs.id,
                teacher_id=key_to_teacher[name].id,
                role="primary",
                is_active=True,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.session.add(cst)
            count += 1
        return count

    subj_per_class = add_class_subjects_and_teachers(class_a)
    add_class_subjects_and_teachers(class_b)

    bell = BellSchedule(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name="Regular Day Schedule",
        academic_year_id=ay.id,
        day_of_week=None,
        is_default=True,
        valid_from=ay.start_date,
        valid_to=ay.end_date,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.session.add(bell)
    db.session.flush()

    periods_spec = [
        (1, "lesson", time(8, 0), time(8, 40)),
        (2, "lesson", time(8, 40), time(9, 20)),
        (3, "lesson", time(9, 20), time(10, 0)),
        (4, "break", time(10, 0), time(10, 20)),
        (5, "lesson", time(10, 20), time(11, 0)),
        (6, "lesson", time(11, 0), time(11, 40)),
        (7, "lesson", time(11, 40), time(12, 20)),
        (8, "lesson", time(12, 20), time(13, 0)),
    ]
    for pn, kind, st_t, en_t in periods_spec:
        db.session.add(
            BellSchedulePeriod(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                bell_schedule_id=bell.id,
                period_number=pn,
                period_kind=kind,
                starts_at=st_t,
                ends_at=en_t,
                sort_order=pn,
            )
        )

    settings = AcademicSettings.query.filter_by(tenant_id=tenant_id).first()
    if not settings:
        settings = AcademicSettings(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            attendance_mode="daily",
            allow_teacher_timetable_override=False,
            allow_admin_attendance_override=True,
        )
        db.session.add(settings)
    settings.current_academic_year_id = ay.id
    settings.default_bell_schedule_id = bell.id
    settings.default_working_days_json = [1, 2, 3, 4, 5]

    for klass in (class_a, class_b):
        db.session.add(
            TimetableVersion(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                class_id=klass.id,
                bell_schedule_id=bell.id,
                label=f"Draft — {klass.section}",
                status="draft",
                effective_from=ay.start_date,
                effective_to=ay.end_date,
                created_by=admin.id,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
        )

    db.session.commit()

    total_users = 1 + len(teachers) + len(students)
    print("\n" + "=" * 60)
    print("Academic dummy data seed complete (development)")
    print("=" * 60)
    print(f"Total users created:     {total_users}")
    print(f"  Students:              {len(students)}")
    print(f"  Teachers:              {len(teachers)}")
    print(f"  Admin:                 1")
    print(f"Classes:                 2 (Grade 10-A, Grade 10-B)")
    print(f"Subjects per class:      {subj_per_class}")
    print(f"Bell schedule:           {bell.name} (id={bell.id})")
    print(f"Working days (JSON):     [1,2,3,4,5] (Mon–Fri)")
    print(f"Academic year:           {ay.name} (id={ay.id})")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        run_seed()
