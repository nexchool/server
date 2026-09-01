"""Reading an uploaded file without letting it decide how much memory to use.

The three bulk importers — students, teachers, examination marks — each grew
their own `_read_xlsx_bytes`, and the newest one says in its docstring that it
is copying the oldest. None of them bounded the size, so the only ceiling was
the global `MAX_CONTENT_LENGTH` of 64 MB shared with every other endpoint.

An xlsx is a zip, and openpyxl expands it inside the worker. Production runs a
small number of gunicorn threads, so one oversized file takes down the worker
and everything sharing it — and a trust onboarding 15,000 students has a
genuinely large spreadsheet, which is the wrong way to discover the ceiling.

The size is measured by seeking rather than by reading, so an oversized upload
is refused before anything large exists in memory. That is the part that
protects the worker; refusing after loading it would only report the problem.
"""

from __future__ import annotations

import os
from typing import Optional

#: Far above a 15,000-row sheet (a few megabytes), far below what hurts.
MAX_SPREADSHEET_BYTES: int = int(
    os.getenv("MAX_SPREADSHEET_BYTES", str(25 * 1024 * 1024))
)

SPREADSHEET_EXTENSIONS = (".xlsx",)


class SpreadsheetTooLarge(Exception):
    """The upload is larger than this endpoint will read.

    Separate from ValueError so a route can answer 413 for this and 400 for the
    ordinary "that is not a spreadsheet" refusals.
    """

    def __init__(self, size: int, limit: int = MAX_SPREADSHEET_BYTES):
        self.size = size
        self.limit = limit
        super().__init__(
            f"Spreadsheet is {size} bytes; the limit is {limit}"
        )


def _measured_size(stream) -> Optional[int]:
    """Length of a seekable stream, without reading it. None if not seekable."""
    try:
        here = stream.tell()
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(here)
        return size
    except (AttributeError, OSError, ValueError):
        return None


def read_spreadsheet_bytes(upload, *, limit: int = MAX_SPREADSHEET_BYTES) -> bytes:
    """The bytes of an uploaded .xlsx, or an exception saying why not.

    Raises:
        ValueError: no file, wrong extension, or empty.
        SpreadsheetTooLarge: over `limit`, measured before reading.
    """
    if upload is None or not getattr(upload, "filename", ""):
        raise ValueError("file is required (xlsx)")

    name = (upload.filename or "").lower()
    if not name.endswith(SPREADSHEET_EXTENSIONS):
        raise ValueError("Only .xlsx files are accepted")

    stream = getattr(upload, "stream", upload)
    size = _measured_size(stream)
    if size is not None and size > limit:
        raise SpreadsheetTooLarge(size, limit)

    data = upload.read()

    # A stream that would not report its length still must not be trusted;
    # this is the backstop for that case, after the fact but before parsing.
    if size is None and len(data) > limit:
        raise SpreadsheetTooLarge(len(data), limit)
    if not data:
        raise ValueError("File is empty")
    return data
