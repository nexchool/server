"""Authentication decorator for REST routes.

The authentication rules live in :mod:`core.authentication`, shared with the
GraphQL transport. This module only maps the outcome onto HTTP.
"""

from functools import wraps

from flask import jsonify, request

from core.authentication import authenticate_request


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

    @wraps(fn)
    def wrapper(*args, **kwargs):
        # CORS preflight: allow OPTIONS without auth
        if request.method == "OPTIONS":
            return ("", 204)

        outcome = authenticate_request()
        if outcome.failed:
            return jsonify({"error": outcome.error}), 401

        response = fn(*args, **kwargs)

        if outcome.new_access_token:
            if not hasattr(response, "headers"):
                # Handle tuple responses like (data, status_code)
                from flask import make_response

                response = make_response(response)
            response.headers["X-New-Access-Token"] = outcome.new_access_token

        return response

    return wrapper
