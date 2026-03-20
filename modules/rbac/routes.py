"""
RBAC Routes

API endpoints for managing roles, permissions, and their assignments.
All routes require authentication and appropriate permissions.

Routes:
- POST /permissions - Create permission
- GET /permissions - List permissions
- GET /permissions/<id> - Get permission
- PUT /permissions/<id> - Update permission
- DELETE /permissions/<id> - Delete permission

- POST /roles - Create role
- GET /roles - List roles
- GET /roles/<id> - Get role
- PUT /roles/<id> - Update role
- DELETE /roles/<id> - Delete role

- POST /roles/<id>/permissions - Assign permission to role
- DELETE /roles/<id>/permissions/<permission_id> - Remove permission from role
- GET /roles/<id>/permissions - Get role permissions

- POST /users/<id>/roles - Assign role to user
- DELETE /users/<id>/roles/<role_id> - Remove role from user
- GET /users/<id>/roles - Get user roles
- GET /users/<id>/permissions - Get user permissions
"""

from flask import request, jsonify

from . import rbac_bp
from backend.core.decorators import auth_required, require_permission, tenant_required
from backend.core.tenant import get_tenant_id
from backend.shared.helpers import success_response, error_response
from .services import (
    # Permission CRUD
    create_permission, list_permissions, get_permission_by_id,
    get_permission_by_name, update_permission, delete_permission,
    # Role CRUD
    create_role, list_roles, get_role_by_id, get_role_by_name,
    update_role, delete_role,
    # Role-Permission Management
    assign_permission_to_role, assign_permission_to_role_by_name,
    remove_permission_from_role, get_role_permissions,
    # User-Role Management
    assign_role_to_user, assign_role_to_user_by_email,
    remove_role_from_user, get_user_roles,
    # Bulk Operations
    bulk_assign_permissions_to_role, bulk_assign_roles_to_user,
    # Utility
    get_user_permissions as get_all_user_permissions
)


# ==================== PERMISSION ROUTES ====================

@rbac_bp.route('/permissions', methods=['POST'])
@tenant_required
@auth_required
@require_permission('permission.manage')
def create_permission_route():
    """Create a new permission"""
    data = request.get_json()
    name = data.get('name')
    description = data.get('description')
    
    if not name:
        return error_response('ValidationError', 'Permission name is required', 400)
    
    result = create_permission(name, description)
    
    if result['success']:
        return success_response(result['permission'], 'Permission created successfully', 201)
    else:
        return error_response('CreationError', result['error'], 400)


@rbac_bp.route('/permissions', methods=['GET'])
@tenant_required
@auth_required
@require_permission('permission.read')
def list_permissions_route():
    """List all permissions with optional search"""
    search = request.args.get('search')
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    permissions = list_permissions(search, limit, offset)
    
    return success_response({
        'permissions': permissions,
        'count': len(permissions)
    })


@rbac_bp.route('/permissions/<permission_id>', methods=['GET'])
@tenant_required
@auth_required
@require_permission('permission.read')
def get_permission_route(permission_id):
    """Get a single permission by ID"""
    permission = get_permission_by_id(permission_id)
    
    if not permission:
        return error_response('NotFound', 'Permission not found', 404)
    
    return success_response(permission)


@rbac_bp.route('/permissions/<permission_id>', methods=['PUT'])
@tenant_required
@auth_required
@require_permission('permission.manage')
def update_permission_route(permission_id):
    """Update a permission"""
    data = request.get_json()
    name = data.get('name')
    description = data.get('description')
    
    result = update_permission(permission_id, name, description)
    
    if result['success']:
        return success_response(result['permission'], 'Permission updated successfully')
    else:
        return error_response('UpdateError', result['error'], 400)


@rbac_bp.route('/permissions/<permission_id>', methods=['DELETE'])
@tenant_required
@auth_required
@require_permission('permission.manage')
def delete_permission_route(permission_id):
    """Delete a permission"""
    result = delete_permission(permission_id)
    
    if result['success']:
        return success_response(message=result['message'])
    else:
        return error_response('DeleteError', result['error'], 400)


