"""
Branch (school-unit) scope resolver + per-domain filter/assert helpers.

Per-sub-admin branch scoping (Phase 2). The rule is intentionally
**fail-open by default, fail-closed once restricted**:

- **No `UserSchoolUnit` rows for a user = UNRESTRICTED** (access to every
  branch). This keeps existing admins / unscoped users unchanged.
- **One or more rows = restricted** to exactly that set of school units.
- **Platform admins are always unrestricted.**

The only domain model carrying a unit column is ``Class.school_unit_id``.
Every other branch-aware domain (students, attendance, fees, timetable)
reaches a unit *through* a Class. So the anchor chain is:

    allowed units -> allowed class ids -> filter each domain by class membership

All resolver results are cached on ``flask.g`` for the request, mirroring
the ``g.tenant_id`` caching style in ``core/tenant.py``. Every helper is a
strict **no-op** for unrestricted users so existing behaviour is untouched.
"""

from __future__ import annotations

from typing import Optional, Set

from flask import g, has_request_context

from shared.helpers import error_response


# Sentinel so a legitimately-``None`` (unrestricted) result is cached and not
# recomputed on every call within the same request.
_UNSET = object()

_ALLOWED_UNITS_ATTR = "_branch_scope_allowed_unit_ids"
_ALLOWED_CLASSES_ATTR = "_branch_scope_allowed_class_ids"


class BranchForbidden(Exception):
    """Raised when a restricted user touches a resource outside their branches.

    Maps to HTTP 403 via :func:`register_branch_scope_error_handler`.
    """

    error_code = "BranchForbidden"
    status_code = 403
    default_message = "You don't have access to this branch."

    def __init__(self, message: Optional[str] = None):
        self.message = message or self.default_message
        super().__init__(self.message)


# ---------------------------------------------------------------------------
# Resolver (cached on g)
# ---------------------------------------------------------------------------

def get_allowed_unit_ids() -> Optional[Set[str]]:
    """Return the set of school_unit_ids the current user is restricted to.

    Returns ``None`` (UNRESTRICTED) when:
      - there is no request context, or
      - there is no ``g.current_user``, or
      - the user ``is_platform_admin``, or
      - the user has **no** ``UserSchoolUnit`` rows (the default).

    Otherwise returns the exact set of ``school_unit_id`` values.
    Cached on ``g`` for the request.
    """
    if not has_request_context():
        return None

    cached = getattr(g, _ALLOWED_UNITS_ATTR, _UNSET)
    if cached is not _UNSET:
        return cached

    allowed = _compute_allowed_unit_ids()
    setattr(g, _ALLOWED_UNITS_ATTR, allowed)
    return allowed


def _compute_allowed_unit_ids() -> Optional[Set[str]]:
    user = getattr(g, "current_user", None)
    if user is None:
        return None
    if getattr(user, "is_platform_admin", False):
        return None

    # Lazy import to avoid circular imports (models import core indirectly).
    from modules.sub_admins.models import UserSchoolUnit

    # tenant_id is auto-applied by the before_compile listener.
    rows = (
        UserSchoolUnit.query
        .with_entities(UserSchoolUnit.school_unit_id)
        .filter(UserSchoolUnit.user_id == user.id)
        .all()
    )
    if not rows:
        return None  # No rows = unrestricted (the default).
    return {row[0] for row in rows}


def get_allowed_class_ids() -> Optional[Set[str]]:
    """Return the set of Class ids inside the user's allowed branches.

    ``None`` when unrestricted (``get_allowed_unit_ids()`` is ``None``).
    Otherwise the set of ``Class.id`` whose ``school_unit_id`` is in the
    allowed units (tenant-scoped). Cached on ``g``.

    Used by asserts/tests. List filters should use the subquery helpers
    below rather than this materialized set, for scale.
    """
    allowed_units = get_allowed_unit_ids()
    if allowed_units is None:
        return None

    cached = getattr(g, _ALLOWED_CLASSES_ATTR, _UNSET)
    if cached is not _UNSET:
        return cached

    from modules.classes.models import Class

    rows = (
        Class.query
        .with_entities(Class.id)
        .filter(Class.school_unit_id.in_(allowed_units))
        .all()
    )
    class_ids = {row[0] for row in rows}
    setattr(g, _ALLOWED_CLASSES_ATTR, class_ids)
    return class_ids


# ---------------------------------------------------------------------------
# Tenant-scoped subqueries (do NOT rely on the listener inside subqueries)
# ---------------------------------------------------------------------------

def _allowed_class_id_subquery(allowed_units: Set[str]):
    """Scalar subquery: select Class.id where unit in allowed and tenant matches.

    Explicitly tenant-scoped rather than depending on the before_compile
    listener (which only fires on the outer query's leading entity).
    """
    from modules.classes.models import Class

    tenant_id = getattr(g, "tenant_id", None)
    query = (
        Class.query
        .with_entities(Class.id)
        .filter(Class.school_unit_id.in_(allowed_units))
    )
    if tenant_id is not None:
        query = query.filter(Class.tenant_id == tenant_id)
    return query.subquery()


