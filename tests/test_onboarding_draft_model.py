"""Shape guarantees for TenantOnboardingDraft and its migration.

Pure-Python: inspects the SQLAlchemy table definition and the migration module
with a stubbed alembic `op`.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

MIGRATION = SERVER_DIR / "migrations" / "versions" / "070_tenant_onboarding_drafts.py"


def test_model_has_the_expected_columns():
    from modules.school_setup.models import TenantOnboardingDraft

    columns = {c.name for c in TenantOnboardingDraft.__table__.columns}
    assert columns == {
        "id",
        "tenant_id",
        "config",
        "created_at",
        "updated_at",
        "updated_by",
    }


def test_table_is_named_tenant_onboarding_drafts():
    from modules.school_setup.models import TenantOnboardingDraft

    assert TenantOnboardingDraft.__tablename__ == "tenant_onboarding_drafts"


def test_one_draft_per_tenant():
    from modules.school_setup.models import TenantOnboardingDraft

    tenant_id = TenantOnboardingDraft.__table__.columns["tenant_id"]
    assert tenant_id.unique is True
    assert tenant_id.nullable is False


def test_model_is_not_tenant_scoped():
    """Platform routes run without g.tenant_id; the scoping listener must not apply."""
    from core.models import TenantBaseModel
    from modules.school_setup.models import TenantOnboardingDraft

    assert not issubclass(TenantOnboardingDraft, TenantBaseModel)


def test_migration_follows_069():
    alembic_stub = types.ModuleType("alembic")
    alembic_stub.op = MagicMock()
    sys.modules["alembic"] = alembic_stub
    spec = importlib.util.spec_from_file_location("migration_069", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "070_tenant_onboarding_drafts"
    assert module.down_revision == "069_subject_exam_codes"
