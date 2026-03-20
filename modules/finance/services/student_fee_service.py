"""Student fee assignment and listing services."""

from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional

from sqlalchemy import case

from backend.core.database import db
from backend.core.tenant import get_tenant_id
from backend.modules.finance.models import (
    FeeStructure,
    FeeComponent,
    StudentFee,
    StudentFeeItem,
    FeeStructureClass,
    Payment,
)
from backend.modules.finance.enums import PaymentStatus, StudentFeeStatus
from backend.modules.students.models import Student
from backend.modules.auth.models import User
from backend.modules.classes.models import Class
from backend.modules.audit.services import log_finance_action


def get_finance_summary(
    academic_year_id: Optional[str] = None,
    class_id: Optional[str] = None,
    include_recent_payments: Optional[int] = None,
) -> Dict:
    """
    Return aggregated finance stats for dashboard without loading full student fee records.
    When include_recent_payments is set (e.g. 10), also returns recent_payments in the response.
    """
    from sqlalchemy import func

    from .payment_service import list_recent_payments

    tenant_id = get_tenant_id()
    if not tenant_id:
        result = {
            "total_expected": 0,
            "total_collected": 0,
            "total_outstanding": 0,
            "overdue_count": 0,
        }
        if include_recent_payments:
            result["recent_payments"] = []
        return result

    query = (
        db.session.query(
            func.coalesce(func.sum(StudentFee.total_amount), 0).label("total_expected"),
            func.coalesce(func.sum(StudentFee.paid_amount), 0).label("total_collected"),
            func.coalesce(
                func.sum(
                    case(
                        (StudentFee.status == StudentFeeStatus.overdue.value, 1),
                        else_=0,
                    )
                ),
                0,
            ).label("overdue_count"),
        )
        .filter(StudentFee.tenant_id == tenant_id)
        .join(Student, StudentFee.student_id == Student.id)
    )
    if academic_year_id:
        query = query.join(
            FeeStructure, StudentFee.fee_structure_id == FeeStructure.id
        ).filter(
            FeeStructure.academic_year_id == academic_year_id,
            FeeStructure.tenant_id == tenant_id,
        )
    if class_id:
        query = query.filter(Student.class_id == class_id)

    row = query.first()
    total_expected = float(row.total_expected or 0)
    total_collected = float(row.total_collected or 0)
    overdue_count = int(row.overdue_count or 0)
    result = {
        "total_expected": total_expected,
        "total_collected": total_collected,
        "total_outstanding": total_expected - total_collected,
        "overdue_count": overdue_count,
    }
    if include_recent_payments and include_recent_payments > 0:
        limit = min(include_recent_payments, 50)
        result["recent_payments"] = list_recent_payments(limit=limit)
    return result


def list_student_fees(
    student_id: Optional[str] = None,
    fee_structure_id: Optional[str] = None,
    status: Optional[str] = None,
    academic_year_id: Optional[str] = None,
    class_id: Optional[str] = None,
    search: Optional[str] = None,
    include_items: bool = True,
) -> List[Dict]:
    """List student fees with optional filters. Set include_items=False for list views."""
    from backend.modules.auth.models import User

    tenant_id = get_tenant_id()
    if not tenant_id:
        return []

    query = StudentFee.query.filter_by(tenant_id=tenant_id).join(
        Student, StudentFee.student_id == Student.id
    )
    if student_id:
        query = query.filter(StudentFee.student_id == student_id)
    if fee_structure_id:
        query = query.filter(StudentFee.fee_structure_id == fee_structure_id)
    if status:
        # Allow records to fall into multiple logical status "buckets".
        # Example: a partially paid fee that is now overdue should appear in both
        # the "partial" and "overdue" views.
        if status == StudentFeeStatus.partial.value:
            query = query.filter(
                db.or_(
                    StudentFee.status == StudentFeeStatus.partial.value,
                    db.and_(
                        StudentFee.status == StudentFeeStatus.overdue.value,
                        StudentFee.paid_amount > 0,
                    ),
                )
            )
        elif status == StudentFeeStatus.unpaid.value:
            # Unpaid: include both status=unpaid and overdue with paid_amount=0 (unpaid but overdue)
            query = query.filter(
                db.or_(
                    StudentFee.status == StudentFeeStatus.unpaid.value,
                    db.and_(
                        StudentFee.status == StudentFeeStatus.overdue.value,
                        StudentFee.paid_amount == 0,
                    ),
                )
            )
        else:
            query = query.filter(StudentFee.status == status)
    if academic_year_id:
        query = query.join(
            FeeStructure, StudentFee.fee_structure_id == FeeStructure.id
        ).filter(
            FeeStructure.academic_year_id == academic_year_id,
            FeeStructure.tenant_id == tenant_id,
        )
    if class_id:
        query = query.filter(Student.class_id == class_id)
    if search and search.strip():
        query = query.join(User, Student.user_id == User.id).filter(
            db.or_(
                User.name.ilike(f"%{search.strip()}%"),
                Student.admission_number.ilike(f"%{search.strip()}%"),
            )
        )

    query = query.order_by(
        case((StudentFee.status == "overdue", 0), else_=1)
    ).order_by(StudentFee.due_date.asc())

    fees = query.all()
    result = []
    for sf in fees:
        d = sf.to_dict()
        if include_items:
            d["items"] = [i.to_dict() for i in sf.items]
        d["student_name"] = sf.student.user.name if sf.student and sf.student.user else None
        d["admission_number"] = sf.student.admission_number if sf.student else None
        d["fee_structure_name"] = sf.fee_structure.name if sf.fee_structure else None
        d["class_id"] = sf.student.class_id if sf.student else None
        d["academic_year_id"] = sf.fee_structure.academic_year_id if sf.fee_structure else None
        result.append(d)
    return result


