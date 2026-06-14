"""
Holiday rollover: copy holidays bound to the source academic year into the
target year. Recurring holidays are copied as-is. Single/range holidays have
their dates shifted by the year-difference between the two academic years so
they land on the equivalent date in the new year (admin can adjust).

Idempotent: holidays whose unique key (tenant_id, start_date, name) already
exists in the target year are skipped.
"""

from __future__ import annotations
from shared.safe_error import safe_error

import logging
import uuid
from datetime import date
from typing import Any, Dict, Optional

from core.database import db
from core.tenant import get_tenant_id
from modules.academics.academic_year.models import AcademicYear
from modules.holidays.models import Holiday

logger = logging.getLogger(__name__)


def _years_between(from_year: AcademicYear, to_year: AcademicYear) -> int:
    if not from_year.start_date or not to_year.start_date:
        return 0
    return to_year.start_date.year - from_year.start_date.year


def _shift_date(d: Optional[date], years: int) -> Optional[date]:
    if not d or years == 0:
        return d
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # Feb 29 → non-leap target year. Use Feb 28 of the new year.
        return d.replace(year=d.year + years, day=28)


def rollover_holidays(from_year_id: str, to_year_id: str) -> Dict[str, Any]:
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}
    if not from_year_id or not to_year_id:
        return {"success": False, "error": "from_year_id and to_year_id are required"}
    if from_year_id == to_year_id:
        return {"success": False, "error": "from_year_id and to_year_id must differ"}

    from_year = AcademicYear.query.filter_by(id=from_year_id, tenant_id=tenant_id).first()
    to_year = AcademicYear.query.filter_by(id=to_year_id, tenant_id=tenant_id).first()
    if not from_year:
        return {"success": False, "error": "from_year_id not found"}
    if not to_year:
        return {"success": False, "error": "to_year_id not found"}

    year_shift = _years_between(from_year, to_year)

    sources = Holiday.query.filter_by(
        tenant_id=tenant_id, academic_year_id=from_year_id
    ).all()

    # The DB unique key is (tenant_id, start_date, name) across ALL years —
    # not just the target year — so we need to check every existing holiday
    # for the tenant before inserting, otherwise a date collision with another
    # year's holiday would roll back the whole batch.
    existing_keys = {
        (h.start_date, h.name)
        for h in Holiday.query.filter_by(tenant_id=tenant_id).all()
    }

    created = 0
    skipped = 0

    try:
        for h in sources:
            new_start = (
                None if h.is_recurring else _shift_date(h.start_date, year_shift)
            )
            new_end = (
                None if h.is_recurring else _shift_date(h.end_date, year_shift)
            )
            key = (new_start, h.name)
            if key in existing_keys:
                skipped += 1
                continue

            db.session.add(
                Holiday(
                    id=str(uuid.uuid4()),
                    tenant_id=tenant_id,
                    name=h.name,
                    description=h.description,
                    holiday_type=h.holiday_type,
                    start_date=new_start,
                    end_date=new_end,
                    is_recurring=h.is_recurring,
                    recurring_day_of_week=h.recurring_day_of_week,
                    academic_year_id=to_year_id,
                )
            )
            existing_keys.add(key)
            created += 1
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.exception("holiday rollover failed: %s", e)
        return {"success": False, "error": safe_error(e)}

    return {
        "success": True,
        "holidays_created": created,
        "skipped_existing": skipped,
    }
