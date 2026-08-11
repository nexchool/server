"""What time it is at the school, as opposed to what time it is on the server.

Two different questions kept being answered by the same clock, and the
confusion was the bug.

**"When did this happen?"** is an instant. It belongs in UTC, stored with the
offset attached so nobody downstream has to guess. `utc_now()` answers it.
The codebase used to answer it with a naive value, so `.isoformat()` emitted no
offset — and JavaScript reads an offsetless datetime as *local*. An
announcement written at 04:32 IST was displayed to every user as 23:02 the
previous evening.

**"What day is it at the school?"** is a local question. A teacher marking
attendance at 8am means the 8th of August wherever the school is, and the
server's clock has no useful opinion — ours runs UTC, so between midnight and
05:30 IST it is still on yesterday. `school_today()` answers it.

Both were wrong only at the edges of the day, which is exactly why they lasted.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import g, has_request_context

# Every school on the platform today is in India. This is the fallback for rows
# written before the column existed, and for work that runs outside a request —
# a Celery job, a seeding script — where there is no tenant to ask.
DEFAULT_SCHOOL_TIMEZONE = "Asia/Kolkata"

UTC = timezone.utc


def utc_now() -> datetime:
    """The current instant, in UTC, carrying its offset."""
    return datetime.now(UTC)


def _zone_name_for(tenant_id: str | None) -> str:
    """The IANA zone this tenant keeps its clocks in."""
    from core.models import Tenant

    # Tenant resolution has already loaded the row on a normal request, so in
    # the common case this costs no query at all.
    if tenant_id is None and has_request_context():
        tenant = getattr(g, "tenant", None)
        if tenant is not None:
            return getattr(tenant, "timezone", None) or DEFAULT_SCHOOL_TIMEZONE
        tenant_id = getattr(g, "tenant_id", None)

    if not tenant_id:
        return DEFAULT_SCHOOL_TIMEZONE

    tenant = Tenant.query.get(tenant_id)
    return (tenant.timezone if tenant else None) or DEFAULT_SCHOOL_TIMEZONE


def school_timezone(tenant_id: str | None = None) -> ZoneInfo:
    """The tenant's timezone, falling back rather than failing.

    A zone name the system cannot resolve should not take a school's attendance
    page down with it, so it degrades to the default. Writes are validated, but
    the data is older than the validation.
    """
    name = _zone_name_for(tenant_id)
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_SCHOOL_TIMEZONE)


def school_now(tenant_id: str | None = None) -> datetime:
    """The current instant, expressed in the school's local time."""
    return datetime.now(school_timezone(tenant_id))


def school_today(tenant_id: str | None = None) -> date:
    """The date it currently is *at the school*.

    Use this for anything a school would call "today": whether attendance is
    being taken for a day that has not happened, which lesson is on now,
    whether a fee is overdue.
    """
    return school_now(tenant_id).date()


def to_school_time(moment: datetime | None, tenant_id: str | None = None) -> datetime | None:
    """Re-express an instant in the school's local time.

    A naive value is read as UTC, because that is what the database held before
    its columns carried an offset.
    """
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(school_timezone(tenant_id))


def is_valid_timezone(name: str) -> bool:
    """Whether this is a zone the system can actually resolve."""
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False
