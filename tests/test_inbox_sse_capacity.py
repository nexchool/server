"""Live notifications must not be able to wedge the API.

`GET /api/notifications/inbox/stream` holds a gunicorn thread for the whole
life of the connection, and `DashboardLayout` opens one for **every** signed-in
admin-web user. Production runs 2 workers x 24 threads, so at ~48 connected
staff every thread is parked in a `while True` and the API stops answering
anything at all — every page in every app hangs. That is a ceiling on
*concurrent people*, not on data, so it arrives at the first school with a
staffroom rather than at the fifteen-thousandth student.

The database connection is already released before streaming begins, so this
is thread starvation and not pool starvation.

A cap converts the failure from "nothing works for anybody" into "some people
fall back to manual refresh", which is the trade the endpoint already makes
when Redis is down — it answers 503 and the client keeps working.
"""

from __future__ import annotations

import pytest

from modules.notifications import inbox_sse


@pytest.fixture(autouse=True)
def _fresh_slots():
    """Each test gets its own accounting, and leaves none behind."""
    inbox_sse.reset_stream_slots(limit=3)
    yield
    inbox_sse.reset_stream_slots()


def test_streams_are_served_up_to_the_cap():
    assert inbox_sse.acquire_stream_slot() is True
    assert inbox_sse.acquire_stream_slot() is True
    assert inbox_sse.acquire_stream_slot() is True


def test_the_cap_refuses_rather_than_parking_another_thread():
    for _ in range(3):
        assert inbox_sse.acquire_stream_slot() is True

    assert inbox_sse.acquire_stream_slot() is False, (
        "the 4th stream must be refused, not queued onto a 4th thread"
    )


def test_releasing_frees_the_slot_for_the_next_person():
    for _ in range(3):
        inbox_sse.acquire_stream_slot()
    assert inbox_sse.acquire_stream_slot() is False

    inbox_sse.release_stream_slot()

    assert inbox_sse.acquire_stream_slot() is True


def test_releasing_more_than_acquired_cannot_inflate_capacity():
    """A double release would hand out more threads than the worker has."""
    inbox_sse.acquire_stream_slot()
    inbox_sse.release_stream_slot()
    inbox_sse.release_stream_slot()
    inbox_sse.release_stream_slot()

    granted = sum(1 for _ in range(10) if inbox_sse.acquire_stream_slot())

    assert granted == 3, f"capacity leaked: {granted} slots handed out, cap is 3"


def test_the_default_cap_leaves_threads_for_ordinary_requests(monkeypatch):
    """Sized against the worker's threads, so the two cannot drift apart."""
    monkeypatch.setenv("GUNICORN_THREADS", "24")

    limit = inbox_sse.default_stream_limit()

    assert 0 < limit < 24, (
        f"a cap of {limit} against 24 threads leaves nothing for real requests"
    )


def test_a_single_threaded_worker_still_allows_one_stream(monkeypatch):
    """The floor matters: a dev box on 1-2 threads must not refuse everything."""
    monkeypatch.setenv("GUNICORN_THREADS", "1")

    assert inbox_sse.default_stream_limit() >= 1
