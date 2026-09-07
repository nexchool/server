"""What a test double pretended to send, so a developer can read it.

A fake provider that returns a reference and throws the message away makes
`mobile_otp` untestable: the code exists, it is valid for five minutes, and
nothing anywhere can tell you what it is. This is the smallest thing that
fixes that.

**In memory, and bounded.** A table would mean a migration, a purge job, and
an OTP in plaintext at rest — which is precisely what the rest of the
authentication module refuses to have. A ring buffer that does not survive a
restart is the right amount of durability for something whose only reader is
a developer with the application running in front of them.

**Not reachable in production.** The endpoint that reads this consults
`resolver._test_doubles_allowed`, the same predicate that decides whether a
fake may run at all. One predicate rather than two that can disagree.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Dict, List

from core.school_time import utc_now

#: How many messages to keep. Enough to debug a flow, few enough that this
#: cannot grow into a memory problem in a long-running development server.
CAPACITY = 50

_messages: deque = deque(maxlen=CAPACITY)
_lock = threading.Lock()


def record(*, tenant_id: str, channel: str, destination: str, body: str, purpose: str) -> None:
    """Keep what a fake provider was asked to send.

    Called only from `messaging.send_message`, after a test double reports
    success. A real provider must never reach this: the body of a real OTP is
    a live secret, and the whole argument for keeping this in memory rests on
    it only ever holding fictional ones.
    """
    with _lock:
        _messages.appendleft(
            {
                "tenant_id": tenant_id,
                "channel": channel,
                "destination": destination,
                "body": body,
                "purpose": purpose,
                "sent_at": utc_now().isoformat(),
            }
        )


def recent(limit: int = 20) -> List[Dict]:
    """The most recent messages, newest first."""
    with _lock:
        return list(_messages)[: max(1, limit)]


def clear() -> None:
    """Empty it. For tests, and for a developer starting a fresh walk-through."""
    with _lock:
        _messages.clear()
