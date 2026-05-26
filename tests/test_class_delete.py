"""Tests for delete_class service — pure-Python, no Flask/DB required.

Covers:
  1. Class not found → success=False, error='Class not found'
  2. Successful delete → success=True
  3. IntegrityError from DB → friendly error message returned
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


# ---------------------------------------------------------------------------
# Test 1: Class not found
# ---------------------------------------------------------------------------

def test_delete_class_returns_error_when_not_found(monkeypatch):
    """delete_class returns success=False when class does not exist."""
    from modules.classes import services

    fake_query = MagicMock()
    fake_query.get.return_value = None
    fake_class_model = MagicMock()
    fake_class_model.query = fake_query

    monkeypatch.setattr(services, "Class", fake_class_model)

    result = services.delete_class("nonexistent-id")

    assert result["success"] is False
    assert result["error"] == "Class not found"


# ---------------------------------------------------------------------------
# Test 2: Successful delete
# ---------------------------------------------------------------------------

def test_delete_class_returns_success_on_valid_delete(monkeypatch):
    """delete_class returns success=True when delete commits without error."""
    from modules.classes import services
    from sqlalchemy.exc import IntegrityError

    fake_cls = MagicMock()
    fake_cls.tenant_id = "tenant-1"

    fake_query = MagicMock()
    fake_query.get.return_value = fake_cls
    fake_class_model = MagicMock()
    fake_class_model.query = fake_query

    fake_session = MagicMock()
    fake_db = MagicMock()
    fake_db.session = fake_session

    monkeypatch.setattr(services, "Class", fake_class_model)
    monkeypatch.setattr(services, "db", fake_db)

    # Suppress the recompute call
    monkeypatch.setattr(
        "modules.school_setup.services.recompute_setup_complete",
        MagicMock(),
        raising=False,
    )

    result = services.delete_class("valid-class-id")

    assert result["success"] is True
    assert result["message"] == "Class deleted"
    fake_session.delete.assert_called_once_with(fake_cls)
    fake_session.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Test 3: IntegrityError → friendly message
# ---------------------------------------------------------------------------

def test_delete_class_returns_friendly_error_on_integrity_error(monkeypatch):
    """delete_class surfaces a friendly message when DB raises IntegrityError."""
    from modules.classes import services
    from sqlalchemy.exc import IntegrityError

    fake_cls = MagicMock()
    fake_cls.tenant_id = "tenant-1"

    fake_query = MagicMock()
    fake_query.get.return_value = fake_cls
    fake_class_model = MagicMock()
    fake_class_model.query = fake_query

    fake_session = MagicMock()
    # Raise IntegrityError on commit
    fake_session.commit.side_effect = IntegrityError(
        statement="DELETE FROM classes",
        params={},
        orig=Exception("fk violation"),
    )
    fake_db = MagicMock()
    fake_db.session = fake_session

    monkeypatch.setattr(services, "Class", fake_class_model)
    monkeypatch.setattr(services, "db", fake_db)

    result = services.delete_class("class-with-dependencies")

    assert result["success"] is False
    assert "students" in result["error"] or "data is still attached" in result["error"]
    fake_session.rollback.assert_called_once()
