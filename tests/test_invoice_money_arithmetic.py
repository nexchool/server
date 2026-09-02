"""What an invoice says is owed is computed in binary floating point.

`FeeInvoice.to_dict` derives two of its numbers rather than reading them:

    total_paid = sum(float(p.amount) for p in self.payments)
    remaining  = float(self.total_amount) - total_paid

Every amount is stored as NUMERIC(12,2) precisely so this arithmetic is exact,
and converting to float first throws that away. A fee of ₹45,000.90 settled by
three termly instalments of ₹15,000.30 comes back as ₹0.0000000000073 still
owing.

Scope, honestly: the invoice's *status* is computed elsewhere
(`_recalculate_invoice_status`) and already sums in SQL and compares as
Decimal, so invoices are marked paid correctly today, and both clients format
`remaining_balance` for display, which rounds the error away. So this is not a
parent being chased for a debt they have settled.

It is wrong in the payload all the same, and the next consumer that compares
these numbers rather than formatting them — a reconciliation, an export, a
"show me everything still owing" filter — inherits the error. It also disagrees
with the list summary, which was moved to SQL and so computes the same total
exactly.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from flask import g


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
                email=f"{suffix}@t.test", password_hash="x" * 60,
                name="Payer", person_id=person.id)
    db_session.add(user)
    db_session.flush()
    student = Student(id=f"s-{suffix}", tenant_id=tenant.id, user_id=user.id,
                      person_id=person.id, admission_number=f"A-{suffix[:8]}")
    db_session.add(student)
    db_session.flush()
    return student


def _invoice(db_session, tenant, total, payments):
    """An invoice for `total`, part-settled by `payments`. All strings."""
    from modules.fees.models import FeeInvoice, FeePayment

    suffix = uuid.uuid4().hex[:10]
    invoice = FeeInvoice(
        id=f"fi-{suffix}", tenant_id=tenant.id,
        student_id=_student(db_session, tenant).id,
        invoice_number=f"INV-{suffix[:8]}", academic_year="2026-27",
        issue_date=date(2026, 6, 1), due_date=date(2026, 7, 1),
        subtotal=Decimal(total), total_amount=Decimal(total), status="unpaid",
    )
    db_session.add(invoice)
    db_session.flush()
    for i, amount in enumerate(payments):
        db_session.add(FeePayment(
            id=f"fp-{suffix}-{i}", tenant_id=tenant.id, invoice_id=invoice.id,
            student_id=invoice.student_id, amount=Decimal(amount),
            payment_method="cash", payment_date=date(2026, 6, 10),
        ))
    db_session.flush()
    return invoice


# ---------------------------------------------------------------------------
# The case a school actually has: three termly instalments
# ---------------------------------------------------------------------------

def test_three_instalments_settle_the_invoice_exactly(ctx, db_session, tenant):
    """₹45,000.90 paid as 3 x ₹15,000.30 owes nothing. Not almost nothing."""
    invoice = _invoice(db_session, tenant, "45000.90",
                       ["15000.30", "15000.30", "15000.30"])

    d = invoice.to_dict()

    assert d["remaining_balance"] == 0, (
        f"reported {d['remaining_balance']!r} still owing on a settled invoice"
    )
    assert d["amount_paid"] == 45000.90


def test_a_two_payment_settlement_is_exact(ctx, db_session, tenant):
    invoice = _invoice(db_session, tenant, "0.80", ["0.10", "0.70"])

    d = invoice.to_dict()

    assert d["remaining_balance"] == 0
    assert d["amount_paid"] == 0.80


# ---------------------------------------------------------------------------
# And the ordinary cases keep working
# ---------------------------------------------------------------------------

def test_a_part_paid_invoice_reports_the_exact_remainder(ctx, db_session, tenant):
    invoice = _invoice(db_session, tenant, "12500.50", ["4166.83"])

    d = invoice.to_dict()

    assert d["amount_paid"] == 4166.83
    assert d["remaining_balance"] == 8333.67


def test_an_unpaid_invoice_owes_the_whole_amount(ctx, db_session, tenant):
    invoice = _invoice(db_session, tenant, "12500.50", [])

    d = invoice.to_dict()

    assert d["amount_paid"] == 0
    assert d["remaining_balance"] == 12500.50


def test_an_overpayment_does_not_report_a_negative_balance(ctx, db_session, tenant):
    """Existing behaviour: the school owes the parent, not the other way round."""
    invoice = _invoice(db_session, tenant, "1000.00", ["1200.00"])

    d = invoice.to_dict()

    assert d["remaining_balance"] == 0
    assert d["amount_paid"] == 1200.00


def test_the_payload_stays_json_serialisable(ctx, db_session, tenant):
    """These go straight into a response; Decimal is not JSON."""
    import json

    invoice = _invoice(db_session, tenant, "45000.90", ["15000.30"])

    json.dumps(invoice.to_dict())  # must not raise


# ---------------------------------------------------------------------------
# The same rule on the finance summary
# ---------------------------------------------------------------------------

def test_the_finance_summary_subtracts_exactly(ctx, db_session, tenant):
    """`total_outstanding` was `float(expected) - float(collected)`.

    Both come out of SQL as Decimal, and subtracting them as floats reports
    0.1999999999999318 where the school is owed 0.20. Same rule as the
    invoice: exact in Decimal, float once at the JSON boundary.
    """
    from modules.finance.models import FeeStructure, Payment, PaymentStatus, StudentFee
    from modules.finance.services import student_fee_service as svc

    suffix = uuid.uuid4().hex[:10]
    year_id = _academic_year(db_session, tenant)
    structure = FeeStructure(
        id=f"fs-{suffix}", tenant_id=tenant.id, academic_year_id=year_id,
        name="Term 1", due_date=date(2026, 7, 1),
    )
    db_session.add(structure)
    db_session.flush()

    fee = StudentFee(
        id=f"sf-{suffix}", tenant_id=tenant.id,
        student_id=_student(db_session, tenant).id,
        fee_structure_id=structure.id, total_amount=Decimal("1000.30"),
        paid_amount=Decimal("1000.10"), due_date=date(2026, 7, 1),
    )
    db_session.add(fee)
    db_session.flush()
    db_session.add(Payment(
        id=f"pm-{suffix}", tenant_id=tenant.id, student_fee_id=fee.id,
        amount=Decimal("1000.10"), method="cash",
        status=PaymentStatus.success.value,
    ))
    db_session.flush()

    result = svc.get_finance_summary()

    assert result["total_outstanding"] == 0.20, (
        f"reported {result['total_outstanding']!r} owed instead of 0.20"
    )


def _academic_year(db_session, tenant):
    from modules.academics.academic_year.models import AcademicYear

    ay = AcademicYear(
        id=f"ay-{uuid.uuid4().hex[:10]}", tenant_id=tenant.id,
        name=f"AY-{uuid.uuid4().hex[:6]}",
        start_date=date(2026, 6, 1), end_date=date(2027, 3, 31),
    )
    db_session.add(ay)
    db_session.flush()
    return ay.id
