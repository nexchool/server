"""The corners of a cache, which is where caches go wrong.

Four separate defects around the one thing this product caches
(`perms:<user_id>`, 120s). None of them is the happy path; all of them are the
kind that surface weeks later as "why can that person still do that".
"""

from __future__ import annotations

import uuid

import pytest

from core import cache
from core.database import db


# ---------------------------------------------------------------------------
# 1. A bulk invalidation must not scan without a bound
# ---------------------------------------------------------------------------

class _Keyspace:
    """A Redis stand-in whose SCAN never finishes returning keys."""

    def __init__(self, total: int):
        self.remaining = total
        self.deleted = 0
        self.scans = 0

    def scan(self, cursor=0, match=None, count=200):
        self.scans += 1
        batch = [f"k{i}" for i in range(min(count, self.remaining))]
        self.remaining -= len(batch)
        # Never report completion while keys remain.
        return (1 if self.remaining else 0), batch

    def delete(self, *keys):
        self.deleted += len(keys)


def test_a_bulk_invalidation_is_bounded(monkeypatch):
    """`invalidate_all_permissions` runs on every role-permission change.

    An unbounded SCAN over a large keyspace holds the connection for as long as
    it takes, and it used to share a database with the Celery broker. The TTL
    already backstops anything missed, so stopping early is safe; running
    forever is not.
    """
    keyspace = _Keyspace(total=1_000_000)
    monkeypatch.setattr(cache, "_redis", lambda: keyspace)

    cache.delete_pattern("erp:cache:v1:perms:*")

    assert keyspace.deleted <= cache.MAX_PATTERN_DELETE_KEYS
    assert keyspace.remaining > 0, "the fixture should still have keys left"


def test_a_small_keyspace_is_deleted_completely(monkeypatch):
    """The bound must not truncate ordinary work."""
    keyspace = _Keyspace(total=50)
    monkeypatch.setattr(cache, "_redis", lambda: keyspace)

    cache.delete_pattern("erp:cache:v1:perms:*")

    assert keyspace.deleted == 50
    assert keyspace.remaining == 0


# ---------------------------------------------------------------------------
# 2. Ending an employment outright must invalidate too
# ---------------------------------------------------------------------------

def test_deleting_an_employment_forgets_its_cached_authority(
    flask_app, db_session, tenant, monkeypatch
):
    """The listener watched `session.dirty` and never `session.deleted`.

    Authority is resolved from employment, so removing the employment row
    removes the authority — but the cached permission set derived from it
    survived until the TTL expired.
    """
    from modules.auth.models import User
    from modules.people.employment import Staff
    from modules.people.models import Person
    from modules.rbac import services as rbac

    forgotten: list[str] = []
    monkeypatch.setattr(
        rbac, "invalidate_user_permissions", lambda uid: forgotten.append(uid)
    )

    suffix = uuid.uuid4().hex[:8]
    person = Person(
        id=f"pe-{suffix}", tenant_id=tenant.id, full_name="Departing Staff"
    )
    db_session.add(person)
    db_session.flush()
    account = User(
        id=f"u-{suffix}", tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name="Departing Staff", person_id=person.id,
    )
    db_session.add(account)
    db_session.flush()
    staff = Staff(id=f"sf-{suffix}", tenant_id=tenant.id, person_id=person.id)
    db_session.add(staff)
    db_session.flush()
    forgotten.clear()

    db_session.delete(staff)
    db_session.flush()

    assert account.id in forgotten, (
        "removing an employment must forget the authority derived from it"
    )


# ---------------------------------------------------------------------------
# 3. Deleting an account must not leave its permissions behind
# ---------------------------------------------------------------------------

def test_deleting_a_user_forgets_their_cached_permissions(
    flask_app, db_session, tenant, monkeypatch
):
    """`delete_user` removed the row and left `perms:<id>` sitting there.

    Not an authorization hole — authentication refuses a missing account
    first — but a cached set outliving the person it describes is exactly the
    kind of thing that stops being harmless when something new reads it.
    """
    from modules.auth.models import User
    from modules.users import services as users_services

    forgotten: list[str] = []
    monkeypatch.setattr(
        users_services, "invalidate_user_permissions", lambda uid: forgotten.append(uid)
    )

    suffix = uuid.uuid4().hex[:8]
    account = User(
        id=f"u-{suffix}", tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name="Leaving",
    )
    db_session.add(account)
    db_session.flush()

    users_services.delete_user(account.id)

    assert account.id in forgotten


# ---------------------------------------------------------------------------
# 4. The key's safety rests on an invariant nothing states
# ---------------------------------------------------------------------------

def test_the_permission_key_is_safe_because_account_ids_are_global():
    """`perms:<user_id>` carries no tenant, and that is only safe by accident.

    It holds because `users.id` is a UUID primary key — unique across the whole
    installation, not per tenant. The moment a cache key is built from an
    identifier that is only unique *within* a tenant, two schools share an
    entry. This pins the assumption so that change fails here rather than in
    production.
    """
    from modules.auth.models import User

    primary_key = User.__table__.primary_key.columns
    assert len(primary_key) == 1, "a composite key would change this argument"
    column = list(primary_key)[0]
    assert column.name == "id"
    assert "tenant" not in str(column.type).lower()

    # And the key really does omit the tenant, so the invariant is load-bearing.
    assert cache.key("perms", "u-1") == "erp:cache:v1:perms:u-1"


def test_a_tenant_scoped_key_helper_exists_for_anything_else(tenant, flask_app):
    """Anything cached per tenant must say so in its key."""
    with flask_app.test_request_context("/"):
        from flask import g

        g.tenant_id = tenant.id
        built = cache.tenant_key("classes", "list")

    assert tenant.id in built, "a tenant-scoped key must name the tenant"
    assert built.startswith("erp:cache:v1:")
