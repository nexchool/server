"""
RBAC (Role-Based Access Control) Decorator

Provides the @require_permission decorator for permission-based authorization.

RBAC Philosophy:
- Authorization via permissions only
- Role names never used in business logic
- Permission naming: resource.action.scope
- 'manage' permission implies all actions on that resource

Usage:
    @bp.route('/students', methods=['POST'])
    @auth_required
    @require_permission('student.create')
    def create_student():
        return jsonify({'message': 'Student created'})
"""

from functools import wraps
from flask import g, jsonify
from typing import Callable


def require_permission(permission_name: str) -> Callable:
    """
    Decorator to enforce permission-based access control on routes.
    
    This decorator checks if the authenticated user (from g.current_user)
    has the required permission. It implements hierarchical permission checking:
    - Allows access if user has the exact permission
    - Allows access if user has '<resource>.manage' for that resource
    - Returns 403 Forbidden otherwise
    
    The decorator MUST be used after @auth_required, which sets g.current_user.
    
    Args:
        permission_name: The permission string to check (e.g., 'student.create')
        
    Returns:
        The decorated function if authorized, or 403/401 response if not
        
    Example:
        @bp.route('/students', methods=['POST'])
        @auth_required
        @require_permission('student.create')
        def create_student():
            return jsonify({'message': 'Student created'})
        
        # A user with 'student.manage' can also access this route
        # due to hierarchical permission checking
            
    Design Rules:
        - Never checks role names, only permissions
        - Always fetches fresh permissions from database (no caching yet)
        - Implements 'manage' implies all rule for hierarchical permissions
    """
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            # Import here to avoid circular imports
            from backend.modules.rbac.services import has_permission
            
            # Check if user is authenticated (set by @auth_required decorator)
            if not hasattr(g, 'current_user') or g.current_user is None:
                return jsonify({
                    'error': 'Unauthorized',
                    'message': 'Authentication required. Use @auth_required before @require_permission.'
                }), 401
            
            # Get user_id from the authenticated user
            user_id = g.current_user.id
            
            # Check if user has the required permission (exact or via manage)
            # This calls the RBAC service which handles the business logic
            if has_permission(user_id, permission_name):
                # User is authorized, proceed with the route handler
                return fn(*args, **kwargs)
            
            # User does not have the required permission
            return jsonify({
                'error': 'Forbidden',
                'message': f'Insufficient permissions. Required: {permission_name}'
            }), 403
        
        return wrapper
    return decorator


def require_any_permission(*permission_names: str) -> Callable:
    """
    Decorator to check if user has ANY of the specified permissions.
    Useful for routes that can be accessed by multiple permission types.
    
    Args:
        *permission_names: Variable number of permission strings
        
    Example:
        @bp.route('/attendance/view')
        @auth_required
        @require_any_permission('attendance.read.self', 'attendance.read.class', 'attendance.manage')
        def view_attendance():
            return jsonify({'data': 'attendance'})
    """
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            from backend.modules.rbac.services import has_permission
            
            if not hasattr(g, 'current_user') or g.current_user is None:
                return jsonify({
                    'error': 'Unauthorized',
                    'message': 'Authentication required'
                }), 401
            
            user_id = g.current_user.id
            
            # Check if user has any of the required permissions
            for permission_name in permission_names:
                if has_permission(user_id, permission_name):
                    return fn(*args, **kwargs)
            
            # User doesn't have any of the required permissions
            return jsonify({
                'error': 'Forbidden',
                'message': f'Insufficient permissions. Required one of: {", ".join(permission_names)}'
            }), 403
        
        return wrapper
    return decorator


def require_all_permissions(*permission_names: str) -> Callable:
    """
    Decorator to check if user has ALL of the specified permissions.
    Useful for routes requiring multiple permissions.
    
    Args:
        *permission_names: Variable number of permission strings
        
    Example:
        @bp.route('/sensitive-operation')
        @auth_required
        @require_all_permissions('user.manage', 'role.manage')
        def sensitive_operation():
            return jsonify({'message': 'Success'})
    """
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            from backend.modules.rbac.services import has_permission
            
            if not hasattr(g, 'current_user') or g.current_user is None:
                return jsonify({
                    'error': 'Unauthorized',
                    'message': 'Authentication required'
                }), 401
            
            user_id = g.current_user.id
            
            # Check if user has all required permissions
            for permission_name in permission_names:
                if not has_permission(user_id, permission_name):
                    return jsonify({
                        'error': 'Forbidden',
                        'message': f'Insufficient permissions. Missing: {permission_name}'
                    }), 403
            
            # User has all required permissions
            return fn(*args, **kwargs)
        
        return wrapper
    return decorator