# ==================== ROLE ROUTES ====================

@rbac_bp.route('/roles', methods=['POST'])
@tenant_required
@auth_required
@require_permission('role.manage')
def create_role_route():
    """Create a new role"""
    data = request.get_json()
    name = data.get('name')
    description = data.get('description')
    
    if not name:
        return error_response('ValidationError', 'Role name is required', 400)
    
    result = create_role(name, description)
    
    if result['success']:
        return success_response(result['role'], 'Role created successfully', 201)
    else:
        return error_response('CreationError', result['error'], 400)


@rbac_bp.route('/roles', methods=['GET'])
@tenant_required
@auth_required
@require_permission('role.read')
def list_roles_route():
    """List all roles with optional search"""
    search = request.args.get('search')
    limit = request.args.get('limit', 100, type=int)
    offset = request.args.get('offset', 0, type=int)
    
    roles = list_roles(search, limit, offset)
    
    return success_response({
        'roles': roles,
        'count': len(roles)
    })


@rbac_bp.route('/roles/<role_id>', methods=['GET'])
@tenant_required
@auth_required
@require_permission('role.read')
def get_role_route(role_id):
    """Get a single role by ID with its permissions"""
    role = get_role_by_id(role_id)
    
    if not role:
        return error_response('NotFound', 'Role not found', 404)
    
    return success_response(role)


@rbac_bp.route('/roles/<role_id>', methods=['PUT'])
@tenant_required
@auth_required
@require_permission('role.manage')
def update_role_route(role_id):
    """Update a role"""
    data = request.get_json()
    name = data.get('name')
    description = data.get('description')
    
    result = update_role(role_id, name, description)
    
    if result['success']:
        return success_response(result['role'], 'Role updated successfully')
    else:
        return error_response('UpdateError', result['error'], 400)


@rbac_bp.route('/roles/<role_id>', methods=['DELETE'])
@tenant_required
@auth_required
@require_permission('role.manage')
def delete_role_route(role_id):
    """Delete a role"""
    result = delete_role(role_id)
    
    if result['success']:
        return success_response(message=result['message'])
    else:
        return error_response('DeleteError', result['error'], 400)


# ==================== ROLE-PERMISSION ASSIGNMENT ROUTES ====================

@rbac_bp.route('/roles/<role_id>/permissions', methods=['POST'])
@tenant_required
@auth_required
@require_permission('role.manage')
def assign_permission_to_role_route(role_id):
    """Assign a permission to a role"""
    data = request.get_json()
    permission_id = data.get('permission_id')
    
    if not permission_id:
        return error_response('ValidationError', 'Permission ID is required', 400)
    
    result = assign_permission_to_role(role_id, permission_id)
    
    if result['success']:
        return success_response(message=result['message'], status_code=201)
    else:
        return error_response('AssignmentError', result['error'], 400)


@rbac_bp.route('/roles/<role_id>/permissions/bulk', methods=['POST'])
@tenant_required
@auth_required
@require_permission('role.manage')
def bulk_assign_permissions_route(role_id):
    """Assign multiple permissions to a role"""
    data = request.get_json()
    permission_ids = data.get('permission_ids', [])
    
    if not permission_ids:
        return error_response('ValidationError', 'Permission IDs are required', 400)
    
    result = bulk_assign_permissions_to_role(role_id, permission_ids)
    
    return success_response(result)


@rbac_bp.route('/roles/<role_id>/permissions/<permission_id>', methods=['DELETE'])
@tenant_required
@auth_required
@require_permission('role.manage')
def remove_permission_from_role_route(role_id, permission_id):
    """Remove a permission from a role"""
    result = remove_permission_from_role(role_id, permission_id)
    
    if result['success']:
        return success_response(message=result['message'])
    else:
        return error_response('RemovalError', result['error'], 400)


