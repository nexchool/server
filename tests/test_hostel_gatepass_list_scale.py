"""The gatepass list is a kanban board, and it was fetched whole.

`list_gatepasses` ended in `.all()` with no bound, and the admin board asked
for it with no filters at all — then split five columns, searched and sorted
them in the browser. Four of those columns are naturally small (a hostel has
only so many children out at once); the fifth is "closed", which accumulates
every gatepass the school has ever issued and is never pruned.

So the board got slower every term, and the search box only ever searched the
rows that had already been downloaded.

This moves the work to the server: each column asks for its own statuses, its
own page and its own sort, and the search runs in SQL across the fields a
warden would actually type.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import pytest
from flask import g

from modules.hostel.services.gatepass_service import (
    GATEPASS_MAX_PAGE_SIZE,
    GATEPASS_PAGE_SIZE,
    GatepassService,
)


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


@pytest.fixture
def service(db_session):
    return GatepassService(db_session)


def _student(db_session, tenant, *, name, admission_suffix, with_login=True):
    """A child, optionally without a login account.

    `students.person_id` is NOT NULL while `students.user_id` is nullable — a
    child is always a person, and only sometimes someone who can sign in. The
    accountless case is the one the search join has to survive.
    """
    from modules.auth.models import User
    from modules.people.models import Person
    from modules.students.models import Student

    person = Person(
        id=f"pe-{uuid.uuid4().hex[:12]}", tenant_id=tenant.id, full_name=name
    )
    db_session.add(person)
    db_session.flush()

    user_id = None
    if with_login:
        user = User(
            id=f"u-{uuid.uuid4().hex[:12]}", tenant_id=tenant.id,
            email=f"{admission_suffix}@test.school", password_hash="x" * 60,
            name=name, person_id=person.id,
        )
        db_session.add(user)
        db_session.flush()
        user_id = user.id

    student = Student(
        id=f"s-{uuid.uuid4().hex[:12]}", tenant_id=tenant.id, user_id=user_id,
        person_id=person.id, admission_number=f"ADM-{admission_suffix}",
    )
    db_session.add(student)
    db_session.flush()
    return student


def _gatepass(db_session, tenant, hostel, student, *, status="pending",
              phone="9800000000", reason=None, requested_at=None):
    from modules.hostel.models import HostelGatepass

    gatepass = HostelGatepass(
        tenant_id=tenant.id, student_id=student.id, hostel_id=hostel.id,
        type="day_out", status=status,
        departure_datetime=datetime(2026, 9, 1, 9, 0),
        expected_return_datetime=datetime(2026, 9, 1, 18, 0),
        parent_phone=phone, reason=reason,
        requested_at=requested_at or datetime(2026, 9, 1, 8, 0),
    )
    db_session.add(gatepass)
    db_session.flush()
    return gatepass


# ---------------------------------------------------------------------------
# The page is bounded; the total is not
# ---------------------------------------------------------------------------

def test_the_list_comes_back_a_page_at_a_time(ctx, db_session, tenant, hostel, service):
    child = _student(db_session, tenant, name="Rita Bose", admission_suffix="p1")
    for _ in range(80):
        _gatepass(db_session, tenant, hostel, child, status="closed")

    result = service.list_gatepasses(tenant_id=tenant.id)

    assert len(result["items"]) <= GATEPASS_PAGE_SIZE
    assert len(result["items"]) < 80


def test_the_total_describes_the_whole_filtered_set(
    ctx, db_session, tenant, hostel, service
):
    """The column header shows this, so it cannot be `len(items)`."""
    child = _student(db_session, tenant, name="Rita Bose", admission_suffix="p2")
    for _ in range(80):
        _gatepass(db_session, tenant, hostel, child, status="closed")

    result = service.list_gatepasses(tenant_id=tenant.id, status="closed")

    assert result["total"] == 80


def test_paging_sees_each_gatepass_exactly_once(
    ctx, db_session, tenant, hostel, service
):
    """Every row shares one requested_at, so ordering must break the tie.

    LIMIT/OFFSET over an order that is not total serves some rows on two pages
    and others on none.
    """
    child = _student(db_session, tenant, name="Rita Bose", admission_suffix="p3")
    made = {
        _gatepass(db_session, tenant, hostel, child, status="closed").id
        for _ in range(70)
    }

    seen: list[str] = []
    page = 1
    while True:
        result = service.list_gatepasses(tenant_id=tenant.id, status="closed", page=page)
        seen.extend(gp.id for gp in result["items"])
        if page >= result["total_pages"]:
            break
        page += 1

    assert len(seen) == len(set(seen)), "a row was served on two pages"
    assert set(seen) == made, "a row was never served at all"


def test_an_enormous_page_size_is_capped(ctx, db_session, tenant, hostel, service):
    child = _student(db_session, tenant, name="Rita Bose", admission_suffix="p4")
    for _ in range(60):
        _gatepass(db_session, tenant, hostel, child, status="closed")

    result = service.list_gatepasses(tenant_id=tenant.id, per_page=100_000)

    assert len(result["items"]) <= GATEPASS_MAX_PAGE_SIZE


@pytest.mark.parametrize("bad", [0, -1, "abc", None])
def test_a_nonsense_page_is_treated_as_the_first(
    ctx, db_session, tenant, hostel, service, bad
):
    """These arrive off a query string, so they must not raise."""
    child = _student(db_session, tenant, name="Rita Bose", admission_suffix="p5")
    _gatepass(db_session, tenant, hostel, child)

    result = service.list_gatepasses(tenant_id=tenant.id, page=bad)

    assert result["page"] == 1
    assert result["total"] == 1


# ---------------------------------------------------------------------------
# What each column asks for
# ---------------------------------------------------------------------------

def test_a_merged_column_can_ask_for_two_statuses(
    ctx, db_session, tenant, hostel, service
):
    """The board's last column shows closed and rejected together."""
    child = _student(db_session, tenant, name="Rita Bose", admission_suffix="s1")
    closed = _gatepass(db_session, tenant, hostel, child, status="closed")
    rejected = _gatepass(db_session, tenant, hostel, child, status="rejected")
    _gatepass(db_session, tenant, hostel, child, status="pending")

    result = service.list_gatepasses(
        tenant_id=tenant.id, status=["closed", "rejected"]
    )

    assert {gp.id for gp in result["items"]} == {closed.id, rejected.id}
    assert result["total"] == 2