def _allowed_student_id_subquery(allowed_units: Set[str]):
    """Scalar subquery: select Student.id whose class is in the allowed set."""
    from modules.students.models import Student

    tenant_id = getattr(g, "tenant_id", None)
    class_subq = _allowed_class_id_subquery(allowed_units)
    query = (
        Student.query
        .with_entities(Student.id)
        .filter(Student.class_id.in_(class_subq.select()))
    )
    if tenant_id is not None:
        query = query.filter(Student.tenant_id == tenant_id)
    return query.subquery()


# ---------------------------------------------------------------------------
# Asserts (raise on violation; no-op when unrestricted)
# ---------------------------------------------------------------------------

def assert_unit_allowed(unit_id: str) -> None:
    """No-op when unrestricted; else ``unit_id`` must be in the allowed units."""
    allowed = get_allowed_unit_ids()
    if allowed is None:
        return
    if unit_id not in allowed:
        raise BranchForbidden()


def assert_class_allowed(class_id: str) -> None:
    """Assert the class is in an allowed branch.

    No-op when unrestricted. The class is loaded with an **explicit
    tenant-scoped query** (not ``.get``, which bypasses the tenant listener).

    Missing-class choice: a class that does not exist in the tenant is left
    to the caller's own 404 handling — we only raise ``BranchForbidden`` when
    the class exists but its ``school_unit_id`` is out of branch. This keeps
    not-found semantics (404) and out-of-branch semantics (403) distinct and
    avoids leaking existence of out-of-tenant ids.
    """
    allowed = get_allowed_unit_ids()
    if allowed is None:
        return

    from modules.classes.models import Class

    tenant_id = getattr(g, "tenant_id", None)
    query = Class.query.with_entities(Class.school_unit_id).filter(Class.id == class_id)
    if tenant_id is not None:
        query = query.filter(Class.tenant_id == tenant_id)
    row = query.first()
    if row is None:
        # Class not found in tenant -> defer to caller's 404 handling.
        return
    if row[0] not in allowed:
        raise BranchForbidden()


def assert_student_allowed(student_id: str) -> None:
    """Assert the student's class is in an allowed branch.

    No-op when unrestricted. For restricted users a **classless student
    (``class_id`` is null) fails closed** (raises ``BranchForbidden``): an
    unassigned student belongs to no branch the user can see. A missing
    student is left to the caller's 404 handling.
    """
    allowed = get_allowed_unit_ids()
    if allowed is None:
        return

    from modules.students.models import Student

    tenant_id = getattr(g, "tenant_id", None)
    query = Student.query.with_entities(Student.class_id).filter(Student.id == student_id)
    if tenant_id is not None:
        query = query.filter(Student.tenant_id == tenant_id)
    row = query.first()
    if row is None:
        # Student not found in tenant -> defer to caller's 404 handling.
        return
    class_id = row[0]
    if class_id is None:
        raise BranchForbidden()  # Fail-closed for classless students.
    assert_class_allowed(class_id)


# ---------------------------------------------------------------------------
# Filter helpers (list queries — subquery/EXISTS, not materialized id sets)
# ---------------------------------------------------------------------------

def filter_classes_by_branch(query):
    """Restrict a Class query to the allowed branches. No-op if unrestricted."""
    allowed = get_allowed_unit_ids()
    if allowed is None:
        return query

    from modules.classes.models import Class

    return query.filter(Class.school_unit_id.in_(allowed))


def filter_by_class_ids(query, class_fk_column):
    """Restrict a query by a direct class FK column to allowed-branch classes.

    Used by attendance / timetable and any model with a direct class FK.
    No-op if unrestricted.
    """
    allowed = get_allowed_unit_ids()
    if allowed is None:
        return query

    class_subq = _allowed_class_id_subquery(allowed)
    return query.filter(class_fk_column.in_(class_subq.select()))


def filter_students_by_branch(query):
    """Restrict a Student query to students in allowed-branch classes.

    Classless students are excluded. No-op if unrestricted.
    """
    allowed = get_allowed_unit_ids()
    if allowed is None:
        return query

    from modules.students.models import Student

    class_subq = _allowed_class_id_subquery(allowed)
    return query.filter(Student.class_id.in_(class_subq.select()))


def filter_fees_by_branch(query, student_fk_column):
    """Restrict a fee-domain query by its student FK to allowed-branch students.

    No-op if unrestricted.
    """
    allowed = get_allowed_unit_ids()
    if allowed is None:
        return query

    student_subq = _allowed_student_id_subquery(allowed)
    return query.filter(student_fk_column.in_(student_subq.select()))


# ---------------------------------------------------------------------------
# Error-handler registration
# ---------------------------------------------------------------------------

def register_branch_scope_error_handler(app) -> None:
    """Map :class:`BranchForbidden` to a 403 JSON via ``error_response``."""

    @app.errorhandler(BranchForbidden)
    def _handle_branch_forbidden(error: BranchForbidden):
        return error_response(error.error_code, error.message, error.status_code)
