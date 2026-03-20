"""
Flask Extensions Module

Centralized initialization of Flask extensions.
Extensions are initialized here and then imported throughout the app.
"""

from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_mail import Mail

# Initialize extensions
# These will be initialized with the app in the application factory
cors = CORS()
mail = Mail()
limiter = Limiter(key_func=get_remote_address)  # Per-route limits only (login, platform)


def init_extensions(app):
    """
    Initialize all Flask extensions with the app.

    Args:
        app: Flask application instance
    """
    # Initialize CORS
    cors_config = {
        'origins': app.config.get('CORS_ORIGINS', ['*']),
        'methods': app.config.get('CORS_METHODS', ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']),
        'allow_headers': app.config.get('CORS_ALLOW_HEADERS', ['Content-Type', 'Authorization', 'X-Refresh-Token', 'X-Tenant-ID']),
        'expose_headers': app.config.get('CORS_EXPOSE_HEADERS', ['X-New-Access-Token']),
        'supports_credentials': app.config.get('CORS_SUPPORTS_CREDENTIALS', True)
    }

    cors.init_app(app, resources={
        r"/api/*": cors_config
    })

    # Initialize Mail
    mail.init_app(app)

    # Initialize rate limiter (per-route limits applied on login and platform routes)
    limiter.init_app(app)
