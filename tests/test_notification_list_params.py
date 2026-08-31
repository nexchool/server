"""A bad number in the query string must not be a 500.

`list_notifications` parses its paging with a bare `int(...)`:

    limit = min(max(int(request.args.get("limit", 20) or 20), 1), 100)

`?limit=abc` raises ValueError inside the handler, which is an unhandled
exception — the caller gets a 500 for what is their own malformed input, and
it lands in the error logs as if the server broke. Same for `offset`.

The list is otherwise correctly bounded; this is only about how it reads the
two numbers.
"""

from __future__ import annotations

import pytest

from modules.notifications.routes import _paging_arg


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("abc", 20),        # not a number at all
        ("", 20),           # present but empty
        (None, 20),         # absent
        ("1e5", 20),        # float syntax is not an int
        ("12", 12),         # the ordinary case
        ("0", 1),           # clamped up to the minimum
        ("-5", 1),
        ("9999", 100),      # clamped down to the maximum
    ],
)
def test_a_limit_is_read_without_raising(raw, expected):
    assert _paging_arg(raw, default=20, minimum=1, maximum=100) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [("abc", 0), (None, 0), ("-1", 0), ("40", 40)],
)
def test_an_offset_is_read_without_raising(raw, expected):
    assert _paging_arg(raw, default=0, minimum=0) == expected
