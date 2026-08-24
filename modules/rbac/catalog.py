"""The permission catalogue, and what each default role holds.

One definition, imported by everything that seeds. Before this there were two —
`scripts/seed_rbac.py` for a fresh install and `modules/rbac/role_seeder.py` for
every tenant created since — kept in step by a comment asking whoever edits one
to remember the other. A tenant's authority then depended on which seeder had
made it, and that is how the Teacher role came to hold `school_setup.read` in
some tenants and not others (debt 33, migration 103).

Two rules for editing this file:

**A key here is not a permission until a role holds it.** `has_permission` never
looks a key up — it compares strings — so a key in the catalogue that no role is
granted denies everyone, quietly and forever. `<resource>.manage` implies every
action on that resource, which is why most sub-keys need no explicit grant.

**Removing a grant is not enough to take it away.** `seed_roles_for_tenant` runs
on login and only ever adds, so a tenant keeps what it was given. Reconciling
(`reseed_rbac --reconcile`) is what actually revokes.
"""

from typing import Dict, List, Tuple

# (name, description) — the rows that become Permission records.
PERMISSIONS: List[Tuple[str, str]] = [
    ('user.read', 'View user information'),
    ('user.create', 'Create new users'),
    ('user.update', 'Update user information'),
    ('user.delete', 'Delete users'),
    ('user.manage', 'Full user management access'),

    ('person.merge', 'Combine two records that describe the same person'),

    ('role.read', 'View roles'),
    ('role.create', 'Create new roles'),
    ('role.update', 'Update roles'),
    ('role.delete', 'Delete roles'),
    ('role.manage', 'Full role management access'),

    ('permission.read', 'View permissions'),
    ('permission.create', 'Create new permissions'),
    ('permission.update', 'Update permissions'),
    ('permission.delete', 'Delete permissions'),
    ('permission.manage', 'Full permission management access'),

    ('student.read.self', 'View own student information'),
    ('student.read.class', 'View class students information'),
    ('student.read.all', 'View all students information'),
    ('student.create', 'Create new students'),
    ('student.update', 'Update student information'),
    ('student.delete', 'Delete students'),
    ('student.manage', 'Full student management access'),

    ('teacher.read', 'View teacher information'),
    ('teacher.create', 'Create new teachers'),
    ('teacher.update', 'Update teacher information'),
    ('teacher.delete', 'Delete teachers'),
    ('teacher.manage', 'Full teacher management access'),
    ('teacher.leave.apply', 'Apply for leave as a teacher'),
    ('teacher.leave.manage', 'View and manage all teacher leave requests'),

    ('student.leave.apply', 'Apply for a leave as a student'),
    ('student.leave.read.own', "Read one's own student leave requests"),
    ('student.leave.read.class', "Read leave requests for the teacher's classes"),
    ('student.leave.read.all', 'Read all student leave requests in the tenant'),
    ('student.leave.approve.class', "Approve/reject leave requests for the teacher's classes"),
    ('student.leave.approve.all', 'Approve/reject any student leave request (admin fallback)'),
    ('student.leave.request_cancel', 'Request cancellation of an own leave (student)'),

    ('announcement.create', 'Create announcements as an admin'),
    ('announcement.update', 'Edit/append revisions to announcements'),
    ('announcement.recall', 'Recall a published announcement'),
    ('announcement.read.own', 'Read announcements where I am a recipient'),
    ('announcement.read.all', 'Read all announcements in the tenant (admin)'),

    ('attendance.read.self', 'View own attendance'),
    ('attendance.read.class', 'View class attendance'),
    ('attendance.read.all', 'View all attendance records'),
    ('attendance.mark', 'Mark attendance'),
    ('attendance.update', 'Update attendance records'),
    ('attendance.manage', 'Full attendance management access'),

    # Marks and results. Named `assessment.*` rather than `grades.*`, which
    # was one letter from the live `grade.*` grade master and resolved on the
    # same string prefix (migration 115).
    ('assessment.read.self', 'View own marks and results'),
    ('assessment.read.class', 'View marks for own classes'),
    ('assessment.read.all', 'View all marks and results'),
    ('assessment.enter', 'Enter marks'),
    ('assessment.update', 'Correct marks'),
    ('assessment.manage', 'Full assessment access'),
    ('examination.read', 'View examinations'),
    ('examination.manage', 'Create, schedule and cancel examinations'),
    ('examination.publish', 'Publish and revise examination results'),

    ('class.read', 'View class information'),
    ('class.create', 'Create new classes'),
    ('class.update', 'Update class information'),
    ('class.delete', 'Delete classes'),
    ('class.manage', 'Full class management access'),

    ('subject.read', 'View subject information'),
    ('subject.create', 'Create new subjects'),
    ('subject.update', 'Update subject information'),
    ('subject.delete', 'Delete subjects'),
    ('subject.manage', 'Full subject management access'),

    ('department.read', 'View department information'),
    ('department.manage', 'Full department management access'),

    ('timetable.read', 'View timetable information'),
    ('timetable.create', 'Create timetable slots'),
    ('timetable.update', 'Update timetable slots'),
    ('timetable.delete', 'Delete timetable slots'),
    ('timetable.manage', 'Full timetable management access'),

    ('class_subject.read', 'View class subject assignments'),
    ('class_subject.manage', 'Manage class subject assignments'),

    ('class_teacher.manage', 'Manage class teacher assignments'),

    ('academics.read', 'View academic summaries and health'),
    ('academics.manage', 'Full academic operations dashboard'),

    ('course.read', 'View course information'),
    ('course.create', 'Create new courses'),
    ('course.update', 'Update course information'),
    ('course.delete', 'Delete courses'),
    ('course.manage', 'Full course management access'),

    ('finance.read', 'View finance and fee information'),
    ('finance.collect', 'Collect fee payments'),
    ('finance.refund', 'Refund payments'),
    ('finance.manage', 'Full finance management access'),

    ('fees.invoice.create', 'Create fee invoices'),
    ('fees.invoice.read', 'View fee invoices'),
    ('fees.invoice.send_reminder', 'Send invoice reminders'),
    ('fees.payment.record', 'Record fee payments'),
    ('fees.receipt.download', 'Download fee receipts'),

    ('transport.manage', 'Full transport module access'),
    ('transport.buses.create', 'Create buses'),
    ('transport.buses.read', 'View buses'),
    ('transport.buses.update', 'Update buses'),
    ('transport.buses.delete', 'Delete or deactivate buses'),
    ('transport.drivers.create', 'Create drivers'),
    ('transport.drivers.read', 'View drivers'),
    ('transport.drivers.update', 'Update drivers'),
    ('transport.drivers.delete', 'Deactivate drivers'),
    ('transport.routes.create', 'Create routes'),
    ('transport.routes.read', 'View routes'),
    ('transport.routes.update', 'Update routes'),
    ('transport.routes.delete', 'Deactivate routes'),
    ('transport.stops.create', 'Create transport stops'),
    ('transport.stops.read', 'View transport stops'),
    ('transport.stops.update', 'Update transport stops'),
    ('transport.stops.delete', 'Deactivate transport stops'),
    ('transport.assignments.create', 'Create bus assignments'),
    ('transport.assignments.read', 'View bus assignments'),
    ('transport.assignments.update', 'Update bus assignments'),
    ('transport.assignments.delete', 'End bus assignments'),
    ('transport.enrollment.create', 'Create transport enrollments'),
    ('transport.enrollment.read', 'View transport enrollments'),
    ('transport.enrollment.update', 'Update transport enrollments'),
    ('transport.enrollment.delete', 'Deactivate transport enrollments'),
    ('transport.fee_plans.read', 'View transport fee plans'),
    ('transport.fee_plans.manage', 'Manage transport fee plans'),
    ('transport.dashboard.read', 'View transport dashboard'),
    ('transport.exports.read', 'Export transport CSV reports'),
    ('transport.student.read_own', 'View own transport details (mobile)'),
    ('transport.info.read.class', 'View transport info for students in own classes'),
    ('transport.info.read.self', 'View own transport details'),
    ('transport.drivers.manage', 'Manage drivers (legacy)'),
    ('transport.routes.manage', 'Manage routes (legacy)'),
    ('transport.assignments.manage', 'Manage bus assignments (legacy)'),

    ('holiday.read', 'View holidays and weekly-off calendar'),
    ('holiday.create', 'Create holidays'),
    ('holiday.update', 'Update holiday details'),
    ('holiday.delete', 'Delete holidays'),
    ('holiday.manage', 'Full holiday management access'),

    ('school_unit.read', 'View school units (campuses)'),
    ('school_unit.manage', 'Manage school units (campuses)'),

    ('programme.read', 'View academic programmes (board + medium)'),
    ('programme.manage', 'Manage academic programmes'),

    ('grade.read', 'View grades / standards master'),
    ('grade.manage', 'Manage grades / standards master'),

    ('religion.read', 'View religion master'),
    ('religion.manage', 'Manage religion master'),

    ('academic_term.read', 'View academic terms'),
    ('academic_term.manage', 'Manage academic terms'),

    ('academic_calendar.read', 'View the academic calendar (events, exams, summary)'),
    ('academic_calendar.manage', 'Configure and publish the academic calendar'),
    ('academic_calendar.create', 'Create an academic calendar'),
    ('academic_calendar.edit', 'Edit calendar setup, events, exams and semesters'),
    ('academic_calendar.delete', 'Delete a draft academic calendar'),
    ('academic_calendar.archive', 'Archive or restore an academic calendar'),
    ('academic_calendar.duplicate', 'Duplicate an academic calendar'),
    ('academic_calendar.export', 'Export the academic calendar (PDF/Excel/CSV)'),
    ('academic_calendar.import', 'Import calendar data from a template'),
    ('academic_calendar.print', 'Print the academic calendar'),
    ('academic_calendar.settings', 'Manage academic calendar preferences'),

    ('school_setup.read', 'View school setup state and validation'),
    ('school_setup.manage', 'Run school setup and mark it complete'),

    ('audit_log.view', 'View tenant audit log'),

    ('subadmin.manage', 'Manage sub-admin accounts and their permissions'),

    ('hostel.read', 'View hostels, rooms, and beds'),
    ('hostel.manage', 'Create / update / delete hostels, rooms, and beds'),
    ('hostel.allocations.read', 'View hostel allocations'),
    ('hostel.allocations.manage', 'Allocate students to beds / check out'),
    ('hostel.visitors.read', 'View hostel visitor logs'),
    ('hostel.visitors.manage', 'Check hostel visitors in / out'),
    ('hostel.gatepass.create', 'Create hostel gatepass requests'),
    ('hostel.gatepass.approve', 'Approve or reject hostel gatepasses (warden)'),
    ('hostel.gatepass.gatekeeper', 'Mark gatepass checkout / checkin at the gate'),
    ('hostel.gatepass.read', 'View hostel gatepasses'),
    ('hostel.reports.read', 'View hostel occupancy reports and dashboard'),
]


