"""Listing invoices was unbounded, N+1, and summed money on the client.

`list_invoices` ended in `query.all()` over every invoice in the tenant. A
15,000-student trust billing three terms is roughly 45,000 invoices in one
response — and `FeeInvoice.to_dict()` sums `self.payments`, a lazy
relationship, so serialising them was another query per invoice on top.

The third problem is why the list could not simply be capped. The mobile
screen derives its header from the whole list:

    totalOutstanding = sum(remaining_balance for unpaid invoices)
    nextDueDate      = min(due_date for still-owed invoices)

Cap the list and those become "the outstanding of the first 25 invoices" —
a wrong amount of money shown to whoever is looking, with nothing on screen
saying so. So the summary has to be computed over the whole filtered set on
the server before the list can be bounded.

The screen also filtered `overdue` and `pending` in the browser, because
neither is a stored status: overdue is derived from `due_date`, and pending is
three statuses at once. Those move to SQL for the same reason.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from flask import g
from sqlalchemy import event

from core.database import db
from modules.fees.services import invoice_service


def _new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@pytest.fixture
def ctx(flask_app, tenant, db_session):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        yield


def _student(db_session, tenant):
    from modules.auth.models import User
    from modules.people.models import Person
    from modules.students.models import Student

    suffix = uuid.uuid4().hex[:10]
    person = Person(id=f"pe-{suffix}", tenant_id=tenant.id, full_name="Payer")
    db_session.add(person)
    db_session.flush()
    user = User(id=f"u-{suffix}", tenant_id=tenant.id,
                email=f"{suffix}@test.school", password_hash="x" * 60,
                name="Payer", person_id=person.id)
    db_session.add(user)
    db_session.flush()
    student = Student(id=f"s-{suffix}", tenant_id=tenant.id, user_id=user.id,
                      person_id=person.id, admission_number=f"A-{suffix[:8]}")
    db_session.add(student)
    db_session.flush()
    return student


def _invoice(db_session, tenant, student, *, status="unpaid", total="1000.00",
             paid=None, due=None):
    from modules.fees.models import FeeInvoice, FeePayment

    suffix = uuid.uuid4().hex[:10]
    invoice = FeeInvoice(
        id=f"inv-{suffix}", tenant_id=tenant.id, student_id=student.id,
        invoice_number=f"INV-{suffix[:8]}", academic_year="2026-27",
        issue_date=date(2026, 6, 1), due_date=due or date(2026, 7, 1),
        subtotal=total, total_amount=total, status=status,
    )
    db_session.add(invoice)
    db_session.flush()
    if paid:
        db_session.add(FeePayment(
            id=f"pay-{suffix}", tenant_id=tenant.id, invoice_id=invoice.id,
            student_id=student.id, amount=paid, payment_method="cash",
            payment_date=date(2026, 6, 15),
        ))
        db_session.flush()
    return invoice


# ---------------------------------------------------------------------------
# Bounded
# ---------------------------------------------------------------------------

def test_the_list_comes_back_a_page_at_a_time(ctx, db_session, tenant):
    student = _student(db_session, tenant)
    for _ in range(60):
        _invoice(db_session, tenant, student)

    result = invoice_service.list_invoices()

    assert len(result["items"]) <= invoice_service.INVOICE_PAGE_SIZE
    assert len(result["items"]) < 60


def test_the_total_counts_the_whole_filtered_set(ctx, db_session, tenant):
    student = _student(db_session, tenant)
    for _ in range(60):
        _invoice(db_session, tenant, student)

    result = invoice_service.list_invoices()

    assert result["total"] == 60


def test_paging_sees_each_invoice_exactly_once(ctx, db_session, tenant):
    """Every row is created in the same instant, so the order must break ties."""
    student = _student(db_session, tenant)
    made = {_invoice(db_session, tenant, student).id for _ in range(55)}

    seen: list[str] = []
    page = 1
    while True:
        result = invoice_service.list_invoices(page=page)
        seen.extend(row["id"] for row in result["items"])
        if page >= result["total_pages"]:
            break
        page += 1

    assert len(seen) == len(set(seen)), "an invoice was served on two pages"
    assert set(seen) == made, "an invoice was never served at all"


def test_an_enormous_page_size_is_capped(ctx, db_session, tenant):
    student = _student(db_session, tenant)
    for _ in range(60):
        _invoice(db_session, tenant, student)

    result = invoice_service.list_invoices(per_page=100_000)

    assert len(result["items"]) <= invoice_service.INVOICE_MAX_PAGE_SIZE


@pytest.mark.parametrize("bad", [0, -1, "abc", None])
def test_a_nonsense_page_is_treated_as_the_first(ctx, db_session, tenant, bad):
    student = _student(db_session, tenant)
    _invoice(db_session, tenant, student)

    result = invoice_service.list_invoices(page=bad)

    assert result["page"] == 1
    assert result["total"] == 1


# ---------------------------------------------------------------------------
# Not N+1
# ---------------------------------------------------------------------------

def _queries_to_list(**kwargs):
    seen: list[str] = []

    def record(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    event.listen(db.engine, "before_cursor_execute", record)
    try:
        result = invoice_service.list_invoices(**kwargs)
    finally:
        event.remove(db.engine, "before_cursor_execute", record)
    return len(seen), result


def test_serialising_a_page_does_not_cost_a_query_per_invoice(
    ctx, db_session, tenant
):
    """`to_dict` sums `self.payments`, which is lazy.

    Cost must be flat in the number of rows on the page, not proportional to
    it — per-row loading would add one query per invoice.
    """
    student = _student(db_session, tenant)
    for _ in range(3):
        _invoice(db_session, tenant, student, paid="100.00")
    small, _ = _queries_to_list(per_page=25)

    for _ in range(15):
        _invoice(db_session, tenant, student, paid="100.00")
    large, _ = _queries_to_list(per_page=25)

    assert large - small <= 2, (
        f"{small} queries for 3 invoices, {large} for 18 — cost grows per row"
    )


# ---------------------------------------------------------------------------
# The summary, which describes the whole set and not the page
# ---------------------------------------------------------------------------

def test_the_outstanding_total_covers_every_invoice_not_just_the_page(
    ctx, db_session, tenant
):
    """This is money on a screen. `len(items)` worth of it is the wrong number."""
    student = _student(db_session, tenant)
    for _ in range(40):
        _invoice(db_session, tenant, student, total="1000.00", status="unpaid")

    result = invoice_service.list_invoices()

    assert len(result["items"]) < 40, "precondition: the list really is paged"
    assert result["summary"]["total_outstanding"] == pytest.approx(40_000.0)


def test_the_outstanding_total_subtracts_part_payments(ctx, db_session, tenant):
    student = _student(db_session, tenant)
    _invoice(db_session, tenant, student, total="1000.00", paid="300.00",
             status="partial")
    _invoice(db_session, tenant, student, total="500.00", status="unpaid")

    result = invoice_service.list_invoices()

    assert result["summary"]["total_outstanding"] == pytest.approx(1200.0)


def test_a_paid_invoice_owes_nothing(ctx, db_session, tenant):
    student = _student(db_session, tenant)
    _invoice(db_session, tenant, student, total="1000.00", paid="1000.00",
             status="paid")

    result = invoice_service.list_invoices()

    assert result["summary"]["total_outstanding"] == pytest.approx(0.0)


def test_a_cancelled_invoice_is_not_owed(ctx, db_session, tenant):
    student = _student(db_session, tenant)
    _invoice(db_session, tenant, student, total="1000.00", status="cancelled")

    result = invoice_service.list_invoices()

    assert result["summary"]["total_outstanding"] == pytest.approx(0.0)


def test_the_next_due_date_is_the_earliest_still_owed(ctx, db_session, tenant):
    student = _student(db_session, tenant)
    _invoice(db_session, tenant, student, due=date(2026, 12, 1), status="unpaid")
    _invoice(db_session, tenant, student, due=date(2026, 8, 1), status="unpaid")
    # Settled, so it must not win the minimum.
    _invoice(db_session, tenant, student, due=date(2026, 1, 1), status="paid",
             paid="1000.00")

    result = invoice_service.list_invoices()

    assert result["summary"]["next_due_date"] == "2026-08-01"


def test_nothing_owed_means_no_next_due_date(ctx, db_session, tenant):
    student = _student(db_session, tenant)
    _invoice(db_session, tenant, student, status="paid", paid="1000.00")

    result = invoice_service.list_invoices()

    assert result["summary"]["next_due_date"] is None


# ---------------------------------------------------------------------------
# The filters the screen actually offers
# ---------------------------------------------------------------------------

def test_pending_is_the_three_unsettled_statuses(ctx, db_session, tenant):
    student = _student(db_session, tenant)
    wanted = {
        _invoice(db_session, tenant, student, status="unpaid").id,
        _invoice(db_session, tenant, student, status="partial", paid="1.00").id,
        _invoice(db_session, tenant, student, status="draft").id,
    }
    _invoice(db_session, tenant, student, status="paid", paid="1000.00")
    _invoice(db_session, tenant, student, status="cancelled")

    result = invoice_service.list_invoices(status="pending")

    assert {row["id"] for row in result["items"]} == wanted


def test_overdue_is_derived_from_the_due_date(ctx, db_session, tenant):
    """`overdue` is not a stored status — the browser worked it out per row."""
    student = _student(db_session, tenant)
    yesterday = date.today() - timedelta(days=1)
    tomorrow = date.today() + timedelta(days=1)
    late = _invoice(db_session, tenant, student, status="unpaid", due=yesterday)
    _invoice(db_session, tenant, student, status="unpaid", due=tomorrow)
    # Already settled, so being past its date does not make it overdue.
    _invoice(db_session, tenant, student, status="paid", paid="1000.00",
             due=yesterday)

    result = invoice_service.list_invoices(status="overdue")

    assert {row["id"] for row in result["items"]} == {late.id}


def test_a_stored_status_still_filters_directly(ctx, db_session, tenant):
    student = _student(db_session, tenant)
    paid = _invoice(db_session, tenant, student, status="paid", paid="1000.00")
    _invoice(db_session, tenant, student, status="unpaid")

    result = invoice_service.list_invoices(status="paid")

    assert {row["id"] for row in result["items"]} == {paid.id}


def test_the_summary_describes_the_filtered_set(ctx, db_session, tenant):
    """Filter to paid and nothing is outstanding — the header must agree."""
    student = _student(db_session, tenant)
    _invoice(db_session, tenant, student, total="1000.00", status="unpaid")
    _invoice(db_session, tenant, student, total="500.00", status="paid",
             paid="500.00")

    result = invoice_service.list_invoices(status="paid")

    assert result["summary"]["total_outstanding"] == pytest.approx(0.0)
