"""
RBAC Seed Script

Seeds the database with default roles and permissions for School ERP.

Usage:
    python -m scripts.seed_rbac
    
Or from Flask shell:
    >>> from scripts.seed_rbac import seed_rbac
    >>> seed_rbac()
"""

from app import create_app
from modules.rbac.services import (
    create_role, create_permission,
    assign_permission_to_role_by_name
)


# ==================== PERMISSIONS DEFINITION ====================

PERMISSIONS = [
    # User permissions
    ('user.read', 'View user information'),
    ('user.create', 'Create new users'),
    ('user.update', 'Update user information'),
    ('user.delete', 'Delete users'),
    ('user.manage', 'Full user management access'),
    
    # Role permissions
    ('role.read', 'View roles'),
    ('role.create', 'Create new roles'),
    ('role.update', 'Update roles'),
    ('role.delete', 'Delete roles'),
    ('role.manage', 'Full role management access'),
    
    # Permission permissions
    ('permission.read', 'View permissions'),
    ('permission.create', 'Create new permissions'),
    ('permission.update', 'Update permissions'),
    ('permission.delete', 'Delete permissions'),
    ('permission.manage', 'Full permission management access'),
    
    # Student permissions
    ('student.read.self', 'View own student information'),
    ('student.read.class', 'View class students information'),
    ('student.read.all', 'View all students information'),
    ('student.create', 'Create new students'),
    ('student.update', 'Update student information'),
    ('student.delete', 'Delete students'),
    ('student.manage', 'Full student management access'),
    
    # Teacher permissions
    ('teacher.read', 'View teacher information'),
    ('teacher.create', 'Create new teachers'),
    ('teacher.update', 'Update teacher information'),
    ('teacher.delete', 'Delete teachers'),
    ('teacher.manage', 'Full teacher management access'),
    ('teacher.leave.apply', 'Apply for leave as a teacher'),
    ('teacher.leave.manage', 'View and manage all teacher leave requests'),

    # Student leave permissions
    ('student.leave.apply', 'Apply for a leave as a student'),
    ('student.leave.read.own', "Read one's own student leave requests"),
    ('student.leave.read.class', "Read leave requests for the teacher's classes"),
    ('student.leave.read.all', 'Read all student leave requests in the tenant'),
    ('student.leave.approve.class', "Approve/reject leave requests for the teacher's classes"),
    ('student.leave.approve.all', 'Approve/reject any student leave request (admin fallback)'),
    ('student.leave.request_cancel', 'Request cancellation of an own leave (student)'),

    # Announcement permissions
    ('announcement.create', 'Create announcements as an admin'),
    ('announcement.update', 'Edit/append revisions to announcements'),
    ('announcement.recall', 'Recall a published announcement'),
    ('announcement.read.own', 'Read announcements where I am a recipient'),
    ('announcement.read.all', 'Read all announcements in the tenant (admin)'),

    # Attendance permissions
    ('attendance.read.self', 'View own attendance'),
    ('attendance.read.class', 'View class attendance'),
    ('attendance.read.all', 'View all attendance records'),
    ('attendance.mark', 'Mark attendance'),
    ('attendance.update', 'Update attendance records'),
    ('attendance.manage', 'Full attendance management access'),
    
    # Academic permissions
    ('grades.read.self', 'View own grades'),
    ('grades.read.class', 'View class grades'),
    ('grades.read.all', 'View all grades'),
    ('grades.create', 'Create grade entries'),
    ('grades.update', 'Update grade entries'),
    ('grades.manage', 'Full grades management access'),
    
    # Class permissions
    ('class.read', 'View class information'),
    ('class.create', 'Create new classes'),
    ('class.update', 'Update class information'),
    ('class.delete', 'Delete classes'),
    ('class.manage', 'Full class management access'),

    # Subject permissions
    ('subject.read', 'View subject information'),
    ('subject.create', 'Create new subjects'),
    ('subject.update', 'Update subject information'),
    ('subject.delete', 'Delete subjects'),
    ('subject.manage', 'Full subject management access'),

    # Timetable permissions
    ('timetable.read', 'View timetable information'),
    ('timetable.create', 'Create timetable slots'),
    ('timetable.update', 'Update timetable slots'),
    ('timetable.delete', 'Delete timetable slots'),
    ('timetable.manage', 'Full timetable management access'),

    # Class subject & class teacher (academic backbone)
    ('class_subject.read', 'View class subject assignments'),
    ('class_subject.manage', 'Manage class subject assignments'),
    ('class_teacher.manage', 'Manage class teacher assignments'),

    # Academics hub (dashboards, health)
    ('academics.read', 'View academic summaries and health'),
    ('academics.manage', 'Full academic operations dashboard'),

    # Course permissions
    ('course.read', 'View course information'),
    ('course.create', 'Create new courses'),
    ('course.update', 'Update course information'),
    ('course.delete', 'Delete courses'),
    ('course.manage', 'Full course management access'),

    # Finance permissions
    ('finance.read', 'View finance and fee information'),
    ('finance.collect', 'Collect fee payments'),
    ('finance.refund', 'Refund payments'),
    ('finance.manage', 'Full finance management access'),

    # Fees Invoice & Receipt permissions
    ('fees.invoice.create', 'Create fee invoices'),
    ('fees.invoice.read', 'View fee invoices'),
    ('fees.invoice.send_reminder', 'Send invoice reminders'),
    ('fees.payment.record', 'Record fee payments'),
    ('fees.receipt.download', 'Download fee receipts'),

    # Transport permissions (granular + transport.manage; legacy grouped perms kept for old roles)
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

    # Holiday permissions
    ('holiday.read', 'View holidays and weekly-off calendar'),
    ('holiday.create', 'Create holidays'),
    ('holiday.update', 'Update holiday details'),
    ('holiday.delete', 'Delete holidays'),
    ('holiday.manage', 'Full holiday management access'),

    # Multi-school structural masters
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

    # School setup flow
    ('school_setup.read', 'View school setup state and validation'),
    ('school_setup.manage', 'Run school setup and mark it complete'),

    # Audit log
    ('audit_log.view', 'View tenant audit log'),

    # Sub-admin management
    ('subadmin.manage', 'Manage sub-admin accounts and their permissions'),

    # Hostel module
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


# ==================== ROLES DEFINITION ====================

ROLES = {
    'Admin': {
        'description': 'System administrator with full access',
        'permissions': [
            'user.manage',
            'role.manage',
            'permission.manage',
            'student.manage',
            'teacher.manage',
            'attendance.manage',
            'grades.manage',
            'course.manage',
            'class.manage',
            'subject.manage',
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
            # Multi-school structural masters + setup flow
            'school_unit.manage',
            'programme.manage',
            'grade.manage',
            'religion.manage',
            'academic_term.manage',
            # Audit log
            'audit_log.view',
            # Sub-admin management
            'subadmin.manage',
            # Hostel
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
        ]
    },
    'Teacher': {
        'description': 'School teacher with class management access',
        'permissions': [
            'student.read.class',
            'attendance.mark',
            'attendance.read.class',
            'grades.create',
            'grades.update',
            'grades.read.class',
            'course.read',
            'class.read',
            'subject.read',
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
            'school_setup.read',
        ]
    },
    'Student': {
        'description': 'Student with limited access to own data',
        'permissions': [
            'student.read.self',
            'attendance.read.self',
            'grades.read.self',
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
        ]
    },
    'Parent': {
        'description': 'Parent with access to their children\'s data',
        'permissions': [
            'student.read.self',  # Access to child's info
            'attendance.read.self',
            'grades.read.self',
            'course.read',
            'timetable.read',
            'holiday.read',
            'transport.info.read.self',
            'transport.student.read_own',
            'announcement.read.own',
        ]
    },
}


def seed_rbac():
    """
    Seed the database with default roles and permissions.
    
    This function:
    1. Creates all permissions
    2. Creates all roles
    3. Assigns permissions to roles
    
    Returns:
        Dict with success status and statistics
    """
    stats = {
        'permissions_created': 0,
        'permissions_existed': 0,
        'roles_created': 0,
        'roles_existed': 0,
        'assignments_created': 0,
        'assignments_failed': 0,
    }
    
    print("\n" + "="*60)
    print("🌱 Seeding RBAC System")
    print("="*60 + "\n")
    
    # 1. Create permissions
    print("📋 Creating Permissions...")
    for permission_name, description in PERMISSIONS:
        result = create_permission(permission_name, description)
        if result['success']:
            print(f"  ✓ Created: {permission_name}")
            stats['permissions_created'] += 1
        else:
            if 'already exists' in result['error']:
                stats['permissions_existed'] += 1
            else:
                print(f"  ✗ Failed: {permission_name} - {result['error']}")
    
    print(f"\n  Summary: {stats['permissions_created']} created, {stats['permissions_existed']} already existed\n")
    
    # 2. Create roles
    print("👥 Creating Roles...")
    for role_name, role_data in ROLES.items():
        result = create_role(role_name, role_data['description'])
        if result['success']:
            print(f"  ✓ Created: {role_name}")
            stats['roles_created'] += 1
        else:
            if 'already exists' in result['error']:
                print(f"  ℹ Already exists: {role_name}")
                stats['roles_existed'] += 1
            else:
                print(f"  ✗ Failed: {role_name} - {result['error']}")
    
    print(f"\n  Summary: {stats['roles_created']} created, {stats['roles_existed']} already existed\n")
    
    # 3. Assign permissions to roles
    print("🔗 Assigning Permissions to Roles...")
    for role_name, role_data in ROLES.items():
        print(f"\n  Role: {role_name}")
        for permission_name in role_data['permissions']:
            result = assign_permission_to_role_by_name(role_name, permission_name)
            if result['success']:
                print(f"    ✓ {permission_name}")
                stats['assignments_created'] += 1
            else:
                if 'already assigned' in result['error']:
                    pass  # Silent for already assigned
                else:
                    print(f"    ✗ {permission_name} - {result['error']}")
                    stats['assignments_failed'] += 1
    
    print("\n" + "="*60)
    print("📊 Seeding Complete!")
    print("="*60)
    print(f"Permissions: {stats['permissions_created']} created, {stats['permissions_existed']} existed")
    print(f"Roles: {stats['roles_created']} created, {stats['roles_existed']} existed")
    print(f"Assignments: {stats['assignments_created']} created, {stats['assignments_failed']} failed")
    print("="*60 + "\n")
    
    return stats


if __name__ == '__main__':
    """Run seeding when script is executed directly"""
    app = create_app()
    
    with app.app_context():
        seed_rbac()
