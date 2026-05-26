"""
Flask Extensions Module

Centralized initialization of Flask extensions.
Extensions are initialized here and then imported throughout the app.
"""

import re

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
        'allow_headers': app.config.get('CORS_ALLOW_HEADERS', ['Content-Type', 'Authorization', 'X-Refresh-Token', 'X-Tenant-ID', 'X-Tenant-Subdomain']),
        'expose_headers': app.config.get('CORS_EXPOSE_HEADERS', ['X-New-Access-Token']),
        'supports_credentials': app.config.get('CORS_SUPPORTS_CREDENTIALS', True)
    }

    # CORS_ORIGIN_REGEX (env var): a single regex that allows any matching origin.
    # Use in production to accept all tenant subdomains without listing them individually.
    # Example: CORS_ORIGIN_REGEX=^https://[a-z0-9-]+\.nexchool\.in$
    import os
    cors_origin_regex = os.getenv('CORS_ORIGIN_REGEX', '').strip()
    if cors_origin_regex:
        try:
            cors_config['origins'] = [re.compile(cors_origin_regex)]
        except re.error as exc:
            app.logger.warning('CORS_ORIGIN_REGEX is invalid and was ignored: %s', exc)

    # Auto-expand wildcard *.localhost support: for every http://localhost:PORT
    # (or 127.0.0.1:PORT) in the origins list, also allow http://*.localhost:PORT.
    # This means adding a new school subdomain only requires an /etc/hosts entry,
    # not a manual CORS_ORIGINS update in .env.local.
    origins = cors_config['origins']
    if isinstance(origins, list) and origins != ['*']:
        extra = []
        for o in origins:
            if not isinstance(o, str):
                continue
            m = re.match(r'^(https?)://(localhost|127\.0\.0\.1)(?::(\d+))?$', o)
            if m:
                scheme, _, port = m.group(1), m.group(2), m.group(3)
                port_part = f':{port}' if port else ''
                extra.append(re.compile(rf'^{scheme}://[a-z0-9-]+\.localhost{port_part}$'))
        if extra:
            cors_config['origins'] = origins + extra

    cors.init_app(app, resources={
        r"/api/*": cors_config
    })

    # Initialize Mail
    mail.init_app(app)

    # Initialize rate limiter (per-route limits applied on login and platform routes)
    limiter.init_app(app)
