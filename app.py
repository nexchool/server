"""
Flask Application Factory

Production-grade application factory pattern for School ERP backend.

This module creates and configures the Flask application with all blueprints,
extensions, and middleware properly initialized.

Usage:
    >>> from app import create_app
    >>> app = create_app()
    >>> app.run()
"""

import logging

from flask import Flask, jsonify, request
from flask_cors import CORS

from config import ProductionConfig, get_config
from core.database import db, init_db
from core.extensions import init_extensions
from utils.memory_monitor import start_memory_monitor


def create_app(config_name=None):
    """
    Application factory function.
    
    Args:
        config_name: Configuration environment name ('development', 'production', etc.)
                    If None, reads from FLASK_ENV environment variable
                    
    Returns:
        Configured Flask application instance
        
    Example:
        >>> app = create_app('development')
        >>> app.run(debug=True)
    """
    # Create Flask app
    app = Flask(__name__)
    
    # Load configuration
    config_class = get_config(config_name)
    app.config.from_object(config_class)
    
    # Initialize extensions
    init_extensions(app)
    
    # Initialize database
    init_db(app)

    # Initialize Celery (ContextTask for db access in tasks) - deferred import to avoid circular
    from celery_app import init_celery
    init_celery(app)

    # Register blueprints
    register_blueprints(app)

    # Tenant resolution: resolve by subdomain or X-Tenant-ID for /api/* (except health)
    register_tenant_middleware(app)

    # Register error handlers
    register_error_handlers(app)
    
    # Register health check route
    register_health_check(app)
    
    # Production / staging initialization (shared validation on ProductionConfig)
    if issubclass(config_class, ProductionConfig):
        config_class.init_app(app)

    # Start lightweight memory monitoring (logs RSS/VMS/CPU every 30s)
    start_memory_monitor(interval=30)

    return app


def register_tenant_middleware(app: Flask):
    """
    Register before_request to resolve tenant for API routes.
    Skips: /api/health, /api, /api/platform/*, and /api/auth/*.
    Auth routes resolve tenant themselves via resolve_tenant_for_auth() (body, header, subdomain, default)
    so login works on single domain / localhost without a tenant in the URL.
    """
    from core.tenant import resolve_tenant

    @app.before_request
    def _ensure_tenant():
        path = request.path.rstrip("/") if request.path else ""
        if path in ("/api/health", "/api"):
            return None
        if request.path.startswith("/api/platform/"):
            return None
        # Auth routes resolve tenant in the route (supports body subdomain/tenant_id, header, host, default)
        if request.path.startswith("/api/auth/"):
            return None
        # CORS preflight: skip tenant resolution so OPTIONS succeeds and browser can send actual request
        if request.method == "OPTIONS":
            return None
        if request.path.startswith("/api/"):
            return resolve_tenant()
        return None


def register_blueprints(app: Flask):
    """
    Register all application blueprints.
    
    Blueprint Organization:
    - /api/auth - Authentication (login, register, logout, etc.)
    - /api/rbac - RBAC management (roles, permissions)
    - /api/users - User management
    
    Future modules can be added here following the same pattern.
    
    Args:
        app: Flask application instance
    """
    # Import blueprints
    from modules.auth import auth_bp
    from modules.rbac import rbac_bp
    from modules.users import users_bp
    from modules.classes import classes_bp
    from modules.students import students_bp
    from modules.teachers import teachers_bp
    from modules.attendance import attendance_bp
    from modules.platform import platform_bp
    from modules.finance import finance_bp
    from modules.academics import academics_bp
    from modules.notifications import notifications_bp
    from modules.subjects import subjects_bp
    from modules.timetable import timetable_bp
    from modules.schedule import schedule_bp
    from modules.holidays import holidays_bp
    from modules.fees import fees_bp
    from modules.transport import transport_bp
    from modules.devices import devices_bp
    from modules.dashboard import dashboard_bp

    # Register blueprints with URL prefixes
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(platform_bp, url_prefix='/api/platform')
    app.register_blueprint(rbac_bp, url_prefix='/api/rbac')
    app.register_blueprint(users_bp, url_prefix='/api/users')
    app.register_blueprint(classes_bp, url_prefix='/api/classes')
    app.register_blueprint(students_bp, url_prefix='/api/students')
    app.register_blueprint(teachers_bp, url_prefix='/api/teachers')
    app.register_blueprint(attendance_bp, url_prefix='/api/attendance')
    app.register_blueprint(finance_bp, url_prefix='/api/finance')
    app.register_blueprint(academics_bp, url_prefix='/api/academics')
    app.register_blueprint(subjects_bp, url_prefix='/api/subjects')
    app.register_blueprint(timetable_bp, url_prefix='/api/timetable')
    app.register_blueprint(schedule_bp, url_prefix='/api/schedule')
    app.register_blueprint(notifications_bp, url_prefix='/api/notifications')
    app.register_blueprint(holidays_bp, url_prefix='/api/holidays')
    app.register_blueprint(fees_bp, url_prefix='/api/fees')
    app.register_blueprint(transport_bp, url_prefix='/api/transport')
    app.register_blueprint(devices_bp, url_prefix='/api/devices')
    app.register_blueprint(dashboard_bp, url_prefix='/api/dashboard')


