"""School onboarding seed service.

Config-driven, idempotent seeding of a tenant's academic foundation:
units -> programmes -> grades -> academic_year -> terms -> subjects ->
subject_contexts -> classes -> class_subjects.

Design notes:
- Logic lives here (unit-testable); scripts/seed_school.py is a thin CLI wrapper.
- Every _ensure_* helper is query-first (create-if-missing), so seed_school is
  safe to re-run. Natural keys: unit.code, programme.code, grade.name,
  academic_year.name, subject.code, term.name (scoped to its academic year).
- Classes are created via the existing bulk_generate_classes service (it sets the
  unit/programme/grade FKs, parses streams, and is itself idempotent).
- class_subjects are derived granularly from each class's (programme, grade)
  SubjectContext rows -- never the blunt every-subject-to-every-class approach.
- Real-board structure: a SubjectContext carries `role` (first/second/third
  language, core, co_curricular), `short_code`, and `sort_order`. A subject may
  declare a default `role`/`short_code` once in `subjects[]`; each offering
  inherits it (and can override per (programme, grade)).
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
from modules.academics.backbone.models import AcademicTerm
from modules.classes.models import Class, ClassSubject
from modules.grades.models import Grade
from modules.mediums.models import Medium
from modules.school_units.models import SchoolUnit
from modules.subject_contexts.models import SubjectContext
from modules.subjects.models import Subject

from .bulk_generator_service import (
    bulk_generate_classes,
    _parse_stream_section,
    _stream_index,
)
from .services import get_status_payload, run_complete_setup

logger = logging.getLogger(__name__)

# Fallback weekly period count when a config offering omits "weekly".
# Mirrors SubjectContext.default_weekly_periods' DB default.
DEFAULT_WEEKLY_PERIODS = 5

# Allowed SubjectContext.role / type values (mirror modules.subject_contexts.models
# CONTEXT_ROLES / CONTEXT_TYPES). Used to validate config offerings.
VALID_CONTEXT_ROLES = {
    "first_language",
    "second_language",
    "third_language",
    "core",
    "co_curricular",
}
VALID_CONTEXT_TYPES = {"mandatory", "elective"}


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

    # Subject-level default role (optional) must be a known role.
    for s in config.get("subjects", []):
        role = s.get("role")
        if role is not None and role not in VALID_CONTEXT_ROLES:
            errors.append(f"subject '{s['code']}' has invalid role '{role}'")

    offered_pairs: set[tuple[str, str]] = set()
    for off in config.get("offerings", []):
        if off["programme"] not in prog_codes:
            errors.append(f"offering references unknown programme '{off['programme']}'")
        if str(off["grade"]) not in grade_names:
            errors.append(f"offering references unknown grade '{off['grade']}'")
        for s in off.get("subjects", []):
            if s["code"] not in subject_codes:
                errors.append(f"offering references unknown subject '{s['code']}'")
            role = s.get("role")
            if role is not None and role not in VALID_CONTEXT_ROLES:
                errors.append(
                    f"offering subject '{s['code']}' in (programme {off['programme']}, "
                    f"grade {off['grade']}) has invalid role '{role}'"
                )
            stype = s.get("type")
            if stype is not None and stype not in VALID_CONTEXT_TYPES:
                errors.append(
                    f"offering subject '{s['code']}' in (programme {off['programme']}, "
                    f"grade {off['grade']}) has invalid type '{stype}'"
                )
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

    # terms (optional) — must sit inside the academic year, not overlap, and
    # carry unique names and (where given) unique codes. Natural keys are
    # (academic_year, name) and (academic_year, code) where code IS NOT NULL,
    # mirroring uq_academic_terms_year_name and uq_academic_terms_year_code.
    ay_start = ay_end = None
    ay_cfg = config.get("academic_year") or {}
    if ay_cfg.get("start") and ay_cfg.get("end"):
        try:
            ay_start = _parse_date(ay_cfg["start"])
            ay_end = _parse_date(ay_cfg["end"])
        except (ValueError, TypeError):
            ay_start = ay_end = None

    seen_term_names: set[str] = set()
    seen_term_codes: set[str] = set()
    parsed_terms: list[tuple[str, object, object]] = []
    for term in config.get("terms", []):
        name = term.get("name")
        if name in seen_term_names:
            errors.append(f"duplicate term name '{name}'")
        seen_term_names.add(name)
        code = term.get("code")
        if code:
            if code in seen_term_codes:
                errors.append(f"duplicate term code '{code}'")
            seen_term_codes.add(code)
        try:
            start = _parse_date(term["start"])
            end = _parse_date(term["end"])
        except (KeyError, ValueError, TypeError, AttributeError):
            errors.append(f"term '{name}' has invalid start/end dates")
            continue
        if start > end:
            errors.append(f"term '{name}' starts after it ends")
            continue
        if ay_start and (start < ay_start or end > ay_end):
            errors.append(f"term '{name}' falls outside the academic year")
        parsed_terms.append((name, start, end))

    parsed_terms.sort(key=lambda t: t[1])
    for earlier, later in zip(parsed_terms, parsed_terms[1:]):
        if later[1] <= earlier[2]:
            errors.append(f"terms '{earlier[0]}' and '{later[0]}' overlap")

    return errors


def _dry_run_plan(config: dict) -> dict:
    return {
        "units": len(config.get("units", [])),
        "programmes": len(config.get("programmes", [])),
        "grades": len(config.get("grades", [])),
        "academic_year": config["academic_year"]["name"],
        "terms": len(config.get("terms", [])),
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
        template_board_code=row.get("template_board_code"),
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


def _ensure_term(tenant_id, academic_year_id, row, sequence):
    """Upsert one AcademicTerm. Natural key: (academic_year, name)."""
    name = row["name"]
    term = (
        AcademicTerm.query.filter_by(
            tenant_id=tenant_id, academic_year_id=academic_year_id, name=name
        )
        .filter(AcademicTerm.deleted_at.is_(None))
        .first()
    )
    if term:
        return term, False
    term = AcademicTerm(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        academic_year_id=academic_year_id,
        name=name,
        code=row.get("code"),
        sequence=int(row.get("sequence", sequence)),
        start_date=_parse_date(row["start"]),
        end_date=_parse_date(row["end"]),
        is_active=True,
    )
    db.session.add(term)
    db.session.flush()
    return term, True


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
        description=row.get("description"),
        is_active=True,
    )
    db.session.add(subj)
    db.session.flush()
    return subj, True


def _ensure_subject_context(
    tenant_id, programme_id, grade_id, subject_id, offered, sort_order=0,
    stream_id=None,
):
    """Upsert one SubjectContext (offering of a subject for a programme x grade).

    `offered` is a config offering line; it may carry `type`, `role`,
    `short_code`, `weekly`, and `sort_order`. `sort_order` defaults to the
    caller-supplied position when the offering omits it.

    `stream_id` is the track this offering belongs to, or None for one every
    stream at this (programme, grade) shares. It is part of the natural key:
    Grade 11 Science and Grade 11 Commerce both teach Mathematics, and those
    are two offerings, not one seen twice.
    """
    ctx = (
        SubjectContext.query.filter_by(
            tenant_id=tenant_id,
            programme_id=programme_id,
            grade_id=grade_id,
            subject_id=subject_id,
            stream_id=stream_id,
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
        stream_id=stream_id,
        type=offered.get("type", "mandatory"),
        role=offered.get("role"),
        short_code=offered.get("short_code"),
        exam_code=offered.get("exam_code"),
        sort_order=int(offered.get("sort_order", sort_order)),
        default_weekly_periods=int(offered.get("weekly", DEFAULT_WEEKLY_PERIODS)),
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
    (programme_id, grade_id). Carries each context's sort_order onto the
    ClassSubject. Additive + idempotent: skips active rows that already exist.
    Returns {"created": n, "skipped": m}.
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
    # Keyed by (programme, grade, stream). A class takes the offerings that name
    # its own stream plus the stream-agnostic ones — Grade 11 Science gets
    # Physics and English, and not Accountancy.
    ctx_by_pair: dict[tuple, list] = {}
    for ctx in contexts:
        ctx_by_pair.setdefault(
            (ctx.programme_id, ctx.grade_id, ctx.stream_id), []
        ).append(ctx)

    created = 0
    skipped = 0
    for c in classes:
        offered = list(ctx_by_pair.get((c.programme_id, c.grade_id, None), []))
        if c.stream_id is not None:
            offered += ctx_by_pair.get(
                (c.programme_id, c.grade_id, c.stream_id), []
            )
        for ctx in offered:
            if (c.id, ctx.subject_id) in existing_pairs:
                skipped += 1
                continue
            db.session.add(
                ClassSubject(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    class_id=c.id,
                    subject_id=ctx.subject_id,
                    weekly_periods=int(ctx.default_weekly_periods),
                    is_mandatory=(ctx.type == "mandatory"),
                    sort_order=ctx.sort_order,
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
def _stream_ids_by_name(tenant_id: str) -> dict:
    """Stream name -> id for this school. Streams are tenant-scoped rows."""
    from modules.streams.models import Stream

    return {
        s.name: s.id
        for s in Stream.query.filter_by(tenant_id=tenant_id).all()
    }


def _subject_defaults(config: dict) -> dict:
    """Map subject code -> default {role, short_code} declared in subjects[]."""
    return {
        s["code"]: {"role": s.get("role"), "short_code": s.get("short_code")}
        for s in config.get("subjects", [])
    }


def _merge_offering(offered: dict, defaults: dict) -> dict:
    """Apply subject-level role/short_code defaults unless the offering overrides."""
    merged = dict(offered)
    d = defaults.get(offered["code"], {})
    if merged.get("role") is None and d.get("role"):
        merged["role"] = d["role"]
    if merged.get("short_code") is None and d.get("short_code"):
        merged["short_code"] = d["short_code"]
    return merged


def seed_school(tenant_id, config, dry_run=False, complete=True) -> dict:
    """Seed a tenant's academic foundation from a config dict.

    Validates first (raises SeedValidationError before any writes). On dry_run,
    returns a plan and writes nothing. Otherwise upserts the foundation, creates
    classes via bulk_generate_classes, derives class_subjects, then verifies via
    get_status_payload and (if ready and complete) flips is_setup_complete.

    Failure model: the foundation, classes, and class_subjects commit in separate
    phases (the driven services self-commit), so this is NOT one atomic
    transaction. If a later phase fails, earlier writes persist; because every
    step is idempotent, re-running the same config safely completes the
    remainder. Partial progress is preserved by design, never corrupted.
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

    terms_created = 0
    for index, term_row in enumerate(config.get("terms", []), start=1):
        _term, created = _ensure_term(tenant_id, year.id, term_row, index)
        if created:
            terms_created += 1

    subj_by_code = {}
    for row in config.get("subjects", []):
        subj, _created = _ensure_subject(tenant_id, row)
        subj_by_code[row["code"]] = subj

    defaults = _subject_defaults(config)
    stream_ids = _stream_ids_by_name(tenant_id)
    for off in config.get("offerings", []):
        prog = prog_by_code[off["programme"]]
        grade = grade_by_name[str(off["grade"])]
        stream_name = off.get("stream")
        if stream_name and stream_name not in stream_ids:
            raise SeedValidationError(
                [f"offering names stream '{stream_name}', which this school "
                 f"does not have"]
            )
        stream_id = stream_ids.get(stream_name) if stream_name else None
        for idx, s in enumerate(off.get("subjects", []), start=1):
            subj = subj_by_code[s["code"]]
            _ensure_subject_context(
                tenant_id, prog.id, grade.id, subj.id, _merge_offering(s, defaults),
                sort_order=idx, stream_id=stream_id,
            )

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
        "terms": {"created": terms_created},
        "class_subjects": cs_result,
        "status": status,
        "setup_complete": completed,
    }


