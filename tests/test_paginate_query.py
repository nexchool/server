"""The shared paginator has to survive whatever a caller puts in the query string.

`paginate_query` clamped only the *upper* bound, and the two routes that use it
(`GET /api/users`, the sub-admin list) read `page` and `per_page` straight from
the query string with `type=int` and no floor. So a caller chose the arithmetic:

    ?per_page=0   -> total_pages divides by zero          -> 500
    ?per_page=-5  -> LIMIT -5                             -> 500
    ?page=0       -> OFFSET -20                            -> 500
    ?page=-3      -> OFFSET -80                            -> 500

Fixed here rather than at each route, because the helper is the choke point and
a route that forgets is exactly how this arrived.
"""

from __future__ import annotations

import pytest

from shared.utils import paginate_query


class _Query:
    """Records what the paginator asked the database for."""

    def __init__(self, total: int = 42):
        self._total = total
        self.limit_arg = None
        self.offset_arg = None

    def count(self):
        return self._total

    def limit(self, value):
        self.limit_arg = value
        return self

    def offset(self, value):
        self.offset_arg = value
        return self

    def all(self):
        return []


def test_an_ordinary_page_is_unchanged():
    query = _Query(total=42)

    result = paginate_query(query, page=2, per_page=20)

    assert (query.limit_arg, query.offset_arg) == (20, 20)
    assert result["total"] == 42
    assert result["total_pages"] == 3


@pytest.mark.parametrize("per_page", [0, -1, -100])
def test_a_page_size_below_one_cannot_reach_the_database(per_page):
    """Zero divided; negative became `LIMIT -5`. Both were 500s."""
    query = _Query()

    result = paginate_query(query, page=1, per_page=per_page)

    assert query.limit_arg >= 1
    assert result["total_pages"] >= 1


@pytest.mark.parametrize("page", [0, -3])
def test_a_page_below_one_cannot_produce_a_negative_offset(page):
    query = _Query()

    paginate_query(query, page=page, per_page=20)

    assert query.offset_arg >= 0, "a negative OFFSET is a database error"


def test_the_upper_clamp_still_holds():
    query = _Query()

    paginate_query(query, page=1, per_page=100_000)

    assert query.limit_arg == 100


def test_an_empty_result_reports_no_pages_rather_than_dividing():
    query = _Query(total=0)

    result = paginate_query(query, page=1, per_page=20)

    assert result["total"] == 0
    assert result["total_pages"] == 0