def register_error_handlers(app: Flask):
    """
    Register global error handlers with logging.
    
    Provides consistent error responses and logs all API errors to the terminal.
    
    Args:
        app: Flask application instance
    """
    logger = logging.getLogger(__name__)

    def _log_error(status_code: int, error_type: str, error_msg: str, exc=None):
        """Log API error with request context."""
        ctx = f"{request.method} {request.path}"
        msg = f"[API Error] {status_code} {ctx} | {error_type}: {error_msg}"
        if status_code >= 500:
            logger.error(msg, exc_info=exc)
        else:
            logger.warning(msg)

    @app.errorhandler(404)
    def not_found(error):
        """Handle 404 Not Found errors"""
        _log_error(404, "NotFound", str(getattr(error, "description", "Resource not found")))
        return jsonify({
            'success': False,
            'error': 'NotFound',
            'message': 'Resource not found'
        }), 404

    @app.errorhandler(500)
    def internal_error(error):
        """Handle 500 Internal Server errors"""
        _log_error(500, "InternalServerError", str(error), exc=True)
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': 'InternalServerError',
            'message': 'An internal server error occurred'
        }), 500

    @app.errorhandler(400)
    def bad_request(error):
        """Handle 400 Bad Request errors"""
        _log_error(400, "BadRequest", str(getattr(error, "description", error)))
        return jsonify({
            'success': False,
            'error': 'BadRequest',
            'message': 'Invalid request'
        }), 400

    @app.errorhandler(403)
    def forbidden(error):
        """Handle 403 Forbidden errors"""
        _log_error(403, "Forbidden", str(getattr(error, "description", "Access forbidden")))
        return jsonify({
            'success': False,
            'error': 'Forbidden',
            'message': 'Access forbidden'
        }), 403

    @app.errorhandler(401)
    def unauthorized(error):
        """Handle 401 Unauthorized errors"""
        _log_error(401, "Unauthorized", str(getattr(error, "description", "Authentication required")))
        return jsonify({
            'success': False,
            'error': 'Unauthorized',
            'message': 'Authentication required'
        }), 401

    @app.errorhandler(Exception)
    def handle_unhandled_exception(error):
        """Catch-all for unhandled exceptions with full traceback."""
        _log_error(500, type(error).__name__, str(error), exc=True)
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': 'InternalServerError',
            'message': 'An internal server error occurred'
        }), 500

    @app.after_request
    def log_error_responses(response):
        """Log any 4xx/5xx response from routes that return error_response() directly."""
        if response.status_code >= 400 and request.path.startswith("/api/"):
            try:
                body = response.get_json(silent=True)
                err_type = body.get("error", "Unknown") if body else "Unknown"
                err_msg = body.get("message", "") if body else ""
                ctx = f"{request.method} {request.path}"
                msg = f"[API Error] {response.status_code} {ctx} | {err_type}: {err_msg}"
                if response.status_code >= 500:
                    logger.error(msg)
                else:
                    logger.warning(msg)
            except Exception:
                logger.warning(
                    "[API Error] %s %s %s",
                    response.status_code,
                    request.method,
                    request.path,
                )
        return response


def register_health_check(app: Flask):
    """
    Register health check endpoint.
    
    Useful for monitoring, load balancers, and container orchestration.
    
    Args:
        app: Flask application instance
    """
    
    @app.route('/api/health', methods=['GET'])
    def health_check():
        """
        Health check endpoint.
        
        Returns:
            200: Service is healthy
        """
        return jsonify({
            'status': 'healthy',
            'service': 'School ERP Backend',
            'version': '1.0.0'
        }), 200
    
    @app.route('/api', methods=['GET'])
    def api_root():
        """
        API root endpoint.
        
        Returns:
            200: API information
        """
        return jsonify({
            'message': 'School ERP Backend API',
            'version': '1.0.0',
            'endpoints': {
                'auth': '/api/auth',
                'rbac': '/api/rbac',
                'users': '/api/users',
                'classes': '/api/classes',
                'students': '/api/students',
                'teachers': '/api/teachers',
                'attendance': '/api/attendance',
                'finance': '/api/finance',
                'fees': '/api/fees',
                'academics': '/api/academics',
                'subjects': '/api/subjects',
                'notifications': '/api/notifications',
                'devices': '/api/devices',
                'platform': '/api/platform',
                'health': '/api/health',
                'fees': '/api/fees'
            }
        }), 200


# Create application instance
app = create_app()


if __name__ == '__main__':
    """
    Development server entry point.
    
    For production, use Gunicorn (run from app/ directory):
        ./run_gunicorn.sh
    Or manually:
        cd app && gunicorn -c gunicorn_conf.py "app:app"
    On macOS with Conda, set: export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
    """
    import os
    
    # Use 0.0.0.0 to listen on all network interfaces
    # Port 5001 because macOS AirPlay Receiver uses port 5000 by default
    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_PORT', 5001))
    debug = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'
    
    print(f"\n{'='*60}")
    print(f"Starting School ERP Backend Server")
    print(f"{'='*60}")
    print(f"Environment: {os.getenv('FLASK_ENV', 'development')}")
    print(f"Host: {host}")
    print(f"Port: {port}")
    print(f"Debug: {debug}")
    print(f"{'='*60}\n")
    
    app.run(host=host, port=port, debug=debug)
