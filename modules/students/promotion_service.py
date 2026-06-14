"""
Academic year promotion: preview counts and execute batch promotion.

Uses StudentClassEnrollment as source of truth; syncs students.class_id / academic_year_id.
"""

from __future__ import annotations
from shared.safe_error import safe_error

import logging
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from core.database import db
from core.tenant import get_tenant_id
from modules.academics.academic_year.models import AcademicYear
from modules.academics.backbone.models import StudentClassEnrollment
from modules.classes.models import Class
from modules.students.models import Student, StudentPromotionBatch

logger = logging.getLogger(__name__)

GRADUATED = "GRADUATED"


class PromotionPlacement(NamedTuple):
    """
    One row to promote from the from-year.

    enrollment is None when the student has class_id/year on the profile but no
    StudentClassEnrollment row for that year (legacy data).
    """

    enrollment: Optional[StudentClassEnrollment]
    student_id: str
    class_id: str


def _placements_for_from_year(tenant_id: str, from_year_id: str) -> List[PromotionPlacement]:
    """
    Prefer StudentClassEnrollment (is_current, matching academic_year_id).
    Also include students whose Class is in from_year_id but who lack such a row.
    """
    enrollments: List[StudentClassEnrollment] = (
        StudentClassEnrollment.query.filter_by(
            tenant_id=tenant_id,
            academic_year_id=from_year_id,
            is_current=True,
        )
        .order_by(StudentClassEnrollment.student_id)
        .all()
    )
    by_student: Dict[str, PromotionPlacement] = {}
    for enr in enrollments:
        by_student[enr.student_id] = PromotionPlacement(
            enrollment=enr,
            student_id=enr.student_id,
            class_id=str(enr.class_id).strip(),
        )

    legacy_students = (
        Student.query.join(Class, Student.class_id == Class.id)
        .filter(
            Student.tenant_id == tenant_id,
            Class.academic_year_id == from_year_id,
            Student.class_id.isnot(None),
        )
        .all()
    )
    for st in legacy_students:
        if st.id in by_student:
            continue
        by_student[st.id] = PromotionPlacement(
            enrollment=None,
            student_id=st.id,
            class_id=str(st.class_id).strip(),
        )

    return sorted(by_student.values(), key=lambda p: p.student_id)