# What each default role holds. `implied_by_relationship` means the role follows
# from being that kind of person rather than from a grant on their account
# (ADR-013) — a student is a student, nobody assigns it.
DEFAULT_ROLES: Dict[str, dict] = {
    'Admin': {
        'description': 'System administrator with full access',
        'permissions': [
            'user.manage',
            'person.merge',
            'role.manage',
            'permission.manage',
            'audit_log.view',
            'student.manage',
            'teacher.manage',
            'attendance.manage',
            'assessment.manage',
            'examination.manage',
            'examination.publish',
            'course.manage',
            'class.manage',
            'subject.manage',
            'department.manage',
            'timetable.manage',
            'finance.read',
            'finance.manage',
            'finance.collect',
            'finance.refund',
            'fees.invoice.create',
            'fees.invoice.read',
            'fees.invoice.send_reminder',
            'fees.payment.record',
            'fees.receipt.download',
            'teacher.leave.manage',
            'student.leave.read.all',
            'student.leave.approve.all',
            'announcement.create',
            'announcement.update',
            'announcement.recall',
            'announcement.read.own',
            'announcement.read.all',
            'holiday.manage',
            'class_subject.manage',
            'class_teacher.manage',
            'academics.read',
            'academics.manage',
            'transport.manage',
            'school_unit.manage',
            'programme.manage',
            'grade.manage',
            'religion.manage',
            'academic_term.manage',
            'subadmin.manage',
            'hostel.read',
            'hostel.manage',
            'hostel.allocations.read',
            'hostel.allocations.manage',
            'hostel.visitors.read',
            'hostel.visitors.manage',
            'hostel.gatepass.create',
            'hostel.gatepass.approve',
            'hostel.gatepass.gatekeeper',
            'hostel.gatepass.read',
            'hostel.reports.read',
            'academic_calendar.read',
            'academic_calendar.manage',
        ],
    },
    'Teacher': {
        'description': 'School teacher with class management access',
        'permissions': [
            'student.read.class',
            'attendance.mark',
            'attendance.read.class',
            'assessment.enter',
            'assessment.update',
            'assessment.read.class',
            'examination.read',
            'course.read',
            'class.read',
            'subject.read',
            'department.read',
            'timetable.read',
            'teacher.leave.apply',
            'student.leave.read.class',
            'student.leave.approve.class',
            'announcement.read.own',
            'holiday.read',
            'class_subject.read',
            'academics.read',
            'transport.info.read.class',
            'school_unit.read',
            'programme.read',
            'grade.read',
            'academic_term.read',
            'academic_calendar.read',
        ],
    },
    'Student': {
        'description': 'Student with limited access to own data',
        'implied_by_relationship': 'student',
        'permissions': [
            'student.read.self',
            'attendance.read.self',
            'assessment.read.self',
            'examination.read',
            'course.read',
            'timetable.read',
            'holiday.read',
            'academics.read',
            'transport.info.read.self',
            'transport.student.read_own',
            'student.leave.apply',
            'student.leave.read.own',
            'student.leave.request_cancel',
            'announcement.read.own',
        ],
    },
    'Parent': {
        'description': "Parent with access to their children's data",
        'permissions': [
            'student.read.self',
            'attendance.read.self',
            'assessment.read.self',
            'examination.read',
            'course.read',
            'timetable.read',
            'holiday.read',
            'transport.info.read.self',
            'transport.student.read_own',
            'announcement.read.own',
        ],
    },
}
