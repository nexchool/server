"""
User Management Routes

API endpoints for user administration.
Requires admin permissions.

Routes:
- GET /users - List users
- GET /users/<id> - Get user details
- PUT /users/<id> - Update user
- DELETE /users/<id> - Delete user
- POST /users/<id>/verify-email - Verify user email (admin action)
"""

from flask import request, g

from . import users_bp
from backend.core.decorators import auth_required, require_permission, tenant_required
from backend.core.tenant import get_tenant_id
from backend.shared.helpers import success_response, error_response
from backend.modules.rbac.services import get_user_permissions, get_user_roles
from .services import (
    list_users, get_user_by_id, get_user_by_email,
    update_user, delete_user, verify_user_email
)


@users_bp.route('', methods=['GET'])
@tenant_required
@auth_required
@require_permission('user.read')
def list_users_route():
    """
    List all users with optional search and filters.
    
    Query Parameters:
        - search: Search string for email or name
        - page: Page number (default 1)
        - per_page: Items per page (default 20)
        - email_verified: Filter by verification status (true/false)
        
    Returns:
        200: Paginated list of users
    """
    search = request.args.get('search')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    
    # Parse email_verified filter
    email_verified = None
    if 'email_verified' in request.args:
        email_verified = request.args.get('email_verified').lower() == 'true'
    
    result = list_users(
        search=search,
        page=page,
        per_page=per_page,
        email_verified=email_verified,
        tenant_id=get_tenant_id(),
    )
    
    return success_response({
        'users': result['items'],
        'pagination': {
            'page': result['page'],
            'per_page': result['per_page'],
            'total': result['total'],
            'total_pages': result['total_pages'],
            'has_prev': result['has_prev'],
            'has_next': result['has_next']
        }
    })


@users_bp.route('/<user_id>', methods=['GET'])
@tenant_required
@auth_required
@require_permission('user.read')
def get_user_route(user_id):
    """
    Get detailed information about a specific user.
    
    Returns:
        200: User details with roles and permissions
        404: User not found
    """
    user = get_user_by_id(user_id)
    
    if not user:
        return error_response('NotFound', 'User not found', 404)
    
    # Get user roles and permissions
    roles = get_user_roles(user_id)
    permissions = get_user_permissions(user_id)
    
    return success_response({
        'user': user,
        'roles': roles,
        'permissions': permissions
    })


@users_bp.route('/<user_id>', methods=['PUT'])
@tenant_required
@auth_required
@require_permission('user.manage')
def update_user_route(user_id):
    """
    Update a user's profile information.
    
    Request Body:
        - name: User name (optional)
        - profile_picture_url: Profile picture URL (optional)
        
    Returns:
        200: User updated successfully
        400: Update failed
        404: User not found
    """
    data = request.get_json()
    
    result = update_user(user_id, data)
    
    if result['success']:
        return success_response(result['user'], 'User updated successfully')
    else:
        status_code = 404 if result['error'] == 'User not found' else 400
        return error_response('UpdateError', result['error'], status_code)


@users_bp.route('/<user_id>', methods=['DELETE'])
@tenant_required
@auth_required
@require_permission('user.manage')
def delete_user_route(user_id):
    """
    Delete a user permanently.
    
    Returns:
        200: User deleted successfully
        400: Deletion failed
        404: User not found
    """
    # Prevent deleting yourself
    if g.current_user.id == user_id:
        return error_response(
            'ForbiddenAction',
            'You cannot delete your own account',
            400
        )
    
    result = delete_user(user_id)
    
    if result['success']:
        return success_response(message=result['message'])
    else:
        status_code = 404 if result['error'] == 'User not found' else 400
        return error_response('DeleteError', result['error'], status_code)


@users_bp.route('/<user_id>/verify-email', methods=['POST'])
@tenant_required
@auth_required
@require_permission('user.manage')
def verify_email_route(user_id):
    """
    Manually verify a user's email (admin action).
    
    Returns:
        200: Email verified successfully
        400: Verification failed
        404: User not found
    """
    result = verify_user_email(user_id)
    
    if result['success']:
        return success_response(message=result['message'])
    else:
        status_code = 404 if result['error'] == 'User not found' else 400
        return error_response('VerificationError', result['error'], status_code)


@users_bp.route('/by-email/<email>', methods=['GET'])
@tenant_required
@auth_required
@require_permission('user.read')
def get_user_by_email_route(email):
    """
    Get user by email address (tenant-scoped).
    
    Returns:
        200: User details
        404: User not found
    """
    user = get_user_by_email(email, tenant_id=get_tenant_id())
    
    if not user:
        return error_response('NotFound', 'User not found', 404)
    
    # Get user roles and permissions
    roles = get_user_roles(user['id'])
    permissions = get_user_permissions(user['id'])
    
    return success_response({
        'user': user,
        'roles': roles,
        'permissions': permissions
    })
