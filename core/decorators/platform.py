"""
Platform Admin Decorator

Provides @platform_admin_required for routes that only platform (super) admins may access.
Must be used together with @auth_required (auth_required must run first so g.current_user is set).
"""

from functools import wraps
from flask import g, jsonify


def platform_admin_required(fn):
    """
    Decorator that restricts access to users with is_platform_admin=True.

    Use after @auth_required so g.current_user is set.
    Returns 403 if user is not a platform admin.

    Usage:
        @platform_bp.route('/dashboard')
        @auth_required
        @platform_admin_required
        def dashboard():
            ...
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not getattr(g, "current_user", None):
            return jsonify(
                success=False,
                error="Unauthorized",
                message="Authentication required",
            ), 401
        if not getattr(g.current_user, "is_platform_admin", False):
            return jsonify(
                success=False,
                error="Forbidden",
                message="Platform admin access required",
            ), 403
        return fn(*args, **kwargs)
    return wrapper
