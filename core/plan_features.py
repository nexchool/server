"""
Plan-based feature flags.

Controls which high-level features are enabled per tenant based on their plan.
Stored in Plan.features_json as { "feature_key": true|false }.
- If a key is missing or not boolean, it is treated as True (enabled) for backward compatibility.
- Use with @require_plan_feature('feature_key') on routes and return enabled_features at login/profile
  so frontend can hide UI for disabled features.

Feature keys are defined here as the single source of truth. Add new features as you build them.
"""

from typing import List, Optional
from functools import wraps

from flask import g, jsonify


# Registry of all plan-controlled feature keys (single source of truth).
# Add new features here when you add new modules; UI and API use these.
PLAN_FEATURE_KEYS = [
    "attendance",
    "fees_management",
    "notifications",
    "schedule_management",
    "search",
    "reports",
    "student_management",
    "teacher_management",
    "class_management",
    "examinations",
    "timetable",
    "library",
    "transport",
    "hostel",
    "inventory",
    "holiday_management",
]

# Human-readable labels for super admin UI (optional; backend can stay key-only).
PLAN_FEATURE_LABELS = {
    "attendance": "Attendance",
    "fees_management": "Fees management",
    "notifications": "Notifications",
    "schedule_management": "Schedule management",
    "search": "Search",
    "reports": "Reports",
    "student_management": "Student management",
    "teacher_management": "Teacher management",
    "class_management": "Class management",
    "examinations": "Examinations",
    "timetable": "Timetable",
    "library": "Library",
    "transport": "Transport",
    "hostel": "Hostel",
    "inventory": "Inventory",
    "holiday_management": "Holiday management",
}


def get_tenant_enabled_features(tenant_id: str) -> List[str]:
    """
    Return list of feature keys that are enabled for the given tenant's plan.
    If tenant has no plan or plan has no features_json, all features are considered enabled.
    """
    from backend.core.models import Tenant, Plan

    tenant = Tenant.query.get(tenant_id)
    if not tenant or not tenant.plan_id:
        return list(PLAN_FEATURE_KEYS)

    plan = Plan.query.get(tenant.plan_id)
    if not plan or not isinstance(plan.features_json, dict):
        return list(PLAN_FEATURE_KEYS)

    enabled = []
    for key in PLAN_FEATURE_KEYS:
        val = plan.features_json.get(key)
        if val is False:
            continue
        enabled.append(key)
    return enabled


def is_plan_feature_enabled(tenant_id: str, feature_key: str) -> bool:
    """Return True if the feature is enabled for the tenant's plan."""
    if feature_key not in PLAN_FEATURE_KEYS:
        return True
    return feature_key in get_tenant_enabled_features(tenant_id)


def require_plan_feature(feature_key: str):
    """
    Decorator: require that the tenant's plan has this feature enabled.
    Use after @tenant_required and @auth_required so g.tenant_id is set.
    Returns 403 if the feature is disabled for the current tenant's plan.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            tenant_id = getattr(g, "tenant_id", None)
            if not tenant_id:
                return jsonify({
                    "error": "Forbidden",
                    "message": "Tenant context required. Use @tenant_required before @require_plan_feature.",
                }), 403
            if not is_plan_feature_enabled(tenant_id, feature_key):
                return jsonify({
                    "error": "FeatureNotAvailable",
                    "message": f"This feature is not available on your current plan.",
                }), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator
