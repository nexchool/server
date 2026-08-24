"""Resolving which cycle an operation belongs to.

**There is deliberately no `current_academic_cycle_id` anywhere.** Several
cycles are legitimately running at once — a main year, a vacation batch, a
coaching programme — so a single global answer would be wrong for at least two
of them. Context answers instead:

    a class      → `Class.academic_cycle_id`
    an enrollment→ its class's cycle
    a calendar   → `AcademicCalendar.academic_cycle_id`
    a term       → `AcademicTerm.academic_cycle_id`

`AcademicSettings.current_academic_year_id` keeps its meaning untouched: the
year the organization is currently reporting under. That is a real question
with one answer, and it is not this one.
"""

from __future__ import annotations

from typing import List, Optional

from core.database import db
from modules.academics.academic_year.models import AcademicYear

from .models import CYCLE_KIND_MAIN, AcademicCycle


def cycles_for_year(academic_year_id: str, tenant_id: str) -> List[AcademicCycle]:
    """Every live cycle in a year, main first then by start date."""
    return (
        AcademicCycle.query.filter(
            AcademicCycle.tenant_id == tenant_id,
            AcademicCycle.academic_year_id == academic_year_id,
            AcademicCycle.deleted_at.is_(None),
        )
        .order_by(
            (AcademicCycle.cycle_kind != CYCLE_KIND_MAIN),
            AcademicCycle.start_date,
        )
        .all()
    )


def default_cycle_for_year(
    academic_year_id: str, tenant_id: str
) -> Optional[AcademicCycle]:
    """The year's main cycle — what an ordinary school operates in.

    Every year has exactly one after migration 112, and `ensure_default_cycle`
    keeps that true for years created since.
    """
    return (
        AcademicCycle.query.filter(
            AcademicCycle.tenant_id == tenant_id,
            AcademicCycle.academic_year_id == academic_year_id,
            AcademicCycle.cycle_kind == CYCLE_KIND_MAIN,
            AcademicCycle.deleted_at.is_(None),
        )
        .order_by(AcademicCycle.start_date)
        .first()
    )


def ensure_default_cycle(year: AcademicYear) -> AcademicCycle:
    """Give a year its main cycle. Idempotent.

    Called when a year is created so an administrator never has to know the
    concept exists: they make a year, and the period it runs in comes with it.
    """
    existing = default_cycle_for_year(year.id, year.tenant_id)
    if existing is not None:
        return existing

    cycle = AcademicCycle(
        tenant_id=year.tenant_id,
        academic_year_id=year.id,
        name=year.name,
        start_date=year.start_date,
        end_date=year.end_date,
        cycle_kind=CYCLE_KIND_MAIN,
    )
    db.session.add(cycle)
    db.session.flush()
    return cycle


def resolve_cycle_id(
    academic_year_id: str, tenant_id: str, cycle_id: Optional[str] = None
) -> str:
    """Which cycle a new class, term or calendar belongs to.

    Three cases, and the third is the one that matters:

    1. A cycle is named → checked against the year rather than trusted. The
       composite foreign key would refuse a mismatch anyway; refusing here
       says why.
    2. None named, the year has **one** cycle → that one. This is every
       ordinary school, and why they never see the field.
    3. None named, the year has **several** → refused.

    Case 3 is deliberate. Falling back to the main cycle would put a new CBSE
    section into the GSEB cycle silently, and nothing downstream would look
    wrong — the class would simply be operating on dates nobody chose for it.
    A school that has taken the trouble to define two cycles has to say which.

    Raises ValueError so callers can surface the reason; every caller in this
    codebase returns `{"success": False, "error": ...}` rather than raising.
    """
    if cycle_id:
        cycle = AcademicCycle.query.filter_by(
            id=cycle_id, tenant_id=tenant_id
        ).first()
        if cycle is None or cycle.deleted_at is not None:
            raise ValueError("Academic cycle not found")
        if cycle.academic_year_id != academic_year_id:
            raise ValueError(
                "That academic cycle belongs to a different academic year"
            )
        return cycle.id

    available = cycles_for_year(academic_year_id, tenant_id)
    if len(available) > 1:
        names = ", ".join(f"'{c.name}'" for c in available)
        raise ValueError(
            f"This academic year runs several cycles ({names}). "
            "Choose which one this belongs to."
        )
    if available:
        return available[0].id

    year = AcademicYear.query.filter_by(
        id=academic_year_id, tenant_id=tenant_id
    ).first()
    if year is None:
        raise ValueError("Academic year not found")
    # A year made before this model existed, or by a path that bypassed
    # creation. Making the cycle is better than refusing the class.
    return ensure_default_cycle(year).id


def year_has_multiple_cycles(academic_year_id: str, tenant_id: str) -> bool:
    """Whether the operator should be shown a cycle choice at all.

    The simple-school rule: one cycle means the field is hidden and defaulted,
    because asking somebody to pick from a list of one teaches them an
    abstraction to no purpose.
    """
    return len(cycles_for_year(academic_year_id, tenant_id)) > 1


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------
#
# Kept deliberately small: a school opens a cycle, corrects it, or retires it.
# There is no separate "activate" — a cycle is live from the day it starts,
# which its dates already say.