def test_a_single_status_is_still_accepted(ctx, db_session, tenant, hostel, service):
    """The existing callers pass a bare string; that must keep working."""
    child = _student(db_session, tenant, name="Rita Bose", admission_suffix="s2")
    pending = _gatepass(db_session, tenant, hostel, child, status="pending")
    _gatepass(db_session, tenant, hostel, child, status="closed")

    result = service.list_gatepasses(tenant_id=tenant.id, status="pending")

    assert {gp.id for gp in result["items"]} == {pending.id}


def test_the_pending_column_can_ask_for_oldest_first(
    ctx, db_session, tenant, hostel, service
):
    """A warden works the queue from the oldest request, not the newest."""
    child = _student(db_session, tenant, name="Rita Bose", admission_suffix="s3")
    older = _gatepass(db_session, tenant, hostel, child,
                      requested_at=datetime(2026, 9, 1, 8, 0))
    newer = _gatepass(db_session, tenant, hostel, child,
                      requested_at=datetime(2026, 9, 2, 8, 0))

    oldest_first = service.list_gatepasses(tenant_id=tenant.id, oldest_first=True)
    newest_first = service.list_gatepasses(tenant_id=tenant.id)

    assert [gp.id for gp in oldest_first["items"]] == [older.id, newer.id]
    assert [gp.id for gp in newest_first["items"]] == [newer.id, older.id]


