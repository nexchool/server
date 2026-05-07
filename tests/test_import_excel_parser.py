"""Tests for Excel parser helpers in import_service — pure-Python, no DB, no Flask.

Uses openpyxl Workbook to build in-memory .xlsx BytesIO fixtures.
"""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def _make_xlsx(rows: list[list]) -> BytesIO:
    """Build an in-memory .xlsx from a list of rows (each row is a list of values)."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


# ---------------------------------------------------------------------------
# parse_headers
# ---------------------------------------------------------------------------


def test_parse_headers_returns_first_row_strings():
    """parse_headers extracts the first row as a list of strings."""
    from modules.school_setup.import_service import parse_headers

    buf = _make_xlsx([
        ["unit_code", "programme_code", "grade", "section", "subject"],
        ["U1", "P1", "Grade 1", "A", "Math"],
    ])
    result = parse_headers(buf, "test.xlsx")
    assert result == ["unit_code", "programme_code", "grade", "section", "subject"]


def test_parse_headers_empty_workbook_returns_empty_list():
    """parse_headers on an empty sheet returns []."""
    from modules.school_setup.import_service import parse_headers

    buf = _make_xlsx([])
    result = parse_headers(buf, "empty.xlsx")
    assert result == []


def test_parse_headers_raises_for_non_xlsx():
    """parse_headers raises UnsupportedFileType for non-.xlsx filenames."""
    from modules.school_setup.import_service import parse_headers, UnsupportedFileType

    buf = BytesIO(b"dummy,csv,content")
    with pytest.raises(UnsupportedFileType):
        parse_headers(buf, "data.csv")


# ---------------------------------------------------------------------------
# parse_workbook
# ---------------------------------------------------------------------------


def test_parse_workbook_maps_cells_by_mapping():
    """parse_workbook maps Excel columns to field names using the supplied mapping."""
    from modules.school_setup.import_service import parse_workbook

    buf = _make_xlsx([
        ["unit_code", "programme_code", "grade", "section"],
        ["U1", "P1", "Grade 1", "A"],
        ["U2", "P2", "Grade 2", "B"],
    ])
    mapping = {
        "unit_code": "unit_code",
        "programme_code": "programme_code",
        "grade": "grade",
        "section": "section",
    }
    rows = parse_workbook(buf, "data.xlsx", mapping)
    assert len(rows) == 2
    assert rows[0] == {"unit_code": "U1", "programme_code": "P1", "grade": "Grade 1", "section": "A"}
    assert rows[1] == {"unit_code": "U2", "programme_code": "P2", "grade": "Grade 2", "section": "B"}


def test_parse_workbook_header_only_returns_empty_list():
    """parse_workbook with only a header row (no data) returns []."""
    from modules.school_setup.import_service import parse_workbook

    buf = _make_xlsx([
        ["unit_code", "programme_code", "grade", "section"],
    ])
    mapping = {
        "unit_code": "unit_code",
        "programme_code": "programme_code",
        "grade": "grade",
        "section": "section",
    }
    rows = parse_workbook(buf, "data.xlsx", mapping)
    assert rows == []


def test_parse_workbook_raises_unsupported_file_type_for_non_xlsx():
    """parse_workbook raises UnsupportedFileType when filename lacks .xlsx extension."""
    from modules.school_setup.import_service import parse_workbook, UnsupportedFileType

    buf = BytesIO(b"not-an-xlsx")
    with pytest.raises(UnsupportedFileType):
        parse_workbook(buf, "data.xls", {"unit_code": "unit_code"})


def test_parse_workbook_raises_value_error_when_row_count_exceeds_max(monkeypatch):
    """parse_workbook raises ValueError when data rows exceed MAX_IMPORT_ROWS."""
    import modules.school_setup.import_service as svc
    monkeypatch.setattr(svc, "MAX_IMPORT_ROWS", 2)

    # 3 data rows → exceeds limit of 2
    buf = _make_xlsx([
        ["unit_code", "grade"],
        ["U1", "G1"],
        ["U2", "G2"],
        ["U3", "G3"],  # this one pushes over the limit
    ])
    with pytest.raises(ValueError, match="exceeds maximum"):
        svc.parse_workbook(buf, "data.xlsx", {"unit_code": "unit_code", "grade": "grade"})


def test_parse_workbook_skips_empty_rows():
    """parse_workbook silently skips rows where all cells are empty/None."""
    from modules.school_setup.import_service import parse_workbook

    buf = _make_xlsx([
        ["unit_code", "grade"],
        ["U1", "G1"],
        [None, None],       # fully empty row → skipped
        ["U2", "G2"],
    ])
    mapping = {"unit_code": "unit_code", "grade": "grade"}
    rows = parse_workbook(buf, "data.xlsx", mapping)
    assert len(rows) == 2
    assert rows[0]["unit_code"] == "U1"
    assert rows[1]["unit_code"] == "U2"


def test_parse_workbook_missing_mapped_column_yields_none():
    """If the mapping references a column not present in the header, the field value is None."""
    from modules.school_setup.import_service import parse_workbook

    buf = _make_xlsx([
        ["unit_code", "grade"],
        ["U1", "G1"],
    ])
    mapping = {
        "unit_code": "unit_code",
        "grade": "grade",
        "section": "section",  # 'section' column does not exist in the file
    }
    rows = parse_workbook(buf, "data.xlsx", mapping)
    assert len(rows) == 1
    assert rows[0]["section"] is None


def test_parse_workbook_uses_custom_column_names():
    """parse_workbook supports arbitrary Excel column header names via mapping."""
    from modules.school_setup.import_service import parse_workbook

    buf = _make_xlsx([
        ["Unit", "Programme", "Year Level", "Class"],
        ["U1", "P1", "Year 1", "Alpha"],
    ])
    mapping = {
        "unit_code": "Unit",
        "programme_code": "Programme",
        "grade": "Year Level",
        "section": "Class",
    }
    rows = parse_workbook(buf, "data.xlsx", mapping)
    assert len(rows) == 1
    assert rows[0] == {
        "unit_code": "U1",
        "programme_code": "P1",
        "grade": "Year 1",
        "section": "Alpha",
    }
