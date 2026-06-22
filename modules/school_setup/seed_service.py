"""School onboarding seed service.

Config-driven, idempotent seeding of a tenant's academic foundation:
units -> programmes -> grades -> academic_year -> subjects -> subject_contexts
-> classes -> class_subjects.

Design notes:
- Logic lives here (unit-testable); scripts/seed_school.py is a thin CLI wrapper.
- Every _ensure_* helper is query-first (create-if-missing), so seed_school is
  safe to re-run. Natural keys: unit.code, programme.code, grade.name,
  academic_year.name, subject.code.
- Classes are created via the existing bulk_generate_classes service (it sets the
  unit/programme/grade FKs, parses streams, and is itself idempotent).
- class_subjects are derived granularly from each class's (programme, grade)
  SubjectContext rows -- never the blunt every-subject-to-every-class approach.
- Mirrors the readiness checks in services.py so get_status_payload /
  run_complete_setup can verify and flip tenant.is_setup_complete at the end.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime

from core.database import db
from modules.academic_programmes.models import AcademicProgramme
from modules.academics.academic_year.models import AcademicYear
from modules.classes.models import Class, ClassSubject
from modules.grades.models import Grade
from modules.mediums.models import Medium
from modules.school_units.models import SchoolUnit
from modules.subject_contexts.models import SubjectContext
from modules.subjects.models import Subject

from .bulk_generator_service import bulk_generate_classes
from .services import get_status_payload, run_complete_setup

logger = logging.getLogger(__name__)


class SeedValidationError(Exception):
    """Raised when the config fails pre-flight validation (no writes performed)."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _validate_config(config: dict) -> list[str]:
    """Structural validation only — no DB. Returns a list of human-readable errors."""
    errors: list[str] = []
    unit_codes = {u["code"] for u in config.get("units", [])}
    prog_codes = {p["code"] for p in config.get("programmes", [])}
    grade_names = {str(g["name"]) for g in config.get("grades", [])}
    subject_codes = {s["code"] for s in config.get("subjects", [])}

    if not config.get("academic_year"):
        errors.append("academic_year is required")
    if not unit_codes:
        errors.append("at least one unit is required")
    if not prog_codes:
        errors.append("at least one programme is required")
    if not grade_names:
        errors.append("at least one grade is required")

    offered_pairs: set[tuple[str, str]] = set()
    for off in config.get("offerings", []):
        if off["programme"] not in prog_codes:
            errors.append(f"offering references unknown programme '{off['programme']}'")
        if str(off["grade"]) not in grade_names:
            errors.append(f"offering references unknown grade '{off['grade']}'")
        for s in off.get("subjects", []):
            if s["code"] not in subject_codes:
                errors.append(f"offering references unknown subject '{s['code']}'")
        offered_pairs.add((off["programme"], str(off["grade"])))

    for cl in config.get("classes", []):
        if cl["unit"] not in unit_codes:
            errors.append(f"class references unknown unit '{cl['unit']}'")
        if cl["programme"] not in prog_codes:
            errors.append(f"class references unknown programme '{cl['programme']}'")
        if str(cl["grade"]) not in grade_names:
            errors.append(f"class references unknown grade '{cl['grade']}'")
        if (cl["programme"], str(cl["grade"])) not in offered_pairs:
            errors.append(
                f"class ({cl['unit']}/{cl['programme']}/grade {cl['grade']}) has no "
                f"subject offering for (programme {cl['programme']}, grade {cl['grade']})"
            )
    return errors


def _dry_run_plan(config: dict) -> dict:
    return {
        "units": len(config.get("units", [])),
        "programmes": len(config.get("programmes", [])),
        "grades": len(config.get("grades", [])),
        "academic_year": config["academic_year"]["name"],
        "subjects": len(config.get("subjects", [])),
        "offering_lines": sum(len(o.get("subjects", [])) for o in config.get("offerings", [])),
        "class_cells": len(config.get("classes", [])),
        "sections_total": sum(len(c.get("sections", [])) for c in config.get("classes", [])),
    }


# --------------------------------------------------------------------------- #
# Idempotent upsert helpers (query-first, natural-key keyed)
# --------------------------------------------------------------------------- #
def _parse_date(value) -> date:
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def _resolve_medium_id(tenant_id: str, medium_str):
    """Best-effort link to an existing Medium by name then code; else None."""
    if not medium_str:
        return None
    m = Medium.query.filter_by(tenant_id=tenant_id, name=medium_str).first()
    if not m:
        m = Medium.query.filter_by(tenant_id=tenant_id, code=medium_str).first()
    return m.id if m else None


