"""
Per-tenant feature flags.

Replaces the old plan-based feature gating. Each tenant has its own
`feature_flags` JSON map of `{ feature_key: bool }`. Missing keys default
to enabled (so a freshly-created tenant gets everything until super-admin
opts out) — with the single exception of DEFAULT_OFF_FEATURES below.

The split is a business one, not a technical one.

CORE is the product. A school cannot run without students, teachers, classes
and the structure they hang off — branches, grades, programmes, mediums,
subjects, terms. Offering those as switches would let a super-admin
decapitate a live school with a checkbox, so they are not offered.

OPTIONAL is what schools genuinely differ on: buses, a hostel, whether fees
are kept here or in the accountant's existing software, whether attendance is
still on paper. Every key here is something a real school either does or does
not do — not a slice of the product held back for a higher price.

That distinction is what keeps onboarding simple. A new school is asked seven
questions it knows the answers to, rather than shown a list of internal module
names and asked to guess.
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
    # The three things a school is made of. `*_management` are the keys the
    # route decorators actually use; the bare names are what the clients read.
    # Both are core, so the pair can never disagree about whether a school is
    # allowed to have students.
    "students",
    "student_management",
    "teachers",
    "teacher_management",
    "classes",
    "class_management",
    # Branches, grades, programmes, mediums, subjects, terms, year rollover.
    # Not an upsell: without them there is nothing to put a class in.
    "academics_advanced",
    # Finding a child by name. Part of using the product, not a module.
    "search",
]

OPTIONAL_FEATURES: List[str] = [
    "attendance",
    "fees_management",
    "timetable",
    "transport",
    "hostel",
    "notifications",
    # Terms, events, exam windows and holidays. Holidays are managed inside
    # the calendar in the UI and were a separate flag by accident.
    "academic_calendar",
    # Scheduling examinations, entering marks, computing and publishing
    # results, and issuing marksheets. A school that reports only on internal
    # assessment, or whose board runs its own examination system, does not
    # use this — and see DEFAULT_OFF_FEATURES for why it starts off.
    "examinations",
]

# The one place where a missing key means *off*.
#
# `effective_flags` defaults a missing optional key to on, and that rule is
# right for the reason it was written: a tenant created before a flag existed
# was already using the module, and inventing "off" would take away something
# the school relies on. A module that has never been released has nothing to
# take away, so the same rule points the other way — it would switch the
# module on for every school on the deploy that introduces it, which is a
# product decision no one made.
#
# A key leaves this set once the module is deliberately rolled out.
DEFAULT_OFF_FEATURES: set = {"examinations"}

ALL_FEATURE_KEYS: List[str] = CORE_FEATURES + OPTIONAL_FEATURES

# Two keys for one capability, from before the two halves agreed on a name:
# the clients read `students`, the route decorators say `student_management`.
# Both are core and both resolve the same, so nothing has to change on either
# side — but only one of each pair is worth showing a human.
LEGACY_ALIASES: List[str] = [
    "student_management",
    "teacher_management",
    "class_management",
]

# What the super-admin reads. Written the way a school talks, not the way the
# code is organised — the person choosing these runs schools, not modules.
FEATURE_LABELS: Dict[str, str] = {
    "auth": "Sign-in",
    "users": "User accounts",
    "rbac": "Roles & permissions",
    "students": "Students",
    "teachers": "Teachers",
    "classes": "Classes",
    "academics_advanced": "Academic structure",
    "search": "Search",
    "attendance": "Attendance",
    "fees_management": "Fees & payments",
    "timetable": "Timetable",
    "transport": "School transport",
    "hostel": "Hostel & boarding",
    "notifications": "Announcements & notifications",
    "academic_calendar": "Academic calendar & holidays",
    "examinations": "Examinations, results & marksheets",
}


def default_feature_flags() -> Dict[str, bool]:
    """Optional features for a new tenant: on, except DEFAULT_OFF_FEATURES."""
    return {key: key not in DEFAULT_OFF_FEATURES for key in OPTIONAL_FEATURES}


def effective_flags(stored: object) -> Dict[str, bool]:
    """Resolve a tenant's stored flag map into the full effective one.

    Core features are always on. Optional features take their stored value and
    default to on when absent, so a tenant created before a feature existed
    gets it rather than silently losing it — except for DEFAULT_OFF_FEATURES,
    where absent means the school has never had the module and turning it on
    unasked would be the surprise.
    """
    flags: Dict[str, bool] = {key: True for key in CORE_FEATURES}
    values = stored if isinstance(stored, dict) else {}
    for key in OPTIONAL_FEATURES:
        val = values.get(key)
        flags[key] = key not in DEFAULT_OFF_FEATURES if val is None else bool(val)
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
    flags = get_tenant_feature_flags(tenant_id)
    return flags.get(feature_key, feature_key not in DEFAULT_OFF_FEATURES)


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
