"""
Application Settings

Production-grade configuration management using class-based configs.
Separates concerns between development and production environments.
"""

import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


def _get_bool_env(var_name: str, default: bool = False) -> bool:
    """Parse common boolean env values (true/false, 1/0, yes/no)."""
    value = os.getenv(var_name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    """Base configuration shared across all environments"""
    
    # Application
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    DEBUG = False
    TESTING = False
    
    # Database
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False
    
    # JWT Configuration
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', SECRET_KEY)
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=int(os.getenv('JWT_ACCESS_TOKEN_EXPIRES_MINUTES', 15)))
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=int(os.getenv('JWT_REFRESH_TOKEN_EXPIRES_DAYS', 7)))
    JWT_ALGORITHM = 'HS256'
    
    # Password Reset
    RESET_TOKEN_EXP_MINUTES = int(os.getenv('RESET_TOKEN_EXP_MINUTES', 30))
    
    # Email Configuration (support both MAIL_* and SMTP_*/EMAIL_* env vars)
    MAIL_SERVER = os.getenv('MAIL_SERVER') or os.getenv('SMTP_SERVER')
    MAIL_PORT = int(os.getenv('MAIL_PORT') or os.getenv('SMTP_PORT', 587))
    MAIL_USE_TLS = _get_bool_env('MAIL_USE_TLS', True)
    MAIL_USE_SSL = _get_bool_env('MAIL_USE_SSL', False)
    if MAIL_USE_TLS and MAIL_USE_SSL:
        # Flask-Mail transports should not enable both at once.
        MAIL_USE_TLS = False
    MAIL_USERNAME = os.getenv('MAIL_USERNAME') or os.getenv('EMAIL_ADDRESS')
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD') or os.getenv('EMAIL_PASSWORD')
    _sender = os.getenv('MAIL_DEFAULT_SENDER') or MAIL_USERNAME
    if os.getenv('DEFAULT_SENDER_NAME') and MAIL_USERNAME and _sender == MAIL_USERNAME:
        MAIL_DEFAULT_SENDER = (os.getenv('DEFAULT_SENDER_NAME'), MAIL_USERNAME)
    else:
        MAIL_DEFAULT_SENDER = _sender
    
    # URLs
    BACKEND_URL = os.getenv('BACKEND_URL', 'http://0.0.0.0:5001')
    FRONTEND_URL = os.getenv('FRONTEND_URL', 'exp://192.168.1.1:8081')
    
    # RBAC
    DEFAULT_USER_ROLE = os.getenv('DEFAULT_USER_ROLE', 'Student')

    # Tenant: when no subdomain/header/body tenant is provided, use this subdomain for auth (e.g. login on single domain or localhost)
    DEFAULT_TENANT_SUBDOMAIN = os.getenv('DEFAULT_TENANT_SUBDOMAIN', 'default')

    # Cookie (Lax for same-origin; production overrides to None for cross-domain panel)
    SESSION_COOKIE_SAMESITE = 'Lax'

    # CORS: when CORS_ORIGINS env is set, use it (required for credentialed cross-origin requests).
    # When unset (local dev), use '*' — but '*' fails with credentials; set CORS_ORIGINS for cross-origin panel.
    _cors_env = os.getenv('CORS_ORIGINS', '').strip()
    CORS_ORIGINS = [o.strip() for o in _cors_env.split(',') if o.strip()] if _cors_env else ['*']
    CORS_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']
    CORS_ALLOW_HEADERS = ['Content-Type', 'Authorization', 'X-Refresh-Token', 'X-Tenant-ID']
    CORS_EXPOSE_HEADERS = ['X-New-Access-Token']
    CORS_SUPPORTS_CREDENTIALS = True

    # Rate limiting (storage URL optional; default in-memory)
    RATELIMIT_ENABLED = True
    RATELIMIT_DEFAULT = "200 per minute"
    
    # Pagination
    DEFAULT_PAGE_SIZE = 20
    MAX_PAGE_SIZE = 100

    # S3 (document storage) — single bucket; S3_ENV_PREFIX separates local/prod keys
    AWS_REGION = os.getenv("AWS_REGION")
    AWS_S3_BUCKET_NAME = os.getenv("AWS_S3_BUCKET_NAME") or os.getenv("S3_BUCKET_NAME")
    S3_BUCKET_NAME = AWS_S3_BUCKET_NAME  # legacy alias
    AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
    AWS_SESSION_TOKEN = os.getenv("AWS_SESSION_TOKEN")
    _raw_prefix = os.getenv("S3_ENV_PREFIX", "").strip()
    S3_ENV_PREFIX = _raw_prefix or (
        "prod" if os.getenv("FLASK_ENV", "development").lower() in ("production", "staging") else "local"
    )

    # Celery
    # In Docker Compose, Redis is reachable via the `redis` service name.
    # If you run locally without Compose, override REDIS_URL to point at your local Redis.
    REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
    CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", os.getenv("REDIS_URL", "redis://redis:6379/0"))
    CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", os.getenv("REDIS_URL", "redis://redis:6379/0"))


class DevelopmentConfig(Config):
    """Development environment configuration"""
    
    DEBUG = True
    SQLALCHEMY_ECHO = False  # Set to True to see SQL queries
    
    # Override URLs for development
    BACKEND_URL = os.getenv('BACKEND_URL_DEV', 'http://0.0.0.0:5001')
    FRONTEND_URL = os.getenv('FRONTEND_URL_DEV', f"exp://{os.getenv('LOCAL_IP', '192.168.1.1')}:8081")


class ProductionConfig(Config):
    """Production environment configuration"""

    DEBUG = False
    TESTING = False

    # Production must have these set
    BACKEND_URL = os.getenv('BACKEND_URL')  # Must be set in production
    FRONTEND_URL = os.getenv('FRONTEND_URL', 'schoolerp://')
    
    # Production inherits CORS_ORIGINS from Config (which reads env); override only if env empty
    if not (os.getenv('CORS_ORIGINS', '').strip()):
        CORS_ORIGINS = []  # Force explicit config; empty will fail — must set CORS_ORIGINS in prod

    # Secure cookies (SESSION_COOKIE_SECURE=false only for rare HTTP-only labs; default true)
    SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "true").lower() == "true"
    SESSION_COOKIE_HTTPONLY = True
    # Use 'None' when panel and API are on different domains (cross-site); 'Lax' when same domain
    SESSION_COOKIE_SAMESITE = os.getenv('SESSION_COOKIE_SAMESITE', 'None')
    
    @classmethod
    def init_app(cls, app):
        """Production-specific initialization"""
        # Validate critical config
        if not cls.BACKEND_URL:
            raise ValueError("BACKEND_URL must be set in production")
        if cls.SECRET_KEY == 'dev-secret-key-change-in-production':
            raise ValueError("SECRET_KEY must be changed in production")


class StagingConfig(ProductionConfig):
    """Staging: production-like validation; inherits SESSION_COOKIE_SECURE from ProductionConfig (env-driven)."""


def is_production():
    """True for production or staging (use production-style URLs and behavior, not local dev)."""
    return os.getenv("FLASK_ENV", "development") in ("production", "staging")


def get_backend_url():
    """Returns the backend API URL"""
    if is_production():
        return os.getenv("BACKEND_URL") or "https://api.yourapp.com"
    return os.getenv("BACKEND_URL_DEV") or "http://0.0.0.0:5001"


def get_frontend_url():
    """Returns the frontend/app URL for deep linking"""
    if is_production():
        return os.getenv("FRONTEND_URL") or "schoolerp://"
    
    frontend_url = os.getenv("FRONTEND_URL_DEV")
    if frontend_url:
        return frontend_url
    
    local_ip = os.getenv("LOCAL_IP")
    expo_port = os.getenv("EXPO_PORT") or "8081"
    return f"exp://{local_ip}:{expo_port}"


def get_reset_password_url(token: str, email: str) -> str:
    """Generates the password reset URL"""
    base_url = get_frontend_url()
    return f"{base_url}/--/reset-password?token={token}&email={email}"


def get_email_verification_url(token: str, email: str) -> str:
    """Generates the email verification URL"""
    base_url = get_backend_url()
    return f"{base_url}/api/auth/email/validate?token={token}&email={email}"


def get_app_verification_success_url(access_token: str, refresh_token: str, user_id: str, email: str) -> str:
    """Generates the app deep link URL for successful email verification"""
    base_url = get_frontend_url()
    return f"{base_url}/--/verify-email?status=success&access_token={access_token}&refresh_token={refresh_token}&user_id={user_id}&email={email}"


def get_app_verification_error_url(error: str) -> str:
    """Generates the app deep link URL for failed email verification"""
    base_url = get_frontend_url()
    return f"{base_url}/--/verify-email?status=error&error={error}"
