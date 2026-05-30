"""Search test fixtures.

Shared fixtures (flask_app, db_session, tenant, ...) are re-exported globally by
the server-root conftest.py, so we only add module-specific fixtures here.
"""

from __future__ import annotations

import uuid

import pytest
from flask import g


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}" if prefix else str(uuid.uuid4())


@pytest.fixture
def tenant_ctx(flask_app, db_session, tenant):
    """Push g.tenant_id so get_tenant_id() resolves inside services."""
    g.tenant_id = tenant.id
    yield tenant


@pytest.fixture
def admin_user(db_session, tenant_ctx):
    """A minimal admin-style user.

    Root conftest doesn't expose admin_user, so we inline a minimal version here.
    """
    from modules.auth.models import User
    user = User(
        id=_new_id("u-s-"),
        tenant_id=tenant_ctx.id,
        email=f"admin-{uuid.uuid4().hex[:6]}@test.school",
        password_hash="x" * 60,
        name="Search Admin",
    )
    db_session.add(user)
    db_session.flush()
    return user