@rbac_bp.route('/roles/<role_id>/permissions', methods=['GET'])
@tenant_required
@auth_required
@require_permission('role.read')
def get_role_permissions_route(role_id):
    """Get all permissions for a role"""
    permissions = get_role_permissions(role_id)
    
    return success_response({
        'permissions': permissions,
        'count': len(permissions)
    })


# ==================== USER-ROLE ASSIGNMENT ROUTES ====================

@rbac_bp.route('/users/<user_id>/roles', methods=['POST'])
@tenant_required
@auth_required
@require_permission('user.manage')
def assign_role_to_user_route(user_id):
    """Assign a role to a user"""
    data = request.get_json()
    role_id = data.get('role_id')
    
    if not role_id:
        return error_response('ValidationError', 'Role ID is required', 400)
    
    result = assign_role_to_user(user_id, role_id)
    
    if result['success']:
        return success_response(message=result['message'], status_code=201)
    else:
        return error_response('AssignmentError', result['error'], 400)


@rbac_bp.route('/users/<user_id>/roles/bulk', methods=['POST'])
@tenant_required
@auth_required
@require_permission('user.manage')
def bulk_assign_roles_route(user_id):
    """Assign multiple roles to a user"""
    data = request.get_json()
    role_ids = data.get('role_ids', [])
    
    if not role_ids:
        return error_response('ValidationError', 'Role IDs are required', 400)
    
    result = bulk_assign_roles_to_user(user_id, role_ids)
    
    return success_response(result)


@rbac_bp.route('/users/<user_id>/roles/<role_id>', methods=['DELETE'])
@tenant_required
@auth_required
@require_permission('user.manage')
def remove_role_from_user_route(user_id, role_id):
    """Remove a role from a user"""
    result = remove_role_from_user(user_id, role_id)
    
    if result['success']:
        return success_response(message=result['message'])
    else:
        return error_response('RemovalError', result['error'], 400)


@rbac_bp.route('/users/<user_id>/roles', methods=['GET'])
@tenant_required
@auth_required
@require_permission('user.read')
def get_user_roles_route(user_id):
    """Get all roles for a user"""
    roles = get_user_roles(user_id)
    
    return success_response({
        'roles': roles,
        'count': len(roles)
    })


@rbac_bp.route('/users/<user_id>/permissions', methods=['GET'])
@tenant_required
@auth_required
@require_permission('user.read')
def get_user_permissions_route(user_id):
    """Get all permissions for a user (aggregated from roles)"""
    permissions = get_all_user_permissions(user_id)
    
    return success_response({
        'permissions': permissions,
        'count': len(permissions)
    })


# ==================== CONVENIENCE ROUTES ====================

@rbac_bp.route('/roles/by-name/<role_name>/permissions', methods=['POST'])
@tenant_required
@auth_required
@require_permission('role.manage')
def assign_permission_by_name_route(role_name):
    """Assign a permission to a role using names instead of IDs"""
    data = request.get_json()
    permission_name = data.get('permission_name')
    
    if not permission_name:
        return error_response('ValidationError', 'Permission name is required', 400)
    
    result = assign_permission_to_role_by_name(role_name, permission_name)
    
    if result['success']:
        return success_response(message=result['message'], status_code=201)
    else:
        return error_response('AssignmentError', result['error'], 400)


@rbac_bp.route('/users/by-email/<email>/roles', methods=['POST'])
@tenant_required
@auth_required
@require_permission('user.manage')
def assign_role_by_email_route(email):
    """Assign a role to a user using email and role name"""
    data = request.get_json()
    role_name = data.get('role_name')
    
    if not role_name:
        return error_response('ValidationError', 'Role name is required', 400)

    tenant_id = get_tenant_id()
    result = assign_role_to_user_by_email(email, role_name, tenant_id=tenant_id)
    
    if result['success']:
        return success_response(message=result['message'], status_code=201)
    else:
        return error_response('AssignmentError', result['error'], 400)
