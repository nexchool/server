"""
Authentication Services

Business logic for authentication, JWT token management, and sessions.
"""

import jwt
from datetime import datetime, timedelta
import os
from typing import Optional, Tuple, Dict, List

from flask import Request

from .models import User, Session
from backend.core.database import db
from backend.core.models import Tenant
from backend.core.models import TENANT_STATUS_ACTIVE


# JWT Configuration
JWT_SECRET = os.getenv("JWT_SECRET_KEY", "your_default_secret_key")
JWT_ALGORITHM = "HS256"
JWT_ACCESS_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES_MINUTES", 15))
JWT_REFRESH_DAYS = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRES_DAYS", 7))


# ==================== JWT Token Generation ====================

def generate_access_token(user: User, access_minutes: Optional[int] = None) -> str:
    """
    Generate a short-lived access token for API authentication.

    Args:
        user: User object
        access_minutes: Optional override for token expiry (e.g. from platform settings).
                        If None, uses JWT_ACCESS_MINUTES from env.
    Returns:
        JWT access token string
    """
    minutes = access_minutes if access_minutes is not None else JWT_ACCESS_MINUTES
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "type": "access",
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def generate_refresh_token(user: User) -> str:
    """
    Generate a long-lived refresh token for obtaining new access tokens.
    
    Args:
        user: User object
        
    Returns:
        JWT refresh token string
        
    Token Payload:
        - sub: User ID
        - type: 'refresh'
        - iat: Issued at timestamp
        - exp: Expiration timestamp
    """
    payload = {
        "sub": str(user.id),
        "type": "refresh",
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(days=JWT_REFRESH_DAYS),
    }

    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def generate_token_pair(user: User) -> Dict[str, str]:
    """
    Generate both access and refresh tokens for a user.
    
    Args:
        user: User object
        
    Returns:
        Dictionary with 'access_token' and 'refresh_token'
    """
    return {
        'access_token': generate_access_token(user),
        'refresh_token': generate_refresh_token(user)
    }


# ==================== JWT Token Validation ====================

def validate_jwt_token(token: str, token_type: str = "access") -> Optional[Dict]:
    """
    Validate and decode a JWT token.
    
    Args:
        token: JWT token string
        token_type: Expected token type ('access' or 'refresh')
        
    Returns:
        Decoded token payload if valid, None otherwise
        
    Validation Rules:
        - Token must be valid JWT
        - Token must not be expired
        - Token type must match expected type
    """
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM]
        )

        # Verify token type
        if payload.get("type") != token_type:
            return None

        return payload

    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def refresh_access_token(refresh_token: str, request: Request = None) -> Optional[str]:
    """
    Generate a new access token using a refresh token.
    
    Args:
        refresh_token: JWT refresh token
        request: Flask request object (for updating session metadata)
        
    Returns:
        New access token if refresh is valid, None otherwise
        
    Process:
        1. Validate refresh token
        2. Check if session exists and is not revoked
        3. Check if refresh token hasn't expired
        4. Generate new access token
        5. Update session last_accessed_at
    """
    # Validate refresh token
    payload = validate_jwt_token(refresh_token, "refresh")
    if not payload:
        return None

    # Check if session exists and is valid
    session = Session.query.filter_by(
        refresh_token=refresh_token,
        revoked=False
    ).first()

    if not session or session.refresh_token_expires_at < datetime.utcnow():
        return None

    # Generate new access token
    new_access_token = generate_access_token(session.user)

    # Update session metadata
    session.last_accessed_at = datetime.utcnow()
    if request:
        session.ip_address = request.remote_addr
        session.user_agent = request.headers.get("User-Agent")

    session.save()

    return new_access_token


# ==================== Session Management ====================

def create_session(user: User, request: Request = None) -> Session:
    """
    Create a new session for a user.
    
    Args:
        user: User object
        request: Flask request object (for device metadata)
        
    Returns:
        Created Session object with refresh token
    """
    # Generate tokens
    refresh_token = generate_refresh_token(user)
    
    # Create session (tenant-scoped)
    session = Session(
        user_id=user.id,
        tenant_id=user.tenant_id,
        refresh_token=refresh_token,
        refresh_token_expires_at=datetime.utcnow() + timedelta(days=JWT_REFRESH_DAYS)
    )

    # Add device metadata if request provided
    if request:
        session.ip_address = request.remote_addr
        session.user_agent = request.headers.get("User-Agent", "")
        session.device_info = request.headers.get("User-Agent", "")
    
    session.save()
    return session


