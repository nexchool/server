"""
User Management Services

Business logic for user administration and management.
"""

from typing import List, Dict, Optional
from sqlalchemy import or_

from backend.core.database import db
from backend.core.tenant import get_tenant_id
from backend.modules.auth.models import User
from backend.shared.utils import paginate_query


def list_users(
    search: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
    email_verified: Optional[bool] = None,
    tenant_id: Optional[str] = None,
) -> Dict:
    """
    List all users with optional search and filters (tenant-scoped).
    
    Args:
        search: Search string for email or name
        page: Page number (1-indexed)
        per_page: Items per page
        email_verified: Filter by email verification status
        tenant_id: Tenant ID (defaults to g.tenant_id when in request context)
        
    Returns:
        Dictionary with paginated user data
    """
    if tenant_id is None:
        tenant_id = get_tenant_id()
    query = User.query
    if tenant_id is not None:
        query = query.filter(User.tenant_id == tenant_id)
    
    # Apply search filter
    if search:
        search_pattern = f'%{search}%'
        query = query.filter(
            or_(
                User.email.ilike(search_pattern),
                User.name.ilike(search_pattern)
            )
        )
    
    # Apply email verification filter
    if email_verified is not None:
        query = query.filter(User.email_verified == email_verified)
    
    # Order by created_at descending
    query = query.order_by(User.created_at.desc())
    
    # Paginate
    result = paginate_query(query, page, per_page)
    
    # Serialize users
    result['items'] = [serialize_user(user) for user in result['items']]
    
    return result


def get_user_by_id(user_id: str) -> Optional[Dict]:
    """
    Get a single user by ID.
    
    Args:
        user_id: User ID
        
    Returns:
        User dictionary or None if not found
    """
    user = User.query.get(user_id)
    if not user:
        return None
    
    return serialize_user(user, include_metadata=True)


def get_user_by_email(email: str, tenant_id: Optional[str] = None) -> Optional[Dict]:
    """
    Get a single user by email (tenant-scoped).
    
    Args:
        email: User email
        tenant_id: Tenant ID (defaults to g.tenant_id when in request context)
        
    Returns:
        User dictionary or None if not found
    """
    if tenant_id is None:
        tenant_id = get_tenant_id()
    q = User.query.filter_by(email=email)
    if tenant_id is not None:
        q = q.filter_by(tenant_id=tenant_id)
    user = q.first()
    if not user:
        return None
    return serialize_user(user, include_metadata=True)


def update_user(user_id: str, data: Dict) -> Dict:
    """
    Update a user's profile information.
    
    Args:
        user_id: User ID
        data: Dictionary with fields to update (name, profile_picture_url, etc.)
        
    Returns:
        Result dictionary with success status
        
    Example:
        >>> result = update_user('user-123', {'name': 'John Doe'})
        >>> print(result['success'])
        True
    """
    try:
        user = User.query.get(user_id)
        if not user:
            return {'success': False, 'error': 'User not found'}
        
        # Update allowed fields
        allowed_fields = ['name', 'profile_picture_url']
        for field in allowed_fields:
            if field in data:
                setattr(user, field, data[field])
        
        user.save()
        
        return {
            'success': True,
            'user': serialize_user(user)
        }
    except Exception as e:
        db.session.rollback()
        return {
            'success': False,
            'error': str(e)
        }


def delete_user(user_id: str) -> Dict:
    """
    Delete a user and all associated data.
    
    Args:
        user_id: User ID
        
    Returns:
        Result dictionary with success status
        
    Warning:
        This will permanently delete the user and all their sessions.
    """
    try:
        user = User.query.get(user_id)
        if not user:
            return {'success': False, 'error': 'User not found'}
        
        # Delete user (cascade will handle sessions)
        db.session.delete(user)
        db.session.commit()
        
        return {
            'success': True,
            'message': 'User deleted successfully'
        }
    except Exception as e:
        db.session.rollback()
        return {
            'success': False,
            'error': str(e)
        }


def verify_user_email(user_id: str) -> Dict:
    """
    Manually verify a user's email (admin action).
    
    Args:
        user_id: User ID
        
    Returns:
        Result dictionary with success status
    """
    try:
        user = User.query.get(user_id)
        if not user:
            return {'success': False, 'error': 'User not found'}
        
        if user.email_verified:
            return {'success': False, 'error': 'Email already verified'}
        
        user.email_verified = True
        user.verification_token = None
        user.save()
        
        return {
            'success': True,
            'message': 'Email verified successfully'
        }
    except Exception as e:
        db.session.rollback()
        return {
            'success': False,
            'error': str(e)
        }


def serialize_user(user: User, include_metadata: bool = False) -> Dict:
    """
    Serialize a user object to dictionary.
    
    Args:
        user: User object
        include_metadata: Include timestamps and verification status
        
    Returns:
        User dictionary
    """
    data = {
        'id': user.id,
        'email': user.email,
        'name': user.name,
        'profile_picture_url': user.profile_picture_url,
        'email_verified': user.email_verified,
    }
    
    if include_metadata:
        data.update({
            'last_login_at': user.last_login_at.isoformat() if user.last_login_at else None,
            'created_at': user.created_at.isoformat(),
            'updated_at': user.updated_at.isoformat(),
        })
    
    return data
