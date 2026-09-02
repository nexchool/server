"""One paging shape for the hostel lists.

Two callers want different things from the same query, and the difference
matters: a screen wants a page, while `rollover_allocations_task` must close
**every** active allocation at year end. Handing that task a page would close
the first few boarders and silently leave the rest on last year's beds.

So the rule, following `get_all_classes`: omit page/per_page and every matching
row comes back with total_pages = 1. It is the route that always pages, because
the HTTP surface is the one that has to be bounded.
"""

from __future__ import annotations

from typing import Optional

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100


def positive_int(value, *, default: int, maximum: Optional[int] = None) -> int:
    """Coerce a query-string number, falling back rather than raising."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    number = max(1, number)
    return min(number, maximum) if maximum else number


def paginate(query, *, order_by, page=None, per_page=None,
             default_page_size: int = DEFAULT_PAGE_SIZE,
             max_page_size: int = MAX_PAGE_SIZE) -> dict:
    """Return ``{items, total, page, per_page, total_pages}``.

    `order_by` must be a total order — every one of these lists sorts on a
    timestamp that ties constantly (a warden admits a batch of boarders in one
    sitting), and LIMIT/OFFSET over a partial order serves some rows on two
    pages and others on none. Pass the id as the last term.
    """
    total = query.count()
    ordered = query.order_by(*order_by)

    if page is None and per_page is None:
        return {
            "items": ordered.all(),
            "total": total,
            "page": 1,
            "per_page": total,
            "total_pages": 1,
        }

    page = positive_int(page, default=1)
    per_page = positive_int(
        per_page, default=default_page_size, maximum=max_page_size
    )
    items = ordered.limit(per_page).offset((page - 1) * per_page).all()

    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
    }
