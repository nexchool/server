"""
RBAC Seed Script

Seeds the database with default roles and permissions for School ERP.

Usage:
    python -m backend.scripts.seed_rbac
    
Or from Flask shell:
    >>> from backend.scripts.seed_rbac import seed_rbac
    >>> seed_rbac()
"""

from backend.app import create_app
from backend.modules.rbac.services import (
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

    # Holiday permissions
    ('holiday.read', 'View holidays and weekly-off calendar'),
    ('holiday.create', 'Create holidays'),
    ('holiday.update', 'Update holiday details'),
    ('holiday.delete', 'Delete holidays'),
    ('holiday.manage', 'Full holiday management access'),
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
            'holiday.manage',
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
            'holiday.read',
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
