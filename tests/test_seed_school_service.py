"""Tests for school_setup.seed_service. Pure-Python — no Flask, no database."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def _good_config() -> dict:
    return {
        "tenant": {"subdomain": "demo"},
        "academic_year": {"name": "2025-2026", "start": "2025-06-01", "end": "2026-03-31"},
        "units": [{"code": "MN", "name": "Main Campus"}],
        "programmes": [{"code": "P1", "name": "CBSE", "board": "CBSE"}],
        "grades": [{"name": "1", "sequence": 1}],
        "subjects": [{"code": "MATH", "name": "Mathematics"}],
        "offerings": [
            {"programme": "P1", "grade": "1", "subjects": [{"code": "MATH", "weekly": 6}]}
        ],
        "classes": [{"unit": "MN", "programme": "P1", "grade": "1", "sections": ["A"]}],
    }


def test_validate_config_passes_for_complete_config():
    from modules.school_setup.seed_service import _validate_config

    assert _validate_config(_good_config()) == []


def test_validate_config_flags_class_without_offering():
    from modules.school_setup.seed_service import _validate_config

    config = _good_config()
    config["offerings"] = []  # no offering covers (P1, grade 1)
    errors = _validate_config(config)
    assert any("no subject offering" in e for e in errors)


def test_validate_config_flags_unknown_codes():
    from modules.school_setup.seed_service import _validate_config

    config = _good_config()
    config["classes"][0]["unit"] = "GHOST"
    config["offerings"][0]["subjects"][0]["code"] = "NOPE"
    errors = _validate_config(config)
    assert any("unknown unit 'GHOST'" in e for e in errors)
    assert any("unknown subject 'NOPE'" in e for e in errors)


def test_validate_config_requires_core_sections():
    from modules.school_setup.seed_service import _validate_config

    errors = _validate_config({"academic_year": None})
    assert any("academic_year is required" in e for e in errors)
    assert any("at least one unit is required" in e for e in errors)
    assert any("at least one programme is required" in e for e in errors)
    assert any("at least one grade is required" in e for e in errors)


# --- helpers ---------------------------------------------------------------

import datetime as _dt


def test_parse_date_accepts_string_and_date():
    from modules.school_setup.seed_service import _parse_date

    assert _parse_date("2025-06-01") == _dt.date(2025, 6, 1)
    assert _parse_date(_dt.date(2026, 3, 31)) == _dt.date(2026, 3, 31)


def test_ensure_unit_returns_existing_without_writing(monkeypatch):
    from modules.school_setup import seed_service as svc

    existing = MagicMock(id="u-existing", code="MN")
    fake_q = MagicMock()
    fake_q.filter_by.return_value = fake_q
    fake_q.filter.return_value = fake_q
    fake_q.first.return_value = existing
    fake_cls = MagicMock()
    fake_cls.query = fake_q
    fake_cls.deleted_at.is_.return_value = True
    fake_session = MagicMock()

    monkeypatch.setattr(svc, "SchoolUnit", fake_cls)
    monkeypatch.setattr(svc.db, "session", fake_session)

    unit, created = svc._ensure_unit("t1", {"code": "MN", "name": "Main"})

    assert unit is existing
    assert created is False
    fake_session.add.assert_not_called()


def test_ensure_unit_creates_when_missing(monkeypatch):
    from modules.school_setup import seed_service as svc

    fake_q = MagicMock()
    fake_q.filter_by.return_value = fake_q
    fake_q.filter.return_value = fake_q
    fake_q.first.return_value = None
    fake_cls = MagicMock()
    fake_cls.query = fake_q
    fake_cls.deleted_at.is_.return_value = True
    fake_session = MagicMock()

    monkeypatch.setattr(svc, "SchoolUnit", fake_cls)
    monkeypatch.setattr(svc.db, "session", fake_session)

    unit, created = svc._ensure_unit("t1", {"code": "MN", "name": "Main"})

    assert created is True
    fake_session.add.assert_called_once()
    fake_session.flush.assert_called_once()


def test_ensure_year_deactivates_other_active_years(monkeypatch):
    from modules.school_setup import seed_service as svc

    fake_q = MagicMock()
    fake_q.filter_by.return_value = fake_q
    fake_q.first.return_value = None  # new year
    fake_q.update.return_value = 1
    fake_cls = MagicMock()
    fake_cls.query = fake_q
    fake_session = MagicMock()

    monkeypatch.setattr(svc, "AcademicYear", fake_cls)
    monkeypatch.setattr(svc.db, "session", fake_session)

    year, created = svc._ensure_year(
        "t1", {"name": "2025-2026", "start": "2025-06-01", "end": "2026-03-31", "active": True}
    )

    assert created is True
    fake_q.update.assert_called_once()  # other active years flipped off


# --- apply_subject_contexts_to_classes -------------------------------------

def _ctx(programme_id, grade_id, subject_id, weekly, type_="mandatory"):
    c = MagicMock()
    c.programme_id = programme_id
    c.grade_id = grade_id
    c.subject_id = subject_id
    c.default_weekly_periods = weekly
    c.type = type_
    return c


def _wire_apply(monkeypatch, classes, existing_cs, contexts):
    from modules.school_setup import seed_service as svc

    class_q = MagicMock()
    class_q.filter_by.return_value = class_q
    class_q.all.return_value = classes
    class_cls = MagicMock(); class_cls.query = class_q

    cs_q = MagicMock()
    cs_q.filter.return_value = cs_q
    cs_q.all.return_value = existing_cs
    cs_cls = MagicMock(); cs_cls.query = cs_q
    cs_cls.class_id.in_.return_value = True
    cs_cls.deleted_at.is_.return_value = True

    ctx_q = MagicMock()
    ctx_q.filter_by.return_value = ctx_q
    ctx_q.filter.return_value = ctx_q
    ctx_q.all.return_value = contexts
    ctx_cls = MagicMock(); ctx_cls.query = ctx_q
    ctx_cls.deleted_at.is_.return_value = True

    session = MagicMock()
    monkeypatch.setattr(svc, "Class", class_cls)
    monkeypatch.setattr(svc, "ClassSubject", cs_cls)
    monkeypatch.setattr(svc, "SubjectContext", ctx_cls)
    monkeypatch.setattr(svc.db, "session", session)
    return svc, session


def test_apply_contexts_creates_one_class_subject_per_context(monkeypatch):
    c1 = MagicMock(id="c1", programme_id="p1", grade_id="g1")
    contexts = [_ctx("p1", "g1", "s1", 6), _ctx("p1", "g1", "s2", 5, "elective")]
    svc, session = _wire_apply(monkeypatch, [c1], [], contexts)

    result = svc.apply_subject_contexts_to_classes("t1", "ay1")

    assert result == {"created": 2, "skipped": 0}
    assert session.add.call_count == 2
    session.commit.assert_called_once()


def test_apply_contexts_skips_existing_active_pairs(monkeypatch):
    c1 = MagicMock(id="c1", programme_id="p1", grade_id="g1")
    existing = MagicMock(class_id="c1", subject_id="s1")
    contexts = [_ctx("p1", "g1", "s1", 6)]
    svc, session = _wire_apply(monkeypatch, [c1], [existing], contexts)

    result = svc.apply_subject_contexts_to_classes("t1", "ay1")

    assert result == {"created": 0, "skipped": 1}
    session.add.assert_not_called()


def test_apply_contexts_returns_zero_when_no_classes(monkeypatch):
    svc, session = _wire_apply(monkeypatch, [], [], [])

    result = svc.apply_subject_contexts_to_classes("t1", "ay1")

    assert result == {"created": 0, "skipped": 0}


# --- seed_school orchestrator ----------------------------------------------

def test_seed_school_raises_on_invalid_config():
    import pytest
    from modules.school_setup.seed_service import seed_school, SeedValidationError

    config = _good_config()
    config["offerings"] = []  # class has no offering
    with pytest.raises(SeedValidationError) as exc:
        seed_school("t1", config)
    assert any("no subject offering" in e for e in exc.value.errors)


def test_seed_school_dry_run_returns_plan_without_writing(monkeypatch):
    from modules.school_setup import seed_service as svc

    # Any DB write would explode the test — assert none happen.
    session = MagicMock()
    session.add.side_effect = AssertionError("dry-run must not write")
    session.commit.side_effect = AssertionError("dry-run must not commit")
    monkeypatch.setattr(svc.db, "session", session)

    result = svc.seed_school("t1", _good_config(), dry_run=True)

    assert result["dry_run"] is True
    assert result["plan"]["units"] == 1
    assert result["plan"]["academic_year"] == "2025-2026"
    assert result["plan"]["sections_total"] == 1
