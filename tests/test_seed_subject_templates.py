"""Tests for seed_subject_templates script — no real DB, no Flask bootstrap.

Strategy
--------
* test_templates_constant_has_four_boards — load the script via stubs and
  check TEMPLATES.keys() at runtime. TEMPLATES is built by combining
  board_subjects.json (cbse, gujarat_state_board) with hardcoded entries
  (icse, ib), so a literal-AST check is no longer possible.

* test_seed_skips_when_template_already_exists
* test_seed_creates_when_no_template_exists
  — inject lightweight stubs into sys.modules before importing the
  script so the module-level imports succeed, then monkeypatch the
  objects the seed() function uses at runtime.
"""
from __future__ import annotations

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


def test_templates_has_three_gujarat_boards():
    """Three Gujarat-scoped boards: cbse, gseb_english, gseb_gujarati. ICSE/IB removed."""
    sst = _load_seed_module()
    keys = set(sst.TEMPLATES.keys())
    assert keys == {"cbse", "gseb_english", "gseb_gujarati"}, (
        f"Expected 3 Gujarat boards, got: {keys}"
    )


def test_cbse_template_loaded_from_json():
    """cbse items should derive from board_subjects.json — verify Std 1 known subjects."""
    sst = _load_seed_module()
    cbse_items = sst.TEMPLATES["cbse"]["items"]
    grade_1 = next(row for row in cbse_items if row["grade"] == 1 and row["stream"] is None)
    subject_names = {s["subject_name"] for s in grade_1["subjects"]}
    assert "English" in subject_names
    assert "The World Around Us" in subject_names


def test_language_scope_is_gujarat_only():
    """No subject should reference foreign or non-Gujarat regional languages."""
    sst = _load_seed_module()
    forbidden = {"Tamil", "Telugu", "Marathi", "Bengali", "Odia", "Kannada", "Malayalam",
                 "Punjabi", "Urdu", "Arabic", "Persian", "Prakrit", "French", "German",
                 "Spanish", "Russian", "Chinese", "Japanese", "Tibetan", "Mizo", "Nepali",
                 "Manipuri", "Bahasa Melayu", "Assamese", "Sindhi"}
    seen = set()
    for tpl in sst.TEMPLATES.values():
        for row in tpl["items"]:
            for s in row["subjects"]:
                seen.add(s["subject_name"])
    leaked = {n for n in seen if any(b in n for b in forbidden)}
    assert not leaked, f"Forbidden languages leaked into template: {leaked}"


def test_gseb_gujarati_first_language_is_gujarati():
    """In gseb_gujarati template, FL at every grade is Gujarati."""
    sst = _load_seed_module()
    items = sst.TEMPLATES["gseb_gujarati"]["items"]
    fl_per_grade = {}
    for row in items:
        for s in row["subjects"]:
            if s.get("role") == "first_language":
                fl_per_grade.setdefault(row["grade"], set()).add(s["subject_name"])
    for grade, langs in fl_per_grade.items():
        assert "Gujarati" in langs, f"Grade {grade} guj-medium FL not Gujarati: {langs}"


def test_g11_science_has_pick_one_track():
    """Std 11 Science must carry elective_group_key on Math vs Biology rows."""
    sst = _load_seed_module()
    cbse = sst.TEMPLATES["cbse"]["items"]
    sci11 = next(r for r in cbse if r["grade"] == 11 and r["stream"] == "Science")
    track_keys = {s["elective_group_key"] for s in sci11["subjects"]
                  if s["subject_name"] in ("Mathematics", "Biology")}
    assert track_keys == {"g11_sci_track"}


def test_vocational_stream_present_at_g11_g12():
    """Each board must define Vocational stream at Std 11 and 12."""
    sst = _load_seed_module()
    for board_code in ("cbse", "gseb_english", "gseb_gujarati"):
        items = sst.TEMPLATES[board_code]["items"]
        voc_grades = {r["grade"] for r in items if r["stream"] == "Vocational"}
        assert voc_grades == {11, 12}, f"{board_code}: vocational grades {voc_grades}"


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
    assert "Done: 0 seeded, 0 replaced, 3 skipped" in captured.out


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

    # 3 commits expected (one per Gujarat board)
    assert fake_session.commit.call_count == 3
    captured = capsys.readouterr()
    assert "SEED cbse" in captured.out
    assert "Done: 3 seeded, 0 replaced, 0 skipped" in captured.out
