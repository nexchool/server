"""Tests for the student bulk-import xlsx parser (parse_xlsx_to_rows).

Pure-Python: no DB, no Flask. Builds in-memory .xlsx fixtures with openpyxl.
"""
from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

import pytest

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


def _xlsx_bytes(rows: list[list]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_xlsx_rejects_non_xlsx_with_friendly_error():
    """A non-xlsx blob (a .csv/.xls renamed to .xlsx, or a corrupt download)
    raises a ValueError that tells the admin to re-save as .xlsx — not openpyxl's
    cryptic 'File is not a zip file'."""
    from modules.students.utils.excel_parser import parse_xlsx_to_rows

    with pytest.raises(ValueError) as exc:
        parse_xlsx_to_rows(b"name,email\nAsha,asha@example.com\n")
    msg = str(exc.value)
    assert ".xlsx" in msg
    assert "zip" not in msg.lower()


def test_parse_xlsx_reads_headers_and_rows():
    """A valid workbook yields normalized header keys, data rows, and 1-based
    Excel row numbers (row 1 = headers, data starts at row 2)."""
    from modules.students.utils.excel_parser import parse_xlsx_to_rows

    data = _xlsx_bytes(
        [
            ["Name", "Email", "Class Name", "Section"],
            ["Asha", "asha@example.com", "10 A", "A"],
        ]
    )
    headers, rows, row_numbers = parse_xlsx_to_rows(data)
    assert headers == ["name", "email", "class_name", "section"]
    assert rows[0]["email"] == "asha@example.com"
    assert row_numbers == [2]


def test_parse_xlsx_skips_fully_blank_rows():
    """Rows where every cell is blank are dropped (admins leave trailing blanks),
    and Excel row numbers stay aligned to the surviving rows."""
    from modules.students.utils.excel_parser import parse_xlsx_to_rows

    data = _xlsx_bytes(
        [
            ["name", "email"],
            ["Asha", "asha@example.com"],
            ["", ""],
            [None, None],
        ]
    )
    _headers, rows, row_numbers = parse_xlsx_to_rows(data)
    assert len(rows) == 1
    assert row_numbers == [2]
