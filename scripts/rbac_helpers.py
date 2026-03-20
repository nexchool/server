"""
RBAC Helper Scripts

Quick helper functions to manage RBAC system from Flask shell or scripts.

Usage:
    >>> from backend.app import create_app
    >>> app = create_app()
    >>> with app.app_context():
    ...     from backend.scripts.rbac_helpers import *
    ...     assign_admin_role('admin@school.com')
"""

from backend.modules.rbac.services import (
    assign_role_to_user_by_email,
    get_user_permissions,
    get_user_roles,
    list_roles,
    list_permissions
)


def assign_admin_role(email: str):
    """Quickly assign Admin role to a user by email"""
    result = assign_role_to_user_by_email(email, 'Admin')
    if result['success']:
        print(f"✓ Admin role assigned to {email}")
    else:
        print(f"✗ Error: {result['error']}")
    return result


def assign_teacher_role(email: str):
    """Quickly assign Teacher role to a user by email"""
    result = assign_role_to_user_by_email(email, 'Teacher')
    if result['success']:
        print(f"✓ Teacher role assigned to {email}")
    else:
        print(f"✗ Error: {result['error']}")
    return result


def assign_student_role(email: str):
    """Quickly assign Student role to a user by email"""
    result = assign_role_to_user_by_email(email, 'Student')
    if result['success']:
        print(f"✓ Student role assigned to {email}")
    else:
        print(f"✗ Error: {result['error']}")
    return result


def assign_parent_role(email: str):
    """Quickly assign Parent role to a user by email"""
    result = assign_role_to_user_by_email(email, 'Parent')
    if result['success']:
        print(f"✓ Parent role assigned to {email}")
    else:
        print(f"✗ Error: {result['error']}")
    return result


def show_user_permissions(email: str):
    """Display all permissions for a user by email"""
    from backend.modules.auth.models import User
    
    user = User.query.filter_by(email=email).first()
    if not user:
        print(f"✗ User not found: {email}")
        return
    
    permissions = get_user_permissions(user.id)
    roles = get_user_roles(user.id)
    
    print(f"\n{'='*60}")
    print(f"User: {email}")
    print(f"{'='*60}")
    
    print(f"\nRoles ({len(roles)}):")
    for role in roles:
        print(f"  - {role['name']}")
    
    print(f"\nPermissions ({len(permissions)}):")
    for perm in permissions:
        print(f"  - {perm}")
    
    print(f"{'='*60}\n")


def show_all_roles():
    """Display all roles and their permission counts"""
    roles = list_roles()
    
    print(f"\n{'='*60}")
    print(f"All Roles ({len(roles)})")
    print(f"{'='*60}")
    
    for role in roles:
        print(f"\n{role['name']}")
        print(f"  Description: {role['description']}")
        print(f"  Permissions: {role['permission_count']}")
    
    print(f"{'='*60}\n")


def show_all_permissions():
    """Display all permissions"""
    permissions = list_permissions()
    
    print(f"\n{'='*60}")
    print(f"All Permissions ({len(permissions)})")
    print(f"{'='*60}\n")
    
    # Group by resource
    by_resource = {}
    for perm in permissions:
        resource = perm['name'].split('.')[0]
        if resource not in by_resource:
            by_resource[resource] = []
        by_resource[resource].append(perm['name'])
    
    for resource, perms in sorted(by_resource.items()):
        print(f"\n{resource.upper()}:")
        for perm in sorted(perms):
            print(f"  - {perm}")
    
    print(f"\n{'='*60}\n")


if __name__ == '__main__':
    print("\nRBAC Helper Functions Available:")
    print("="*60)
    print("\nQuick Role Assignment:")
    print("  - assign_admin_role('email@example.com')")
    print("  - assign_teacher_role('email@example.com')")
    print("  - assign_student_role('email@example.com')")
    print("  - assign_parent_role('email@example.com')")
    
    print("\nInformation Display:")
    print("  - show_user_permissions('email@example.com')")
    print("  - show_all_roles()")
    print("  - show_all_permissions()")
    
    print("\n" + "="*60)
    print("\nUsage from Flask shell:")
    print("  >>> from backend.app import create_app")
    print("  >>> app = create_app()")
    print("  >>> with app.app_context():")
    print("  ...     from backend.scripts.rbac_helpers import *")
    print("  ...     assign_admin_role('admin@school.com')")
    print("="*60 + "\n")
