"""
School Setup Services

`compute_module_status` — per-module readiness for the wizard dashboard.
`recompute_setup_complete` — derived completeness; flips
`tenants.is_setup_complete` back to false when readiness drops. Never auto-
flips to true: that requires explicit POST /school-setup/complete.

All probes are existence + count queries; no full table loads.
"""
from shared.safe_error import safe_error

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import distinct, func

from core.database import db
from core.models import Tenant


logger = logging.getLogger(__name__)

from modules.academic_programmes.models import AcademicProgramme
from modules.academics.academic_year.models import AcademicYear
from modules.classes.models import Class, ClassSubject
from modules.grades.models import Grade
from modules.school_units.models import SchoolUnit
from modules.subject_contexts.models import SubjectContext


try:
    from modules.academics.backbone.models import AcademicTerm
except ImportError:
    AcademicTerm = None  # type: ignore[assignment]


REQUIRED_MODULES = (
    "units",
    "programmes",
    "grades",
    "academic_year",
    "classes",
    "subjects",
)


def _count_units(tenant_id: str) -> int:
    return (
        SchoolUnit.query.filter_by(tenant_id=tenant_id)
        .filter(SchoolUnit.deleted_at.is_(None))
        .count()
    )


def _count_programmes(tenant_id: str) -> int:
    return (
        AcademicProgramme.query.filter_by(tenant_id=tenant_id)
        .filter(AcademicProgramme.deleted_at.is_(None))
        .count()
    )


def _count_grades(tenant_id: str) -> int:
    return (
        Grade.query.filter_by(tenant_id=tenant_id)
        .filter(Grade.deleted_at.is_(None))
        .count()
    )


def _academic_year_summary(tenant_id: str) -> Dict[str, Any]:
    total = AcademicYear.query.filter_by(tenant_id=tenant_id).count()
    active = (
        AcademicYear.query.filter_by(tenant_id=tenant_id, is_active=True)
        .order_by(AcademicYear.start_date.desc())
        .first()
    )
    return {"count": total, "active_id": active.id if active else None}


def _classes_summary(
    tenant_id: str,
    units_count: int,
    programmes_count: int,
    active_year_id: Optional[str],
) -> Dict[str, Any]:
    total = Class.query.filter_by(tenant_id=tenant_id).count()
    if total == 0 or units_count == 0 or programmes_count == 0:
        return {
            "count": total,
            "coverage_ok": False,
            "active_year_count": 0,
            "uncovered_units": units_count,
            "uncovered_programmes": programmes_count,
        }

    base = db.session.query(Class).filter(Class.tenant_id == tenant_id)
    if active_year_id:
        base = base.filter(Class.academic_year_id == active_year_id)

    active_year_count = base.with_entities(func.count(Class.id)).scalar() or 0

    units_with_classes = (
        base.with_entities(func.count(distinct(Class.school_unit_id)))
        .filter(Class.school_unit_id.isnot(None))
        .scalar()
        or 0
    )
    programmes_with_classes = (
        base.with_entities(func.count(distinct(Class.programme_id)))
        .filter(Class.programme_id.isnot(None))
        .scalar()
        or 0
    )

    coverage_ok = (
        active_year_count > 0
        and units_with_classes >= units_count
        and programmes_with_classes >= programmes_count
    )
    return {
        "count": total,
        "coverage_ok": coverage_ok,
        "active_year_count": active_year_count,
        "uncovered_units": max(0, units_count - units_with_classes),
        "uncovered_programmes": max(0, programmes_count - programmes_with_classes),
    }


def _subjects_summary(
    tenant_id: str,
    classes_count: int,
    active_year_id: Optional[str],
) -> Dict[str, Any]:
    if classes_count == 0:
        return {
            "contexts_defined": False,
            "applied_to_classes": False,
            "missing_pairs": 0,
            "classes_without_subjects": 0,
        }

    class_pair_q = db.session.query(Class.programme_id, Class.grade_id).filter(
        Class.tenant_id == tenant_id,
        Class.programme_id.isnot(None),
        Class.grade_id.isnot(None),
    )
    if active_year_id:
        class_pair_q = class_pair_q.filter(Class.academic_year_id == active_year_id)
    class_pairs = set(class_pair_q.distinct().all())
    if not class_pairs:
        contexts_defined = False
        missing_pairs = 0
    else:
        ctx_pairs = set(
            db.session.query(SubjectContext.programme_id, SubjectContext.grade_id)
            .filter(
                SubjectContext.tenant_id == tenant_id,
                SubjectContext.is_active.is_(True),
                SubjectContext.deleted_at.is_(None),
            )
            .distinct()
            .all()
        )
        missing = class_pairs - ctx_pairs
        missing_pairs = len(missing)
        contexts_defined = missing_pairs == 0

    if active_year_id:
        active_class_ids = [
            row[0]
            for row in db.session.query(Class.id)
            .filter(
                Class.tenant_id == tenant_id,
                Class.academic_year_id == active_year_id,
            )
            .all()
        ]
        if active_class_ids:
            classes_with_subjects = (
                db.session.query(func.count(distinct(ClassSubject.class_id)))
                .filter(
                    ClassSubject.tenant_id == tenant_id,
                    ClassSubject.class_id.in_(active_class_ids),
                    ClassSubject.deleted_at.is_(None),
                    ClassSubject.status == "active",
                )
                .scalar()
                or 0
            )
            classes_without_subjects = max(0, len(active_class_ids) - classes_with_subjects)
        else:
            classes_without_subjects = 0
    else:
        classes_with_subjects = (
            db.session.query(func.count(distinct(ClassSubject.class_id)))
            .filter(
                ClassSubject.tenant_id == tenant_id,
                ClassSubject.deleted_at.is_(None),
                ClassSubject.status == "active",
            )
            .scalar()
            or 0
        )
        classes_without_subjects = max(0, classes_count - classes_with_subjects)
    applied_to_classes = classes_without_subjects == 0

    return {
        "contexts_defined": contexts_defined,
        "applied_to_classes": applied_to_classes,
        "missing_pairs": missing_pairs,
        "classes_without_subjects": classes_without_subjects,
    }


