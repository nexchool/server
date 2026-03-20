"""
RBAC Services

Business logic for Role-Based Access Control including:
1. Authorization logic (permission checking)
2. CRUD operations for roles and permissions
3. Role-permission and user-role management

RBAC Philosophy:
- Authorization via permissions only
- Role names never used in business logic
- Permission naming: resource.action.scope
- 'manage' permission implies all actions on that resource
"""

from typing import List, Dict, Optional
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload

from backend.core.database import db
from backend.core.tenant import get_tenant_id
from backend.modules.auth.models import User
from .models import Role, Permission, RolePermission, UserRole


# ==================== AUTHORIZATION LOGIC ====================

def get_user_permissions(user_id: str) -> List[str]:
    """
    Fetch all unique permissions for a user by traversing their roles.
    
    This function queries the user and eagerly loads their roles and permissions
    using SQLAlchemy relationships: User -> UserRole -> Role -> RolePermission -> Permission
    
    Args:
        user_id: The UUID string of the user
        
    Returns:
        A sorted list of unique permission name strings (e.g., ['attendance.mark', 'student.read'])
        Returns empty list if user not found or has no permissions
        
    Example:
        >>> permissions = get_user_permissions('user-uuid-123')
        >>> print(permissions)
        ['attendance.mark', 'attendance.read.class', 'student.read']
    """
    # Query user roles with eager loading of permissions
    user_roles = UserRole.query.filter_by(user_id=user_id).all()
    
    if not user_roles:
        return []
    
    # Get all role IDs for the user
    role_ids = [ur.role_id for ur in user_roles]
    
    # Query roles with their permissions
    roles = Role.query.options(
        joinedload(Role.permissions)
    ).filter(Role.id.in_(role_ids)).all()
    
    # Collect all unique permission names
    permission_names = set()
    for role in roles:
        for permission in role.permissions:
            permission_names.add(permission.name)
    
    # Return sorted list for consistency
    return sorted(list(permission_names))


def has_permission(user_id: str, permission_name: str) -> bool:
    """
    Check if a user has a specific permission or its hierarchical equivalent.
    
    This function implements the hierarchical permission rule:
    - If user has the exact permission, return True
    - If user has '<resource>.manage', they have all permissions for that resource
    
    Args:
        user_id: The UUID string of the user
        permission_name: The permission to check (e.g., 'attendance.read.self')
        
    Returns:
        True if user has the permission or the manage permission for that resource
        False otherwise
        
    Example:
        >>> # User has 'attendance.manage'
        >>> has_permission('user-123', 'attendance.mark')
        True
        >>> has_permission('user-123', 'attendance.read.self')
        True
        >>> has_permission('user-123', 'student.create')
        False
    """
    # Get all permissions for the user
    user_permissions = get_user_permissions(user_id)
    
    # Check for exact permission match
    if permission_name in user_permissions:
        return True
    
    # Check for hierarchical 'manage' permission
    # Extract resource name from permission (e.g., 'attendance' from 'attendance.read.self')
    resource = parse_resource_from_permission(permission_name)
    manage_permission = f"{resource}.manage"
    
    # If user has resource.manage, they can do anything with that resource
    if manage_permission in user_permissions:
        return True
    
    return False


def parse_resource_from_permission(permission: str) -> str:
    """
    Extract the resource name from a permission string.
    
    Permissions follow the format: <resource>.<action>[.<scope>]
    This function extracts the resource (first part before the dot).
    
    Args:
        permission: Permission string (e.g., 'attendance.read.self')
        
    Returns:
        The resource name (e.g., 'attendance')
        Returns the full permission string if no dot is found (edge case)
        
    Example:
        >>> parse_resource_from_permission('attendance.read.self')
        'attendance'
        >>> parse_resource_from_permission('student.create')
        'student'
    """
    # Split on first dot and return the resource part
    parts = permission.split('.', 1)
    return parts[0]


def check_user_has_any_permissions(user_id: str) -> bool:
    """
    Check if a user has at least one permission assigned.
    
    This is used during login to enforce the security rule that users
    with zero permissions should not be allowed to access the system.
    
    Args:
        user_id: The UUID string of the user
        
    Returns:
        True if user has at least one permission, False otherwise
        
    Example:
        >>> check_user_has_any_permissions('user-with-role')
        True
        >>> check_user_has_any_permissions('user-without-role')
        False
    """
    permissions = get_user_permissions(user_id)
    return len(permissions) > 0


# ==================== PERMISSION CRUD ====================

