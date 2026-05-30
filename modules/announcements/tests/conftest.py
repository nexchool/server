"""Announcement test fixtures. Re-exports shared root fixtures + adds module-specific ones."""

from __future__ import annotations

import uuid

import pytest
from flask import g

# Re-export shared fixtures so tests under modules/announcements/tests/ pick them up.
from tests.conftest import flask_app, _db_engine, db_session, tenant  # noqa: F401


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}" if prefix else str(uuid.uuid4())


@pytest.fixture
def tenant_ctx(flask_app, db_session, tenant):
    """Push g.tenant_id so get_tenant_id() resolves inside services."""
    g.tenant_id = tenant.id
    yield tenant


@pytest.fixture
def author_user(db_session, tenant_ctx):
    """A plain admin-style user that authors announcements.

    Root conftest doesn't expose admin_user, so we inline a minimal version here.
    Permissions are not checked by services (only routes will check), so we just
    need a valid User row.
    """
    from modules.auth.models import User
    user = User(
        id=_new_id("u-a-"),
        tenant_id=tenant_ctx.id,
        email=f"author-{uuid.uuid4().hex[:6]}@test.school",
        password_hash="x" * 60,
        name="Announcement Author",
    )
    db_session.add(user)
    db_session.flush()
    return user