# ---------------------------------------------------------------------------
# Search, which used to only search what had already been downloaded
# ---------------------------------------------------------------------------

def test_search_matches_a_child_by_name(ctx, db_session, tenant, hostel, service):
    wanted = _student(db_session, tenant, name="Priya Sharma", admission_suffix="q1")
    other = _student(db_session, tenant, name="Arjun Mehta", admission_suffix="q2")
    hers = _gatepass(db_session, tenant, hostel, wanted)
    _gatepass(db_session, tenant, hostel, other)

    result = service.list_gatepasses(tenant_id=tenant.id, search="priya")

    assert {gp.id for gp in result["items"]} == {hers.id}


def test_search_matches_by_admission_number(ctx, db_session, tenant, hostel, service):
    wanted = _student(db_session, tenant, name="Priya Sharma", admission_suffix="zx99")
    other = _student(db_session, tenant, name="Arjun Mehta", admission_suffix="q4")
    hers = _gatepass(db_session, tenant, hostel, wanted)
    _gatepass(db_session, tenant, hostel, other)

    result = service.list_gatepasses(tenant_id=tenant.id, search="ADM-zx99")

    assert {gp.id for gp in result["items"]} == {hers.id}


def test_search_matches_the_parent_phone(ctx, db_session, tenant, hostel, service):
    """A gatekeeper searching by phone is the common case at the gate."""
    child = _student(db_session, tenant, name="Priya Sharma", admission_suffix="q5")
    theirs = _gatepass(db_session, tenant, hostel, child, phone="9812345678")
    _gatepass(db_session, tenant, hostel, child, phone="9900000000")

    result = service.list_gatepasses(tenant_id=tenant.id, search="98123")

    assert {gp.id for gp in result["items"]} == {theirs.id}


def test_a_child_with_no_login_is_still_listed(
    ctx, db_session, tenant, hostel, service
):
    """`students.user_id` is nullable, and plenty of rows have no account.

    Searching joins the student to their user to match on name. An inner join
    would drop every gatepass belonging to a child without a login — they would
    vanish from the board the moment a warden typed anything.
    """
    accountless = _student(db_session, tenant, name="No Login",
                           admission_suffix="nl1", with_login=False)
    theirs = _gatepass(db_session, tenant, hostel, accountless)

    unfiltered = service.list_gatepasses(tenant_id=tenant.id)
    searched = service.list_gatepasses(tenant_id=tenant.id, search="ADM-nl1")

    assert theirs.id in {gp.id for gp in unfiltered["items"]}
    assert {gp.id for gp in searched["items"]} == {theirs.id}


def test_search_is_case_insensitive_and_trimmed(
    ctx, db_session, tenant, hostel, service
):
    child = _student(db_session, tenant, name="Priya Sharma", admission_suffix="q6")
    hers = _gatepass(db_session, tenant, hostel, child)

    result = service.list_gatepasses(tenant_id=tenant.id, search="  PRIYA  ")

    assert {gp.id for gp in result["items"]} == {hers.id}


def test_an_empty_search_is_not_a_filter(ctx, db_session, tenant, hostel, service):
    child = _student(db_session, tenant, name="Priya Sharma", admission_suffix="q7")
    hers = _gatepass(db_session, tenant, hostel, child)

    result = service.list_gatepasses(tenant_id=tenant.id, search="   ")

    assert {gp.id for gp in result["items"]} == {hers.id}


def test_a_search_term_with_a_wildcard_is_matched_literally(
    ctx, db_session, tenant, hostel, service
):
    """`%` in a LIKE pattern would otherwise match every child on the board."""
    child = _student(db_session, tenant, name="Priya Sharma", admission_suffix="q8")
    _gatepass(db_session, tenant, hostel, child)

    result = service.list_gatepasses(tenant_id=tenant.id, search="%")

    assert result["items"] == []
