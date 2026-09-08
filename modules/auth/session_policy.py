"""How long a session lives, and why that is not one number.

Until now it was one number: seven days from sign-in, never extended, for
everybody. That is wrong at both ends. A student who opens the app every single
day was still signed out on day seven, mid-week, for no reason they could see —
because the clock ran from the sign-in and nothing they did moved it. And a
platform operator, who holds authority across every school on the system, got
exactly the same seven days as that student.

So a session now has two limits instead of one.

**The idle limit** slides. Every renewal pushes it forward, so a session in use
stays alive and a session nobody has touched dies on its own. This is the limit
that answers "has this person gone away?"

**The absolute cap** does not slide. It is measured from the moment of sign-in
and nothing extends it, so every session ends eventually no matter how busy it
is. This is the limit that answers "how long may one act of proving who you are
keep working?" — and it is the reason a stolen phone stops being useful without
anybody having to notice it was stolen.

The numbers differ by surface because the risk does:

- A **phone** is a personal object, kept in a pocket, behind the operating
  system's own lock and — where its owner opts in — a biometric gate. Signing a
  child out of it weekly is friction with nothing bought for it.
- A **staff browser** may be a shared machine in a staff room. A working week
  is the natural unit; a month is the outside edge.
- The **panel** is different in kind. An operator there can enter any school on
  the system, and `authenticate_platform_admin` is deliberately cross-tenant.
  Thirty minutes of idle and twelve hours absolute is deliberately close to what
  a bank gives its own staff: a console left alone over lunch is dead, and no
  operator session outlives a working day.
- **`unknown`** is what a client that predates the `X-Client-Surface` header
  sends, and it gets the conservative browser numbers rather than the most
  permissive ones. An old build must keep working (NFR-1); it must not be
  rewarded for saying nothing.

Every value is overridable per deployment — `SESSION_PANEL_IDLE_MINUTES`,
`SESSION_STUDENT_MOBILE_ABSOLUTE_MINUTES`, and so on — so tightening a window
during an incident is a configuration change, not a release.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta

from core.school_time import utc_now

DAY = 24 * 60
HOUR = 60


@dataclass(frozen=True)
class SessionLifetime:
    """The two limits, in minutes."""

    idle_minutes: int
    absolute_minutes: int

    @property
    def idle(self) -> timedelta:
        return timedelta(minutes=self.idle_minutes)

    @property
    def absolute(self) -> timedelta:
        return timedelta(minutes=self.absolute_minutes)


def _configured(surface: str, limit: str, default: int) -> int:
    """This surface's limit, from the environment or the default.

    `student-mobile` reads `SESSION_STUDENT_MOBILE_IDLE_MINUTES`. A value that
    is not a positive integer is ignored rather than obeyed: a typo in a
    deployment variable must not silently produce a session that never expires.
    """
    name = f"SESSION_{surface.upper().replace('-', '_')}_{limit}_MINUTES"
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _lifetime(surface: str, idle: int, absolute: int) -> SessionLifetime:
    return SessionLifetime(
        idle_minutes=_configured(surface, "IDLE", idle),
        absolute_minutes=_configured(surface, "ABSOLUTE", absolute),
    )


#: Keyed by `sessions.client_surface`. Every value in `CLIENT_SURFACES` has an
#: entry; anything else falls back to `unknown`, which is the conservative one.
SESSION_POLICY = {
    "student-mobile": _lifetime("student-mobile", idle=30 * DAY, absolute=90 * DAY),
    "parent-mobile": _lifetime("parent-mobile", idle=30 * DAY, absolute=90 * DAY),
    "admin-web": _lifetime("admin-web", idle=7 * DAY, absolute=30 * DAY),
    "panel": _lifetime("panel", idle=30, absolute=12 * HOUR),
    "public-api": _lifetime("public-api", idle=7 * DAY, absolute=30 * DAY),
    "unknown": _lifetime("unknown", idle=7 * DAY, absolute=30 * DAY),
}

FALLBACK = SESSION_POLICY["unknown"]


def lifetime_for(client_surface: str | None) -> SessionLifetime:
    """The two limits this surface's sessions live by."""
    return SESSION_POLICY.get(client_surface or "unknown", FALLBACK)


def initial_expiry(client_surface: str | None, *, created_at: datetime | None = None) -> datetime:
    """When a session just created would expire if never used again.

    The lesser of the two limits, which for every surface here is the idle one
    — but written as a `min` rather than assumed, so a deployment that
    configures an absolute cap shorter than its idle limit gets the cap it
    asked for instead of a session that outlives it.
    """
    start = created_at or utc_now()
    policy = lifetime_for(client_surface)
    return min(start + policy.idle, start + policy.absolute)


def slid_expiry(session, *, now: datetime | None = None) -> datetime:
    """When a session expires after being renewed at `now`.

    The idle limit moves forward; the absolute cap does not move at all, and
    once it is reached this returns a time in the past — which is exactly
    right. A session at its cap is over, and the next renewal finds it expired
    rather than being handed one more window.
    """
    moment = now or utc_now()
    policy = lifetime_for(getattr(session, "client_surface", None))
    ceiling = session.created_at + policy.absolute
    return min(moment + policy.idle, ceiling)
