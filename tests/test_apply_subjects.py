"""Tests for apply_subjects_service.apply_subject_offerings.

Pure-Python unit tests — no Flask, no database.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def _make_class(id_: str) -> MagicMock:
    c = MagicMock()
    c.id = id_
    return c


def _make_subject(id_: str) -> MagicMock:
    s = MagicMock()
    s.id = id_
    return s


def _make_class_subject(class_id: str, subject_id: str) -> MagicMock:
    cs = MagicMock()
    cs.class_id = class_id
    cs.subject_id = subject_id
    return cs


# ---------------------------------------------------------------------------
# No classes → early return
# ---------------------------------------------------------------------------

def test_returns_zero_when_no_classes(monkeypatch):
    """When there are no classes, returns {created: 0, skipped: 0} without querying subjects."""
    from modules.school_setup import apply_subjects_service as svc

    fake_class_query = MagicMock()
    fake_class_query.filter_by.return_value = fake_class_query
    fake_class_query.all.return_value = []

    fake_subject_query = MagicMock()
    fake_subject_query.filter_by.return_value = fake_subject_query
    fake_subject_query.all.return_value = [_make_subject("s1")]

    import modules.classes.models as cls_mod
    import modules.subjects.models as subj_mod

    fake_class_cls = MagicMock()
    fake_class_cls.query = fake_class_query

    fake_subject_cls = MagicMock()
    fake_subject_cls.query = fake_subject_query

    monkeypatch.setattr(cls_mod, "Class", fake_class_cls)
    monkeypatch.setattr(subj_mod, "Subject", fake_subject_cls)
    monkeypatch.setattr(svc, "Class", fake_class_cls)
    monkeypatch.setattr(svc, "Subject", fake_subject_cls)

    result = svc.apply_subject_offerings(tenant_id="t1", academic_year_id="ay1")

    assert result == {"created": 0, "skipped": 0}


# ---------------------------------------------------------------------------
# No subjects → early return
# ---------------------------------------------------------------------------

def test_returns_zero_when_no_subjects(monkeypatch):
    """When there are no active subjects, returns {created: 0, skipped: 0}."""
    from modules.school_setup import apply_subjects_service as svc

    fake_class_query = MagicMock()
    fake_class_query.filter_by.return_value = fake_class_query
    fake_class_query.all.return_value = [_make_class("c1")]

    fake_subject_query = MagicMock()
    fake_subject_query.filter_by.return_value = fake_subject_query
    fake_subject_query.all.return_value = []

    import modules.classes.models as cls_mod
    import modules.subjects.models as subj_mod

    fake_class_cls = MagicMock()
    fake_class_cls.query = fake_class_query

    fake_subject_cls = MagicMock()
    fake_subject_cls.query = fake_subject_query

    monkeypatch.setattr(cls_mod, "Class", fake_class_cls)
    monkeypatch.setattr(subj_mod, "Subject", fake_subject_cls)
    monkeypatch.setattr(svc, "Class", fake_class_cls)
    monkeypatch.setattr(svc, "Subject", fake_subject_cls)

    result = svc.apply_subject_offerings(tenant_id="t1", academic_year_id="ay1")

    assert result == {"created": 0, "skipped": 0}


# ---------------------------------------------------------------------------
# Skips existing pairs, creates missing
# ---------------------------------------------------------------------------

def test_skips_existing_creates_missing(monkeypatch):
    """With 2 classes × 2 subjects and 1 existing pair, creates 3 and skips 1."""
    from modules.school_setup import apply_subjects_service as svc

    c1 = _make_class("c1")
    c2 = _make_class("c2")
    s1 = _make_subject("s1")
    s2 = _make_subject("s2")

    # (c1, s1) already exists
    existing = _make_class_subject("c1", "s1")

    fake_class_query = MagicMock()
    fake_class_query.filter_by.return_value = fake_class_query
    fake_class_query.all.return_value = [c1, c2]

    fake_subject_query = MagicMock()
    fake_subject_query.filter_by.return_value = fake_subject_query
    fake_subject_query.all.return_value = [s1, s2]

    fake_cs_query = MagicMock()
    fake_cs_query.filter.return_value = fake_cs_query
    fake_cs_query.all.return_value = [existing]

    import modules.classes.models as cls_mod
    import modules.subjects.models as subj_mod
    from core.database import db

    fake_class_cls = MagicMock()
    fake_class_cls.query = fake_class_query

    fake_subject_cls = MagicMock()
    fake_subject_cls.query = fake_subject_query

    fake_cs_cls = MagicMock()
    fake_cs_cls.query = fake_cs_query
    # Make class_id.in_() work
    fake_cs_cls.class_id = MagicMock()
    fake_cs_cls.class_id.in_ = MagicMock(return_value=True)

    fake_session = MagicMock()

    monkeypatch.setattr(cls_mod, "Class", fake_class_cls)
    monkeypatch.setattr(subj_mod, "Subject", fake_subject_cls)
    monkeypatch.setattr(svc, "Class", fake_class_cls)
    monkeypatch.setattr(svc, "Subject", fake_subject_cls)
    monkeypatch.setattr(svc, "ClassSubject", fake_cs_cls)
    monkeypatch.setattr(cls_mod, "ClassSubject", fake_cs_cls)
    monkeypatch.setattr(db, "session", fake_session)

    result = svc.apply_subject_offerings(tenant_id="t1", academic_year_id="ay1")

    assert result == {"created": 3, "skipped": 1}
    # 3 ClassSubject instances should have been added
    assert fake_session.add.call_count == 3
    fake_session.commit.assert_called_once()