# --------------------------------------------------------------------------- #
# In-app upload support: parse an uploaded config + read-only preview
# --------------------------------------------------------------------------- #
class UnsupportedConfigType(Exception):
    """Raised when an uploaded config isn't .yaml/.yml/.json or isn't a mapping."""


def parse_config_bytes(filename: str, raw: bytes) -> dict:
    """Parse uploaded config bytes into a dict by file extension (.yaml/.yml/.json)."""
    name = (filename or "").lower()
    text = raw.decode("utf-8")
    if name.endswith((".yaml", ".yml")):
        import yaml

        data = yaml.safe_load(text)
    elif name.endswith(".json"):
        import json as _json

        data = _json.loads(text)
    else:
        raise UnsupportedConfigType("Config must be a .yaml, .yml, or .json file")
    if not isinstance(data, dict):
        raise UnsupportedConfigType("Config root must be a mapping/object")
    return data


def _existing_natural_keys(tenant_id):
    """Maps of existing entities by natural key (one query each) for preview diffing."""
    units = {
        u.code: u.id
        for u in SchoolUnit.query.filter_by(tenant_id=tenant_id)
        .filter(SchoolUnit.deleted_at.is_(None))
        .all()
    }
    programmes = {
        p.code: p.id
        for p in AcademicProgramme.query.filter_by(tenant_id=tenant_id)
        .filter(AcademicProgramme.deleted_at.is_(None))
        .all()
    }
    grades = {
        gr.name: gr.id
        for gr in Grade.query.filter_by(tenant_id=tenant_id)
        .filter(Grade.deleted_at.is_(None))
        .all()
    }
    subjects = {
        s.code: s.id
        for s in Subject.query.filter_by(tenant_id=tenant_id)
        .filter(Subject.deleted_at.is_(None))
        .all()
        if s.code
    }
    years = {y.name: y.id for y in AcademicYear.query.filter_by(tenant_id=tenant_id).all()}
    return units, programmes, grades, subjects, years


