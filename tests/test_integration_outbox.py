"""What a test double sent, readable only where test doubles may run."""

from __future__ import annotations

import importlib.util
import sys
import uuid

import pytest

from modules.auth.services import generate_access_token
from modules.integrations import outbox
from tests.auth._characterization import grant_permissions, make_tenant, make_user

#: A real, independently-running Redis reachable from the host test process
#: (a Homebrew instance on the default port — separate from the docker
#: compose service `.env` points at, which resolves only inside the
#: container network). Good enough to prove the property that matters here:
#: the outbox's source of truth is external to any one process.
_HOST_REDIS_URL = "redis://localhost:6379/0"


@pytest.fixture
def _reachable_redis(flask_app, monkeypatch):
    """Point at `_HOST_REDIS_URL` and skip, rather than fail for the wrong
    reason, when this host has none reachable there.

    Only the two tests below that assert a fact specific to a *real* shared
    Redis — cross-process visibility, `LTRIM` bounding — need this. Without
    it, `test_a_message_recorded_by_one_worker_is_read_by_another` fails
    loudly with a connection error when Redis is down (there is no
    process-local fallback that could make two separate module namespaces
    agree, so a fail-loud is the honest outcome), and
    `test_the_buffer_stays_bounded_when_backed_by_redis` passes *anyway* for
    the wrong reason: the in-memory fallback this module degrades to is
    bounded too (`deque(maxlen=CAPACITY)`), so that test proved nothing
    about `LTRIM` at all when Redis was unreachable. Skipping both makes
    that silent, vacuous pass visible as "did not run" instead. The same
    posture `tests/auth/test_mobile_otp.py`'s fixture of the same name takes
    for the OTP throttle.
    """
    from core import cache as cache_module

    monkeypatch.setitem(flask_app.config, "REDIS_URL", _HOST_REDIS_URL)
    monkeypatch.setattr(cache_module, "_pool", None)
    with flask_app.app_context():
        client = cache_module.redis_client()
        try:
            assert client is not None and client.ping()
        except Exception:  # noqa: BLE001
            pytest.skip("this test needs a reachable Redis at localhost:6379")


def _load_independent_outbox_module(alias: str):
    """A second, wholly separate module object for `modules.integrations.outbox`.

    `importlib.reload` re-executes a module in place and hands back the same
    object — useless for proving cross-process visibility, since "the same
    object" is exactly what two gunicorn workers never share. Loading the
    same file under a second name in `sys.modules` gives it its own globals
    (its own `_messages` deque, its own `threading.Lock`), which is the part
    of "a separate worker process" that actually matters for this test: two
    independent pieces of process-local state that must agree only because
    something outside both of them (Redis) holds the real data.
    """
    spec = importlib.util.spec_from_file_location(alias, outbox.__file__)
    module = importlib.util.module_from_spec(spec)
    sys.modules[alias] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def client(flask_app):
    return flask_app.test_client()


def _platform_admin(db_session, tenant):
    operator = make_user(
        db_session,
        tenant,
        password="Platform12345",
        email=f"ops-{uuid.uuid4().hex[:8]}@nexchool.test",
        is_platform_admin=True,
    )
    return {"Authorization": f"Bearer {generate_access_token(operator)}"}


def _school_user(db_session, tenant, *, permissions=("subscription.read",)):
    user = make_user(db_session, tenant, password="Member12345")
    grant_permissions(db_session, tenant, user, permissions)
    return {
        "Authorization": f"Bearer {generate_access_token(user)}",
        "X-Tenant-ID": tenant.id,
    }


@pytest.fixture
def enabled_fake_sms(db_session, tenant):
    """A school configured onto the SMS test double, with a template."""
    from core.database import db
    from modules.integrations.services import configure_integration, set_integration_status

    configure_integration(
        tenant.id,
        capability="sms",
        provider_key="fake_sms",
        # Named — Task 8b — so the two-value OTP send below (code, minutes)
        # matches the template's declared slots instead of being refused.
        configuration={
            "templates": {
                "authentication_otp": {"id": "test-template-1", "variables": ["OTP", "MINUTES"]},
            }
        },
    )
    set_integration_status(tenant.id, capability="sms", status="enabled")
    db.session.commit()


def test_the_buffer_is_bounded(flask_app):
    """An unbounded in-memory collection is a memory leak with a schedule."""
    outbox.clear()
    for index in range(outbox.CAPACITY + 10):
        outbox.record(
            tenant_id="t", channel="sms", destination="+91987654321",
            body=f"message {index}", purpose="authentication_otp",
        )
    assert len(outbox.recent(limit=1000)) == outbox.CAPACITY


def test_asking_for_zero_returns_zero(flask_app):
    """`recent(limit=0)` used to floor up to one message on the in-memory
    fallback path (`max(1, limit)`) — a caller asking for none got one
    anyway. Zero means zero."""
    outbox.clear()
    outbox.record(
        tenant_id="t", channel="sms", destination="+9198", body="one",
        purpose="authentication_otp",
    )
    assert outbox.recent(limit=0) == []


