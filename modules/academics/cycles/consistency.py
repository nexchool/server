"""A row that names an academic year also names the cycle inside it.

`academic_cycle_id` is NOT NULL on classes, terms and calendars, and it is
**derivable from `academic_year_id` alone** while a year has one main cycle —
which is every year until a school opens a second.

Deriving it centrally rather than at each writer follows the precedent
`modules/auth/person_link.py` set for accounts and persons: there are ten
production sites that build one of these rows and several dozen fixtures and
seeds, and "remember the cycle too" is a rule that will eventually be
forgotten. The one that forgets is the one that fails at insert.

This is **consistency, not workflow**. Nothing is decided here and no business
event happens: opening a cycle is `ensure_default_cycle`, which a reader can
find. All this does is fill in the cycle a row's own year already implies, and
only when the writer did not say. A writer that names a cycle explicitly is
left alone, and the composite foreign key still refuses a cycle from the wrong
year.

Registered explicitly in `app.py` rather than on import, so it does not depend
on which module imported this one first.
"""

from __future__ import annotations

import uuid

from sqlalchemy import event
from sqlalchemy.orm import Session as OrmSession


def _needs_cycle(instance) -> bool:
    return (
        hasattr(instance, "academic_cycle_id")
        and hasattr(instance, "academic_year_id")
        and getattr(instance, "academic_cycle_id", None) is None
        and getattr(instance, "academic_year_id", None) is not None
    )


def _fill_cycle(session, flush_context, instances):
    """Give every new year its main cycle, and every new row the cycle it implies.

    Two halves, in this order, because the second depends on the first:

    1. **A new academic year gets its main cycle.** Built by assigning the
       relationship (`cycle.academic_year = year`), which is what orders the
       cycle's insert after the year's — the lesson `User.person` taught.
    2. **A new class, term or calendar gets the cycle its year implies**, found
       in the database or among the cycles queued a moment ago in (1).

    Nothing is created for a row whose year cannot be resolved; the foreign key
    says so more clearly than a guess would.
    """
    from modules.academics.academic_year.models import AcademicYear

    from .models import CYCLE_KIND_MAIN, AcademicCycle

    new_years = [obj for obj in session.new if isinstance(obj, AcademicYear)]
    pending = [obj for obj in session.new if _needs_cycle(obj)]
    if not new_years and not pending:
        return

    # Inside a flush: no flushing here (it would recurse), and reads are
    # wrapped so SQLAlchemy does not autoflush the objects being handled.
    with session.no_autoflush:
        queued = {
            obj.academic_year_id: obj
            for obj in session.new
            if isinstance(obj, AcademicCycle) and obj.cycle_kind == CYCLE_KIND_MAIN
        }

        for year in new_years:
            if year.id in queued:
                continue
            cycle = AcademicCycle(
                # Minted here rather than left to the column default, which is
                # applied at INSERT: rows written in this same flush need the
                # value now.
                id=str(uuid.uuid4()),
                tenant_id=year.tenant_id,
                name=year.name,
                start_date=year.start_date,
                end_date=year.end_date,
                cycle_kind=CYCLE_KIND_MAIN,
            )
            # The relationship, not the id — the unit of work orders inserts
            # from mapper relationships, and the year may not be written yet.
            cycle.academic_year = year
            session.add(cycle)
            queued[year.id] = cycle

        for obj in pending:
            year_id = obj.academic_year_id
            cycle = queued.get(year_id)
            if cycle is None:
                live = (
                    session.query(AcademicCycle)
                    .filter(
                        AcademicCycle.academic_year_id == year_id,
                        AcademicCycle.deleted_at.is_(None),
                    )
                    .order_by(AcademicCycle.start_date)
                    .all()
                )
                if len(live) > 1:
                    # The same rule `resolve_cycle_id` applies, enforced on the
                    # direct-construction path too. Guessing the main cycle here
                    # would put a CBSE section into the GSEB cycle silently, and
                    # a fixture or seed is exactly where that would go unnoticed.
                    raise ValueError(
                        f"{type(obj).__name__} names an academic year that runs "
                        f"{len(live)} cycles. Set academic_cycle_id explicitly — "
                        "there is no safe default once a year has more than one."
                    )
                cycle = live[0] if live else None
            if cycle is None:
                continue
            obj.academic_cycle_id = cycle.id
            if getattr(obj, "tenant_id", None) is None:
                obj.tenant_id = cycle.tenant_id


def register_cycle_consistency() -> None:
    """Attach the listener. Called once from `app.py`."""
    if not event.contains(OrmSession, "before_flush", _fill_cycle):
        event.listen(OrmSession, "before_flush", _fill_cycle)