def get_student_fee(fee_id: str) -> Optional[Dict]:
    """Get student fee by ID with items and payments."""
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None

    sf = StudentFee.query.filter_by(id=fee_id, tenant_id=tenant_id).first()
    if not sf:
        return None

    d = sf.to_dict()
    d["items"] = [i.to_dict() for i in sf.items]
    d["payments"] = [p.to_dict() for p in sf.payments]
    d["student_name"] = sf.student.user.name if sf.student and sf.student.user else None
    d["admission_number"] = sf.student.admission_number if sf.student else None
    d["fee_structure_name"] = sf.fee_structure.name if sf.fee_structure else None
    return d


def assign_student_fees_for_structure(
    fee_structure_id: str,
    student_ids: Optional[List[str]] = None,
    user_id: Optional[str] = None,
) -> Dict:
    """
    Assign fee structure to students. If student_ids is None, assigns to all
    students in the structure's class (or all if structure has no class).
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}

    fs = FeeStructure.query.filter_by(id=fee_structure_id, tenant_id=tenant_id).first()
    if not fs:
        return {"success": False, "error": "Fee structure not found"}

    # Resolve student set
    if student_ids:
        students = Student.query.filter(
            Student.id.in_(student_ids),
            Student.tenant_id == tenant_id,
        ).all()
    else:
        # Query FeeStructureClass directly to ensure we have committed data (e.g. after update)
        class_ids = [
            fsc.class_id
            for fsc in FeeStructureClass.query.filter_by(
                fee_structure_id=fee_structure_id,
                tenant_id=tenant_id,
            ).all()
        ]
        if class_ids:
            # Include students in structure's classes; match academic year when set
            query = Student.query.filter(
                Student.class_id.in_(class_ids),
                Student.tenant_id == tenant_id,
            )
            if fs.academic_year_id:
                from sqlalchemy import or_
                query = query.filter(
                    or_(
                        Student.academic_year_id == fs.academic_year_id,
                        Student.academic_year_id.is_(None),
                    )
                )
            students = query.all()
        else:
            students = Student.query.filter_by(tenant_id=tenant_id).all()

    created = 0
    for student in students:
        existing = StudentFee.query.filter_by(
            student_id=student.id,
            fee_structure_id=fee_structure_id,
            tenant_id=tenant_id,
        ).first()
        if existing:
            continue

        total = Decimal("0")
        sf = StudentFee(
            tenant_id=tenant_id,
            student_id=student.id,
            fee_structure_id=fee_structure_id,
            status=StudentFeeStatus.unpaid.value,
            total_amount=0,
            paid_amount=0,
            due_date=fs.due_date,
        )
        db.session.add(sf)
        db.session.flush()

        for comp in fs.components:
            total += comp.amount
            sfi = StudentFeeItem(
                tenant_id=tenant_id,
                student_fee_id=sf.id,
                fee_component_id=comp.id,
                amount=comp.amount,
                paid_amount=0,
            )
            db.session.add(sfi)

        sf.total_amount = total
        created += 1

    try:
        db.session.commit()
        log_finance_action(
            action="finance.student_fee.assigned",
            tenant_id=tenant_id,
            user_id=user_id,
            extra_data={
                "fee_structure_id": fee_structure_id,
                "created_count": created,
            },
        )
        return {"success": True, "created_count": created}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}


def unassign_fees_for_removed_classes(
    fee_structure_id: str,
    class_ids: List[str],
    user_id: Optional[str] = None,
) -> Dict:
    """
    Remove StudentFee assignments for students in the given classes.
    Only removes when there are no successful payments for that fee.
    Call this when a fee structure is updated to exclude certain classes.
    """
    if not class_ids:
        return {"success": True, "removed_count": 0}

    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}

    students_in_classes = Student.query.filter(
        Student.class_id.in_(class_ids),
        Student.tenant_id == tenant_id,
    ).with_entities(Student.id).all()
    student_ids = [s[0] for s in students_in_classes]
    if not student_ids:
        return {"success": True, "removed_count": 0}

    student_fees = StudentFee.query.filter(
        StudentFee.fee_structure_id == fee_structure_id,
        StudentFee.student_id.in_(student_ids),
        StudentFee.tenant_id == tenant_id,
    ).all()

    removed = 0
    for sf in student_fees:
        has_payments = (
            Payment.query.filter_by(
                tenant_id=tenant_id,
                student_fee_id=sf.id,
                status=PaymentStatus.success.value,
            ).count()
            > 0
        )
        if has_payments:
            continue
        Payment.query.filter_by(
            tenant_id=tenant_id, student_fee_id=sf.id
        ).delete(synchronize_session=False)
        StudentFeeItem.query.filter_by(
            tenant_id=tenant_id, student_fee_id=sf.id
        ).delete(synchronize_session=False)
        StudentFee.query.filter_by(
            tenant_id=tenant_id, id=sf.id
        ).delete(synchronize_session=False)
        removed += 1

    try:
        db.session.commit()
        if removed > 0:
            log_finance_action(
                action="finance.student_fee.bulk_removed",
                tenant_id=tenant_id,
                user_id=user_id,
                extra_data={
                    "fee_structure_id": fee_structure_id,
                    "removed_count": removed,
                    "class_ids": class_ids,
                },
            )
        return {"success": True, "removed_count": removed}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e), "removed_count": 0}


def remove_student_fee_for_structure(
    fee_structure_id: str,
    student_id: str,
) -> Dict:
    """
    Remove a student's assignment to a given fee structure.

    Only allowed when there are no successful payments for that StudentFee.
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}

    sf = StudentFee.query.filter_by(
        tenant_id=tenant_id,
        fee_structure_id=fee_structure_id,
        student_id=student_id,
    ).first()
    if not sf:
        return {"success": False, "error": "Student fee not found"}

    try:
        # Prevent deletion if there are successful payments
        has_payments = (
            Payment.query.filter_by(
                tenant_id=tenant_id,
                student_fee_id=sf.id,
                status=PaymentStatus.success.value,
            ).count()
            > 0
        )
        if has_payments:
            return {
                "success": False,
                "error": "Cannot remove fee: there are successful payments recorded for this student",
            }

        # Delete related records in safe order (payments, items, then student_fee)
        Payment.query.filter_by(
            tenant_id=tenant_id,
            student_fee_id=sf.id,
        ).delete(synchronize_session=False)

        StudentFeeItem.query.filter_by(
            tenant_id=tenant_id,
            student_fee_id=sf.id,
        ).delete(synchronize_session=False)

        StudentFee.query.filter_by(
            tenant_id=tenant_id,
            id=sf.id,
        ).delete(synchronize_session=False)

        db.session.commit()
        log_finance_action(
            action="finance.student_fee.removed",
            tenant_id=tenant_id,
            user_id=None,
            extra_data={
                "fee_structure_id": fee_structure_id,
                "student_id": student_id,
                "student_fee_id": sf.id,
            },
        )
        return {"success": True, "message": "Student removed from fee structure"}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}


def auto_assign_fees_for_student(student_id: str) -> None:
    """
    Ensure a student has StudentFee records for all fee structures
    that apply to their class and academic year.
    Safe to call multiple times; underlying assignment is idempotent.
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        return

    student = Student.query.filter_by(id=student_id, tenant_id=tenant_id).first()
    if not student or not student.class_id or not student.academic_year_id:
        return

    # Find all fee structures linked to this class in this academic year
    structure_ids = [
        fsc.fee_structure_id
        for fsc in FeeStructureClass.query.filter_by(
            tenant_id=tenant_id,
            class_id=student.class_id,
            academic_year_id=student.academic_year_id,
        ).all()
    ]
    if not structure_ids:
        return

    for sid in structure_ids:
        # Use existing assignment logic; it will skip if already present
        assign_student_fees_for_structure(
            fee_structure_id=sid,
            student_ids=[student_id],
            user_id=None,
        )