def _terms_count(tenant_id: str) -> int:
    if AcademicTerm is None:
        return 0
    q = AcademicTerm.query.filter_by(tenant_id=tenant_id)
    if hasattr(AcademicTerm, "deleted_at"):
        q = q.filter(AcademicTerm.deleted_at.is_(None))
    return q.count()


def _count_subject_offerings(tenant_id: str) -> int:
    """Rows in subject_contexts (programme × grade × subject lines)."""
    return (
        db.session.query(func.count(SubjectContext.id))
        .filter(
            SubjectContext.tenant_id == tenant_id,
            SubjectContext.is_active.is_(True),
            SubjectContext.deleted_at.is_(None),
        )
        .scalar()
        or 0
    )


def compute_module_status(tenant_id: str) -> Dict[str, Any]:
    """Per-module readiness payload. No DB writes."""
    units_count = _count_units(tenant_id)
    programmes_count = _count_programmes(tenant_id)
    grades_count = _count_grades(tenant_id)
    year = _academic_year_summary(tenant_id)
    classes = _classes_summary(tenant_id, units_count, programmes_count, year["active_id"])
    subjects = _subjects_summary(tenant_id, classes["count"], year["active_id"])
    terms_count = _terms_count(tenant_id)
    subject_offerings_count = _count_subject_offerings(tenant_id)

    units_ready = units_count > 0
    programmes_ready = programmes_count > 0
    grades_ready = grades_count > 0
    year_ready = year["count"] > 0
    classes_ready = classes["count"] > 0 and classes["coverage_ok"]
    subjects_ready = subjects["contexts_defined"] and subjects["applied_to_classes"]

    classes_blockers = []
    if classes["count"] == 0:
        classes_blockers.append("create_at_least_one_class")
    else:
        if year["active_id"] and classes["active_year_count"] == 0:
            classes_blockers.append("no_classes_in_active_academic_year")
        if classes["uncovered_units"] > 0:
            classes_blockers.append(
                f"{classes['uncovered_units']}_units_have_no_classes"
            )
        if classes["uncovered_programmes"] > 0:
            classes_blockers.append(
                f"{classes['uncovered_programmes']}_programmes_have_no_classes"
            )

    subjects_blockers = []
    if classes["count"] == 0:
        subjects_blockers.append("create_classes_first")
    else:
        if not subjects["contexts_defined"]:
            subjects_blockers.append(
                f"subject_offerings_missing_for_{subjects['missing_pairs']}_programme_grade_pairs"
            )
        if not subjects["applied_to_classes"]:
            subjects_blockers.append(
                f"{subjects['classes_without_subjects']}_classes_without_subjects"
            )

    return {
        "units": {
            "ready": units_ready,
            "count": units_count,
            "blockers": [] if units_ready else ["add_at_least_one_unit"],
        },
        "programmes": {
            "ready": programmes_ready,
            "count": programmes_count,
            "blockers": [] if programmes_ready else ["add_at_least_one_programme"],
        },
        "grades": {
            "ready": grades_ready,
            "count": grades_count,
            "is_full_ladder": grades_count >= 1,
            "blockers": [] if grades_ready else ["add_at_least_one_grade"],
        },
        "academic_year": {
            "ready": year_ready,
            "count": year["count"],
            "active_id": year["active_id"],
            "blockers": [] if year_ready else ["create_an_academic_year"],
        },
        "classes": {
            "ready": classes_ready,
            "count": classes["count"],
            "coverage_ok": classes["coverage_ok"],
            "active_year_count": classes["active_year_count"],
            "blockers": classes_blockers,
        },
        "subjects": {
            "ready": subjects_ready,
            "count": subject_offerings_count,
            "contexts_defined": subjects["contexts_defined"],
            "applied_to_classes": subjects["applied_to_classes"],
            "missing_pairs": subjects["missing_pairs"],
            "classes_without_subjects": subjects["classes_without_subjects"],
            "blockers": subjects_blockers,
        },
        "terms": {
            "ready": terms_count > 0,
            "count": terms_count,
            "optional": True,
            "blockers": [],
        },
    }


