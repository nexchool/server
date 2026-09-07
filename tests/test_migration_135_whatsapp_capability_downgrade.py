"""Tests for migration 135's downgrade — refusing to strand a WhatsApp row.

Pure-Python: the alembic `op` module is stubbed, so neither a database nor an
alembic environment is required (the same pattern
`test_migration_068_template_item_metadata.py` uses).
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent
MIGRATION = (
    SERVER_DIR
    / "migrations"
    / "versions"
    / "135_a_school_may_be_configured_for_whatsapp.py"
)


def _load(op_stub):
    # See test_migration_068_template_item_metadata.py's `_load` for why the
    # backup/restore dance around `sys.modules["alembic"]` matters:
    # flask_migrate imports the real `alembic` at import time, and a leaked
    # stub would break any test that imports `core.database` afterward.
    backup = sys.modules.get("alembic")
    alembic_stub = types.ModuleType("alembic")
    alembic_stub.op = op_stub
    sys.modules["alembic"] = alembic_stub
    try:
        spec = importlib.util.spec_from_file_location("migration_135", MIGRATION)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if backup is None:
            sys.modules.pop("alembic", None)
        else:
            sys.modules["alembic"] = backup
    return module


def _op_with_whatsapp_count(count: int) -> MagicMock:
    """An `op` stub whose `get_bind().execute(...).scalar()` reports `count`
    — standing in for `SELECT count(*) ... WHERE capability = 'whatsapp'`."""
    op = MagicMock()
    op.get_bind.return_value.execute.return_value.scalar.return_value = count
    return op


def test_revision_ids_are_declared_correctly():
    module = _load(_op_with_whatsapp_count(0))
    assert module.revision == "135_a_school_may_be_configured_for_whatsapp"
    assert module.down_revision == "134_which_wire_a_schools_codes_go_down"


def test_downgrade_widens_nothing_and_narrows_the_constraint_when_no_whatsapp_row_exists():
    op = _op_with_whatsapp_count(0)
    module = _load(op)

    module.downgrade()

    op.drop_constraint.assert_called_once_with(
        "ck_tenant_integrations_capability", "tenant_integrations", type_="check"
    )
    op.create_check_constraint.assert_called_once_with(
        "ck_tenant_integrations_capability",
        "tenant_integrations",
        "capability IN ('sms')",
    )


def test_downgrade_refuses_rather_than_stranding_a_whatsapp_row():
    """A downgrade that touched the schema anyway would either have Postgres
    refuse the `ALTER` with a constraint-violation naming a row id and
    nothing about why, or — worse — silently decide a school's fate. Neither
    is this migration's call to make, so it raises first, in words, and
    changes nothing."""
    op = _op_with_whatsapp_count(2)
    module = _load(op)

    with pytest.raises(RuntimeError) as raised:
        module.downgrade()

    assert "whatsapp" in str(raised.value).lower()
    op.drop_constraint.assert_not_called()
    op.create_check_constraint.assert_not_called()
