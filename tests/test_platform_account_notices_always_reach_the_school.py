"""A school cannot switch off the notice that says it owes money.

`notifications` is an optional feature a school can turn off, and the
dispatcher honours that for every message — which is right for school
modules and wrong for the platform's own account notices. A school with
notifications disabled would never learn its subscription payment was due,
and would simply be suspended one morning.

The same goes for templates: the email strategy refuses to send a type it
has no template row for. A payment reminder carries its whole message in the
body already, so it is delivered as written rather than dropped.
"""

from __future__ import annotations

import pytest

from modules.notifications.enums import NotificationChannel, NotificationType


class _SpyStrategy:
    def __init__(self):
        self.sent = []

    def send(self, **kwargs):
        self.sent.append(kwargs)
        return True


@pytest.fixture
def dispatcher_with_notifications_off(monkeypatch):
    """A dispatcher for a school that has turned notifications off."""
    from modules.notifications.services import dispatcher as dispatcher_module

    monkeypatch.setattr(
        dispatcher_module, "is_feature_enabled", lambda *a, **k: False, raising=False
    )
    monkeypatch.setattr(
        "core.feature_flags.is_feature_enabled", lambda *a, **k: False
    )
    instance = dispatcher_module.NotificationDispatcher()
    spy = _SpyStrategy()
    instance._strategies = {NotificationChannel.EMAIL.value: spy}
    return instance, spy


def test_a_payment_reminder_still_goes_out(dispatcher_with_notifications_off):
    instance, spy = dispatcher_with_notifications_off

    result = instance.dispatch(
        user_id="u-1",
        tenant_id="t-1",
        notification_type=NotificationType.SUBSCRIPTION_PAYMENT_DUE.value,
        channels=[NotificationChannel.EMAIL.value],
        title="Subscription payment due",
        body="Your payment is due on 2026-09-20.",
    )

    assert result[NotificationChannel.EMAIL.value] is True
    assert len(spy.sent) == 1


def test_a_school_announcement_still_respects_the_switch(dispatcher_with_notifications_off):
    instance, spy = dispatcher_with_notifications_off

    result = instance.dispatch(
        user_id="u-1",
        tenant_id="t-1",
        notification_type=NotificationType.ANNOUNCEMENT.value,
        channels=[NotificationChannel.EMAIL.value],
        title="Sports day",
    )

    assert result[NotificationChannel.EMAIL.value] is False
    assert spy.sent == []


def test_a_payment_reminder_is_sent_even_with_no_email_template(monkeypatch):
    """The reminder's body is the whole message; a missing template must not eat it."""
    import celery_app as celery_module
    from modules.notifications.services.strategies import email_strategy as module

    monkeypatch.setattr(
        module,
        "get_and_render_notification_template",
        lambda **kwargs: (_ for _ in ()).throw(module.TemplateNotFoundError("none")),
    )

    queued = {}

    class _Celery:
        def send_task(self, name, args=None, kwargs=None):
            queued.update(name=name, to=args[0], subject=args[1], body=args[2])

    monkeypatch.setattr(celery_module, "get_celery", lambda: _Celery())

    sent = module.EmailStrategy().send(
        user_id="u-1",
        tenant_id="t-1",
        notification_type=NotificationType.SUBSCRIPTION_PAYMENT_DUE.value,
        title="Subscription payment due",
        body="Your payment is due on 2026-09-20.",
        extra_data={"_prefetch_user_email": "head@school.test"},
    )

    assert sent is True
    assert queued["subject"] == "Subscription payment due"
    assert "2026-09-20" in queued["body"]


def test_a_type_with_no_template_and_no_exemption_is_still_refused(monkeypatch):
    """The fallback is for named account notices, not a blanket loosening."""
    from modules.notifications.services.strategies import email_strategy as module

    monkeypatch.setattr(
        module,
        "get_and_render_notification_template",
        lambda **kwargs: (_ for _ in ()).throw(module.TemplateNotFoundError("none")),
    )

    sent = module.EmailStrategy().send(
        user_id="u-1",
        tenant_id="t-1",
        notification_type=NotificationType.FEE_OVERDUE.value,
        title="Fee overdue",
        body="Pay up.",
        extra_data={"_prefetch_user_email": "head@school.test"},
    )

    assert sent is False
