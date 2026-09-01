"""A spreadsheet upload is read whole into memory and then parsed in process.

The three bulk importers — students, teachers, examination marks — each carry
their own copy of `_read_xlsx_bytes`, and none of them bounds the size. The
only ceiling is the global `MAX_CONTENT_LENGTH` of 64 MB, shared with every
other endpoint.

That matters for two reasons, neither of which is an open door — all three
routes require a create permission, so this is a signed-in administrator, not
an anonymous caller:

  * an xlsx is a zip. Sixty-four megabytes of it decompresses to far more, and
    openpyxl expands it in the worker's own memory. Production runs a small
    number of gunicorn threads, so one bad file takes the worker down and every
    request sharing it.

  * a genuinely large import is a normal thing for this product. A trust
    onboarding 15,000 students has a real spreadsheet, and "the worker died" is
    the wrong way to find out it was too big.

A measured cap turns both into a clear refusal. 25 MB is far above a
15,000-row sheet (a few megabytes) and far below what hurts.
"""

from __future__ import annotations

import io

import pytest

from core.uploads import (
    MAX_SPREADSHEET_BYTES,
    SpreadsheetTooLarge,
    read_spreadsheet_bytes,
)


class _Upload:
    """Stands in for a Werkzeug FileStorage."""

    def __init__(self, data: bytes, filename: str = "students.xlsx"):
        self.filename = filename
        self.stream = io.BytesIO(data)

    def read(self, *args):
        return self.stream.read(*args)

    def seek(self, *args):
        return self.stream.seek(*args)

    def tell(self):
        return self.stream.tell()


def test_an_ordinary_sheet_is_read(): 
    data = b"PK\x03\x04" + b"rows" * 100

    assert read_spreadsheet_bytes(_Upload(data)) == data


def test_a_sheet_at_the_limit_is_still_accepted():
    """The cap is a ceiling, not a fence just below the real maximum."""
    data = b"P" * MAX_SPREADSHEET_BYTES

    assert len(read_spreadsheet_bytes(_Upload(data))) == MAX_SPREADSHEET_BYTES


def test_a_sheet_over_the_limit_is_refused():
    data = b"P" * (MAX_SPREADSHEET_BYTES + 1)

    with pytest.raises(SpreadsheetTooLarge):
        read_spreadsheet_bytes(_Upload(data))


def test_an_oversize_sheet_is_not_read_into_memory_first():
    """Refusing after loading it would defeat the point.

    The stream is measured by seeking, so nothing large is ever materialised —
    which is what protects the worker rather than merely reporting on it.
    """
    huge = MAX_SPREADSHEET_BYTES * 4

    class _Tripwire(_Upload):
        def __init__(self):
            super().__init__(b"")
            # The helper measures `upload.stream`; point it back at this
            # object so the overrides below are what it sees.
            self.stream = self
            self.read_calls = 0

        def read(self, *args):
            self.read_calls += 1
            return b"P" * huge

        def seek(self, offset, whence=0):
            return 0

        def tell(self):
            return huge

    upload = _Tripwire()
    with pytest.raises(SpreadsheetTooLarge):
        read_spreadsheet_bytes(upload)

    assert upload.read_calls == 0, "the file was read before being refused"


def test_an_empty_file_is_refused():
    with pytest.raises(ValueError):
        read_spreadsheet_bytes(_Upload(b""))


def test_a_missing_file_is_refused():
    with pytest.raises(ValueError):
        read_spreadsheet_bytes(None)


def test_a_file_that_is_not_a_spreadsheet_is_refused():
    with pytest.raises(ValueError):
        read_spreadsheet_bytes(_Upload(b"PK\x03\x04", filename="students.csv"))


def test_the_extension_check_ignores_case():
    data = b"PK\x03\x04"

    assert read_spreadsheet_bytes(_Upload(data, filename="STUDENTS.XLSX")) == data


def test_the_three_importers_share_one_reader():
    """They had a copy each, and the marks one says so in its docstring.

    Three copies is how one of them ends up with a bound and the others do not.
    """
    import pathlib
    import re

    offenders = []
    for path in (
        "modules/students/bulk_import_routes.py",
        "modules/teachers/bulk_import_routes.py",
        "modules/examinations/marks_import_routes.py",
    ):
        src = pathlib.Path(path).read_text()
        if re.search(r"^\s*data = \w+\.read\(\)\s*$", src, re.M):
            offenders.append(path)

    assert offenders == [], (
        "these read an upload whole with no bound of their own:\n  "
        + "\n  ".join(offenders)
    )