def test_the_newest_message_is_first(flask_app):
    outbox.clear()
    outbox.record(tenant_id="t", channel="sms", destination="+9198", body="first", purpose="authentication_otp")
    outbox.record(tenant_id="t", channel="sms", destination="+9198", body="second", purpose="authentication_otp")
    assert outbox.recent()[0]["body"] == "second"


def test_a_fake_send_reaches_the_outbox(flask_app, tenant, enabled_fake_sms):
    from modules.integrations.sms import send_sms

    outbox.clear()
    send_sms(
        tenant_id=tenant.id, destination="+919876543210",
        body="418302 is your NexSchool sign-in code.",
        purpose="authentication_otp", variables=["418302", "5"],
    )
    assert "418302" in outbox.recent()[0]["body"]


def test_the_endpoint_is_absent_where_test_doubles_may_not_run(
    flask_app, db_session, client
):
    """One predicate decides whether fakes run and whether their outbox can
    be read. Two that could disagree is how a fake reaches production."""
    tenant = make_tenant(db_session)
    headers = _platform_admin(db_session, tenant)
    flask_app.config["TESTING"] = False
    flask_app.config["DEBUG"] = False
    try:
        response = client.get("/api/platform/integrations/outbox", headers=headers)
        assert response.status_code == 404
    finally:
        flask_app.config["TESTING"] = True


def test_the_endpoint_needs_a_platform_admin(flask_app, db_session, client):
    tenant = make_tenant(db_session)
    headers = _school_user(db_session, tenant)
    response = client.get("/api/platform/integrations/outbox", headers=headers)
    assert response.status_code in (401, 403)


def test_a_message_recorded_by_one_worker_is_read_by_another(
    flask_app, monkeypatch, _reachable_redis
):
    """The bug this module exists to fix: gunicorn runs multiple worker
    processes, a send lands in whichever one handled the request, and a read
    is served by whichever one the load balancer picks next. Measured against
    the real deployment: 2 of 12 outbox reads after one OTP send returned the
    message, 10 returned nothing.

    A bare `deque` behind a `threading.Lock` cannot pass this test no matter
    how the test is written, because two worker processes never share one
    Python object. Two independent module namespaces stand in for two
    workers; both must resolve to the same store for this to pass.
    """
    monkeypatch.setitem(sys.modules, "outbox_worker_a", None)
    monkeypatch.setitem(sys.modules, "outbox_worker_b", None)

    with flask_app.app_context():
        worker_a = _load_independent_outbox_module("outbox_worker_a")
        worker_b = _load_independent_outbox_module("outbox_worker_b")
        assert worker_a is not worker_b
        assert worker_a._messages is not worker_b._messages

        worker_a.clear()
        worker_a.record(
            tenant_id="t", channel="sms", destination="+919876543210",
            body="817263 is your NexSchool sign-in code.", purpose="authentication_otp",
        )

        messages = worker_b.recent()

    assert messages, "a message recorded by one worker must be readable by another"
    assert messages[0]["body"] == "817263 is your NexSchool sign-in code."


def test_the_buffer_stays_bounded_when_backed_by_redis(flask_app, _reachable_redis):
    """`CAPACITY` is a promise about the store, not about whichever process
    happens to be reading it — the same bound must hold when Redis is the
    backing store, via `LTRIM`, not just against the in-memory fallback."""
    with flask_app.app_context():
        outbox.clear()
        for index in range(outbox.CAPACITY + 10):
            outbox.record(
                tenant_id="t", channel="sms", destination="+91987654321",
                body=f"message {index}", purpose="authentication_otp",
            )
        assert len(outbox.recent(limit=1000)) == outbox.CAPACITY
        outbox.clear()


def test_falls_back_to_memory_when_redis_is_unavailable(monkeypatch):
    """No Redis configured (or Redis down) must be silent and safe: the
    developer flow that reads OTPs out of the outbox cannot depend on a
    service the rest of the test suite and a bare local run do not have."""
    from core import cache as cache_module

    monkeypatch.setattr(cache_module, "redis_client", lambda: None)

    outbox.clear()
    outbox.record(
        tenant_id="t", channel="sms", destination="+9198", body="fallback works",
        purpose="authentication_otp",
    )
    assert outbox.recent()[0]["body"] == "fallback works"
    outbox.clear()
    assert outbox.recent() == []


def test_falls_back_to_memory_when_redis_raises(monkeypatch):
    """A Redis that is configured but unreachable (refused connection, DNS
    failure, timeout) must degrade the same way as no Redis at all — never
    surface as an error to a developer just trying to read an OTP."""

    class _ExplodingRedis:
        def pipeline(self):
            raise ConnectionError("simulated redis outage")

        def lrange(self, *a, **k):
            raise ConnectionError("simulated redis outage")

        def delete(self, *a, **k):
            raise ConnectionError("simulated redis outage")

    from core import cache as cache_module

    monkeypatch.setattr(cache_module, "redis_client", lambda: _ExplodingRedis())

    outbox.clear()
    outbox.record(
        tenant_id="t", channel="sms", destination="+9198", body="still works",
        purpose="authentication_otp",
    )
    assert outbox.recent()[0]["body"] == "still works"
    outbox.clear()
