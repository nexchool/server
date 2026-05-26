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


# ── invalid FK error paths ─────────────────────────────────────────────

def _validate_fk_factory(invalid_models):
    """Returns a fake _validate_fk that returns False when model is in invalid_models."""

    def _fake(model, pk, tenant_id):
        if model in invalid_models:
            return False
        return True

    return _fake


def test_bulk_generate_rejects_invalid_school_unit_id(monkeypatch):
    """Hits the school_unit_id validation error branch (lines 71-72)."""
    from modules.school_setup import bulk_generator_service as bgs

    monkeypatch.setattr(bgs, "AcademicYear", _fake_year_model(exists=True))
    monkeypatch.setattr(bgs, "_validate_fk", _validate_fk_factory({bgs.SchoolUnit}))

    result = bgs.bulk_generate_classes("tenant-1", {
        "academic_year_id": "y1",
        "cells": [{"grade_id": "g", "school_unit_id": "ghost", "programme_id": "p", "sections": ["A"]}],
    })
    assert result["success"] is False
    assert any("school_unit_id" in e["error"] for e in result["errors"])


def test_bulk_generate_rejects_invalid_programme_id(monkeypatch):
    """Hits the programme_id validation error branch (lines 74-75)."""
    from modules.school_setup import bulk_generator_service as bgs

    monkeypatch.setattr(bgs, "AcademicYear", _fake_year_model(exists=True))
    monkeypatch.setattr(bgs, "_validate_fk", _validate_fk_factory({bgs.AcademicProgramme}))

    result = bgs.bulk_generate_classes("tenant-1", {
        "academic_year_id": "y1",
        "cells": [{"grade_id": "g", "school_unit_id": "u", "programme_id": "ghost", "sections": ["A"]}],
    })
    assert result["success"] is False
    assert any("programme_id" in e["error"] for e in result["errors"])


def test_bulk_generate_rejects_invalid_grade_id(monkeypatch):
    """Hits the grade_id validation error branch (lines 77-78)."""
    from modules.school_setup import bulk_generator_service as bgs

    monkeypatch.setattr(bgs, "AcademicYear", _fake_year_model(exists=True))
    monkeypatch.setattr(bgs, "_validate_fk", _validate_fk_factory({bgs.Grade}))

    result = bgs.bulk_generate_classes("tenant-1", {
        "academic_year_id": "y1",
        "cells": [{"grade_id": "ghost", "school_unit_id": "u", "programme_id": "p", "sections": ["A"]}],
    })
    assert result["success"] is False
    assert any("grade_id" in e["error"] for e in result["errors"])


# ── unknown stream defensive branch ────────────────────────────────────

def test_bulk_generate_rejects_unknown_stream(monkeypatch):
    """If _parse_stream_section returns a stream not in VALID_STREAMS, error out (lines 87-92)."""
    from modules.school_setup import bulk_generator_service as bgs

    monkeypatch.setattr(bgs, "AcademicYear", _fake_year_model(exists=True))
    monkeypatch.setattr(bgs, "_validate_fk", lambda *a, **k: True)
    monkeypatch.setattr(bgs, "Class", _fake_class_model(existing_row=None))
    # Force the parser to return an invalid stream label
    monkeypatch.setattr(bgs, "_parse_stream_section", lambda raw: ("Bogus", "A"))

    fake_session = MagicMock()
    monkeypatch.setattr(bgs.db, "session", fake_session)

    result = bgs.bulk_generate_classes("tenant-1", {
        "academic_year_id": "y1",
        "cells": [{"grade_id": "g", "school_unit_id": "u", "programme_id": "p", "sections": ["A"]}],
    })

    # No classes created — only an error
    assert result["success"] is False
    assert any("Unknown stream prefix" in e["error"] for e in result["errors"])


# ── stream filter branch (line 105) ────────────────────────────────────

def test_bulk_generate_with_stream_uses_stream_filter(monkeypatch):
    """When a section has a stream (Sci-A), the exists query filters by stream value (line 105)."""
    from modules.school_setup import bulk_generator_service as bgs

    monkeypatch.setattr(bgs, "AcademicYear", _fake_year_model(exists=True))
    monkeypatch.setattr(bgs, "_validate_fk", lambda *a, **k: True)
    monkeypatch.setattr(bgs, "Class", _fake_class_model(existing_row=None))

    fake_session = MagicMock()
    monkeypatch.setattr(bgs.db, "session", fake_session)

    result = bgs.bulk_generate_classes("tenant-1", {
        "academic_year_id": "y1",
        "cells": [{"grade_id": "g", "school_unit_id": "u", "programme_id": "p", "sections": ["Sci-A", "Com-B"]}],
    })

    assert result["success"] is True
    assert result["created_count"] == 2
    # Each created Class gets a stream value populated in the summary
    streams = {entry["stream"] for entry in result["created"]}
    assert streams == {"Science", "Commerce"}


# ── _validate_fk implementation ────────────────────────────────────────

def test_validate_fk_returns_true_when_row_exists():
    """Direct call: filter_by(...).first() returns an object → True."""
    from modules.school_setup.bulk_generator_service import _validate_fk

    fake_q = MagicMock()
    fake_q.filter_by.return_value = fake_q
    fake_q.first.return_value = MagicMock(id="x")
    fake_model = MagicMock(spec=[])  # no deleted_at attr
    fake_model.query = fake_q

    assert _validate_fk(fake_model, "x", "tenant-1") is True


def test_validate_fk_returns_false_when_row_missing():
    """Direct call: filter_by(...).first() returns None → False."""
    from modules.school_setup.bulk_generator_service import _validate_fk

    fake_q = MagicMock()
    fake_q.filter_by.return_value = fake_q
    fake_q.first.return_value = None
    fake_model = MagicMock(spec=[])
    fake_model.query = fake_q

    assert _validate_fk(fake_model, "x", "tenant-1") is False


def test_validate_fk_applies_soft_delete_filter():
    """When model has deleted_at, an extra .filter() is applied for soft-deletes."""
    from modules.school_setup.bulk_generator_service import _validate_fk

    fake_q = MagicMock()
    fake_q.filter_by.return_value = fake_q
    fake_q.filter.return_value = fake_q
    fake_q.first.return_value = MagicMock(id="x")

    # Build a class-like object that exposes a `deleted_at` descriptor
    class FakeModel:
        deleted_at = MagicMock()
        deleted_at.is_ = MagicMock(return_value="is-null-clause")
        query = fake_q

    assert _validate_fk(FakeModel, "x", "tenant-1") is True
    # The is_(None) clause must have been used as a filter argument
    fake_q.filter.assert_called_once()
