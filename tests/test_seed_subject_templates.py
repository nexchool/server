"""Tests for seed_subject_templates script — no real DB, no Flask bootstrap.

Strategy
--------
* test_templates_constant_has_four_boards — uses AST to extract the
  TEMPLATES dict keys without importing the module (avoids the
  module-level `from app import create_app` that requires python-dotenv).

* test_seed_skips_when_template_already_exists
* test_seed_creates_when_no_template_exists
  — inject lightweight stubs into sys.modules before importing the
  script so the module-level imports succeed, then monkeypatch the
  objects the seed() function uses at runtime.
"""
from __future__ import annotations

import ast
import importlib
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

SERVER_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SERVER_DIR / "scripts"
SEED_FILE = SCRIPTS_DIR / "seed_subject_templates.py"

for _p in (SERVER_DIR, SCRIPTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ---------------------------------------------------------------------------
# AST helper — read TEMPLATES keys without importing the script
# ---------------------------------------------------------------------------

def _extract_template_keys() -> set:
    """Parse seed_subject_templates.py with AST and return TEMPLATES top-level keys."""
    source = SEED_FILE.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "TEMPLATES":
                    if isinstance(node.value, ast.Dict):
                        return {
                            k.value
                            for k in node.value.keys
                            if isinstance(k, ast.Constant)
                        }
    return set()


def test_templates_constant_has_four_boards():
    """Sanity check on the data table — 4 boards expected."""
    keys = _extract_template_keys()
    assert keys == {"cbse", "gujarat_state_board", "icse", "ib"}, (
        f"Expected 4 boards, got: {keys}"
    )


# ---------------------------------------------------------------------------
# Stub-injection helper — makes `import seed_subject_templates` succeed
# ---------------------------------------------------------------------------

def _make_stub_modules():
    """
    Return a dict of sys.modules stubs that satisfy the top-level imports in
    seed_subject_templates.py:
        from app import create_app
        from core.database import db
        from modules.school_setup.template_models import SubjectTemplateGroup, SubjectTemplateItem
    """
    stubs = {}

    # stub app module
    fake_app_mod = types.ModuleType("app")
    fake_app_mod.create_app = MagicMock(return_value=MagicMock())
    stubs["app"] = fake_app_mod

    # stub core.database
    fake_db = MagicMock()
    fake_core = types.ModuleType("core")
    fake_core_db = types.ModuleType("core.database")
    fake_core_db.db = fake_db
    stubs["core"] = fake_core
    stubs["core.database"] = fake_core_db

    # stub modules hierarchy
    fake_modules = types.ModuleType("modules")
    fake_school_setup = types.ModuleType("modules.school_setup")
    fake_template_models = types.ModuleType("modules.school_setup.template_models")
    fake_template_models.SubjectTemplateGroup = MagicMock()
    fake_template_models.SubjectTemplateItem = MagicMock()
    stubs["modules"] = fake_modules
    stubs["modules.school_setup"] = fake_school_setup
    stubs["modules.school_setup.template_models"] = fake_template_models

    return stubs


def _load_seed_module():
    """
    Import (or reload) seed_subject_templates with stub modules in place.
    Returns the freshly loaded module object.
    """
    # Remove any cached version so each test gets a clean import
    sys.modules.pop("seed_subject_templates", None)

    stubs = _make_stub_modules()
    # Back up any real entries we're about to shadow
    backup = {k: sys.modules.get(k) for k in stubs}
    sys.modules.update(stubs)
    try:
        sst = importlib.import_module("seed_subject_templates")
    finally:
        # Restore original entries (remove stubs we added)
        for k, v in backup.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        # Remove the now-loaded seed module too so we don't leak state
        sys.modules.pop("seed_subject_templates", None)

    return sst


def test_seed_skips_when_template_already_exists(capsys):
    """seed() should print SKIP and NOT add duplicate rows when board_code exists."""
    sst = _load_seed_module()

    # create_app returns a fake app that supports app_context()
    fake_app = MagicMock()
    fake_app.app_context.return_value.__enter__ = lambda s: None
    fake_app.app_context.return_value.__exit__ = lambda s, *a: None
    sst.create_app = lambda: fake_app

    # SubjectTemplateGroup.query.filter_by(...).first() always returns existing
    fake_group = MagicMock(id="existing-id")
    fake_query = MagicMock()
    fake_query.filter_by.return_value = fake_query
    fake_query.first.return_value = fake_group
    fake_group_cls = MagicMock()
    fake_group_cls.query = fake_query
    sst.SubjectTemplateGroup = fake_group_cls

    fake_session = MagicMock()
    sst.db.session = fake_session

    sst.seed()

    fake_session.add.assert_not_called()
    fake_session.commit.assert_not_called()

    captured = capsys.readouterr()
    assert "SKIP cbse" in captured.out
    assert "Done: 0 seeded, 4 skipped" in captured.out


def test_seed_creates_when_no_template_exists(capsys):
    """seed() should add new groups + items when filter_by(...).first() returns None."""
    sst = _load_seed_module()

    fake_app = MagicMock()
    fake_app.app_context.return_value.__enter__ = lambda s: None
    fake_app.app_context.return_value.__exit__ = lambda s, *a: None
    sst.create_app = lambda: fake_app

    # Group query: first() returns None (template doesn't exist)
    fake_group_query = MagicMock()
    fake_group_query.filter_by.return_value = fake_group_query
    fake_group_query.first.return_value = None
    fake_group_cls = MagicMock(side_effect=lambda **kw: MagicMock(id="g-new", **kw))
    fake_group_cls.query = fake_group_query
    sst.SubjectTemplateGroup = fake_group_cls

    # Item query: count() returns 5
    fake_item_query = MagicMock()
    fake_item_query.filter_by.return_value = fake_item_query
    fake_item_query.count.return_value = 5
    fake_item_cls = MagicMock(side_effect=lambda **kw: MagicMock(**kw))
    fake_item_cls.query = fake_item_query
    sst.SubjectTemplateItem = fake_item_cls

    fake_session = MagicMock()
    sst.db.session = fake_session

    sst.seed()

    # 4 commits expected (one per board)
    assert fake_session.commit.call_count == 4
    captured = capsys.readouterr()
    assert "SEED cbse" in captured.out
    assert "Done: 4 seeded, 0 skipped" in captured.out
