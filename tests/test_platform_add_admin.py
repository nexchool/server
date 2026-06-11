"""add_tenant_admin returns the temporary password once (for the panel's
one-time reveal) without leaking it to the audit log; the new admin can
authenticate with it and is forced to change it at first login.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def test_add_tenant_admin_returns_one_time_password(flask_app, db_session, tenant):
    from core.models import AuditLog
    from modules.auth.models import User
    from modules.rbac.models import Role
    from modules.platform import services

    role = Role(id=uuid.uuid4().hex, tenant_id=tenant.id, name="Admin")
    db_session.add(role)
    # The audit row's platform_admin_id FK needs a real user.
    platform_admin = User(
        id=uuid.uuid4().hex,
        tenant_id=tenant.id,
        email=f"pa-{uuid.uuid4().hex[:6]}@test.local",
        password_hash="x" * 60,
        name="Platform Admin",
    )
    db_session.add(platform_admin)
    db_session.flush()

    email = f"newadmin-{uuid.uuid4().hex[:6]}@test.local"
    with flask_app.test_request_context("/"):
        result = services.add_tenant_admin(
            tenant_id=tenant.id,
            email=email,
            name="New Admin",
            platform_admin_id=platform_admin.id,
        )

    assert result["success"] is True
    pwd = result.get("temp_password")
    assert isinstance(pwd, str) and len(pwd) >= 10

    user = User.query.filter_by(tenant_id=tenant.id, email=email).first()
    assert user is not None
    assert user.check_password(pwd) is True
    # Temporary by design: the admin must change it at first login.
    assert user.force_password_reset is True

    # The audit entry records the email but never the password.
    rows = AuditLog.query.filter_by(action="school_admin.created").all()
    assert rows, "expected an audit entry for school_admin.created"
    assert all(pwd not in str(r.extra_data or "") for r in rows)
