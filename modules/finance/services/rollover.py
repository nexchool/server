"""
Finance rollover: clone FeeStructure + FeeComponent + FeeStructureClass rows
from one academic year into another.

Inputs:
  - from_year_id, to_year_id
  - class_mapping = { old_class_id: new_class_id }  (optional; used to remap
    FeeStructureClass entries; entries whose old class is not in the mapping
    are skipped).

Idempotent: if a fee structure with the same `name` already exists in the
target year, it is reused (its class links are upserted but its existing
components are left untouched so admins do not lose customisations).

Does NOT auto-generate StudentFee rows — that stays a separate explicit
admin action through the existing finance flow.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from core.database import db
from core.tenant import get_tenant_id
from core.branch_scope import BranchForbidden, get_allowed_unit_ids
from modules.classes.models import Class
from modules.finance.models import FeeComponent, FeeStructure, FeeStructureClass

logger = logging.getLogger(__name__)


_GRADUATED = "GRADUATED"


def _normalize_mapping(raw: Any) -> Dict[str, str]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("class_mapping must be an object")
    out: Dict[str, str] = {}
    for k, v in raw.items():
        key = str(k).strip() if k is not None else ""
        val = str(v).strip() if v is not None else ""
        if not key or not val or key == val:
            continue
        if val == _GRADUATED:
            continue
        out[key] = val
    return out


def rollover_fee_structures(
    from_year_id: str,
    to_year_id: str,
    class_mapping: Any = None,
) -> Dict[str, Any]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}

    # Branch scope: year-transition rollover clones tenant-wide fee config
    # across every branch. Not a branch sub-admin operation. Deny for
    # restricted users; no-op when unrestricted.
    if get_allowed_unit_ids() is not None:
        raise BranchForbidden("Fee rollover is a tenant-wide operation.")

    if not from_year_id or not to_year_id:
        return {"success": False, "error": "from_year_id and to_year_id are required"}
    if from_year_id == to_year_id:
        return {"success": False, "error": "from_year_id and to_year_id must differ"}

    try:
        mapping = _normalize_mapping(class_mapping)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    # Validate mapped classes belong to the correct years.
    new_class_ids = list({v for v in mapping.values()})
    if new_class_ids:
        target_classes = Class.query.filter(
            Class.tenant_id == tenant_id,
            Class.id.in_(new_class_ids),
        ).all()
        target_year_by_id = {c.id: c.academic_year_id for c in target_classes}
        missing = [cid for cid in new_class_ids if cid not in target_year_by_id]
        if missing:
            return {
                "success": False,
                "error": f"Unknown target class_id(s): {', '.join(missing)}",
            }
        wrong_year = [
            cid for cid, yid in target_year_by_id.items() if yid != to_year_id
        ]
        if wrong_year:
            return {
                "success": False,
                "error": (
                    "Target class(es) do not belong to to_year_id: "
                    + ", ".join(wrong_year)
                ),
            }

    sources: List[FeeStructure] = (
        FeeStructure.query.filter_by(
            tenant_id=tenant_id, academic_year_id=from_year_id
        ).all()
    )

    existing_targets: List[FeeStructure] = (
        FeeStructure.query.filter_by(
            tenant_id=tenant_id, academic_year_id=to_year_id
        ).all()
    )
    target_by_name = {fs.name: fs for fs in existing_targets}

    # FeeStructureClass is unique on (tenant_id, academic_year_id, class_id) —
    # a class can only be linked to ONE structure per year. Track which
    # target-year classes are already linked anywhere so we don't trip the
    # constraint by re-linking them under a different structure.
    classes_already_linked: Dict[str, str] = {
        link.class_id: link.fee_structure_id
        for link in FeeStructureClass.query.filter_by(
            tenant_id=tenant_id, academic_year_id=to_year_id
        ).all()
    }

    structures_created = 0
    structures_reused = 0
    components_created = 0
    class_links_created = 0
    class_links_skipped_unmapped = 0
    class_links_skipped_conflict = 0

    try:
        for src in sources:
            target = target_by_name.get(src.name)
            if target is None:
                target = FeeStructure(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    academic_year_id=to_year_id,
                    name=src.name,
                    is_transport_only=src.is_transport_only,
                    due_date=src.due_date,
                )
                db.session.add(target)
                target_by_name[src.name] = target
                db.session.flush()
                structures_created += 1

                for comp in (src.components or []):
                    db.session.add(
                        FeeComponent(
                            id=str(uuid.uuid4()),
                            tenant_id=tenant_id,
                            fee_structure_id=target.id,
                            name=comp.name,
                            amount=comp.amount,
                            is_optional=comp.is_optional,
                            sort_order=comp.sort_order,
                        )
                    )
                    components_created += 1
            else:
                structures_reused += 1

            src_links: List[FeeStructureClass] = (
                FeeStructureClass.query.filter_by(
                    tenant_id=tenant_id,
                    fee_structure_id=src.id,
                    academic_year_id=from_year_id,
                ).all()
            )
            for link in src_links:
                new_class_id = mapping.get(link.class_id)
                if not new_class_id:
                    class_links_skipped_unmapped += 1
                    continue
                already_linked_to = classes_already_linked.get(new_class_id)
                if already_linked_to == target.id:
                    # Same class already linked to this target — idempotent skip.
                    continue
                if already_linked_to is not None:
                    # Linked to a different structure already; do not steal it.
                    class_links_skipped_conflict += 1
                    continue
                db.session.add(
                    FeeStructureClass(
                        id=str(uuid.uuid4()),
                        tenant_id=tenant_id,
                        fee_structure_id=target.id,
                        class_id=new_class_id,
                        academic_year_id=to_year_id,
                    )
                )
                classes_already_linked[new_class_id] = target.id
                class_links_created += 1

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.exception("finance rollover failed: %s", e)
        return {"success": False, "error": str(e)}

    return {
        "success": True,
        "structures_created": structures_created,
        "structures_reused": structures_reused,
        "components_created": components_created,
        "class_links_created": class_links_created,
        "class_links_skipped_unmapped": class_links_skipped_unmapped,
        "class_links_skipped_conflict": class_links_skipped_conflict,
    }