def create_permission(name: str, description: str = None) -> Dict:
    """
    Create a new permission.
    
    Args:
        name: Permission name (e.g., 'attendance.mark')
        description: Optional description of what this permission allows
        
    Returns:
        Dict with success status and permission data or error message
    """
    try:
        # Check if permission already exists
        existing = Permission.query.filter_by(name=name).first()
        if existing:
            return {
                'success': False,
                'error': 'Permission already exists',
                'permission': None
            }
        
        # Create new permission
        permission = Permission(name=name, description=description)
        permission.save()
        
        return {
            'success': True,
            'permission': {
                'id': permission.id,
                'name': permission.name,
                'description': permission.description,
                'created_at': permission.created_at.isoformat()
            }
        }
    except Exception as e:
        db.session.rollback()
        return {
            'success': False,
            'error': str(e),
            'permission': None
        }


def list_permissions(search: str = None, limit: int = 100, offset: int = 0) -> List[Dict]:
    """List all permissions with optional search and pagination."""
    query = Permission.query
    
    if search:
        query = query.filter(Permission.name.ilike(f'%{search}%'))
    
    permissions = query.limit(limit).offset(offset).all()
    
    return [{
        'id': p.id,
        'name': p.name,
        'description': p.description,
        'created_at': p.created_at.isoformat()
    } for p in permissions]


def get_permission_by_id(permission_id: str) -> Optional[Dict]:
    """Get a single permission by ID."""
    permission = Permission.query.get(permission_id)
    if not permission:
        return None
    
    return {
        'id': permission.id,
        'name': permission.name,
        'description': permission.description,
        'created_at': permission.created_at.isoformat()
    }


def get_permission_by_name(name: str) -> Optional[Dict]:
    """Get a single permission by name."""
    permission = Permission.query.filter_by(name=name).first()
    if not permission:
        return None
    
    return {
        'id': permission.id,
        'name': permission.name,
        'description': permission.description,
        'created_at': permission.created_at.isoformat()
    }


def update_permission(permission_id: str, name: str = None, description: str = None) -> Dict:
    """Update an existing permission."""
    try:
        permission = Permission.query.get(permission_id)
        if not permission:
            return {
                'success': False,
                'error': 'Permission not found'
            }
        
        if name:
            permission.name = name
        if description is not None:
            permission.description = description
        
        permission.save()
        
        return {
            'success': True,
            'permission': {
                'id': permission.id,
                'name': permission.name,
                'description': permission.description
            }
        }
    except Exception as e:
        db.session.rollback()
        return {
            'success': False,
            'error': str(e)
        }


def delete_permission(permission_id: str) -> Dict:
    """Delete a permission and remove all role associations."""
    try:
        permission = Permission.query.get(permission_id)
        if not permission:
            return {
                'success': False,
                'error': 'Permission not found'
            }
        
        db.session.delete(permission)
        db.session.commit()
        
        return {
            'success': True,
            'message': 'Permission deleted successfully'
        }
    except Exception as e:
        db.session.rollback()
        return {
            'success': False,
            'error': str(e)
        }


# ==================== ROLE CRUD ====================

def create_role(name: str, description: str = None) -> Dict:
    """Create a new role (tenant-scoped)."""
    try:
        tenant_id = get_tenant_id()
        if not tenant_id:
            return {'success': False, 'error': 'Tenant context is required', 'role': None}

        # Check if role already exists in this tenant
        existing = Role.query.filter_by(name=name).first()
        if existing:
            return {
                'success': False,
                'error': 'Role already exists',
                'role': None
            }

        # Create new role (tenant-scoped)
        role = Role(tenant_id=tenant_id, name=name, description=description)
        role.save()
        
        return {
            'success': True,
            'role': {
                'id': role.id,
                'name': role.name,
                'description': role.description,
                'created_at': role.created_at.isoformat()
            }
        }
    except Exception as e:
        db.session.rollback()
        return {
            'success': False,
            'error': str(e),
            'role': None
        }


def list_roles(search: str = None, limit: int = 100, offset: int = 0) -> List[Dict]:
    """List all roles with optional search and pagination."""
    query = Role.query
    
    if search:
        query = query.filter(Role.name.ilike(f'%{search}%'))
    
    roles = query.limit(limit).offset(offset).all()
    
    return [{
        'id': r.id,
        'name': r.name,
        'description': r.description,
        'created_at': r.created_at.isoformat(),
        'permission_count': len(r.permissions)
    } for r in roles]


