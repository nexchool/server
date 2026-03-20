"""Fee structure and component CRUD services."""

from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional

from sqlalchemy.exc import IntegrityError

from backend.core.database import db
from backend.core.tenant import get_tenant_id
from backend.modules.academics.academic_year.models import AcademicYear
from backend.modules.finance.models import (
    FeeStructure,
    FeeStructureClass,
    FeeComponent,
    StudentFee,
    StudentFeeItem,
    Payment,
)
from backend.modules.audit.services import log_finance_action
from backend.modules.classes.models import Class
from backend.modules.finance.services.payment_service import recalculate_student_fee_status


def list_available_classes_for_structure(
    academic_year_id: str,
    exclude_structure_id: Optional[str] = None,
) -> List[Dict]:
    """
    Return classes that can be assigned to a fee structure.
    Excludes classes already in another structure for this academic year.
    When editing (exclude_structure_id), includes that structure's own classes.
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        return []

    taken_class_ids = set(
        c.class_id
        for c in FeeStructureClass.query.filter_by(
            academic_year_id=academic_year_id,
            tenant_id=tenant_id,
        ).all()
    )
    if exclude_structure_id:
        for sc in FeeStructureClass.query.filter_by(
            fee_structure_id=exclude_structure_id,
            tenant_id=tenant_id,
        ).all():
            taken_class_ids.discard(sc.class_id)

    classes = Class.query.filter_by(
        tenant_id=tenant_id,
        academic_year_id=academic_year_id,
    ).all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "section": c.section,
        }
        for c in classes
        if c.id not in taken_class_ids
    ]


def list_fee_structures(
    academic_year_id: Optional[str] = None,
    class_id: Optional[str] = None,
) -> List[Dict]:
    """List fee structures for current tenant."""
    tenant_id = get_tenant_id()
    if not tenant_id:
        return []

    query = FeeStructure.query.filter_by(tenant_id=tenant_id)
    if academic_year_id:
        query = query.filter_by(academic_year_id=academic_year_id)
    if class_id:
        query = query.join(FeeStructureClass).filter(
            FeeStructureClass.class_id == class_id,
            FeeStructureClass.tenant_id == tenant_id,
        ).distinct()
    query = query.order_by(FeeStructure.due_date)
    structures = query.all()
    result = []
    for s in structures:
        d = s.to_dict()
        d["components"] = [c.to_dict() for c in s.components]
        result.append(d)
    return result


def get_fee_structure(structure_id: str) -> Optional[Dict]:
    """Get fee structure by ID with components."""
    tenant_id = get_tenant_id()
    if not tenant_id:
        return None

    s = FeeStructure.query.filter_by(id=structure_id, tenant_id=tenant_id).first()
    if not s:
        return None
    d = s.to_dict()
    d["components"] = [c.to_dict() for c in s.components]
    return d


def _get_all_class_ids_for_academic_year(
    academic_year_id: str, tenant_id: str
) -> List[str]:
    """Return all class IDs for the given academic year (for 'all classes' semantics)."""
    classes = Class.query.filter_by(
        tenant_id=tenant_id,
        academic_year_id=academic_year_id,
    ).all()
    return [c.id for c in classes]


def create_fee_structure(
    academic_year_id: str,
    name: str,
    due_date: date | str,
    class_ids: Optional[List[str]] = None,
    components: Optional[List[Dict]] = None,
    user_id: Optional[str] = None,
) -> Dict:
    """Create fee structure with components. class_ids: list of class IDs (optional). Empty = all classes."""
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}

    ay = AcademicYear.query.filter_by(id=academic_year_id, tenant_id=tenant_id).first()
    if not ay:
        return {"success": False, "error": "Academic year not found"}

    class_ids = class_ids or []
    # Empty class_ids means "apply to all classes" per UI convention
    if not class_ids:
        class_ids = _get_all_class_ids_for_academic_year(academic_year_id, tenant_id)
    # Validate: no class can be in another structure for this academic year
    for cid in class_ids:
        taken = FeeStructureClass.query.filter_by(
            class_id=cid,
            academic_year_id=academic_year_id,
            tenant_id=tenant_id,
        ).first()
        if taken:
            return {"success": False, "error": "One or more classes are already assigned to another fee structure in this academic year"}

    try:
        if isinstance(due_date, str):
            due_date = date.fromisoformat(due_date)

        fs = FeeStructure(
            tenant_id=tenant_id,
            academic_year_id=academic_year_id,
            name=name,
            due_date=due_date,
        )
        db.session.add(fs)
        db.session.flush()

        for cid in class_ids:
            fsc = FeeStructureClass(
                tenant_id=tenant_id,
                fee_structure_id=fs.id,
                class_id=cid,
                academic_year_id=academic_year_id,
            )
            db.session.add(fsc)

        total = Decimal("0")
        for i, comp in enumerate(components or []):
            amount = Decimal(str(comp.get("amount", 0)))
            total += amount
            fc = FeeComponent(
                tenant_id=tenant_id,
                fee_structure_id=fs.id,
                name=comp.get("name", "Component"),
                amount=amount,
                is_optional=bool(comp.get("is_optional", False)),
                sort_order=int(comp.get("sort_order", i)),
            )
            db.session.add(fc)

        db.session.commit()

        log_finance_action(
            action="finance.fee_structure.created",
            tenant_id=tenant_id,
            user_id=user_id,
            extra_data={"fee_structure_id": fs.id, "name": name},
        )
        d = fs.to_dict()
        d["components"] = [c.to_dict() for c in fs.components]
        return {"success": True, "fee_structure": d}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}


def update_fee_structure(
    structure_id: str,
    name: Optional[str] = None,
    due_date: Optional[date | str] = None,
    class_ids: Optional[List[str]] = None,
    components: Optional[List[Dict]] = None,
    user_id: Optional[str] = None,
) -> Dict:
    """Update fee structure. class_ids: list of class IDs (None = no change). components: replace all (None = no change)."""
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}

    fs = FeeStructure.query.filter_by(id=structure_id, tenant_id=tenant_id).first()
    if not fs:
        return {"success": False, "error": "Fee structure not found"}

    if class_ids is not None:
        # Empty class_ids means "apply to all classes" per UI convention
        if not class_ids:
            class_ids = _get_all_class_ids_for_academic_year(
                fs.academic_year_id, tenant_id
            )
        # Validate: no class can be in another structure (except this one) for this academic year
        current_class_ids = {sc.class_id for sc in fs.structure_classes}
        for cid in class_ids:
            if cid in current_class_ids:
                continue
            taken = FeeStructureClass.query.filter(
                FeeStructureClass.class_id == cid,
                FeeStructureClass.academic_year_id == fs.academic_year_id,
                FeeStructureClass.tenant_id == tenant_id,
                FeeStructureClass.fee_structure_id != structure_id,
            ).first()
            if taken:
                return {"success": False, "error": "One or more classes are already assigned to another fee structure in this academic year"}

    try:
        if name is not None:
            fs.name = name
        if due_date is not None:
            new_due = date.fromisoformat(due_date) if isinstance(due_date, str) else due_date
            fs.due_date = new_due
            # Propagate due_date to existing student fees so they stay in sync
            for sf in StudentFee.query.filter_by(
                fee_structure_id=structure_id, tenant_id=tenant_id
            ).all():
                sf.due_date = new_due
                recalculate_student_fee_status(sf)
        if class_ids is not None:
            # Diff-based update: only delete removed classes, only add new ones.
            # This avoids unique constraint violations when removing then re-adding the same class.
            target_ids = set(class_ids)
            current = {sc.class_id: sc for sc in fs.structure_classes}
            to_remove = [sc for cid, sc in current.items() if cid not in target_ids]
            removed_class_ids = [sc.class_id for sc in to_remove]
            to_add = [cid for cid in target_ids if cid not in current]
            for sc in to_remove:
                db.session.delete(sc)
            if to_remove:
                db.session.flush()
            for cid in to_add:
                fsc = FeeStructureClass(
                    tenant_id=tenant_id,
                    fee_structure_id=structure_id,
                    class_id=cid,
                    academic_year_id=fs.academic_year_id,
                )
                db.session.add(fsc)

        if components is not None:
            if not components:
                return {"success": False, "error": "At least one component is required"}

            # Replace all components: delete StudentFeeItems first, then FeeComponents.
            # ORM delete on FeeComponent would set fee_component_id=null on related
            # StudentFeeItems (violates NOT NULL). Bulk-delete items first.
            component_ids_to_delete = [fc.id for fc in fs.components]
            if component_ids_to_delete:
                StudentFeeItem.query.filter(
                    StudentFeeItem.fee_component_id.in_(component_ids_to_delete),
                    StudentFeeItem.tenant_id == tenant_id,
                ).delete(synchronize_session=False)
            for fc in list(fs.components):
                db.session.delete(fc)
            db.session.flush()

            # Create new components
            new_components = []
            for i, comp in enumerate(components):
                name = (comp.get("name") or "").strip()
                if not name:
                    continue
                amount = Decimal(str(comp.get("amount", 0)))
                fc = FeeComponent(
                    tenant_id=tenant_id,
                    fee_structure_id=structure_id,
                    name=name,
                    amount=amount,
                    is_optional=bool(comp.get("is_optional", False)),
                    sort_order=int(comp.get("sort_order", i)),
                )
                db.session.add(fc)
                db.session.flush()
                new_components.append(fc)

            if not new_components:
                return {"success": False, "error": "At least one valid component is required"}

            # Recreate StudentFeeItems for each StudentFee and recalculate totals
            student_fees = StudentFee.query.filter_by(
                fee_structure_id=structure_id, tenant_id=tenant_id
            ).all()
            total_from_components = sum(c.amount for c in new_components)
            for sf in student_fees:
                for fc in new_components:
                    sfi = StudentFeeItem(
                        tenant_id=tenant_id,
                        student_fee_id=sf.id,
                        fee_component_id=fc.id,
                        amount=fc.amount,
                        paid_amount=0,
                    )
                    db.session.add(sfi)
                sf.total_amount = total_from_components
                recalculate_student_fee_status(sf)

        db.session.commit()
        db.session.refresh(fs)
        log_finance_action(
            action="finance.fee_structure.updated",
            tenant_id=tenant_id,
            user_id=user_id,
            extra_data={"fee_structure_id": structure_id},
        )
        d = fs.to_dict()
        d["components"] = [c.to_dict() for c in fs.components]
        result = {"success": True, "fee_structure": d}
        if class_ids is not None:
            result["removed_class_ids"] = removed_class_ids
        return result
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}


def delete_fee_structure(structure_id: str, user_id: Optional[str] = None) -> Dict:
    """Delete fee structure and all related records in dependency order."""
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}

    if not FeeStructure.query.filter_by(id=structure_id, tenant_id=tenant_id).first():
        return {"success": False, "error": "Fee structure not found"}

    try:
        # Get student_fee ids for this structure before we start deleting
        student_fee_ids = [
            sf.id for sf in StudentFee.query.filter_by(
                fee_structure_id=structure_id, tenant_id=tenant_id
            ).all()
        ]

        # Delete in dependency order to avoid FK constraint violations
        if student_fee_ids:
            # Payments reference student_fees
            Payment.query.filter(
                Payment.student_fee_id.in_(student_fee_ids),
                Payment.tenant_id == tenant_id,
            ).delete(synchronize_session=False)

            # StudentFeeItems reference student_fees (and fee_components)
            StudentFeeItem.query.filter(
                StudentFeeItem.student_fee_id.in_(student_fee_ids),
                StudentFeeItem.tenant_id == tenant_id,
            ).delete(synchronize_session=False)

            # StudentFees reference fee_structures
            StudentFee.query.filter(
                StudentFee.fee_structure_id == structure_id,
                StudentFee.tenant_id == tenant_id,
            ).delete(synchronize_session=False)

        # FeeStructureClasses (junction table)
        FeeStructureClass.query.filter_by(
            fee_structure_id=structure_id, tenant_id=tenant_id
        ).delete(synchronize_session=False)

        # FeeComponents reference fee_structures
        FeeComponent.query.filter_by(
            fee_structure_id=structure_id, tenant_id=tenant_id
        ).delete(synchronize_session=False)

        # Finally delete the fee structure (bulk delete to avoid ORM session conflicts)
        FeeStructure.query.filter_by(
            id=structure_id, tenant_id=tenant_id
        ).delete(synchronize_session=False)

        db.session.commit()

        log_finance_action(
            action="finance.fee_structure.deleted",
            tenant_id=tenant_id,
            user_id=user_id,
            extra_data={"fee_structure_id": structure_id},
        )
        return {"success": True, "message": "Fee structure deleted"}
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}
