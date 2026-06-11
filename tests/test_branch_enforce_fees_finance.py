"""Branch enforcement on the Fees and Finance domains.

Phase 2 (P2-T4c) — wiring the ``core/branch_scope`` primitives into the Fees
(invoices / payments / receipts / reminders) and Finance (student-fees /
payments / fee-structure config / summaries) domains.

Both domains reach a branch through the student:
``student_id`` -> ``Student.class_id`` -> ``Class.school_unit_id``. A restricted
sub-admin (unit A) may only touch fee records of students in unit A; an
out-of-branch id -> 403 (``BranchForbidden``). Classless students fail closed.
Tenant-wide config / aggregates (fee structures with no class link, rollover,
tenant profile, recent-payments / summary) are denied for restricted users.
Unrestricted admins are a strict no-op.

Pattern mirrors ``tests/test_branch_enforce_attendance_timetable.py``: push
``g.tenant_id`` / ``g.current_user`` via ``flask_app.test_request_context`` and
call the service layer directly. Runs against the localhost Postgres bound to
the savepoint connection in conftest (rolled back per test).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from flask import g

from core.branch_scope import BranchForbidden
from modules.auth.models import User
from modules.classes.models import Class
from modules.fees import models as fees_models
from modules.fees.services import (
    fee_payment_service,
    invoice_service,
    receipt_service,
    reminder_service,
)
from modules.finance import models as finance_models
from modules.finance.enums import PaymentStatus, StudentFeeStatus
from modules.finance.services import (
    payment_service,
    structure_service,
    student_fee_service,
)
from modules.finance.services import rollover as rollover_service
from modules.students.models import Student
from modules.sub_admins.models import UserSchoolUnit


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def units(db_session, tenant):
    from modules.school_units.models import SchoolUnit

    unit_a = SchoolUnit(
        id=_new_id("su-"), tenant_id=tenant.id, name="Campus A",
        code=f"A-{uuid.uuid4().hex[:6]}",
    )
    unit_b = SchoolUnit(
        id=_new_id("su-"), tenant_id=tenant.id, name="Campus B",
        code=f"B-{uuid.uuid4().hex[:6]}",
    )
    db_session.add_all([unit_a, unit_b])
    db_session.flush()
    return unit_a, unit_b


@pytest.fixture
def academic_year(db_session, tenant):
    from modules.academics.academic_year.models import AcademicYear

    ay = AcademicYear(
        id=_new_id("ay-"),
        tenant_id=tenant.id,
        name="2025-2026",
        start_date="2025-06-01",
        end_date="2026-03-31",
    )
    db_session.add(ay)
    db_session.flush()
    return ay


@pytest.fixture
def classes(db_session, tenant, units, academic_year):
    """class_a in unit A, class_b in unit B."""
    unit_a, unit_b = units
    class_a = Class(
        id=_new_id("c-"), tenant_id=tenant.id, name="Grade 1", section="A",
        academic_year_id=academic_year.id, school_unit_id=unit_a.id,
    )
    class_b = Class(
        id=_new_id("c-"), tenant_id=tenant.id, name="Grade 1", section="B",
        academic_year_id=academic_year.id, school_unit_id=unit_b.id,
    )
    db_session.add_all([class_a, class_b])
    db_session.flush()
    return class_a, class_b


def _make_student(db_session, tenant, class_id, academic_year_id=None):
    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=_new_id("u-"), tenant_id=tenant.id, email=f"{suffix}@test.school",
        password_hash="x" * 60, name="Test Student",
    )
    db_session.add(user)
    db_session.flush()
    student = Student(
        id=_new_id("s-"), tenant_id=tenant.id, user_id=user.id,
        admission_number=f"ADM-{suffix}", class_id=class_id,
        academic_year_id=academic_year_id,
    )
    db_session.add(student)
    db_session.flush()
    return student


@pytest.fixture
def students(db_session, tenant, classes, academic_year):
    """student_a (unit A), student_b (unit B), student_classless (no class)."""
    class_a, class_b = classes
    student_a = _make_student(db_session, tenant, class_a.id, academic_year.id)
    student_b = _make_student(db_session, tenant, class_b.id, academic_year.id)
    student_classless = _make_student(db_session, tenant, None, academic_year.id)
    return student_a, student_b, student_classless


@pytest.fixture
def actor(db_session, tenant):
    """A user to attribute created_by / collected_by columns to."""
    u = User(
        id=_new_id("act-"), tenant_id=tenant.id,
        email=f"act-{uuid.uuid4().hex[:6]}@test.school",
        password_hash="x" * 60, name="Actor",
    )
    db_session.add(u)
    db_session.flush()
    return u


@pytest.fixture
def unrestricted_user(db_session, tenant):
    """Tenant user with NO UserSchoolUnit rows -> unrestricted."""
    u = User(
        id=_new_id("uu-"), tenant_id=tenant.id,
        email=f"uu-{uuid.uuid4().hex[:6]}@test.school",
        password_hash="x" * 60, name="Unrestricted Admin",
    )
    db_session.add(u)
    db_session.flush()
    return u


@pytest.fixture
def restricted_user(db_session, tenant, units):
    """Tenant user restricted to unit A only."""
    unit_a, _unit_b = units
    u = User(
        id=_new_id("ru-"), tenant_id=tenant.id,
        email=f"ru-{uuid.uuid4().hex[:6]}@test.school",
        password_hash="x" * 60, name="Restricted Sub-Admin",
    )
    db_session.add(u)
    db_session.flush()
    db_session.add(
        UserSchoolUnit(
            id=_new_id("usu-"), tenant_id=tenant.id,
            user_id=u.id, school_unit_id=unit_a.id,
        )
    )
    db_session.flush()
    return u


# ---------- Fees domain fixtures ----------

def _make_invoice(db_session, tenant, student_id):
    inv = fees_models.FeeInvoice(
        id=_new_id("inv-"), tenant_id=tenant.id, student_id=student_id,
        invoice_number=f"INV-{uuid.uuid4().hex[:6]}", academic_year="2025-2026",
        issue_date=date(2025, 6, 1), due_date=date(2025, 7, 1),
        subtotal=Decimal("1000"), total_amount=Decimal("1000"), status="unpaid",
    )
    db_session.add(inv)
    db_session.flush()
    return inv


@pytest.fixture
def invoices(db_session, tenant, students):
    """One invoice per student (A, B, classless)."""
    student_a, student_b, student_classless = students
    inv_a = _make_invoice(db_session, tenant, student_a.id)
    inv_b = _make_invoice(db_session, tenant, student_b.id)
    inv_c = _make_invoice(db_session, tenant, student_classless.id)
    return inv_a, inv_b, inv_c


@pytest.fixture
def fee_payments(db_session, tenant, invoices, actor):
    """One FeePayment + receipt per invoice."""
    inv_a, inv_b, _inv_c = invoices
    out = {}
    for key, inv in (("a", inv_a), ("b", inv_b)):
        pay = fees_models.FeePayment(
            id=_new_id("fp-"), tenant_id=tenant.id, invoice_id=inv.id,
            student_id=inv.student_id, amount=Decimal("500"),
            payment_method="cash", payment_date=date(2025, 6, 15),
            collected_by=actor.id,
        )
        db_session.add(pay)
        db_session.flush()
        rcp = fees_models.FeeReceipt(
            id=_new_id("rcp-"), tenant_id=tenant.id, payment_id=pay.id,
            receipt_number=f"RCP-{uuid.uuid4().hex[:6]}",
        )
        db_session.add(rcp)
        db_session.flush()
        out[key] = pay
    return out


# ---------- Finance domain fixtures ----------

def _make_structure(db_session, tenant, academic_year_id, class_id=None):
    fs = finance_models.FeeStructure(
        id=_new_id("fs-"), tenant_id=tenant.id, academic_year_id=academic_year_id,
        name=f"Struct-{uuid.uuid4().hex[:6]}", due_date=date(2025, 7, 1),
    )
    db_session.add(fs)
    db_session.flush()
    comp = finance_models.FeeComponent(
        id=_new_id("fc-"), tenant_id=tenant.id, fee_structure_id=fs.id,
        name="Tuition", amount=Decimal("1000"),
    )
    db_session.add(comp)
    db_session.flush()
    if class_id is not None:
        fsc = finance_models.FeeStructureClass(
            id=_new_id("fsc-"), tenant_id=tenant.id, fee_structure_id=fs.id,
            class_id=class_id, academic_year_id=academic_year_id,
        )
        db_session.add(fsc)
        db_session.flush()
    return fs, comp


@pytest.fixture
def structures(db_session, tenant, classes, academic_year):
    """structure_a (class A), structure_b (class B), structure_tenant (no class)."""
    class_a, class_b = classes
    fs_a, _ = _make_structure(db_session, tenant, academic_year.id, class_a.id)
    fs_b, _ = _make_structure(db_session, tenant, academic_year.id, class_b.id)
    fs_t, _ = _make_structure(db_session, tenant, academic_year.id, None)
    return fs_a, fs_b, fs_t


def _make_student_fee(db_session, tenant, student_id, fee_structure_id):
    sf = finance_models.StudentFee(
        id=_new_id("sf-"), tenant_id=tenant.id, student_id=student_id,
        fee_structure_id=fee_structure_id, status=StudentFeeStatus.unpaid.value,
        total_amount=Decimal("1000"), paid_amount=Decimal("0"),
        due_date=date(2025, 7, 1),
    )
    db_session.add(sf)
    db_session.flush()
    return sf


@pytest.fixture
def student_fees(db_session, tenant, students, structures):
    """student_fee for A (structure_a), B (structure_b), classless (structure_tenant)."""
    student_a, student_b, student_classless = students
    fs_a, fs_b, fs_t = structures
    sf_a = _make_student_fee(db_session, tenant, student_a.id, fs_a.id)
    sf_b = _make_student_fee(db_session, tenant, student_b.id, fs_b.id)
    sf_c = _make_student_fee(db_session, tenant, student_classless.id, fs_t.id)
    return sf_a, sf_b, sf_c


@pytest.fixture
def finance_payments(db_session, tenant, student_fees, actor):
    """Successful Payment for student_fee A and B."""
    sf_a, sf_b, _sf_c = student_fees
    out = {}
    for key, sf in (("a", sf_a), ("b", sf_b)):
        pay = finance_models.Payment(
            id=_new_id("pay-"), tenant_id=tenant.id, student_fee_id=sf.id,
            amount=Decimal("200"), method="cash",
            status=PaymentStatus.success.value, created_by=actor.id,
        )
        db_session.add(pay)
        db_session.flush()
        out[key] = pay
    return out


# ===========================================================================
# FEES — invoice list
# ===========================================================================

def test_fees_invoice_list_restricted_sees_only_unit_a(
    flask_app, db_session, tenant, invoices, restricted_user
):
    inv_a, inv_b, inv_c = invoices
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        result = invoice_service.list_invoices()
        ids = {r["id"] for r in result}
        assert inv_a.id in ids
        assert inv_b.id not in ids  # unit B excluded
        assert inv_c.id not in ids  # classless excluded


def test_fees_invoice_list_unrestricted_sees_all(
    flask_app, db_session, tenant, invoices, unrestricted_user
):
    inv_a, inv_b, inv_c = invoices
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        ids = {r["id"] for r in invoice_service.list_invoices()}
        assert {inv_a.id, inv_b.id, inv_c.id} <= ids


def test_fees_invoice_list_student_b_param_forbidden(
    flask_app, db_session, tenant, invoices, students, restricted_user
):
    _a, student_b, _c = students
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            invoice_service.list_invoices(student_id=student_b.id)


# ===========================================================================
# FEES — invoice get / send-reminder / create / payment / receipt
# ===========================================================================

def test_fees_invoice_get_unit_b_forbidden(
    flask_app, db_session, tenant, invoices, restricted_user
):
    _a, inv_b, _c = invoices
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            invoice_service.get_invoice(inv_b.id)


def test_fees_invoice_get_unit_a_ok(
    flask_app, db_session, tenant, invoices, restricted_user
):
    inv_a, _b, _c = invoices
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        assert invoice_service.get_invoice(inv_a.id)["id"] == inv_a.id


def test_fees_send_reminder_unit_b_forbidden(
    flask_app, db_session, tenant, invoices, restricted_user
):
    _a, inv_b, _c = invoices
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            reminder_service.send_invoice_reminder(inv_b.id)


def test_fees_send_reminder_unit_a_ok(
    flask_app, db_session, tenant, invoices, restricted_user
):
    inv_a, _b, _c = invoices
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        result = reminder_service.send_invoice_reminder(inv_a.id)
        assert result["success"] is True


def test_fees_create_invoice_unit_b_forbidden(
    flask_app, db_session, tenant, students, restricted_user
):
    _a, student_b, _c = students
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            invoice_service.create_invoice(
                student_id=student_b.id, academic_year="2025-2026",
                issue_date=date(2025, 6, 1), due_date=date(2025, 7, 1),
                items=[{"fee_head": "Tuition", "amount": 1000}],
            )


def test_fees_create_invoice_unit_a_ok(
    flask_app, db_session, tenant, students, restricted_user
):
    student_a, _b, _c = students
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        result = invoice_service.create_invoice(
            student_id=student_a.id, academic_year="2025-2026",
            issue_date=date(2025, 6, 1), due_date=date(2025, 7, 1),
            items=[{"fee_head": "Tuition", "amount": 1000}],
        )
        assert result["success"] is True


def test_fees_create_invoice_classless_forbidden(
    flask_app, db_session, tenant, students, restricted_user
):
    _a, _b, student_classless = students
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            invoice_service.create_invoice(
                student_id=student_classless.id, academic_year="2025-2026",
                issue_date=date(2025, 6, 1), due_date=date(2025, 7, 1),
                items=[{"fee_head": "Tuition", "amount": 1000}],
            )


def test_fees_record_payment_unit_b_forbidden(
    flask_app, db_session, tenant, invoices, restricted_user
):
    _a, inv_b, _c = invoices
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            fee_payment_service.record_fee_payment(
                invoice_id=inv_b.id, amount=Decimal("100"), payment_method="cash",
            )


def test_fees_record_payment_unit_a_ok(
    flask_app, db_session, tenant, invoices, restricted_user
):
    inv_a, _b, _c = invoices
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        result = fee_payment_service.record_fee_payment(
            invoice_id=inv_a.id, amount=Decimal("100"), payment_method="cash",
        )
        assert result["success"] is True


def test_fees_get_payment_unit_b_forbidden(
    flask_app, db_session, tenant, fee_payments, restricted_user
):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            fee_payment_service.get_fee_payment(fee_payments["b"].id)


def test_fees_get_payment_unit_a_ok(
    flask_app, db_session, tenant, fee_payments, restricted_user
):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        assert fee_payment_service.get_fee_payment(fee_payments["a"].id) is not None


def test_fees_receipt_pdf_unit_b_forbidden(
    flask_app, db_session, tenant, fee_payments, restricted_user, monkeypatch
):
    monkeypatch.setattr(
        "modules.fees.services.receipt_service.generate_receipt_pdf",
        lambda pid: b"%PDF-stub",
    )
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            receipt_service.get_receipt_pdf_bytes(fee_payments["b"].id)


# ===========================================================================
# FINANCE — student-fee list / get
# ===========================================================================

def test_finance_student_fee_list_restricted_sees_only_unit_a(
    flask_app, db_session, tenant, student_fees, restricted_user
):
    sf_a, sf_b, sf_c = student_fees
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        ids = {r["id"] for r in student_fee_service.list_student_fees()}
        assert sf_a.id in ids
        assert sf_b.id not in ids
        assert sf_c.id not in ids  # classless excluded


def test_finance_student_fee_list_unrestricted_sees_all(
    flask_app, db_session, tenant, student_fees, unrestricted_user
):
    sf_a, sf_b, sf_c = student_fees
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        ids = {r["id"] for r in student_fee_service.list_student_fees()}
        assert {sf_a.id, sf_b.id, sf_c.id} <= ids


def test_finance_student_fee_get_unit_b_forbidden(
    flask_app, db_session, tenant, student_fees, restricted_user
):
    _a, sf_b, _c = student_fees
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            student_fee_service.get_student_fee(sf_b.id)


def test_finance_student_fee_get_unit_a_ok(
    flask_app, db_session, tenant, student_fees, restricted_user
):
    sf_a, _b, _c = student_fees
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        assert student_fee_service.get_student_fee(sf_a.id)["id"] == sf_a.id


def test_finance_student_fee_list_class_b_param_forbidden(
    flask_app, db_session, tenant, classes, student_fees, restricted_user
):
    _class_a, class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            student_fee_service.list_student_fees(class_id=class_b.id)


# ===========================================================================
# FINANCE — payment create / refund
# ===========================================================================

def test_finance_create_payment_unit_b_forbidden(
    flask_app, db_session, tenant, student_fees, restricted_user
):
    _a, sf_b, _c = student_fees
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            payment_service.create_payment(
                student_fee_id=sf_b.id, amount="100", method="cash",
            )


def test_finance_create_payment_unit_a_ok(
    flask_app, db_session, tenant, student_fees, restricted_user
):
    sf_a, _b, _c = student_fees
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        result = payment_service.create_payment(
            student_fee_id=sf_a.id, amount="100", method="cash",
        )
        assert result["success"] is True


def test_finance_refund_unit_b_forbidden(
    flask_app, db_session, tenant, finance_payments, restricted_user
):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            payment_service.refund_payment(payment_id=finance_payments["b"].id)


def test_finance_refund_unit_a_ok(
    flask_app, db_session, tenant, finance_payments, restricted_user
):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        result = payment_service.refund_payment(payment_id=finance_payments["a"].id)
        assert result["success"] is True


# ===========================================================================
# FINANCE — fee structure config (class-linked vs tenant-wide)
# ===========================================================================

def test_finance_structure_get_class_b_forbidden(
    flask_app, db_session, tenant, structures, restricted_user
):
    _a, fs_b, _t = structures
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            structure_service.get_fee_structure(fs_b.id)


def test_finance_structure_get_class_a_ok(
    flask_app, db_session, tenant, structures, restricted_user
):
    fs_a, _b, _t = structures
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        assert structure_service.get_fee_structure(fs_a.id)["id"] == fs_a.id


def test_finance_structure_get_tenant_wide_forbidden(
    flask_app, db_session, tenant, structures, restricted_user
):
    _a, _b, fs_t = structures
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            structure_service.get_fee_structure(fs_t.id)


def test_finance_structure_delete_tenant_wide_forbidden(
    flask_app, db_session, tenant, structures, restricted_user
):
    _a, _b, fs_t = structures
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            structure_service.delete_fee_structure(fs_t.id)


def test_finance_structure_list_restricted_excludes_tenant_and_unit_b(
    flask_app, db_session, tenant, structures, restricted_user
):
    fs_a, fs_b, fs_t = structures
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        ids = {s["id"] for s in structure_service.list_fee_structures()}
        assert fs_a.id in ids
        assert fs_b.id not in ids
        assert fs_t.id not in ids


def test_finance_structure_list_unrestricted_sees_all(
    flask_app, db_session, tenant, structures, unrestricted_user
):
    fs_a, fs_b, fs_t = structures
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        ids = {s["id"] for s in structure_service.list_fee_structures()}
        assert {fs_a.id, fs_b.id, fs_t.id} <= ids


def test_finance_structure_create_class_b_forbidden(
    flask_app, db_session, tenant, classes, academic_year, restricted_user
):
    _class_a, class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            structure_service.create_fee_structure(
                academic_year_id=academic_year.id, name="New",
                due_date="2025-07-01", class_ids=[class_b.id],
                components=[{"name": "Tuition", "amount": 1000}],
            )


# ===========================================================================
# FINANCE — dashboard read-aggregates -> BRANCH-SCOPED for restricted
# (summary + recent-payments). Must include ONLY the caller's branches.
# ===========================================================================

def test_finance_summary_no_class_branch_scoped_for_restricted(
    flask_app, db_session, tenant, student_fees, restricted_user
):
    """Restricted user with NO class_id: 200 with unit-A-only totals.

    Fixture: sf_a (unit A, total 1000), sf_b (unit B, 1000), sf_c (classless,
    1000). The restricted user is bound to unit A, so the summary must reflect
    ONLY sf_a — total_expected == 1000, not 2000/3000.
    """
    sf_a, _sf_b, _sf_c = student_fees
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        result = student_fee_service.get_finance_summary()
        # Only unit-A data: exactly sf_a's 1000. Unit-B + classless excluded.
        assert result["total_expected"] == 1000.0
        assert result["total_collected"] == 0.0
        assert result["total_outstanding"] == 1000.0


def test_finance_summary_no_class_excludes_other_branch_collected(
    flask_app, db_session, tenant, student_fees, restricted_user
):
    """The scoped total_collected must NOT include unit-B's paid amount.

    total_collected aggregates StudentFee.paid_amount. We mark BOTH sf_a (unit
    A) and sf_b (unit B) as paid 200; a restricted (unit A) summary must collect
    only sf_a's 200, never 400 (which would mean unit B leaked).
    """
    sf_a, sf_b, _sf_c = student_fees
    sf_a.paid_amount = Decimal("200")
    sf_b.paid_amount = Decimal("200")
    db_session.flush()
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        result = student_fee_service.get_finance_summary()
        # Unit A only: expected 1000, collected 200. Unit-B figures excluded.
        assert result["total_expected"] == 1000.0
        assert result["total_collected"] == 200.0  # NOT 400 (would mean unit B leaked)
        assert result["total_outstanding"] == 800.0


def test_finance_summary_class_a_ok_for_restricted(
    flask_app, db_session, tenant, classes, student_fees, restricted_user
):
    class_a, _class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        result = student_fee_service.get_finance_summary(class_id=class_a.id)
        assert result["total_expected"] == 1000.0


def test_finance_summary_class_b_param_forbidden_for_restricted(
    flask_app, db_session, tenant, classes, student_fees, restricted_user
):
    """An explicit out-of-branch class_id still 403s (existing assert)."""
    _class_a, class_b = classes
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            student_fee_service.get_finance_summary(class_id=class_b.id)


def test_finance_summary_unrestricted_sees_all_branches(
    flask_app, db_session, tenant, student_fees, unrestricted_user
):
    """Unrestricted admin: tenant-wide total incl. unit A + B + classless."""
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        result = student_fee_service.get_finance_summary()
        # All three student_fees (1000 each) sum tenant-wide.
        assert result["total_expected"] == 3000.0


def test_finance_recent_payments_branch_scoped_for_restricted(
    flask_app, db_session, tenant, student_fees, finance_payments, restricted_user
):
    """Restricted user: only unit-A payments, never unit-B rows.

    finance_payments: pay 'a' (sf_a, unit A) + pay 'b' (sf_b, unit B). A
    restricted (unit A) user must see only pay 'a'.
    """
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        result = payment_service.list_recent_payments(limit=10)
        ids = {p["id"] for p in result}
        assert finance_payments["a"].id in ids
        assert finance_payments["b"].id not in ids  # unit B excluded


def test_finance_recent_payments_unrestricted_sees_all(
    flask_app, db_session, tenant, student_fees, finance_payments, unrestricted_user
):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        result = payment_service.list_recent_payments(limit=10)
        ids = {p["id"] for p in result}
        assert {finance_payments["a"].id, finance_payments["b"].id} <= ids


def test_finance_rollover_denied_for_restricted(
    flask_app, db_session, tenant, academic_year, restricted_user
):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = restricted_user
        with pytest.raises(BranchForbidden):
            rollover_service.rollover_fee_structures(
                from_year_id=academic_year.id, to_year_id="other-year-id",
            )


# ===========================================================================
# Regression — unrestricted admin is a strict no-op
# ===========================================================================

def test_unrestricted_counts_unchanged(
    flask_app, db_session, tenant, invoices, student_fees, structures,
    unrestricted_user
):
    inv_a, inv_b, inv_c = invoices
    sf_a, sf_b, sf_c = student_fees
    fs_a, fs_b, fs_t = structures
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        assert len({r["id"] for r in invoice_service.list_invoices()}) >= 3
        assert len({r["id"] for r in student_fee_service.list_student_fees()}) >= 3
        struct_ids = {s["id"] for s in structure_service.list_fee_structures()}
        assert {fs_a.id, fs_b.id, fs_t.id} <= struct_ids


# ===========================================================================
# FINANCE — student-fee pagination + server-side summary
# ===========================================================================

def test_finance_student_fee_pagination_splits_into_pages(
    flask_app, db_session, tenant, student_fees, unrestricted_user
):
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        assert student_fee_service.count_student_fees() == 3
        page1 = student_fee_service.list_student_fees(page=1, page_size=2)
        page2 = student_fee_service.list_student_fees(page=2, page_size=2)
        assert len(page1) == 2
        assert len(page2) == 1
        # Pages must not overlap and together cover every row.
        ids = {r["id"] for r in page1} | {r["id"] for r in page2}
        assert ids == {sf.id for sf in student_fees}


def test_finance_student_fee_summary_aggregates_over_all_rows(
    flask_app, db_session, tenant, student_fees, unrestricted_user
):
    sf_a, sf_b, sf_c = student_fees
    sf_a.status = StudentFeeStatus.paid.value
    sf_a.paid_amount = Decimal("1000")
    sf_b.status = StudentFeeStatus.partial.value
    sf_b.paid_amount = Decimal("400")
    sf_c.status = StudentFeeStatus.overdue.value
    sf_c.paid_amount = Decimal("0")
    db_session.flush()
    with flask_app.test_request_context("/"):
        g.tenant_id = tenant.id
        g.current_user = unrestricted_user
        summary = student_fee_service.summarize_student_fees()
        assert summary["total_count"] == 3
        assert summary["total_amount"] == 3000.0
        assert summary["paid_amount"] == 1400.0
        # Outstanding is clamped per row (>= 0): 0 + 600 + 1000.
        assert summary["outstanding_amount"] == 1600.0
        assert summary["paid_count"] == 1
        assert summary["overdue_count"] == 1
