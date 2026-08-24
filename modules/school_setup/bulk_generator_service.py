"""
Bulk Class Generator Service

Accepts a matrix of cells (grade × unit × programme), each with a list of
section strings, and creates Class rows for every combination.

Section strings may encode a stream prefix for Grade 11-12:
  "Sci-A"  -> stream="Science", section="A"
  "Com-B"  -> stream="Commerce", section="B"
  "Arts-A" -> stream="Arts", section="A"
  "Voc-A"  -> stream="Vocational", section="A"
  "A"      -> stream=None, section="A"

Idempotent: skips classes that already exist (matched on
tenant+year+unit+programme+grade+section+stream).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from core.database import db
from modules.academic_programmes.models import AcademicProgramme
from modules.academics.academic_year.models import AcademicYear
from modules.classes.models import Class
from modules.grades.models import Grade
from modules.school_units.models import SchoolUnit
from modules.streams.services import list_streams

logger = logging.getLogger(__name__)

def _stream_index(tenant_id: str) -> Dict[str, Any]:
    """Prefix → Stream for this tenant, keyed by both code and name.

    Replaces a hardcoded {"Sci": "Science", …} map. A school that defines
    "Humanities" with code "HUM" can write "HUM-A" and it resolves, which is
    the whole point of the streams table (migration 107). The four seeded
    codes (SCI/COM/ART/VOC) and names still match the prefixes schools already
    type, so existing sheets keep working.
    """
    index: Dict[str, Any] = {}
    for stream in list_streams(tenant_id):
        if stream.code:
            index[stream.code.strip().lower()] = stream
        index[stream.name.strip().lower()] = stream
    return index


def bulk_generate_classes(tenant_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    academic_year_id: Optional[str] = payload.get("academic_year_id")
    cells: List[Dict[str, Any]] = payload.get("cells") or []

    if not academic_year_id:
        return {"success": False, "error": "academic_year_id is required"}
    if not cells:
        return {"success": False, "error": "cells is required and must not be empty"}

    if not AcademicYear.query.filter_by(id=academic_year_id, tenant_id=tenant_id).first():
        return {"success": False, "error": "Invalid academic_year_id for this tenant"}

    # Read once for the whole sheet, and only if a section actually names a
    # stream — most sheets are plain letters and should not pay for a catalogue
    # they never consult.
    _cached: Dict[str, Any] = {}

    def streams() -> Dict[str, Any]:
        if "index" not in _cached:
            _cached["index"] = _stream_index(tenant_id)
        return _cached["index"]

    created: List[Dict] = []
    skipped: List[Dict] = []
    errors: List[Dict] = []

    for cell_index, cell in enumerate(cells):
        grade_id = cell.get("grade_id")
        school_unit_id = cell.get("school_unit_id")
        programme_id = cell.get("programme_id")
        sections: List[str] = cell.get("sections") or []

        if not all([grade_id, school_unit_id, programme_id, sections]):
            errors.append({
                "cell": cell_index,
                "error": "grade_id, school_unit_id, programme_id, sections are all required",
            })
            continue

        if not _validate_fk(SchoolUnit, school_unit_id, tenant_id):
            errors.append({"cell": cell_index, "error": f"Invalid school_unit_id: {school_unit_id}"})
            continue
        if not _validate_fk(AcademicProgramme, programme_id, tenant_id):
            errors.append({"cell": cell_index, "error": f"Invalid programme_id: {programme_id}"})
            continue
        if not _validate_fk(Grade, grade_id, tenant_id):
            errors.append({"cell": cell_index, "error": f"Invalid grade_id: {grade_id}"})
            continue

        for section_raw in sections:
            section_raw = section_raw.strip()
            if not section_raw:
                continue

            if "-" in section_raw:
                stream, section_label = _parse_stream_section(section_raw, streams())
            else:
                stream, section_label = None, section_raw

            exists_q = Class.query.filter(
                Class.tenant_id == tenant_id,
                Class.academic_year_id == academic_year_id,
                Class.school_unit_id == school_unit_id,
                Class.programme_id == programme_id,
                Class.grade_id == grade_id,
                Class.section == section_label,
            )
            if stream is None:
                exists_q = exists_q.filter(Class.stream_id.is_(None))
            else:
                exists_q = exists_q.filter(Class.stream_id == stream.id)

            if exists_q.first():
                skipped.append(
                    _cell_summary(
                        grade_id, school_unit_id, programme_id, section_label, stream
                    )
                )
                continue

            new_class = Class(
                tenant_id=tenant_id,
                academic_year_id=academic_year_id,
                school_unit_id=school_unit_id,
                programme_id=programme_id,
                grade_id=grade_id,
                section=section_label,
                stream_id=stream.id if stream else None,
            )
            db.session.add(new_class)
            created.append(
                _cell_summary(
                    grade_id, school_unit_id, programme_id, section_label, stream
                )
            )

    if errors and not created and not skipped:
        return {"success": False, "errors": errors}

    try:
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.exception("bulk_generate_classes.commit_failed", extra={"tenant_id": tenant_id})
        return {"success": False, "error": str(exc)}

    logger.info(
        "bulk_generate_classes.done",
        extra={"tenant_id": tenant_id, "created": len(created), "skipped": len(skipped), "errors": len(errors)},
    )
    return {
        "success": True,
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "created_count": len(created),
        "skipped_count": len(skipped),
    }


def _parse_stream_section(raw: str, streams: Dict[str, Any]) -> Tuple[Optional[Any], str]:
    """'Sci-A' -> (<Stream Science>, 'A'),  'A' -> (None, 'A')."""
    parts = raw.split("-", 1)
    if len(parts) == 2:
        found = streams.get(parts[0].strip().lower())
        if found is not None:
            return found, parts[1]
    return None, raw


def _validate_fk(model, pk: str, tenant_id: str) -> bool:
    q = model.query.filter_by(id=pk, tenant_id=tenant_id)
    if hasattr(model, "deleted_at"):
        q = q.filter(model.deleted_at.is_(None))
    return q.first() is not None


def _cell_summary(grade_id, unit_id, programme_id, section, stream):
    return {
        "grade_id": grade_id,
        "school_unit_id": unit_id,
        "programme_id": programme_id,
        "section": section,
        # The name, as this payload has always carried it.
        "stream": stream.name if stream is not None else None,
        "stream_id": stream.id if stream is not None else None,
    }