def _ensure_unit(tenant_id, row):
    unit = (
        SchoolUnit.query.filter_by(tenant_id=tenant_id, code=row["code"])
        .filter(SchoolUnit.deleted_at.is_(None))
        .first()
    )
    if unit:
        return unit, False
    unit = SchoolUnit(
        id=str(uuid.uuid4()), tenant_id=tenant_id, name=row["name"], code=row["code"]
    )
    db.session.add(unit)
    db.session.flush()
    return unit, True


def _ensure_programme(tenant_id, row):
    prog = (
        AcademicProgramme.query.filter_by(tenant_id=tenant_id, code=row["code"])
        .filter(AcademicProgramme.deleted_at.is_(None))
        .first()
    )
    if prog:
        return prog, False
    medium_str = row.get("medium")
    prog = AcademicProgramme(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=row["name"],
        board=row["board"],
        code=row["code"],
        medium=medium_str,
        medium_id=_resolve_medium_id(tenant_id, medium_str),
    )
    db.session.add(prog)
    db.session.flush()
    return prog, True


def _ensure_grade(tenant_id, row):
    name = str(row["name"])
    grade = (
        Grade.query.filter_by(tenant_id=tenant_id, name=name)
        .filter(Grade.deleted_at.is_(None))
        .first()
    )
    if grade:
        return grade, False
    grade = Grade(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=name,
        sequence=int(row.get("sequence", 0)),
    )
    db.session.add(grade)
    db.session.flush()
    return grade, True


def _ensure_year(tenant_id, ay):
    name = ay["name"]
    active = bool(ay.get("active", True))
    if active:
        # Keep exactly one active year per tenant.
        AcademicYear.query.filter_by(tenant_id=tenant_id, is_active=True).update(
            {"is_active": False}, synchronize_session=False
        )
    year = AcademicYear.query.filter_by(tenant_id=tenant_id, name=name).first()
    if year:
        if active:
            year.is_active = True
        db.session.flush()
        return year, False
    year = AcademicYear(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=name,
        start_date=_parse_date(ay["start"]),
        end_date=_parse_date(ay["end"]),
        is_active=active,
    )
    db.session.add(year)
    db.session.flush()
    return year, True


def _ensure_subject(tenant_id, row):
    subj = (
        Subject.query.filter_by(tenant_id=tenant_id, code=row["code"])
        .filter(Subject.deleted_at.is_(None))
        .first()
    )
    if subj:
        return subj, False
    subj = Subject(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        name=row["name"],
        code=row["code"],
        subject_type=row.get("subject_type", "core"),
        is_active=True,
    )
    db.session.add(subj)
    db.session.flush()
    return subj, True


def _ensure_subject_context(tenant_id, programme_id, grade_id, subject_id, offered):
    ctx = (
        SubjectContext.query.filter_by(
            tenant_id=tenant_id,
            programme_id=programme_id,
            grade_id=grade_id,
            subject_id=subject_id,
        )
        .filter(SubjectContext.deleted_at.is_(None))
        .first()
    )
    if ctx:
        return ctx, False
    ctx = SubjectContext(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        programme_id=programme_id,
        grade_id=grade_id,
        subject_id=subject_id,
        type=offered.get("type", "mandatory"),
        default_weekly_periods=int(offered.get("weekly", 5)),
        is_active=True,
    )
    db.session.add(ctx)
    db.session.flush()
    return ctx, True


