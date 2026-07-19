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

import sqlalchemy as sa

SERVER_DIR = Path(__file__).resolve().parent.parent
MIGRATION = (
    SERVER_DIR / "migrations" / "versions" / "068_subject_template_item_metadata.py"
)

# The lengths the seeder truncates to (scripts/seed_subject_templates.py:
# _ROLE_MAX, _MEDIUM_MAX, _GROUP_KEY_MAX). The migration's column lengths
# must match these exactly or inserts fail with StringDataRightTruncation.
_EXPECTED_LENGTHS = {"role": 32, "medium": 16, "elective_group_key": 80}


def _load(op_stub):
    # Back up and restore any real `alembic` binding so this stub never
    # leaks into later tests (flask_migrate does `from alembic import
    # __version__` at import time, so a leaked stub breaks any test that
    # imports core.database afterward). Mirrors _load_seed_module() in
    # tests/test_seed_subject_templates.py.
    backup = sys.modules.get("alembic")
    alembic_stub = types.ModuleType("alembic")
    alembic_stub.op = op_stub
    sys.modules["alembic"] = alembic_stub
    try:
        spec = importlib.util.spec_from_file_location("migration_068", MIGRATION)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if backup is None:
            sys.modules.pop("alembic", None)
        else:
            sys.modules["alembic"] = backup
    return module


def test_revision_ids_are_declared_correctly():
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


def test_added_columns_match_seeder_truncation_lengths():
    op = MagicMock()
    module = _load(op)
    module.upgrade()
    columns = {call.args[1].name: call.args[1] for call in op.add_column.call_args_list}
    for name, expected_length in _EXPECTED_LENGTHS.items():
        column_type = columns[name].type
        assert isinstance(column_type, sa.String), f"{name} must be sa.String"
        assert column_type.length == expected_length, (
            f"{name} length is {column_type.length}, expected {expected_length}"
        )
