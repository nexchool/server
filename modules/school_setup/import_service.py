"""
CSV Import Service

Accepts a CSV with the columns:
    unit_code, programme_code, grade, section, subject?, periods?

Per-row validation: invalid rows are reported in `errors[]` with their
row number; valid rows are inserted, skipping duplicates via the same
structural unique index used by bulk_create_classes. Each row insert is
wrapped in a savepoint so a single bad row never poisons the batch.

If `subject` is provided, the matching active Subject (per tenant) is
attached to the class via class_subjects (uses default weekly_periods=5
or the value in the `periods` column when present).
"""

from __future__ import annotations

import csv
import io
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.exc import IntegrityError

from core.database import db
from modules.academic_programmes.models import AcademicProgramme
from modules.academics.academic_year.models import AcademicYear
from modules.classes.models import Class, ClassSubject
from modules.grades.models import Grade
from modules.school_units.models import SchoolUnit
from modules.subjects.models import Subject


REQUIRED_HEADERS = ("unit_code", "programme_code", "grade", "section")
OPTIONAL_HEADERS = ("subject", "periods")


def _parse_csv(file_storage) -> Tuple[Optional[List[Dict[str, str]]], Optional[str]]:
    try:
        raw = file_storage.read()
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(raw))
        if not reader.fieldnames:
            return None, "CSV is empty"
        missing = [h for h in REQUIRED_HEADERS if h not in reader.fieldnames]
        if missing:
            return None, f"Missing required columns: {', '.join(missing)}"
        return [dict(row) for row in reader], None
    except UnicodeDecodeError:
        return None, "CSV must be UTF-8 encoded"
    except Exception as e:
        return None, f"Could not parse CSV: {e}"


def _coerce_periods(value: Any, default: int = 5) -> int:
    if value is None or value == "":
        return default
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    if n < 1 or n > 40:
        return default
    return n


