"""Tests for medium_id and stream persistence on Class.

Pure-Python / mock-based — no DB, no Flask app context required.

Covers:
  1. create_class persists medium_id and stream
  2. update_class updates stream to a new value
  3. update_class clears stream when explicitly passed empty string
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def _make_fake_class(**kwargs):
    """Return a MagicMock that behaves like a Class instance."""
    obj = MagicMock()
    for k, v in kwargs.items():
        setattr(obj, k, v)
    obj.to_dict.return_value = {k: v for k, v in kwargs.items()}
    return obj


def test_create_class_persists_medium_id_and_stream(monkeypatch):
    """create_class should pass medium_id and stream to the Class constructor."""
    from modules.classes import services

    created_kwargs = {}

    def fake_class_init(**kw):
        created_kwargs.update(kw)
        obj = _make_fake_class(**kw)
        obj.id = "cls-1"
        obj.save = MagicMock()
        return obj

    fake_class_cls = MagicMock(side_effect=fake_class_init)

    # Minimal query stubs so the function reaches Class(...)
    fake_query = MagicMock()
    fake_query.filter_by.return_value = fake_query
    fake_query.first.return_value = None  # no duplicate, no existing teacher class
    fake_class_cls.query = fake_query

    monkeypatch.setattr(services, "Class", fake_class_cls)
    monkeypatch.setattr(services, "get_tenant_id", lambda: "t1")

    # Stub _resolve_class_teacher_user_id to be a no-op
    monkeypatch.setattr(services, "_resolve_class_teacher_user_id", lambda tid, tid2: None)

    result = services.create_class(
        name="Grade 11 A",
        section="A",
        academic_year_id="ay-1",
        medium_id="med-english",
        stream="Science",
    )

    assert result.get("success") is True, f"Expected success, got: {result}"
    assert created_kwargs.get("medium_id") == "med-english"
    assert created_kwargs.get("stream") == "Science"


def test_update_class_updates_stream(monkeypatch):
    """update_class should update stream when a new value is provided."""
    from modules.classes import services

    fake_cls = _make_fake_class(
        id="cls-2",
        tenant_id="t1",
        name="Grade 11",
        section="B",
        academic_year_id="ay-1",
        stream="Commerce",
        medium_id=None,
    )
    fake_cls.save = MagicMock()
    fake_cls.to_dict.return_value = {"id": "cls-2", "stream": "Science"}

    fake_query = MagicMock()
    fake_query.filter_by.return_value = fake_query
    fake_query.first.return_value = fake_cls
    # Also handle filter(...).first() used for duplicate check
    fake_query.filter.return_value = fake_query

    fake_class_cls = MagicMock()
    fake_class_cls.query = fake_query

    monkeypatch.setattr(services, "Class", fake_class_cls)
    monkeypatch.setattr(services, "get_tenant_id", lambda: "t1")

    result = services.update_class("cls-2", stream="Science")

    assert result.get("success") is True, f"Expected success, got: {result}"
    assert fake_cls.stream == "Science"


def test_update_class_clears_stream_on_empty_string(monkeypatch):
    """update_class should set stream=None when passed an empty string."""
    from modules.classes import services

    fake_cls = _make_fake_class(
        id="cls-3",
        tenant_id="t1",
        name="Grade 11",
        section="C",
        academic_year_id="ay-1",
        stream="Arts",
        medium_id=None,
    )
    fake_cls.save = MagicMock()
    fake_cls.to_dict.return_value = {"id": "cls-3", "stream": None}

    fake_query = MagicMock()
    fake_query.filter_by.return_value = fake_query
    fake_query.first.return_value = fake_cls
    fake_query.filter.return_value = fake_query

    fake_class_cls = MagicMock()
    fake_class_cls.query = fake_query

    monkeypatch.setattr(services, "Class", fake_class_cls)
    monkeypatch.setattr(services, "get_tenant_id", lambda: "t1")

    result = services.update_class("cls-3", stream="")

    assert result.get("success") is True, f"Expected success, got: {result}"
    assert fake_cls.stream is None
