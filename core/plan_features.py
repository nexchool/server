"""
Compatibility shim — the per-tenant feature flag system lives in
`core.feature_flags`. This module is kept only so external imports
(scripts, tests, third-party integrations) keep working during transition.
New code should import from `core.feature_flags` directly.
"""

from core.feature_flags import (
    ALL_FEATURE_KEYS as PLAN_FEATURE_KEYS,
    FEATURE_LABELS as PLAN_FEATURE_LABELS,
    get_tenant_enabled_features,
    is_feature_enabled as is_plan_feature_enabled,
    require_feature as require_plan_feature,
)

__all__ = [
    "PLAN_FEATURE_KEYS",
    "PLAN_FEATURE_LABELS",
    "get_tenant_enabled_features",
    "is_plan_feature_enabled",
    "require_plan_feature",
]
