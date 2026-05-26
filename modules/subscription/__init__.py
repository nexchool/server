"""
Subscription Module

Holds the helpers that bridge tenant lifecycle (trial / active / suspended)
and per-tenant usage tracking, plus a tenant-facing read endpoint at
/api/subscription/state used by the admin-web banner / dashboard widgets.

Super-admin pricing / lifecycle controls live under /api/platform.
"""

from .routes import subscription_bp  # noqa: F401
