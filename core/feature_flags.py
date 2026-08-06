"""
Per-tenant feature flags.

Replaces the old plan-based feature gating. Each tenant has its own
`feature_flags` JSON map of `{ feature_key: bool }`. Missing keys default
to enabled (so a freshly-created tenant gets everything until super-admin
opts out).

Features are split into two groups:
- CORE_FEATURES: cannot be disabled (auth, users, RBAC, students, classes,
  teachers). The decorator allows them through unconditionally.
- OPTIONAL_FEATURES: super-admin-toggleable per tenant. Disabling one returns
  403 from gated endpoints and is observed by side-effect callers
  (e.g. notification dispatcher silently skips when 'notifications' is off).
"""

from __future__ import annotations

import hashlib
from functools import wraps
from typing import Dict, List

from flask import g, jsonify


CORE_FEATURES: List[str] = [
    "auth",
    "users",
    "rbac",
    "students",
    "classes",
    "teachers",
]

OPTIONAL_FEATURES: List[str] = [
    "attendance",
    "fees_management",
    "timetable",
    "schedule_management",
    "transport",
    "notifications",
    "holiday_management",
    "academic_calendar",
    "hostel",
    "search",
    "academics_advanced",
    "student_management",
    "teacher_management",
    "class_management",
]

ALL_FEATURE_KEYS: List[str] = CORE_FEATURES + OPTIONAL_FEATURES

FEATURE_LABELS: Dict[str, str] = {
    "auth": "Authentication",
    "users": "User accounts",
    "rbac": "Roles & permissions",
    "students": "Students",
    "classes": "Classes",
    "teachers": "Teachers",
    "attendance": "Attendance",
    "fees_management": "Fees & finance",
    "timetable": "Timetable",
    "schedule_management": "Schedule management",
    "transport": "Transport",
    "notifications": "Notifications",
    "holiday_management": "Holiday management",
    "academic_calendar": "Academic calendar",
    "hostel": "Hostel",
    "search": "Search",
    "academics_advanced": "Advanced academics",
    "student_management": "Student management",
    "teacher_management": "Teacher management",
    "class_management": "Class management",
}


def default_feature_flags() -> Dict[str, bool]:
    """All optional features ON by default for new tenants."""
    return {key: True for key in OPTIONAL_FEATURES}


def effective_flags(stored: object) -> Dict[str, bool]:
    """Resolve a tenant's stored flag map into the full effective one.

    Core features are always on. Optional features take their stored value and
    default to on when absent, so a tenant created before a feature existed
    gets it rather than silently losing it.
    """
    flags: Dict[str, bool] = {key: True for key in CORE_FEATURES}
    values = stored if isinstance(stored, dict) else {}
    for key in OPTIONAL_FEATURES:
        val = values.get(key)
        flags[key] = True if val is None else bool(val)
    return flags


def get_tenant_feature_flags(tenant_id: str) -> Dict[str, bool]:
    """The effective flag map for a tenant, read from the database."""
    from core.models import Tenant

    tenant = Tenant.query.get(tenant_id)
    return effective_flags(tenant.feature_flags if tenant else None)


def feature_stamp(stored: object) -> str:
    """A short value that changes if and only if the enabled set changes.

    Sent on every API response so a client can notice a super-admin turning a
    module on or off without being told, and without polling. It is derived
    from the flags rather than from a timestamp so that saving the same
    settings again does not look like a change and force needless refreshes.

    Not a secret and not a signature — it only says "different from what you
    last saw". The client's answer to a change is to re-ask the server.
    """
    flags = effective_flags(stored)
    enabled = ",".join(sorted(key for key, on in flags.items() if on))
    return hashlib.sha256(enabled.encode()).hexdigest()[:12]


def get_tenant_enabled_features(tenant_id: str) -> List[str]:
    """List of enabled feature keys for the tenant. Used by auth responses."""
    flags = get_tenant_feature_flags(tenant_id)
    return [key for key, enabled in flags.items() if enabled]


def is_feature_enabled(tenant_id: str, feature_key: str) -> bool:
    """True if the feature is enabled for the tenant. Core features always True."""
    if feature_key in CORE_FEATURES:
        return True
    if feature_key not in OPTIONAL_FEATURES:
        return True
    return get_tenant_feature_flags(tenant_id).get(feature_key, True)


def require_feature(feature_key: str):
    """
    Decorator: 403 if the feature is disabled for the current tenant.
    Use after `@tenant_required` so `g.tenant_id` is populated.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            tenant_id = getattr(g, "tenant_id", None)
            if not tenant_id:
                return jsonify({
                    "success": False,
                    "error": "Forbidden",
                    "message": "Tenant context required.",
                }), 403
            if not is_feature_enabled(tenant_id, feature_key):
                return jsonify({
                    "success": False,
                    "error": "FeatureDisabled",
                    "message": "This feature is disabled for your school.",
                }), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator
