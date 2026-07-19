"""Tests for migration 068 — subject_template_items metadata columns.

Pure-Python: the alembic `op` module is stubbed, so neither a database nor an
alembic environment is required.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

SERVER_DIR = Path(__file__).resolve().parent.parent
MIGRATION = (
    SERVER_DIR / "migrations" / "versions" / "068_subject_template_item_metadata.py"
)


def _load(op_stub):
    alembic_stub = types.ModuleType("alembic")
    alembic_stub.op = op_stub
    sys.modules["alembic"] = alembic_stub
    spec = importlib.util.spec_from_file_location("migration_068", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_follows_current_head():
    module = _load(MagicMock())
    assert module.revision == "068_subject_template_item_metadata"
    assert module.down_revision == "067_rename_student_document_storage_columns"


def test_upgrade_adds_the_three_missing_columns():
    op = MagicMock()
    module = _load(op)
    module.upgrade()
    tables = {call.args[0] for call in op.add_column.call_args_list}
    added = {call.args[1].name for call in op.add_column.call_args_list}
    assert tables == {"subject_template_items"}
    assert added == {"role", "medium", "elective_group_key"}


def test_added_columns_are_nullable():
    op = MagicMock()
    module = _load(op)
    module.upgrade()
    for call in op.add_column.call_args_list:
        column = call.args[1]
        assert column.nullable is True, f"{column.name} must be nullable"


def test_downgrade_drops_all_three():
    op = MagicMock()
    module = _load(op)
    module.downgrade()
    dropped = {call.args[1] for call in op.drop_column.call_args_list}
    assert dropped == {"role", "medium", "elective_group_key"}