def preview_seed(tenant_id, config, active_subdomain=None) -> dict:
    """Read-only preview of what seed_school would do — NO DB writes.

    Returns validation errors plus, per entity type, totals split into new vs
    already-existing, so the UI can render a confirm-before-apply summary.
    """
    errors = _validate_config(config)
    ex_units, ex_progs, ex_grades, ex_subjects, ex_years = _existing_natural_keys(tenant_id)

    def _simple(rows, key, exists_fn):
        items, new = [], 0
        for r in rows:
            exists = exists_fn(r)
            if not exists:
                new += 1
            items.append({"key": str(r.get(key)), "name": r.get("name"), "exists": exists})
        return {"total": len(rows), "new": new, "existing": len(rows) - new, "items": items}

    units = _simple(config.get("units", []), "code", lambda r: r["code"] in ex_units)
    programmes = _simple(config.get("programmes", []), "code", lambda r: r["code"] in ex_progs)
    grades = _simple(config.get("grades", []), "name", lambda r: str(r["name"]) in ex_grades)
    subjects = _simple(config.get("subjects", []), "code", lambda r: r["code"] in ex_subjects)

    ay = config.get("academic_year") or {}
    ay_name = ay.get("name")
    academic_year = {
        "name": ay_name,
        "exists": ay_name in ex_years,
        "active": bool(ay.get("active", True)),
    }

    ex_terms: set[str] = set()
    if ay_name in ex_years:
        ex_terms = {
            t.name
            for t in AcademicTerm.query.filter_by(
                tenant_id=tenant_id, academic_year_id=ex_years[ay_name]
            )
            .filter(AcademicTerm.deleted_at.is_(None))
            .all()
        }
    terms = _simple(
        config.get("terms", []), "name", lambda r: r.get("name") in ex_terms
    )

    # offerings -> subject_contexts (existing iff programme+grade+subject all exist
    # AND a context row already links them)
    ex_ctx = {
        (c.programme_id, c.grade_id, c.subject_id)
        for c in SubjectContext.query.filter_by(tenant_id=tenant_id)
        .filter(SubjectContext.deleted_at.is_(None))
        .all()
    }
    off_total = off_new = 0
    for off in config.get("offerings", []):
        pid = ex_progs.get(off["programme"])
        gid = ex_grades.get(str(off["grade"]))
        for s in off.get("subjects", []):
            off_total += 1
            sid = ex_subjects.get(s["code"])
            if not (pid and gid and sid and (pid, gid, sid) in ex_ctx):
                off_new += 1
    offerings = {"total": off_total, "new": off_new, "existing": off_total - off_new}

    # classes (existing iff the year + unit + programme + grade exist AND a row
    # with that section/stream already exists in the active year)
    year_id = ex_years.get(ay_name)
    ex_classes = set()
    if year_id:
        ex_classes = {
            (c.school_unit_id, c.programme_id, c.grade_id, c.section, c.stream_id)
            for c in Class.query.filter_by(
                tenant_id=tenant_id, academic_year_id=year_id
            ).all()
        }
    cls_items, cls_new, cls_total = [], 0, 0
    # `ex_classes` is keyed on stream_id, so the preview has to resolve a
    # section prefix to the same row the generator would (migration 107).
    # Read only if a section actually names a stream — a plain-letter sheet
    # should not pay for a catalogue it never consults.
    _stream_cache: Dict[str, Any] = {}

    def _streams() -> Dict[str, Any]:
        if "index" not in _stream_cache:
            _stream_cache["index"] = _stream_index(tenant_id)
        return _stream_cache["index"]

    for cl in config.get("classes", []):
        uid = ex_units.get(cl["unit"])
        pid = ex_progs.get(cl["programme"])
        gid = ex_grades.get(str(cl["grade"]))
        for sec_raw in cl.get("sections", []):
            cls_total += 1
            raw_section = str(sec_raw).strip()
            if "-" in raw_section:
                stream, section = _parse_stream_section(raw_section, _streams())
            else:
                stream, section = None, raw_section
            stream_id = stream.id if stream is not None else None
            exists = bool(
                year_id and uid and pid and gid
                and (uid, pid, gid, section, stream_id) in ex_classes
            )
            if not exists:
                cls_new += 1
            cls_items.append({
                "label": f"{cl['unit']} / {cl['programme']} / {cl['grade']} / {section}",
                "exists": exists,
            })
    classes = {
        "total": cls_total,
        "new": cls_new,
        "existing": cls_total - cls_new,
        "items": cls_items,
    }

    tenant_info = {"subdomain": (config.get("tenant") or {}).get("subdomain")}
    if active_subdomain is not None:
        tenant_info["active_subdomain"] = active_subdomain
        tenant_info["matches"] = (
            tenant_info["subdomain"] is None
            or tenant_info["subdomain"] == active_subdomain
        )

    return {
        "valid": not errors,
        "errors": errors,
        "tenant": tenant_info,
        "academic_year": academic_year,
        "entities": {
            "units": units,
            "programmes": programmes,
            "grades": grades,
            "subjects": subjects,
            "offerings": offerings,
            "terms": terms,
            "classes": classes,
        },
    }
