"""Deleting an account leaves nothing behind that points at it.

Removing a school's last-but-one administrator deletes the `User` row when the
account administers nothing and is nobody here (`platform.remove_tenant_admin`).
Two tables carry a **NOT NULL** `user_id` at it, and both already say
`ON DELETE CASCADE` — so the database was always able to clear them.

SQLAlchemy was not. A `backref` collection on `User` makes the ORM try to
*de-associate* the children first, which means `UPDATE … SET user_id = NULL`
against a NOT NULL column, and the delete fails with an IntegrityError that
reads like a data problem rather than a mapping one. `passive_deletes=True` is
what tells the ORM the database has this.

These tests delete an account that owns a row in each table. Without the flag
they fail with the production error verbatim.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from core.database import db
from modules.devices.models import DeviceToken
from modules.notifications.models import Notification, NotificationRecipient


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def account(db_session, tenant):
    from modules.auth.models import User

    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=f"u-{suffix}", tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name="Departing Admin",
    )
    db_session.add(user)
    db_session.flush()
    return user


def test_deleting_an_account_takes_its_notification_rows_with_it(
    db_session, tenant, account
):
    """The production failure: DELETE /platform/tenants/<id>/admins/<id> → 500,
    `null value in column "user_id" of relation "notification_recipients"`."""
    notification = Notification(
        id=_new_id("nt-"), tenant_id=tenant.id, user_id=None,
        type="ANNOUNCEMENT", channel="in_app", title="Sports day",
    )
    db_session.add(notification)
    db_session.flush()
    recipient = NotificationRecipient(
        id=_new_id("nr-"), notification_id=notification.id, user_id=account.id,
    )
    db_session.add(recipient)
    db_session.flush()
    recipient_id = recipient.id

    db_session.delete(account)
    db_session.flush()

    # The database's ON DELETE CASCADE cleared it; the ORM did not try to
    # blank a NOT NULL column on the way.
    assert NotificationRecipient.query.filter_by(id=recipient_id).first() is None
    # The parent notification is nobody's in particular and stays.
    assert Notification.query.filter_by(id=notification.id).first() is not None


def test_deleting_an_account_takes_its_device_tokens_with_it(
    db_session, tenant, account
):
    """The same mapping defect, one table over — it had simply not been hit
    yet, because the failing delete needs the account to own a token."""
    token = DeviceToken(
        id=_new_id("dt-"), tenant_id=tenant.id, user_id=account.id,
        device_token=f"tok-{uuid.uuid4().hex}", platform="ios",
    )
    db_session.add(token)
    db_session.flush()
    token_id = token.id

    db_session.delete(account)
    db_session.flush()

    assert DeviceToken.query.filter_by(id=token_id).first() is None


def test_an_account_holding_both_still_deletes(db_session, tenant, account):
    """Both collections are de-associated in one flush, so a fix to only one
    would still fail here."""
    notification = Notification(
        id=_new_id("nt-"), tenant_id=tenant.id, user_id=None,
        type="ANNOUNCEMENT", channel="in_app", title="Closure",
    )
    db_session.add(notification)
    db_session.flush()
    db_session.add(NotificationRecipient(
        id=_new_id("nr-"), notification_id=notification.id, user_id=account.id,
    ))
    db_session.add(DeviceToken(
        id=_new_id("dt-"), tenant_id=tenant.id, user_id=account.id,
        device_token=f"tok-{uuid.uuid4().hex}", platform="android",
    ))
    db_session.flush()

    db_session.delete(account)
    db_session.flush()          # raised IntegrityError before the fix