# --------------------------------------------------------------------------- #
# Granular class_subjects (derive from each class's (programme, grade) contexts)
# --------------------------------------------------------------------------- #
def apply_subject_contexts_to_classes(tenant_id, academic_year_id) -> dict:
    """Create one ClassSubject per (class, offered subject) for the active year.

    A class's offered subjects are the SubjectContext rows matching its
    (programme_id, grade_id). Additive + idempotent: skips active rows that
    already exist. Returns {"created": n, "skipped": m}.
    """
    classes = Class.query.filter_by(
        tenant_id=tenant_id, academic_year_id=academic_year_id
    ).all()
    if not classes:
        return {"created": 0, "skipped": 0}

    class_ids = [c.id for c in classes]
    existing_pairs = {
        (cs.class_id, cs.subject_id)
        for cs in ClassSubject.query.filter(
            ClassSubject.class_id.in_(class_ids),
            ClassSubject.deleted_at.is_(None),
            ClassSubject.status == "active",
        ).all()
    }

    contexts = (
        SubjectContext.query.filter_by(tenant_id=tenant_id, is_active=True)
        .filter(SubjectContext.deleted_at.is_(None))
        .all()
    )
    ctx_by_pair: dict[tuple, list] = {}
    for ctx in contexts:
        ctx_by_pair.setdefault((ctx.programme_id, ctx.grade_id), []).append(ctx)

    created = 0
    skipped = 0
    for c in classes:
        for ctx in ctx_by_pair.get((c.programme_id, c.grade_id), []):
            if (c.id, ctx.subject_id) in existing_pairs:
                skipped += 1
                continue
            db.session.add(
                ClassSubject(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    class_id=c.id,
                    subject_id=ctx.subject_id,
                    weekly_periods=int(ctx.default_weekly_periods or 5),
                    is_mandatory=(ctx.type == "mandatory"),
                    status="active",
                )
            )
            existing_pairs.add((c.id, ctx.subject_id))
            created += 1
    db.session.commit()
    return {"created": created, "skipped": skipped}


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #
def seed_school(tenant_id, config, dry_run=False, complete=True) -> dict:
    """Seed a tenant's academic foundation from a config dict.

    Validates first (raises SeedValidationError before any writes). On dry_run,
    returns a plan and writes nothing. Otherwise upserts the foundation, creates
    classes via bulk_generate_classes, derives class_subjects, then verifies via
    get_status_payload and (if ready and complete) flips is_setup_complete.
    """
    errors = _validate_config(config)
    if errors:
        raise SeedValidationError(errors)
    if dry_run:
        return {"dry_run": True, "validation": "ok", "plan": _dry_run_plan(config)}

    unit_by_code = {}
    for row in config["units"]:
        unit, _created = _ensure_unit(tenant_id, row)
        unit_by_code[row["code"]] = unit
    prog_by_code = {}
    for row in config["programmes"]:
        prog, _created = _ensure_programme(tenant_id, row)
        prog_by_code[row["code"]] = prog
    grade_by_name = {}
    for row in config["grades"]:
        grade, _created = _ensure_grade(tenant_id, row)
        grade_by_name[str(row["name"])] = grade

    year, _created = _ensure_year(tenant_id, config["academic_year"])

    subj_by_code = {}
    for row in config.get("subjects", []):
        subj, _created = _ensure_subject(tenant_id, row)
        subj_by_code[row["code"]] = subj

    for off in config.get("offerings", []):
        prog = prog_by_code[off["programme"]]
        grade = grade_by_name[str(off["grade"])]
        for s in off.get("subjects", []):
            subj = subj_by_code[s["code"]]
            _ensure_subject_context(tenant_id, prog.id, grade.id, subj.id, s)

    db.session.commit()

    cells = [
        {
            "grade_id": grade_by_name[str(cl["grade"])].id,
            "school_unit_id": unit_by_code[cl["unit"]].id,
            "programme_id": prog_by_code[cl["programme"]].id,
            "sections": list(cl.get("sections", [])),
        }
        for cl in config.get("classes", [])
    ]
    class_result = bulk_generate_classes(
        tenant_id, {"academic_year_id": year.id, "cells": cells}
    )
    if not class_result.get("success"):
        raise SeedValidationError(
            ["class generation failed: "
             + str(class_result.get("error") or class_result.get("errors"))]
        )

    cs_result = apply_subject_contexts_to_classes(tenant_id, year.id)

    status = get_status_payload(tenant_id)
    completed = False
    if complete and status["overall"]["ready"]:
        completed = bool(run_complete_setup(tenant_id).get("success", False))

    logger.info(
        "seed_school.done",
        extra={
            "tenant_id": tenant_id,
            "classes_created": class_result.get("created_count", 0),
            "class_subjects_created": cs_result.get("created", 0),
            "setup_complete": completed,
        },
    )
    return {
        "dry_run": False,
        "academic_year_id": year.id,
        "classes": {
            "created": class_result.get("created_count", 0),
            "skipped": class_result.get("skipped_count", 0),
        },
        "class_subjects": cs_result,
        "status": status,
        "setup_complete": completed,
    }
