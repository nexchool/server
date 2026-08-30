"""
Flask Extensions Module

Centralized initialization of Flask extensions.
Extensions are initialized here and then imported throughout the app.
"""

import os
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
    #
    # Share the counters in Redis. Without a storage URI Flask-Limiter keeps them
    # in process memory, and this runs four gunicorn workers by default — so
    # `@limiter.limit("5 per minute")` on login was five attempts *per worker*,
    # four times the protection the security guardrails ask for, and the count
    # reset on every deploy. The in-memory backend also spawns a expiry thread
    # per process and raised `RuntimeError: threads can only be started once`
    # under load, which surfaced as intermittent 500s on any limited route.
    #
    # Falls back to in-memory when Redis is not configured (tests, a bare local
    # run) and when it is configured but unreachable — a rate limiter should
    # degrade rather than take the API down with it.
    _configure_rate_limit_storage(app.config)
    limiter.init_app(app)


def _configure_rate_limit_storage(config) -> None:
    """Choose where the rate limiter keeps its counters.

    `RATELIMIT_STORAGE_URI` is read from the environment first, so the limiter
    can be given a database of its own rather than sharing the broker's.
    `.env.prod` has always set `RATELIMIT_STORAGE_URL` — a name Flask-Limiter
    does not recognise and nothing here ever read — so the separation it
    described never happened and the counters have been sitting in database 0
    alongside the queued task messages.

    That matters once eviction is off: a full Redis must not be able to drop a
    login counter, and it must not be able to drop a queued email either.
    """
    explicit = os.getenv("RATELIMIT_STORAGE_URI", "").strip()
    redis_url = os.getenv("REDIS_URL", "").strip()
    storage = explicit or redis_url
    if storage:
        config.setdefault("RATELIMIT_STORAGE_URI", storage)
        config.setdefault("RATELIMIT_IN_MEMORY_FALLBACK_ENABLED", True)