def get_role_by_id(role_id: str) -> Optional[Dict]:
    """Get a single role by ID with its permissions."""
    role = Role.query.get(role_id)
    if not role:
        return None
    
    return {
        'id': role.id,
        'name': role.name,
        'description': role.description,
        'created_at': role.created_at.isoformat(),
        'permissions': [p.name for p in role.permissions]
    }


def get_role_by_name(name: str) -> Optional[Dict]:
    """Get a single role by name with its permissions."""
    role = Role.query.filter_by(name=name).first()
    if not role:
        return None
    
    return {
        'id': role.id,
        'name': role.name,
        'description': role.description,
        'created_at': role.created_at.isoformat(),
        'permissions': [p.name for p in role.permissions]
    }


def update_role(role_id: str, name: str = None, description: str = None) -> Dict:
    """Update an existing role."""
    try:
        role = Role.query.get(role_id)
        if not role:
            return {
                'success': False,
                'error': 'Role not found'
            }
        
        if name:
            role.name = name
        if description is not None:
            role.description = description
        
        role.save()
        
        return {
            'success': True,
            'role': {
                'id': role.id,
                'name': role.name,
                'description': role.description
            }
        }
    except Exception as e:
        db.session.rollback()
        return {
            'success': False,
            'error': str(e)
        }


def delete_role(role_id: str) -> Dict:
    """Delete a role and remove all user and permission associations."""
    try:
        role = Role.query.get(role_id)
        if not role:
            return {
                'success': False,
                'error': 'Role not found'
            }
        
        db.session.delete(role)
        db.session.commit()
        
        return {
            'success': True,
            'message': 'Role deleted successfully'
        }
    except Exception as e:
        db.session.rollback()
        return {
            'success': False,
            'error': str(e)
        }


# ==================== ROLE-PERMISSION MANAGEMENT ====================

def assign_permission_to_role(role_id: str, permission_id: str) -> Dict:
    """Assign a permission to a role."""
    try:
        role = Role.query.get(role_id)
        if not role:
            return {'success': False, 'error': 'Role not found'}
        
        permission = Permission.query.get(permission_id)
        if not permission:
            return {'success': False, 'error': 'Permission not found'}
        
        # Check if already assigned
        existing = RolePermission.query.filter_by(
            role_id=role_id,
            permission_id=permission_id
        ).first()
        
        if existing:
            return {
                'success': False,
                'error': 'Permission already assigned to this role'
            }

        # Create association (tenant-scoped)
        role_permission = RolePermission(
            tenant_id=role.tenant_id,
            role_id=role_id,
            permission_id=permission_id,
        )
        role_permission.save()
        
        return {
            'success': True,
            'message': f'Permission "{permission.name}" assigned to role "{role.name}"'
        }
    except IntegrityError:
        db.session.rollback()
        return {
            'success': False,
            'error': 'Permission already assigned to this role'
        }
    except Exception as e:
        db.session.rollback()
        return {
            'success': False,
            'error': str(e)
        }


def assign_permission_to_role_by_name(role_name: str, permission_name: str) -> Dict:
    """Assign a permission to a role by their names (convenience function)."""
    role = Role.query.filter_by(name=role_name).first()
    if not role:
        return {'success': False, 'error': f'Role "{role_name}" not found'}
    
    permission = Permission.query.filter_by(name=permission_name).first()
    if not permission:
        return {'success': False, 'error': f'Permission "{permission_name}" not found'}
    
    return assign_permission_to_role(role.id, permission.id)


def remove_permission_from_role(role_id: str, permission_id: str) -> Dict:
    """Remove a permission from a role."""
    try:
        role_permission = RolePermission.query.filter_by(
            role_id=role_id,
            permission_id=permission_id
        ).first()
        
        if not role_permission:
            return {
                'success': False,
                'error': 'Permission not assigned to this role'
            }
        
        db.session.delete(role_permission)
        db.session.commit()
        
        return {
            'success': True,
            'message': 'Permission removed from role'
        }
    except Exception as e:
        db.session.rollback()
        return {
            'success': False,
            'error': str(e)
        }


def get_role_permissions(role_id: str) -> List[Dict]:
    """Get all permissions for a specific role."""
    role = Role.query.get(role_id)
    if not role:
        return []
    
    return [{
        'id': p.id,
        'name': p.name,
        'description': p.description
    } for p in role.permissions]


# ==================== USER-ROLE MANAGEMENT ====================

