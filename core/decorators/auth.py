"""
Authentication Decorator

Provides the @auth_required decorator for protecting routes that need authentication.
Handles JWT validation and token refresh logic.
"""

from functools import wraps
from flask import request, jsonify, g
from datetime import datetime


def auth_required(fn):
    """
    Decorator to protect routes requiring authentication.
    
    This decorator:
    1. Validates the access token from Authorization header
    2. If expired, attempts to refresh using X-Refresh-Token header
    3. Sets g.current_user for use in route handlers
    4. Returns 401 if authentication fails
    
    The decorator must be the OUTERMOST decorator (closest to the route).
    Other decorators like @require_permission should come after this.
    
    Usage:
        @bp.route('/protected')
        @auth_required
        def protected_route():
            # g.current_user is now available
            return jsonify({'user_id': g.current_user.id})
    
    Headers:
        Authorization: Bearer <access_token>
        X-Refresh-Token: <refresh_token> (optional, for token refresh)
        
    Response Headers:
        X-New-Access-Token: <new_access_token> (if token was refreshed)
    """
    def _account_inactive(user):
        """True if the user is soft-deleted or suspended.

        A live access token outlives suspension/soft-delete (~15 min) unless we
        re-check status on every request. Returning True here lets the caller
        reject with 401 immediately, so revocation takes effect at once instead
        of only on the next refresh.
        """
        return (
            getattr(user, "deleted_at", None) is not None
            or getattr(user, "is_suspended", False)
        )

    @wraps(fn)
    def wrapper(*args, **kwargs):
        # CORS preflight: allow OPTIONS without auth
        if request.method == "OPTIONS":
            return ("", 204)

        # Import here to avoid circular imports
        from modules.auth.models import User, Session
        from modules.auth.services import validate_jwt_token, refresh_access_token
        
        # Check for Authorization header or auth-token cookie (for panel / Super Admin)
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            access_token = auth_header.split(" ", 1)[1]
        else:
            access_token = request.cookies.get("auth-token")
        if not access_token:
            return jsonify({"error": "Missing access token"}), 401

        # Try to validate the access token
        payload = validate_jwt_token(access_token, token_type="access")
        if payload:
            # Token is valid, get user
            user = User.query.get(payload["sub"])
            if not user:
                return jsonify({"error": "User not found"}), 401

            # Re-check account status on every request so a suspension or
            # soft-delete cuts the user off immediately, not when the live
            # access token finally expires. 401 (not 403) routes admin-web
            # through its logout+redirect-to-login path, where a re-login then
            # surfaces the proper 403 AccountSuspended / invalid-credentials.
            if _account_inactive(user):
                return jsonify({"error": "Session expired"}), 401

            g.current_user = user
            return fn(*args, **kwargs)

        # Access token expired, try to refresh
        refresh_token = request.headers.get("X-Refresh-Token")
        if not refresh_token:
            return jsonify({"error": "Access token expired"}), 401

        new_access_token = refresh_access_token(refresh_token, request)
        if not new_access_token:
            return jsonify({"error": "Invalid refresh token"}), 401

        # Get session and user
        session = Session.query.filter_by(
            refresh_token=refresh_token,
            revoked=False
        ).first()

        if not session:
            return jsonify({"error": "Session not found"}), 401

        # Set current user from session
        user = session.user

        # Defense in depth: the refresh path already revokes sessions on
        # suspend/delete, but re-check here too so a stale-but-unrevoked
        # session can never re-mint access for an inactive account.
        if _account_inactive(user):
            return jsonify({"error": "Session expired"}), 401

        g.current_user = user

        # Update session last accessed time
        session.last_accessed_at = datetime.utcnow()
        session.save()

        # Call the route handler
        response = fn(*args, **kwargs)
        
        # Add new access token to response headers
        if hasattr(response, 'headers'):
            response.headers["X-New-Access-Token"] = new_access_token
        else:
            # Handle tuple responses like (data, status_code)
            from flask import make_response
            response = make_response(response)
            response.headers["X-New-Access-Token"] = new_access_token

        return response

    return wrapper
