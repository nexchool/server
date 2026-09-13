"""The tenant's student seat limit counts students the school is teaching.

The limit used to count every student row, so a school that had graduated
or transferred students still had them held against its licence. It now
uses the same definition of "active" as billing and usage
(modules.subscription.usage.INACTIVE_STUDENT_STATUSES), so the number a
school is limited by is the number it is billed for.
"""

from __future__ import annotations


import pytest

from modules.students import services
from tests.conftest import _make_student


@pytest.fixture
def two_seat_plan(db_session, tenant):
    """A tenant licensed for two active students — the limit lives on the tenant."""
    tenant.max_active_students = 2
    db_session.flush()
    return tenant


def _student_with_status(db_session, tenant, *, suffix, status):
    student = _make_student(db_session, tenant, name=f"S {suffix}", admission_suffix=suffix)
    student.student_status = status
    db_session.flush()
    return student


def test_students_who_have_left_do_not_use_up_the_plan(db_session, tenant, two_seat_plan):
    _student_with_status(db_session, tenant, suffix="a1", status="active")
    _student_with_status(db_session, tenant, suffix="g1", status="graduated")
    _student_with_status(db_session, tenant, suffix="t1", status="transferred")

    allowed, message = services._check_student_plan_limit(tenant.id)
    assert allowed is True and message is None


def test_the_limit_still_bites_on_active_students(db_session, tenant, two_seat_plan):
    _student_with_status(db_session, tenant, suffix="a1", status="active")
    # A student flagged to leave at year end is still here and still taught.
    _student_with_status(db_session, tenant, suffix="l1", status="leaving")

    allowed, message = services._check_student_plan_limit(tenant.id)
    assert allowed is False
    assert "2" in message


def test_headroom_is_seats_left_for_active_students(db_session, tenant, two_seat_plan):
    _student_with_status(db_session, tenant, suffix="a1", status="active")
    _student_with_status(db_session, tenant, suffix="d1", status="dropped_out")

    assert services.plan_student_headroom(tenant.id) == 1


def test_headroom_is_unlimited_without_a_plan(db_session, tenant):
    assert services.plan_student_headroom(tenant.id) is None