def revoke_session(session_id: str) -> bool:
    """
    Revoke a specific session.
    
    Args:
        session_id: Session ID to revoke
        
    Returns:
        True if session was revoked, False if not found
    """
    session = Session.query.get(session_id)
    if not session:
        return False
    
    session.revoke()
    return True


def revoke_all_user_sessions(user_id: str) -> int:
    """
    Revoke all sessions for a user (logout from all devices).
    
    Args:
        user_id: User ID
        
    Returns:
        Number of sessions revoked
    """
    sessions = Session.query.filter_by(user_id=user_id, revoked=False).all()
    count = 0
    
    for session in sessions:
        session.revoke()
        count += 1
    
    return count


def cleanup_expired_sessions():
    """
    Clean up expired sessions from the database.
    Should be run periodically (e.g., via cron job).
    
    Returns:
        Number of sessions deleted
    """
    expired_sessions = Session.query.filter(
        Session.refresh_token_expires_at < datetime.utcnow()
    ).all()
    
    count = len(expired_sessions)
    
    for session in expired_sessions:
        db.session.delete(session)
    
    db.session.commit()
    return count


# ==================== Authentication ====================

def authenticate_user(
    email: str,
    password: str,
    tenant_id: Optional[str] = None,
) -> Optional[User]:
    """
    Authenticate a user by email and password within a tenant.

    Args:
        email: User email
        password: Plain text password
        tenant_id: Tenant ID (required in multi-tenant; from g.tenant_id)

    Returns:
        User object if authentication successful, None otherwise
    """
    user = User.get_user_by_email(email, tenant_id=tenant_id)

    if not user:
        return None

    if not user.check_password(password):
        return None

    return user


def find_users_by_email_password(
    email: str,
    password: str,
) -> List[Tuple[User, Tenant]]:
    """
    Find all (user, tenant) pairs where the user has this email and password matches.
    Used when the app sends only email+password (no tenant) so we can identify
    which tenant(s) the user belongs to. Call only when g.tenant_id is None so
    User query is not tenant-scoped.

    Returns:
        List of (user, tenant) for active tenants only. Empty if no match.
    """
    users = User.query.filter_by(email=email).all()
    matches: List[Tuple[User, Tenant]] = []
    for u in users:
        if not u.check_password(password):
            continue
        tenant = Tenant.query.get(u.tenant_id)
        if tenant and tenant.status == TENANT_STATUS_ACTIVE:
            matches.append((u, tenant))
    return matches


def login_user(
    email: str,
    password: str,
    request: Request = None,
    tenant_id: Optional[str] = None,
) -> Optional[Tuple[User, Dict[str, str]]]:
    """
    Complete login flow: authenticate user and create session.
    
    Args:
        email: User email
        password: Plain text password
        request: Flask request object
        tenant_id: Tenant ID (from g.tenant_id in multi-tenant)
        
    Returns:
        Tuple of (User, tokens_dict) if successful, None otherwise
        tokens_dict contains 'access_token' and 'refresh_token'
    """
    # Authenticate user (tenant-scoped)
    user = authenticate_user(email, password, tenant_id=tenant_id)
    if not user:
        return None

    # Update last login
    user.last_login_at = datetime.utcnow()
    user.save()

    # Create session and generate tokens
    access_token = generate_access_token(user)
    session = create_session(user, request)
    
    tokens = {
        'access_token': access_token,
        'refresh_token': session.refresh_token
    }
    
    return user, tokens


def logout_user(refresh_token: str) -> bool:
    """
    Logout user by revoking the session.
    
    Args:
        refresh_token: Refresh token of the session to revoke
        
    Returns:
        True if logout successful, False otherwise
    """
    session = Session.query.filter_by(
        refresh_token=refresh_token,
        revoked=False
    ).first()
    
    if not session:
        return False
    
    session.revoke()
    return True
