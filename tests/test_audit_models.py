"""Pure-Python tests for audit models."""
from __future__ import annotations

import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from tests._model_loader import load_all_models  # noqa: E402

load_all_models()


def test_tenant_audit_log_repr():
    from modules.audit.models import TenantAuditLog

    entry = TenantAuditLog(
        tenant_id="t1",
        actor_name="A",
        actor_role="admin",
        module="students",
        action="created",
        resource_type="student",
        description="d",
    )
    rendered = repr(entry)
    assert "students.created" in rendered
    assert "t1" in rendered