def _normalize_mapping(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("class_mapping must be an object")
    out: Dict[str, Any] = {}
    for k, v in raw.items():
        key = str(k).strip()
        if isinstance(v, str):
            out[key] = v.strip()
        else:
            out[key] = v
    return out


def _parse_bool_opt(value: Any, default: bool) -> bool:
    """Coerce JSON/body values; missing → default (backward compatible)."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _is_graduated(val: Any) -> bool:
    return isinstance(val, str) and val.strip().upper() == GRADUATED


def _is_leaving_student(student: Optional[Student]) -> bool:
    if not student or not student.student_status:
        return False
    return student.student_status.strip().lower() == "leaving"


def _is_fail_result_student(student: Optional[Student]) -> bool:
    if not student or not student.academic_result:
        return False
    return str(student.academic_result).strip().lower() == "fail"


def _should_skip_student(
    student: Optional[Student],
    *,
    exclude_leaving: bool,
    include_failed: bool,
) -> bool:
    if exclude_leaving and _is_leaving_student(student):
        return True
    if not include_failed and _is_fail_result_student(student):
        return True
    return False


def _effective_class_grade(cls: Optional[Class]) -> Optional[int]:
    if not cls:
        return None
    if cls.grade_level is not None:
        return int(cls.grade_level)
    name = (cls.name or "").strip()
    m1 = re.search(
        r"(?:^|\s)(?:grade|class|std|standard)\s*[:\-]?\s*(\d{1,2})(?:\s|$)",
        name,
        re.I,
    )
    if m1:
        return int(m1.group(1))
    m2 = re.match(r"^(\d{1,2})\s*$", name)
    if m2:
        return int(m2.group(1))
    m3 = re.search(r"(\d{1,2})", name)
    return int(m3.group(1)) if m3 else None


def _classify_promoted_vs_repeated(
    from_cls: Optional[Class], to_cls: Optional[Class]
) -> Tuple[str, str]:
    """
    Returns ("promoted", reason) | ("repeated", reason) for a class→class move.
    """
    fg = _effective_class_grade(from_cls)
    tg = _effective_class_grade(to_cls)
    if fg is not None and tg is not None:
        if tg > fg:
            return "promoted", "grade_up"
        if tg == fg:
            return "repeated", "same_grade"
        return "repeated", "grade_down_or_hold"
    return "promoted", "grade_unknown"


def _class_target_kind(
    tenant_id: str, to_year_id: str, raw_val: Any
) -> Tuple[str, Optional[str]]:
    """
    Returns ("graduated", None) | ("class", class_id) | ("invalid", None)
    """
    if _is_graduated(raw_val):
        return "graduated", None
    if raw_val is None or raw_val == "":
        return "invalid", None
    cid = str(raw_val).strip()
    cls = Class.query.filter_by(id=cid, tenant_id=tenant_id).first()
    if not cls or cls.academic_year_id != to_year_id:
        return "invalid", None
    return "class", cid


def analyze_promotion(
    tenant_id: str,
    from_year_id: str,
    to_year_id: str,
    class_mapping: Dict[str, Any],
    *,
    exclude_leaving: bool = False,
    include_failed: bool = True,
) -> Dict[str, Any]:
    """
    Load current enrollments for from_year_id and compute preview summary.
    Does not mutate the database.
    """
    if not from_year_id or not to_year_id:
        return {"success": False, "error": "from_year_id and to_year_id are required"}
    if from_year_id == to_year_id:
        return {"success": False, "error": "from_year_id and to_year_id must differ"}

    ay_from = AcademicYear.query.filter_by(id=from_year_id, tenant_id=tenant_id).first()
    ay_to = AcademicYear.query.filter_by(id=to_year_id, tenant_id=tenant_id).first()
    if not ay_from:
        return {"success": False, "error": "from_year_id not found for this tenant"}
    if not ay_to:
        return {"success": False, "error": "to_year_id not found for this tenant"}

    try:
        mapping = _normalize_mapping(class_mapping)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    placements = _placements_for_from_year(tenant_id, from_year_id)
    legacy_placement_only = sum(1 for p in placements if p.enrollment is None)

    student_ids = [p.student_id for p in placements]
    students_by_id: Dict[str, Student] = {}
    if student_ids:
        students_by_id = {
            s.id: s
            for s in Student.query.filter(
                Student.tenant_id == tenant_id,
                Student.id.in_(student_ids),
            ).all()
        }

    class_cache: Dict[str, Optional[Class]] = {}

    def get_class(cid: str) -> Optional[Class]:
        if cid in class_cache:
            return class_cache[cid]
        c = Class.query.filter_by(id=cid, tenant_id=tenant_id).first()
        class_cache[cid] = c
        return c

    skipped = 0
    eligible_student_ids: List[str] = []

    for pl in placements:
        st = students_by_id.get(pl.student_id)
        if _should_skip_student(
            st,
            exclude_leaving=exclude_leaving,
            include_failed=include_failed,
        ):
            skipped += 1
            continue
        eligible_student_ids.append(pl.student_id)

    blocked = 0
    if eligible_student_ids:
        blocked = (
            StudentClassEnrollment.query.filter(
                StudentClassEnrollment.tenant_id == tenant_id,
                StudentClassEnrollment.student_id.in_(eligible_student_ids),
                StudentClassEnrollment.academic_year_id == to_year_id,
                StudentClassEnrollment.is_current.is_(True),
            ).count()
        )

    promoted = 0
    repeated = 0
    graduated = 0
    unmapped = 0
    unmapped_class_ids: List[str] = []

    for pl in placements:
        st = students_by_id.get(pl.student_id)
        if _should_skip_student(
            st,
            exclude_leaving=exclude_leaving,
            include_failed=include_failed,
        ):
            continue

        key = pl.class_id
        if key not in mapping:
            unmapped += 1
            if key not in unmapped_class_ids:
                unmapped_class_ids.append(key)
            continue
        kind, next_cid = _class_target_kind(tenant_id, to_year_id, mapping[key])
        if kind == "graduated":
            graduated += 1
        elif kind == "class" and next_cid:
            from_cls = get_class(key)
            to_cls = get_class(next_cid)
            branch, _ = _classify_promoted_vs_repeated(from_cls, to_cls)
            if branch == "promoted":
                promoted += 1
            else:
                repeated += 1
        else:
            unmapped += 1
            if key not in unmapped_class_ids:
                unmapped_class_ids.append(key)

    from_year_class_ids = {
        c.id
        for c in Class.query.filter_by(
            tenant_id=tenant_id, academic_year_id=from_year_id
        ).all()
    }
    unknown_keys = [k for k in mapping if k not in from_year_class_ids]

    total = len(placements)
    promotable = promoted + repeated

    return {
        "success": True,
        "filters": {
            "exclude_leaving": exclude_leaving,
            "include_failed": include_failed,
        },
        "summary": {
            "total_enrollments": total,
            "legacy_placement_only_rows": legacy_placement_only,
            "skipped": skipped,
            "promoted": promoted,
            "repeated": repeated,
            "graduated": graduated,
            "unmapped": unmapped,
            "blocked_double_promotion": blocked,
            "unused_mapping_keys": len(unknown_keys),
            # Backward-compatible aggregate (class targets only, incl. repeat year).
            "promotable": promotable,
        },
        "unmapped_source_class_ids": unmapped_class_ids,
        "unused_mapping_keys": unknown_keys,
    }


def preview_promotion(
    from_year_id: str,
    to_year_id: str,
    class_mapping: Any,
    *,
    exclude_leaving: bool = False,
    include_failed: bool = True,
) -> Dict[str, Any]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}
    if not isinstance(class_mapping, dict):
        return {"success": False, "error": "class_mapping must be an object"}
    return analyze_promotion(
        tenant_id,
        from_year_id,
        to_year_id,
        class_mapping,
        exclude_leaving=exclude_leaving,
        include_failed=include_failed,
    )


def execute_promotion(
    from_year_id: str,
    to_year_id: str,
    class_mapping: Any,
    *,
    user_id: Optional[str] = None,
    exclude_leaving: bool = False,
    include_failed: bool = True,
) -> Dict[str, Any]:
    """
    Run promotion in a single DB transaction. Persists StudentPromotionBatch on success.
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}
    if not isinstance(class_mapping, dict):
        return {"success": False, "error": "class_mapping must be an object"}

    analysis = analyze_promotion(
        tenant_id,
        from_year_id,
        to_year_id,
        class_mapping,
        exclude_leaving=exclude_leaving,
        include_failed=include_failed,
    )
    if not analysis.get("success"):
        return analysis

    summary = analysis["summary"]
    if summary["blocked_double_promotion"] > 0:
        return {
            "success": False,
            "error": (
                f"{summary['blocked_double_promotion']} student(s) already have a current "
                "enrollment in the target year (double promotion blocked)"
            ),
            "summary": summary,
            "filters": analysis.get("filters"),
        }
    if summary["unmapped"] > 0:
        return {
            "success": False,
            "error": "Cannot promote: unmapped or invalid class targets remain. Fix class_mapping.",
            "summary": summary,
            "unmapped_source_class_ids": analysis.get("unmapped_source_class_ids"),
            "filters": analysis.get("filters"),
        }

    try:
        mapping = _normalize_mapping(class_mapping)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    placements = _placements_for_from_year(tenant_id, from_year_id)

    student_ids = [p.student_id for p in placements]
    students_by_id: Dict[str, Student] = {}
    if student_ids:
        students_by_id = {
            s.id: s
            for s in Student.query.filter(
                Student.tenant_id == tenant_id,
                Student.id.in_(student_ids),
            ).all()
        }

    class_cache: Dict[str, Optional[Class]] = {}

    def get_class(cid: str) -> Optional[Class]:
        if cid in class_cache:
            return class_cache[cid]
        c = Class.query.filter_by(id=cid, tenant_id=tenant_id).first()
        class_cache[cid] = c
        return c

    batch_id = str(uuid.uuid4())
    logger.info(
        "promotion batch %s: starting tenant=%s from_year=%s to_year=%s placements=%s",
        batch_id,
        tenant_id,
        from_year_id,
        to_year_id,
        len(placements),
    )

    today = datetime.utcnow().date()
    promoted_count = 0
    repeated_count = 0
    graduated_count = 0
    skipped_count = 0
    processed_count = 0

    try:
        for pl in placements:
            st = students_by_id.get(pl.student_id)
            if _should_skip_student(
                st,
                exclude_leaving=exclude_leaving,
                include_failed=include_failed,
            ):
                skipped_count += 1
                continue

            key = pl.class_id
            raw_target = mapping[key]
            kind, next_class_id = _class_target_kind(tenant_id, to_year_id, raw_target)

            promoted_from_id: Optional[str] = None
            if pl.enrollment:
                enr = pl.enrollment
                enr.is_current = False
                enr.enrollment_status = "promoted"
                enr.ended_on = today
                promoted_from_id = enr.id

            student = Student.query.filter_by(id=pl.student_id, tenant_id=tenant_id).first()
            if not student:
                raise RuntimeError(f"Student {pl.student_id} not found")

            processed_count += 1

            if kind == "graduated":
                graduated_count += 1
                student.class_id = None
                student.academic_year_id = to_year_id
            elif kind == "class" and next_class_id:
                from_cls = get_class(key)
                to_cls = get_class(next_class_id)
                branch, _ = _classify_promoted_vs_repeated(from_cls, to_cls)
                if branch == "promoted":
                    promoted_count += 1
                else:
                    repeated_count += 1
                new_enr = StudentClassEnrollment(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    student_id=student.id,
                    class_id=next_class_id,
                    academic_year_id=to_year_id,
                    enrollment_status="active",
                    is_current=True,
                    started_on=None,
                    ended_on=None,
                    promoted_from_enrollment_id=promoted_from_id,
                )
                db.session.add(new_enr)
                student.class_id = next_class_id
                student.academic_year_id = to_year_id
            else:
                raise RuntimeError(f"Invalid promotion target for class {key}")

        final_summary = {
            **summary,
            "filters": analysis.get("filters"),
            "processed": processed_count,
            "skipped_in_batch": skipped_count,
            "promoted_to_class": promoted_count,
            "repeated_to_class": repeated_count,
            "marked_graduated": graduated_count,
        }

        batch = StudentPromotionBatch(
            id=batch_id,
            tenant_id=tenant_id,
            from_academic_year_id=from_year_id,
            to_academic_year_id=to_year_id,
            status="completed",
            summary=final_summary,
            class_mapping_snapshot=mapping,
            created_by_user_id=user_id,
        )
        db.session.add(batch)

        db.session.commit()
        logger.info(
            "promotion batch %s: completed promoted=%s repeated=%s graduated=%s skipped=%s",
            batch_id,
            promoted_count,
            repeated_count,
            graduated_count,
            skipped_count,
        )
        return {
            "success": True,
            "promotion_batch_id": batch_id,
            "summary": final_summary,
            "filters": analysis.get("filters"),
            "batch": batch.to_dict(),
        }
    except Exception as e:
        db.session.rollback()
        logger.exception("promotion batch %s: failed %s", batch_id, e)
        return {"success": False, "error": safe_error(e), "promotion_batch_id": batch_id}


def parse_promotion_filters(data: Dict[str, Any]) -> Tuple[bool, bool]:
    """From JSON body: defaults preserve legacy behavior."""
    exclude_leaving = _parse_bool_opt(data.get("exclude_leaving"), False)
    include_failed = _parse_bool_opt(data.get("include_failed"), True)
    return exclude_leaving, include_failed