def assign_role_to_user(user_id: str, role_id: str) -> Dict:
    """Assign a role to a user."""
    try:
        user = User.query.get(user_id)
        if not user:
            return {'success': False, 'error': 'User not found'}
        
        role = Role.query.get(role_id)
        if not role:
            return {'success': False, 'error': 'Role not found'}
        
        # Check if already assigned
        existing = UserRole.query.filter_by(
            user_id=user_id,
            role_id=role_id
        ).first()
        
        if existing:
            return {
                'success': False,
                'error': 'Role already assigned to this user'
            }

        # Create association (tenant_id from user)
        user_role = UserRole(
            tenant_id=user.tenant_id,
            user_id=user_id,
            role_id=role_id,
        )
        user_role.save()
        
        return {
            'success': True,
            'message': f'Role "{role.name}" assigned to user {user.email}'
        }
    except IntegrityError:
        db.session.rollback()
        return {
            'success': False,
            'error': 'Role already assigned to this user'
        }
    except Exception as e:
        db.session.rollback()
        return {
            'success': False,
            'error': str(e)
        }


def assign_role_to_user_by_email(email: str, role_name: str, tenant_id: str = None) -> Dict:
    """
    Assign a role to a user by email and role name (convenience function).

    When tenant_id is provided (recommended in multi-tenant context), looks up the user
    and role within that tenant. When omitted, uses unscoped queries (legacy behavior).
    """
    user_query = User.query.filter_by(email=email)
    if tenant_id is not None:
        user_query = user_query.filter_by(tenant_id=tenant_id)
    user = user_query.first()
    if not user:
        return {'success': False, 'error': f'User with email "{email}" not found'}

    role_query = Role.query.filter_by(name=role_name)
    if tenant_id is not None:
        role_query = role_query.filter_by(tenant_id=tenant_id)
    role = role_query.first()
    if not role:
        return {'success': False, 'error': f'Role "{role_name}" not found'}

    return assign_role_to_user(user.id, role.id)


def remove_role_from_user(user_id: str, role_id: str) -> Dict:
    """Remove a role from a user."""
    try:
        user_role = UserRole.query.filter_by(
            user_id=user_id,
            role_id=role_id
        ).first()
        
        if not user_role:
            return {
                'success': False,
                'error': 'Role not assigned to this user'
            }
        
        db.session.delete(user_role)
        db.session.commit()
        
        return {
            'success': True,
            'message': 'Role removed from user'
        }
    except Exception as e:
        db.session.rollback()
        return {
            'success': False,
            'error': str(e)
        }


def get_user_roles(user_id: str) -> List[Dict]:
    """Get all roles for a specific user."""
    user_roles = UserRole.query.filter_by(user_id=user_id).all()
    if not user_roles:
        return []
    
    role_ids = [ur.role_id for ur in user_roles]
    roles = Role.query.filter(Role.id.in_(role_ids)).all()
    
    return [{
        'id': r.id,
        'name': r.name,
        'description': r.description
    } for r in roles]


# ==================== BULK OPERATIONS ====================

def bulk_assign_permissions_to_role(role_id: str, permission_ids: List[str]) -> Dict:
    """Assign multiple permissions to a role at once."""
    try:
        role = Role.query.get(role_id)
        if not role:
            return {'success': False, 'error': 'Role not found'}
        
        assigned_count = 0
        errors = []
        
        for permission_id in permission_ids:
            result = assign_permission_to_role(role_id, permission_id)
            if result['success']:
                assigned_count += 1
            else:
                errors.append(result['error'])
        
        return {
            'success': True,
            'assigned_count': assigned_count,
            'total': len(permission_ids),
            'errors': errors if errors else None
        }
    except Exception as e:
        db.session.rollback()
        return {
            'success': False,
            'error': str(e)
        }


def bulk_assign_roles_to_user(user_id: str, role_ids: List[str]) -> Dict:
    """Assign multiple roles to a user at once."""
    try:
        user = User.query.get(user_id)
        if not user:
            return {'success': False, 'error': 'User not found'}
        
        assigned_count = 0
        errors = []
        
        for role_id in role_ids:
            result = assign_role_to_user(user_id, role_id)
            if result['success']:
                assigned_count += 1
            else:
                errors.append(result['error'])
        
        return {
            'success': True,
            'assigned_count': assigned_count,
            'total': len(role_ids),
            'errors': errors if errors else None
        }
    except Exception as e:
        db.session.rollback()
        return {
            'success': False,
            'error': str(e)
        }