def import_csv(
    tenant_id: str,
    file_storage,
    *,
    academic_year_id: Optional[str],
) -> Dict[str, Any]:
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}
    if not academic_year_id:
        return {"success": False, "error": "academic_year_id is required"}
    if not AcademicYear.query.filter_by(id=academic_year_id, tenant_id=tenant_id).first():
        return {"success": False, "error": "Invalid academic_year_id for this tenant"}

    rows, parse_err = _parse_csv(file_storage)
    if parse_err is not None:
        return {"success": False, "error": parse_err}

    units = {
        u.code.strip().lower(): u
        for u in SchoolUnit.query.filter_by(tenant_id=tenant_id)
        .filter(SchoolUnit.deleted_at.is_(None))
        .all()
    }
    programmes = {
        p.code.strip().lower(): p
        for p in AcademicProgramme.query.filter_by(tenant_id=tenant_id)
        .filter(AcademicProgramme.deleted_at.is_(None))
        .all()
    }
    grades = {
        g.name.strip().lower(): g
        for g in Grade.query.filter_by(tenant_id=tenant_id)
        .filter(Grade.deleted_at.is_(None))
        .all()
    }
    subjects = {
        s.code.strip().lower(): s
        for s in Subject.query.filter(
            Subject.tenant_id == tenant_id,
            Subject.deleted_at.is_(None),
            Subject.is_active.is_(True),
            Subject.code.isnot(None),
        ).all()
    }
    subjects_by_name = {
        s.name.strip().lower(): s
        for s in Subject.query.filter(
            Subject.tenant_id == tenant_id,
            Subject.deleted_at.is_(None),
            Subject.is_active.is_(True),
        ).all()
    }

    created_rows: List[Dict[str, Any]] = []
    skipped_rows: List[Dict[str, Any]] = []
    error_rows: List[Dict[str, Any]] = []
    subject_links_created = 0
    subject_links_skipped = 0

    for idx, raw in enumerate(rows, start=2):  # row 1 is header
        unit_code = (raw.get("unit_code") or "").strip()
        programme_code = (raw.get("programme_code") or "").strip()
        grade_name = (raw.get("grade") or "").strip()
        section = (raw.get("section") or "").strip()
        subject_token = (raw.get("subject") or "").strip()
        periods = _coerce_periods(raw.get("periods"))

        if not (unit_code and programme_code and grade_name and section):
            error_rows.append({"row_number": idx, "error": "missing required column value"})
            continue

        unit = units.get(unit_code.lower())
        if not unit:
            error_rows.append({"row_number": idx, "error": f"unknown unit_code: {unit_code}"})
            continue
        programme = programmes.get(programme_code.lower())
        if not programme:
            error_rows.append({"row_number": idx, "error": f"unknown programme_code: {programme_code}"})
            continue
        grade = grades.get(grade_name.lower())
        if not grade:
            error_rows.append({"row_number": idx, "error": f"unknown grade: {grade_name}"})
            continue

        existing_class = Class.query.filter_by(
            tenant_id=tenant_id,
            school_unit_id=unit.id,
            programme_id=programme.id,
            grade_id=grade.id,
            section=section,
            academic_year_id=academic_year_id,
        ).first()

        if existing_class:
            class_id = existing_class.id
            skipped_rows.append({"row_number": idx, "class_id": class_id, "reason": "already_exists"})
        else:
            new_cls = Class(
                tenant_id=tenant_id,
                name=f"{grade.name} {section}".strip(),
                section=section,
                academic_year_id=academic_year_id,
                school_unit_id=unit.id,
                programme_id=programme.id,
                grade_id=grade.id,
            )
            try:
                with db.session.begin_nested():
                    db.session.add(new_cls)
                class_id = new_cls.id
                created_rows.append({"row_number": idx, "class_id": class_id})
            except IntegrityError as e:
                msg = str(getattr(e, "orig", e)).lower()
                if "uq_classes_unit_programme_grade_section_year" in msg:
                    existing_class = Class.query.filter_by(
                        tenant_id=tenant_id,
                        school_unit_id=unit.id,
                        programme_id=programme.id,
                        grade_id=grade.id,
                        section=section,
                        academic_year_id=academic_year_id,
                    ).first()
                    class_id = existing_class.id if existing_class else None
                    skipped_rows.append({"row_number": idx, "class_id": class_id, "reason": "already_exists"})
                else:
                    error_rows.append({"row_number": idx, "error": "db_error: constraint violation"})
                    continue

        if subject_token and class_id:
            subject = (
                subjects.get(subject_token.lower())
                or subjects_by_name.get(subject_token.lower())
            )
            if not subject:
                error_rows.append({"row_number": idx, "error": f"unknown subject: {subject_token}"})
                continue
            existing_link = ClassSubject.query.filter(
                ClassSubject.tenant_id == tenant_id,
                ClassSubject.class_id == class_id,
                ClassSubject.subject_id == subject.id,
                ClassSubject.deleted_at.is_(None),
                ClassSubject.status == "active",
            ).first()
            if existing_link:
                subject_links_skipped += 1
            else:
                cs = ClassSubject(
                    tenant_id=tenant_id,
                    class_id=class_id,
                    subject_id=subject.id,
                    weekly_periods=periods,
                )
                try:
                    with db.session.begin_nested():
                        db.session.add(cs)
                    subject_links_created += 1
                except IntegrityError:
                    subject_links_skipped += 1

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return {"success": False, "error": str(e)}

    try:
        from .services import recompute_setup_complete
        recompute_setup_complete(tenant_id)
    except Exception:
        pass

    return {
        "success": True,
        "created": created_rows,
        "skipped": skipped_rows,
        "failed": [
            {**err, "row_number": err.get("row_number", i + 2)}
            for i, err in enumerate(error_rows)
        ],
        "created_count": len(created_rows),
        "skipped_count": len(skipped_rows),
        "failed_count": len(error_rows),
        "subject_links_created": subject_links_created,
        "subject_links_skipped": subject_links_skipped,
    }