def derive_ready(status: Dict[str, Any]) -> bool:
    return all(status[m]["ready"] for m in REQUIRED_MODULES)


def _read_tenant(tenant_id: str) -> Optional[Tenant]:
    return Tenant.query.filter_by(id=tenant_id).first()


def recompute_setup_complete(
    tenant_id: str, status: Optional[Dict[str, Any]] = None
) -> bool:
    """Flip stored flag back to false on drift. Never auto-flips to true."""
    if status is None:
        status = compute_module_status(tenant_id)
    derived = derive_ready(status)

    tenant = _read_tenant(tenant_id)
    if tenant is None:
        return derived

    if tenant.is_setup_complete and not derived:
        tenant.is_setup_complete = False
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
    return derived


def run_complete_setup(
    tenant_id: str, actor_user_id: Optional[str] = None
) -> Dict[str, Any]:
    """Atomic complete: lock the tenant row, validate, flip flag, commit.

    Records telemetry: `setup_completed_at`, `setup_completed_by`, and
    `setup_reconfirmed_at` (only on a re-completion after first time).
    """
    try:
        with db.session.begin_nested():
            tenant = (
                db.session.query(Tenant)
                .filter(Tenant.id == tenant_id)
                .with_for_update()
                .first()
            )
            if tenant is None:
                return {"success": False, "error": "Tenant not found", "code": "NotFound"}

            status = compute_module_status(tenant_id)
            if not derive_ready(status):
                unmet = [m for m in REQUIRED_MODULES if not status[m]["ready"]]
                logger.info(
                    "school_setup.complete.failed",
                    extra={
                        "tenant_id": tenant_id,
                        "actor_user_id": actor_user_id,
                        "blockers": {m: status[m]["blockers"] for m in unmet},
                    },
                )
                return {
                    "success": False,
                    "error": "Setup is incomplete.",
                    "code": "ValidationError",
                    "details": {m: status[m]["blockers"] for m in unmet},
                }

            now = datetime.now(timezone.utc)
            first_completion = tenant.setup_completed_at is None
            tenant.is_setup_complete = True
            tenant.setup_completed_at = now
            tenant.setup_completed_by = actor_user_id
            if not first_completion:
                tenant.setup_reconfirmed_at = now
        db.session.commit()
        try:
            from modules.school_setup.models import SetupModuleEvent
            event_type = "setup_complete" if first_completion else "setup_reconfirmed"
            event = SetupModuleEvent(
                tenant_id=tenant_id,
                module="overall",
                event=event_type,
                actor_user_id=actor_user_id,
            )
            db.session.add(event)
            db.session.commit()
        except Exception:
            logger.warning("school_setup.event_log.failed", extra={"tenant_id": tenant_id})
            # Non-fatal — do not surface to caller
        logger.info(
            "school_setup.complete.success",
            extra={
                "tenant_id": tenant_id,
                "actor_user_id": actor_user_id,
                "first_completion": first_completion,
            },
        )
        return {
            "success": True,
            "is_setup_complete": True,
            "first_completion": first_completion,
        }
    except Exception as e:
        db.session.rollback()
        logger.exception(
            "school_setup.complete.error",
            extra={"tenant_id": tenant_id, "actor_user_id": actor_user_id},
        )
        return {"success": False, "error": safe_error(e), "code": "UpdateError"}


def get_status_payload(tenant_id: str) -> Dict[str, Any]:
    """Status response for GET /api/school-setup/status. Recomputes on read."""
    status = compute_module_status(tenant_id)
    derived = derive_ready(status)

    tenant = _read_tenant(tenant_id)
    is_complete = bool(getattr(tenant, "is_setup_complete", False)) if tenant else False

    if tenant is not None and is_complete and not derived:
        tenant.is_setup_complete = False
        try:
            db.session.commit()
            is_complete = False
        except Exception:
            db.session.rollback()

    regressed = []
    if is_complete and not derived:
        regressed = [m for m in REQUIRED_MODULES if not status[m]["ready"]]
    elif not is_complete and tenant and getattr(tenant, "setup_completed_at", None):
        regressed = [m for m in REQUIRED_MODULES if not status[m]["ready"]]

    status["overall"] = {
        "ready": derived,
        "is_setup_complete": is_complete,
        "needs_reconfirm": derived and not is_complete,
        "regressed_modules": regressed,
    }
    return status
