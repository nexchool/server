"""Revoking access must not be undone by a concurrent read.

Permissions are the one thing this product caches (`perms:<user_id>`, 120s,
`rbac/services.py`). Most of it is careful — but the invalidation runs at
different points relative to the commit depending on which path you came in
through, and one of those points is wrong:

    invalidate perms:U          <- cache is now empty
    ...                          <- another request for U arrives, misses,
                                    reloads from the *committed* database,
                                    and caches the OLD permissions
    COMMIT                       <- the revocation lands
                                    ...and the cache holds the old set for
                                    the full TTL

So a withdrawn authority, a suspension, or a deleted profile can keep working
for two minutes. `rbac/services.py` says so in a comment — "Caller commits the
surrounding txn; TTL backstops any race" — and the ORM listener in
`authority_service.py` fires on `after_flush`, which is also before the
commit. Meanwhile `sub_admins/services.py` commits first and then invalidates,
which is right. The same operation is therefore safe or unsafe depending on
the route that reached it.

Fixed in the shared helper rather than at seventeen call sites: an
invalidation raised inside a transaction is held until that transaction
commits, and dropped if it rolls back.
"""

from __future__ import annotations

import pytest

from core.database import db
from modules.rbac import services as rbac


@pytest.fixture(autouse=True)
def _in_a_transaction(db_session):
    """Put the session in a transaction, as any real caller already has.

    SQLAlchemy 2.0 autobegins lazily, so a Session that has not touched the
    database yet reports `in_transaction() == False`. Every path that
    invalidates permissions has just written rows, so a transaction is open by
    the time it gets there — this reproduces that rather than the empty case.
    """
    from sqlalchemy import text

    db_session.execute(text("SELECT 1"))


@pytest.fixture
def dropped(monkeypatch):
    """Record the keys actually deleted from Redis."""
    from core import cache

    seen: list[str] = []
    monkeypatch.setattr(cache, "delete", lambda *keys: seen.extend(keys))
    monkeypatch.setattr(cache, "delete_pattern", lambda pattern: seen.append(pattern))
    return seen


def test_an_invalidation_inside_a_transaction_waits_for_the_commit(
    flask_app, db_session, dropped
):
    """The window this closes: cleared early, then repopulated stale."""
    assert db.session().in_transaction(), "the test session is mid-transaction"

    rbac.invalidate_user_permissions("u-someone")

    assert dropped == [], (
        "clearing before the commit lets a concurrent reader repopulate "
        "the old permissions and pin them for the whole TTL"
    )


def test_the_commit_is_what_actually_clears_it(flask_app, db_session, dropped):
    rbac.invalidate_user_permissions("u-someone")

    rbac.flush_pending_permission_invalidations(db.session())

    assert dropped == [rbac_key("u-someone")]


def test_a_rollback_discards_the_invalidation(flask_app, db_session, dropped):
    """Nothing changed, so nothing needs forgetting."""
    rbac.invalidate_user_permissions("u-someone")

    rbac.discard_pending_permission_invalidations(db.session())
    rbac.flush_pending_permission_invalidations(db.session())

    assert dropped == []


def test_the_same_user_twice_is_dropped_once(flask_app, db_session, dropped):
    rbac.invalidate_user_permissions("u-someone")
    rbac.invalidate_user_permissions("u-someone")

    rbac.flush_pending_permission_invalidations(db.session())

    assert dropped == [rbac_key("u-someone")]


def test_a_whole_cache_drop_also_waits(flask_app, db_session, dropped):
    """`invalidate_all_permissions` has the same race, on every user at once."""
    rbac.invalidate_all_permissions()
    assert dropped == []

    rbac.flush_pending_permission_invalidations(db.session())

    assert dropped == [rbac_key("*")]


def test_the_session_listeners_are_registered():
    """Without these, a queued invalidation would never run."""
    from sqlalchemy import event
    from sqlalchemy.orm import Session as OrmSession

    assert event.contains(
        OrmSession, "after_commit", rbac._flush_permission_invalidations_on_commit
    )
    assert event.contains(
        OrmSession, "after_rollback", rbac._discard_permission_invalidations_on_rollback
    )


def rbac_key(suffix: str) -> str:
    from core import cache

    return cache.key("perms", suffix)
