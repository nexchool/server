"""Test the seed_subject_templates script via mocks (no real DB)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

SERVER_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = SERVER_DIR / "scripts"
for _p in (SERVER_DIR, SCRIPTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def test_templates_constant_has_four_boards():
    """Sanity check on the data table — 4 boards expected."""
    import seed_subject_templates as sst
    assert set(sst.TEMPLATES.keys()) == {"cbse", "gujarat_state_board", "icse", "ib"}


def test_seed_skips_when_template_already_exists(monkeypatch, capsys):
    """seed() should print SKIP and NOT add duplicate rows when board_code exists."""
    import seed_subject_templates as sst

    # Mock create_app to avoid Flask boot
    fake_app = MagicMock()
    fake_app.app_context.return_value.__enter__ = lambda s: None
    fake_app.app_context.return_value.__exit__ = lambda s, *a: None
    monkeypatch.setattr(sst, "create_app", lambda: fake_app)

    # Mock SubjectTemplateGroup.query.filter_by(...).first() to always return existing
    fake_group = MagicMock(id="existing-id")
    fake_query = MagicMock()
    fake_query.filter_by.return_value = fake_query
    fake_query.first.return_value = fake_group
    fake_group_cls = MagicMock()
    fake_group_cls.query = fake_query
    monkeypatch.setattr(sst, "SubjectTemplateGroup", fake_group_cls)

    fake_session = MagicMock()
    monkeypatch.setattr(sst.db, "session", fake_session)

    sst.seed()

    # No new groups should have been added
    fake_session.add.assert_not_called()
    fake_session.commit.assert_not_called()

    captured = capsys.readouterr()
    assert "SKIP cbse" in captured.out
    assert "Done: 0 seeded, 4 skipped" in captured.out


def test_seed_creates_when_no_template_exists(monkeypatch, capsys):
    """seed() should add new groups + items when filter_by(...).first() returns None."""
    import seed_subject_templates as sst

    fake_app = MagicMock()
    fake_app.app_context.return_value.__enter__ = lambda s: None
    fake_app.app_context.return_value.__exit__ = lambda s, *a: None
    monkeypatch.setattr(sst, "create_app", lambda: fake_app)

    # Group query: returns None (template doesn't exist) — for first()
    fake_group_query = MagicMock()
    fake_group_query.filter_by.return_value = fake_group_query
    fake_group_query.first.return_value = None  # always missing => seed
    fake_group_cls = MagicMock(side_effect=lambda **kw: MagicMock(id="g-new", **kw))
    fake_group_cls.query = fake_group_query
    monkeypatch.setattr(sst, "SubjectTemplateGroup", fake_group_cls)

    # Item query: returns 5 (item count)
    fake_item_query = MagicMock()
    fake_item_query.filter_by.return_value = fake_item_query
    fake_item_query.count.return_value = 5
    fake_item_cls = MagicMock(side_effect=lambda **kw: MagicMock(**kw))
    fake_item_cls.query = fake_item_query
    monkeypatch.setattr(sst, "SubjectTemplateItem", fake_item_cls)

    fake_session = MagicMock()
    monkeypatch.setattr(sst.db, "session", fake_session)

    sst.seed()

    # 4 commits expected (one per board)
    assert fake_session.commit.call_count == 4
    captured = capsys.readouterr()
    assert "SEED cbse" in captured.out
    assert "Done: 4 seeded, 0 skipped" in captured.out
