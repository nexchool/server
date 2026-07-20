"""Migration 071 — academic_programmes.template_board_code.

Pure-Python: alembic's `op` is stubbed, so no database or alembic env is needed.
The sys.modules stub is backed up and restored, because a leaked stub breaks any
later test that imports flask_migrate (which does `from alembic import __version__`).
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

SERVER_DIR = Path(__file__).resolve().parent.parent
MIGRATION = (
    SERVER_DIR / "migrations" / "versions" / "071_programme_template_board_code.py"
)


def _load(op_stub):
    backup = sys.modules.get("alembic")
    alembic_stub = types.ModuleType("alembic")
    alembic_stub.op = op_stub
    sys.modules["alembic"] = alembic_stub
    try:
        spec = importlib.util.spec_from_file_location("migration_071", MIGRATION)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if backup is None:
            sys.modules.pop("alembic", None)
        else:
            sys.modules["alembic"] = backup


def test_revision_follows_070():
    module = _load(MagicMock())
    assert module.revision == "071_programme_template_board_code"
    assert module.down_revision == "070_tenant_onboarding_drafts"


def test_upgrade_adds_a_nullable_template_board_code():
    op = MagicMock()
    module = _load(op)
    module.upgrade()
    calls = op.add_column.call_args_list
    assert len(calls) == 1
    table, column = calls[0].args
    assert table == "academic_programmes"
    assert column.name == "template_board_code"
    assert column.nullable is True
    assert column.type.length == 30


def test_downgrade_drops_it():
    op = MagicMock()
    module = _load(op)
    module.downgrade()
    assert op.drop_column.call_args_list[0].args == (
        "academic_programmes",
        "template_board_code",
    )