def get_cycle(cycle_id: str, tenant_id: str) -> Optional[AcademicCycle]:
    return AcademicCycle.query.filter_by(id=cycle_id, tenant_id=tenant_id).first()


def _validate(
    tenant_id: str,
    academic_year_id: str,
    name: str,
    start_date,
    end_date,
    cycle_kind: str,
    exclude_id: Optional[str] = None,
) -> Optional[str]:
    from .models import CYCLE_KINDS

    if not (name or "").strip():
        return "Cycle name is required"
    if cycle_kind not in CYCLE_KINDS:
        return f"cycle_kind must be one of {', '.join(CYCLE_KINDS)}"
    if not start_date or not end_date:
        return "start_date and end_date are required"
    if start_date > end_date:
        return "end_date must be on or after start_date"

    year = AcademicYear.query.filter_by(
        id=academic_year_id, tenant_id=tenant_id
    ).first()
    if year is None:
        return "Academic year not found"

    clash = AcademicCycle.query.filter(
        AcademicCycle.tenant_id == tenant_id,
        AcademicCycle.academic_year_id == academic_year_id,
        AcademicCycle.name == name.strip(),
        AcademicCycle.deleted_at.is_(None),
    )
    if exclude_id:
        clash = clash.filter(AcademicCycle.id != exclude_id)
    if clash.first():
        return f"This academic year already has a cycle called '{name.strip()}'"
    # Dates are deliberately NOT checked against the year's, and cycles are
    # deliberately allowed to overlap each other: a vacation batch runs inside
    # the main year, and a board's cycle may start before the year the school
    # reports it under.
    return None


def create_cycle(
    tenant_id: str,
    academic_year_id: str,
    name: str,
    start_date,
    end_date,
    cycle_kind: str = CYCLE_KIND_MAIN,
) -> dict:
    error = _validate(
        tenant_id, academic_year_id, name, start_date, end_date, cycle_kind
    )
    if error:
        return {"success": False, "error": error}

    cycle = AcademicCycle(
        tenant_id=tenant_id,
        academic_year_id=academic_year_id,
        name=name.strip(),
        start_date=start_date,
        end_date=end_date,
        cycle_kind=cycle_kind,
    )
    db.session.add(cycle)
    db.session.commit()
    return {"success": True, "academic_cycle": cycle}


def update_cycle(cycle_id: str, tenant_id: str, changes: dict) -> dict:
    cycle = get_cycle(cycle_id, tenant_id)
    if cycle is None or cycle.deleted_at is not None:
        return {"success": False, "error": "Academic cycle not found"}

    name = changes.get("name", cycle.name)
    start_date = changes.get("start_date", cycle.start_date)
    end_date = changes.get("end_date", cycle.end_date)
    cycle_kind = changes.get("cycle_kind", cycle.cycle_kind)

    error = _validate(
        tenant_id, cycle.academic_year_id, name, start_date, end_date,
        cycle_kind, exclude_id=cycle.id,
    )
    if error:
        return {"success": False, "error": error}

    cycle.name = (name or "").strip()
    cycle.start_date = start_date
    cycle.end_date = end_date
    cycle.cycle_kind = cycle_kind
    db.session.commit()
    return {"success": True, "academic_cycle": cycle}


def archive_cycle(cycle_id: str, tenant_id: str) -> dict:
    """Retire a cycle. Refused while anything still operates in it.

    Soft-deleted, following every other academic catalogue: what a school ran
    last year is not something to erase, and the classes, terms and calendars
    that named this cycle keep pointing at it.
    """
    from modules.academics.backbone.models import AcademicTerm
    from modules.academics.calendar.models import AcademicCalendar
    from modules.classes.models import Class
    from core.school_time import utc_now

    cycle = get_cycle(cycle_id, tenant_id)
    if cycle is None or cycle.deleted_at is not None:
        return {"success": False, "error": "Academic cycle not found"}

    holders = [
        ("class", Class.query.filter_by(
            tenant_id=tenant_id, academic_cycle_id=cycle.id).count()),
        ("term", AcademicTerm.query.filter_by(
            tenant_id=tenant_id, academic_cycle_id=cycle.id).filter(
            AcademicTerm.deleted_at.is_(None)).count()),
        ("calendar", AcademicCalendar.query.filter_by(
            tenant_id=tenant_id, academic_cycle_id=cycle.id).count()),
    ]
    blocking = [f"{count} {label}(s)" for label, count in holders if count]
    if blocking:
        return {
            "success": False,
            "error": (
                f"'{cycle.name}' still holds {', '.join(blocking)}. "
                "Move or remove them before retiring the cycle."
            ),
        }

    cycle.deleted_at = utc_now()
    db.session.commit()
    return {"success": True, "academic_cycle": cycle}
