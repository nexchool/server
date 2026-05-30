"""Structural tests for _resolve_audience input validation."""

from __future__ import annotations

import pytest

from modules.announcements.services import _resolve_audience, ValidationError


def test_audience_rejects_unknown_scope(tenant_ctx):
    with pytest.raises(ValidationError):
        _resolve_audience(tenant_ctx.id, {"scope": "invalid"})


def test_audience_rejects_missing_roles(tenant_ctx):
    with pytest.raises(ValidationError):
        _resolve_audience(tenant_ctx.id, {"scope": "roles"})


def test_audience_rejects_empty_roles(tenant_ctx):
    with pytest.raises(ValidationError):
        _resolve_audience(tenant_ctx.id, {"scope": "roles", "roles": []})


def test_audience_rejects_missing_class_ids(tenant_ctx):
    with pytest.raises(ValidationError):
        _resolve_audience(tenant_ctx.id, {"scope": "classes"})


def test_audience_rejects_missing_student_ids(tenant_ctx):
    with pytest.raises(ValidationError):
        _resolve_audience(tenant_ctx.id, {"scope": "students"})


def test_audience_all_returns_set(tenant_ctx):
    """Sanity — scope=all returns a set (possibly empty in pristine test DB)."""
    result = _resolve_audience(tenant_ctx.id, {"scope": "all"})
    assert isinstance(result, set)
