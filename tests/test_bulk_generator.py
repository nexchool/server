"""Tests for bulk class generator service — pure-Python, no DB."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


# ── _parse_stream_section ──────────────────────────────────────────────

def test_parse_stream_section_plain_letter():
    from modules.school_setup.bulk_generator_service import _parse_stream_section
    assert _parse_stream_section("A") == (None, "A")


def test_parse_stream_section_science():
    from modules.school_setup.bulk_generator_service import _parse_stream_section
    assert _parse_stream_section("Sci-A") == ("Science", "A")


def test_parse_stream_section_commerce():
    from modules.school_setup.bulk_generator_service import _parse_stream_section
    assert _parse_stream_section("Com-B") == ("Commerce", "B")


def test_parse_stream_section_arts():
    from modules.school_setup.bulk_generator_service import _parse_stream_section
    assert _parse_stream_section("Arts-A") == ("Arts", "A")


def test_parse_stream_section_vocational():
    from modules.school_setup.bulk_generator_service import _parse_stream_section
    assert _parse_stream_section("Voc-A") == ("Vocational", "A")


def test_parse_stream_section_unknown_prefix_falls_through():
    from modules.school_setup.bulk_generator_service import _parse_stream_section
    # Unknown prefix is treated as plain section text
    assert _parse_stream_section("Xyz-A") == (None, "Xyz-A")


# ── bulk_generate_classes input validation ────────────────────────────

def test_bulk_generate_rejects_missing_academic_year_id(monkeypatch):
    from modules.school_setup.bulk_generator_service import bulk_generate_classes
    result = bulk_generate_classes("tenant-1", {"cells": [{"grade_id": "g", "school_unit_id": "u", "programme_id": "p", "sections": ["A"]}]})
    assert result["success"] is False
    assert "academic_year_id" in result["error"]


def test_bulk_generate_rejects_empty_cells():
    from modules.school_setup.bulk_generator_service import bulk_generate_classes
    result = bulk_generate_classes("tenant-1", {"academic_year_id": "y1", "cells": []})
    assert result["success"] is False
    assert "cells" in result["error"]


def _fake_year_model(exists: bool):
    """Return a MagicMock standing in for the AcademicYear class.

    Patches the module-level name (bgs.AcademicYear) rather than the
    descriptor on the real class so no Flask app-context is needed.
    """
    fake_q = MagicMock()
    fake_q.filter_by.return_value = fake_q
    fake_q.first.return_value = MagicMock(id="y1") if exists else None
    fake_model = MagicMock()
    fake_model.query = fake_q
    return fake_model


def test_bulk_generate_rejects_invalid_academic_year_id(monkeypatch):
    """When AcademicYear.query.filter_by(...).first() returns None."""
    from modules.school_setup import bulk_generator_service as bgs

    monkeypatch.setattr(bgs, "AcademicYear", _fake_year_model(exists=False))

    result = bgs.bulk_generate_classes("tenant-1", {
        "academic_year_id": "ghost",
        "cells": [{"grade_id": "g", "school_unit_id": "u", "programme_id": "p", "sections": ["A"]}],
    })
    assert result["success"] is False
    assert "academic_year_id" in result["error"].lower()


def test_bulk_generate_rejects_cell_missing_required_fields(monkeypatch):
    """A cell with empty sections list or missing IDs fails validation."""
    from modules.school_setup import bulk_generator_service as bgs

    monkeypatch.setattr(bgs, "AcademicYear", _fake_year_model(exists=True))

    result = bgs.bulk_generate_classes("tenant-1", {
        "academic_year_id": "y1",
        "cells": [{"grade_id": None, "school_unit_id": "u", "programme_id": "p", "sections": ["A"]}],
    })
    assert result["success"] is False
    assert "errors" in result


# ── happy path with full mock ────────────────────────────────────────

def _fake_class_model(existing_row=None):
    """Return a MagicMock standing in for the Class model."""
    fake_q = MagicMock()
    fake_q.filter.return_value = fake_q
    fake_q.first.return_value = existing_row
    fake_model = MagicMock()
    fake_model.query = fake_q
    return fake_model


def test_bulk_generate_creates_classes_for_valid_cells(monkeypatch):
    """All FKs valid + no existing class → creates new Class rows."""
    from modules.school_setup import bulk_generator_service as bgs

    monkeypatch.setattr(bgs, "AcademicYear", _fake_year_model(exists=True))
    monkeypatch.setattr(bgs, "_validate_fk", lambda *a, **k: True)
    monkeypatch.setattr(bgs, "Class", _fake_class_model(existing_row=None))

    # Fake db.session
    fake_session = MagicMock()
    monkeypatch.setattr(bgs.db, "session", fake_session)

    result = bgs.bulk_generate_classes("tenant-1", {
        "academic_year_id": "y1",
        "cells": [{"grade_id": "g", "school_unit_id": "u", "programme_id": "p", "sections": ["A", "B", "C"]}],
    })

    assert result["success"] is True
    assert result["created_count"] == 3
    assert result["skipped_count"] == 0
    fake_session.commit.assert_called_once()
    assert fake_session.add.call_count == 3


def test_bulk_generate_idempotent_skip_existing(monkeypatch):
    """When Class.query returns existing rows, skip them."""
    from modules.school_setup import bulk_generator_service as bgs

    monkeypatch.setattr(bgs, "AcademicYear", _fake_year_model(exists=True))
    monkeypatch.setattr(bgs, "_validate_fk", lambda *a, **k: True)
    monkeypatch.setattr(bgs, "Class", _fake_class_model(existing_row=MagicMock(id="existing-class")))

    fake_session = MagicMock()
    monkeypatch.setattr(bgs.db, "session", fake_session)

    result = bgs.bulk_generate_classes("tenant-1", {
        "academic_year_id": "y1",
        "cells": [{"grade_id": "g", "school_unit_id": "u", "programme_id": "p", "sections": ["A"]}],
    })

    assert result["success"] is True
    assert result["created_count"] == 0
    assert result["skipped_count"] == 1


def test_bulk_generate_handles_commit_failure(monkeypatch):
    """Simulated db.session.commit failure → rollback + success=False."""
    from modules.school_setup import bulk_generator_service as bgs

    monkeypatch.setattr(bgs, "AcademicYear", _fake_year_model(exists=True))
    monkeypatch.setattr(bgs, "_validate_fk", lambda *a, **k: True)
    monkeypatch.setattr(bgs, "Class", _fake_class_model(existing_row=None))

    fake_session = MagicMock()
    fake_session.commit.side_effect = RuntimeError("boom")
    monkeypatch.setattr(bgs.db, "session", fake_session)

    result = bgs.bulk_generate_classes("tenant-1", {
        "academic_year_id": "y1",
        "cells": [{"grade_id": "g", "school_unit_id": "u", "programme_id": "p", "sections": ["A"]}],
    })

    assert result["success"] is False
    assert "boom" in result["error"]
    fake_session.rollback.assert_called_once()


def test_bulk_generate_skips_blank_sections(monkeypatch):
    """Empty / whitespace-only section strings are silently skipped."""
    from modules.school_setup import bulk_generator_service as bgs

    monkeypatch.setattr(bgs, "AcademicYear", _fake_year_model(exists=True))
    monkeypatch.setattr(bgs, "_validate_fk", lambda *a, **k: True)
    monkeypatch.setattr(bgs, "Class", _fake_class_model(existing_row=None))

    fake_session = MagicMock()
    monkeypatch.setattr(bgs.db, "session", fake_session)

    result = bgs.bulk_generate_classes("tenant-1", {
        "academic_year_id": "y1",
        "cells": [{"grade_id": "g", "school_unit_id": "u", "programme_id": "p", "sections": ["", "  ", "A"]}],
    })

    assert result["success"] is True
    assert result["created_count"] == 1  # only "A" counted
