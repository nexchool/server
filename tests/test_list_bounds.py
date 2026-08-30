"""No list may read a whole table because a caller left a parameter off.

The dominant shape across this codebase is **opt-in pagination** — "if the
caller passed `page`, paginate; otherwise `.all()`" — so the cap only applied
on the path a client opted into. Roughly two dozen endpoints are shaped that
way.

Most of them cannot simply be capped: their clients derive totals from
`array.length` (announcement read-receipts, hostel occupancy, transport rider
counts) or filter the full set in the browser, so a silent cap would produce
*wrong numbers* rather than a visible truncation. Those need the client
changed first and are deliberately untouched here.

What this file pins is the subset where no client depends on completeness, plus
the caller-controlled limits that were never clamped at all.
"""

from __future__ import annotations

import pytest

from modules.attendance import services as attendance_services
from modules.classes import services as classes_services


# ---------------------------------------------------------------------------
# Caller-controlled limits that reached `.limit()` unclamped
# ---------------------------------------------------------------------------

class _Recorder:
    """Captures what a service asked the database for."""

    def __init__(self):
        self.limit_arg = None
        self.offset_arg = None

    def limit(self, value):
        self.limit_arg = value
        return self

    def offset(self, value):
        self.offset_arg = value
        return self

    def all(self):
        return []

    def count(self):
        return 0


def test_the_attendance_page_size_honours_the_documented_maximum():
    """It clamped to 200 — double the maximum api-conventions states."""
    assert attendance_services.MAX_ATTENDANCE_PAGE_SIZE == 100


def test_the_classes_page_size_has_a_ceiling():
    assert classes_services.MAX_PER_PAGE == 100


@pytest.mark.parametrize(
    "routes_module, line_desc",
    [
        ("modules.rbac.routes", "permissions and roles"),
    ],
)
def test_rbac_limits_are_clamped(routes_module, line_desc):
    """`?limit=` flowed straight into `.limit()` on both rbac lists."""
    import importlib
    import inspect

    source = inspect.getsource(importlib.import_module(routes_module))
    unclamped = "limit = request.args.get('limit', 100, type=int)"
    assert unclamped not in source, (
        f"an unclamped ?limit= reached .limit() for {line_desc}"
    )


def test_the_holiday_list_limit_is_clamped():
    import inspect

    from modules.academics.calendar import holiday_routes

    source = inspect.getsource(holiday_routes)
    assert 'limit = int(request.args.get("limit", 100))' not in source, (
        "the holiday list took ?limit= verbatim while its sibling clamped"
    )


# ---------------------------------------------------------------------------
# Corrections: filtered in SQL, not by reading the tenant and picking in Python
# ---------------------------------------------------------------------------

def test_correction_queue_accepts_a_narrowing_filter():
    """Both callers read every correction in the tenant and filtered after.

    `correctionsForMark` wanted one mark's history, and the re-read after every
    approve/reject wanted one row — so deciding a single correction scanned
    every correction the school had ever raised.
    """
    import inspect

    from modules.examinations import corrections_service

    signature = inspect.signature(corrections_service.correction_queue)
    assert "exam_mark_id" in signature.parameters
    assert "correction_id" in signature.parameters


def test_the_resolvers_narrow_instead_of_filtering_in_python():
    import inspect

    from modules.examinations import resolvers

    source = inspect.getsource(resolvers)
    assert 'if row["correction"].exam_mark_id == str(exam_mark_id)' not in source, (
        "correctionsForMark is still scanning the tenant's corrections"
    )
