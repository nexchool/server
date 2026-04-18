"""
Timetable Generator — Constraint-Based Scheduler (v3)
=====================================================

Why this module exists
----------------------
The original `timetable_v2.generate_draft` is a naive sequential filler:
it sorts work by ``class_subject_id`` (so every period of the same
subject sits next to each other in the list) then walks ``(day, period)``
in calendar order picking the first free lesson slot.  Result: all five
English periods land on Monday, teacher load is lopsided and the
timetable is unusable.

This module replaces the inner placement algorithm with a real
scheduling engine — inspired by CSP with heuristic ordering, greedy
placement per attempt and randomised multi-start search:

1.  **Preprocessing** — expand weekly loads into placement "work items"
    (subject slot + candidate teachers: primary → assistants).
2.  **Day planning** — spread each subject's N weekly periods across
    N distinct working days preferring least-loaded days; overflow
    (N > working_days) goes to the day already carrying that subject to
    form intentional double-periods.
3.  **Slot assignment** — for each (day, subject) pair, try each lesson
    period on that day, validate every hard constraint, and pick the
    first valid (period, teacher).  Fall back to another day when the
    planned day is infeasible.
4.  **Scoring** — a weighted score (placements dominant, penalties for
    clustering / teacher back-to-back / load imbalance) ranks each
    attempt.  Best result wins across ``max_attempts``.

Hard constraints (never violated)
---------------------------------
* Teacher cannot be double-booked across classes on the same day+period.
* Class cannot have two subjects at the same day+period.
* ``max_consecutive_same_subject`` (default 2) — no 3-in-a-row.
* ``max_same_subject_per_day`` (default 2) — no 3 of a subject per day.
* Per-teacher daily / weekly workload caps from ``TeacherWorkloadRule``.
* Period must be a lesson period of the class's bell schedule.

Soft preferences (optimised via score)
--------------------------------------
* Even distribution of a subject across the week.
* No long unbroken teaching streaks for a single teacher.
* Balanced teacher daily load.
* Class-teacher subjects prefer period 1.

Teacher availability is **NOT** enforced here
---------------------------------------------
`TeacherAvailability` and approved `TeacherLeave` are dynamic/temporary
and must not block weekly generation — they are overlayed at read-time
in :func:`overlay_daily_schedule`.
"""

from __future__ import annotations

import logging
import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from modules.academics.backbone.models import (
    BellSchedulePeriod,
    ClassSubjectTeacher,
    TimetableEntry,
    TimetableVersion,
)
from modules.classes.models import ClassSubject
from modules.teachers.models import (
    TeacherAvailability,
    TeacherLeave,
    TeacherWorkloadRule,
)


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tunables — change here to adjust generator behaviour for all tenants
# ---------------------------------------------------------------------------

DEFAULT_MAX_ATTEMPTS = 40
DEFAULT_MAX_CONSECUTIVE_SAME_SUBJECT = 2
DEFAULT_MAX_SAME_SUBJECT_PER_DAY = 2
DEFAULT_TEACHER_MAX_DAY = 6
DEFAULT_TEACHER_MAX_WEEK = 30

# Scoring weights — slots_filled dominates so we always prefer more
# placements; penalties act as tie-breakers between equally full results.
SCORE_SLOT_WEIGHT = 100
PENALTY_SUBJECT_CLUSTER = 6     # per same-subject repeat on the same day
PENALTY_TEACHER_STREAK = 4      # per extra period in a 3+ consecutive streak
PENALTY_LOAD_IMBALANCE = 2      # per teacher-day near / at the daily cap
PENALTY_UNPLACED = 50           # per unplaced period

# ISO 1=Mon … 7=Sun
_DAY_NAMES = ["", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass
class _Candidate:
    """A teacher eligible to teach a class_subject, ranked by role."""
    teacher_id: str
    role: str           # 'primary' | 'assistant' | 'guest'
    rank: int           # 0 for primary (best), 1 for assistant, 2 for guest


@dataclass
class _SubjectSpec:
    """Everything the scheduler needs about one subject offering."""
    class_subject_id: str
    subject_name: str
    weekly_periods: int
    is_mandatory: bool
    candidates: List[_Candidate]         # ordered best-first
    is_class_teacher_subject: bool = False


@dataclass
class _Placement:
    class_subject_id: str
    subject_name: str
    teacher_id: str
    teacher_role: str
    day_of_week: int
    period_number: int


@dataclass
class _AttemptResult:
    placements: List[_Placement] = field(default_factory=list)
    unplaced: List[Dict[str, Any]] = field(default_factory=list)
    debug: List[str] = field(default_factory=list)
    score: int = 0


# ---------------------------------------------------------------------------
# Loader — pure DB access, returns plain data shapes the algorithm uses
# ---------------------------------------------------------------------------

def _load_subject_specs(
    tenant_id: str,
    class_id: str,
    class_teacher_user_id: Optional[str],
) -> Tuple[List[_SubjectSpec], List[str]]:
    """Build one :class:`_SubjectSpec` per active class_subject.

    Returns ``(specs, warnings)``.  Warnings list offerings that cannot be
    scheduled (no assigned teacher) so the caller can surface them.
    """
    warnings: List[str] = []
    offerings: List[ClassSubject] = (
        ClassSubject.query.filter_by(tenant_id=tenant_id, class_id=class_id)
        .filter(ClassSubject.deleted_at.is_(None), ClassSubject.status == "active")
        .order_by(ClassSubject.sort_order.asc().nulls_last(), ClassSubject.id)
        .all()
    )

    specs: List[_SubjectSpec] = []
    for cs in offerings:
        weekly = int(cs.weekly_periods or 0)
        if weekly <= 0:
            continue

        subject_name = cs.subject_ref.name if cs.subject_ref else cs.id
        candidates = _candidates_for_class_subject(tenant_id, cs.id)
        if not candidates:
            warnings.append(
                f"No teacher assigned for subject '{subject_name}' — skipping"
            )
            continue

        # A class_subject is considered the "class teacher's" subject when
        # its primary teacher's user_id matches the class homeroom teacher.
        # This gives it a weak preference for period 1.
        is_ct_subject = False
        if class_teacher_user_id:
            primary = candidates[0]
            # Look up Teacher.user_id indirectly via CST → Teacher row.
            # Avoid N+1 — keep this lightweight, only called once per subject.
            from modules.teachers.models import Teacher  # local import avoids cycles
            t = Teacher.query.filter_by(
                id=primary.teacher_id, tenant_id=tenant_id
            ).first()
            if t and str(t.user_id) == str(class_teacher_user_id):
                is_ct_subject = True

        specs.append(
            _SubjectSpec(
                class_subject_id=cs.id,
                subject_name=subject_name,
                weekly_periods=weekly,
                is_mandatory=bool(cs.is_mandatory),
                candidates=candidates,
                is_class_teacher_subject=is_ct_subject,
            )
        )

    return specs, warnings


def _candidates_for_class_subject(tenant_id: str, class_subject_id: str) -> List[_Candidate]:
    """Ordered teacher candidates: primary → assistants → guests."""
    rows: List[ClassSubjectTeacher] = (
        ClassSubjectTeacher.query.filter(
            ClassSubjectTeacher.tenant_id == tenant_id,
            ClassSubjectTeacher.class_subject_id == class_subject_id,
            ClassSubjectTeacher.is_active.is_(True),
            ClassSubjectTeacher.deleted_at.is_(None),
        ).all()
    )
    role_rank = {"primary": 0, "assistant": 1, "guest": 2}
    # Stable order within the same role: prefer rows that actually have a
    # ``created_at`` (they were explicitly saved), then by id.  We avoid
    # sorting by ``created_at`` itself to dodge aware-vs-naive datetime
    # TypeErrors that can happen across migrations.
    ordered = sorted(
        rows,
        key=lambda r: (
            role_rank.get(r.role, 3),
            0 if r.created_at else 1,
            r.id,
        ),
    )
    return [
        _Candidate(teacher_id=str(r.teacher_id), role=r.role, rank=role_rank.get(r.role, 3))
        for r in ordered
    ]


def _load_lesson_periods(tenant_id: str, bell_schedule_id: str) -> List[int]:
    """Return lesson period numbers in display order."""
    rows: List[BellSchedulePeriod] = (
        BellSchedulePeriod.query.filter_by(
            tenant_id=tenant_id, bell_schedule_id=bell_schedule_id
        )
        .order_by(BellSchedulePeriod.sort_order.asc(), BellSchedulePeriod.period_number.asc())
        .all()
    )
    return [int(p.period_number) for p in rows if p.period_kind == "lesson"]


def _load_teacher_workload(tenant_id: str) -> Dict[str, Tuple[int, int]]:
    """Map teacher_id → (max_per_day, max_per_week) with defaults for unlisted teachers."""
    rows = TeacherWorkloadRule.query.filter_by(tenant_id=tenant_id).all()
    return {
        str(r.teacher_id): (
            int(r.max_periods_per_day or DEFAULT_TEACHER_MAX_DAY),
            int(r.max_periods_per_week or DEFAULT_TEACHER_MAX_WEEK),
        )
        for r in rows
    }


def _load_cross_class_teacher_occupancy(
    tenant_id: str, exclude_class_id: Optional[str]
) -> Set[Tuple[str, int, int]]:
    """Return ``(teacher_id, day, period)`` tuples taken by other classes.

    Active and draft versions of **other** classes both count — we cannot
    collide with something that might go live.  All versions of *this*
    class are excluded because only one will ever be active at a time.
    """
    from core.database import db
    q = (
        db.session.query(
            TimetableEntry.teacher_id,
            TimetableEntry.day_of_week,
            TimetableEntry.period_number,
        )
        .join(TimetableVersion, TimetableEntry.timetable_version_id == TimetableVersion.id)
        .filter(
            TimetableEntry.tenant_id == tenant_id,
            TimetableEntry.entry_status == "active",
            TimetableVersion.status.in_(["active", "draft"]),
            TimetableEntry.teacher_id.isnot(None),
        )
    )
    if exclude_class_id:
        q = q.filter(TimetableVersion.class_id != exclude_class_id)
    return {(str(r[0]), int(r[1]), int(r[2])) for r in q.all()}


# ---------------------------------------------------------------------------
# Phase 1 — Day planning (which day each occurrence of a subject lands on)
# ---------------------------------------------------------------------------

def _plan_days(
    specs: Sequence[_SubjectSpec],
    working_days: List[int],
    max_same_per_day: int,
    rnd: random.Random,
) -> List[Tuple[int, _SubjectSpec]]:
    """Assign each subject's N occurrences across ``working_days``.

    Heuristics (in priority order):

    1.  Process "hardest" subjects first: higher weekly load + fewer
        candidate teachers + more constrained rank first.  This mirrors
        the Most-Constrained-Variable rule from CSP.
    2.  First N (or ``len(working_days)``) occurrences go on N distinct
        days, preferring the least-loaded day first — gives even spread.
    3.  Overflow (N > len(working_days)) goes to days already carrying
        the subject to form intentional double-periods instead of
        random 3rd-days.
    4.  Class-teacher subjects anchor Monday whenever possible.

    Result: an ordered list ``[(day, spec), …]`` grouped by day so Phase 2
    walks the timetable day-by-day.  Within each day class-teacher
    subjects come first so they win period-1 ties.
    """
    # Rank subjects — most constrained first.  Negative weekly so higher
    # counts come first; teacher count asc means single-teacher subjects
    # are placed before multi-teacher ones.
    ranked = sorted(
        specs,
        key=lambda s: (
            0 if s.is_class_teacher_subject else 1,
            -s.weekly_periods,
            len(s.candidates),
            s.class_subject_id,
        ),
    )

    day_load: Dict[int, int] = {d: 0 for d in working_days}
    day_subjects: Dict[int, List[_SubjectSpec]] = {d: [] for d in working_days}

    for spec in ranked:
        total = spec.weekly_periods
        n_unique = min(total, len(working_days))

        # --- first-pass: one occurrence per unique day ---
        if spec.is_class_teacher_subject and 1 in working_days:
            # Anchor Monday first, then least-loaded
            ordered_days = [1] + [d for d in working_days if d != 1]
        else:
            ordered_days = list(working_days)

        ordered_days.sort(key=lambda d: (day_load[d], rnd.random()))
        chosen = ordered_days[:n_unique]
        for d in chosen:
            day_subjects[d].append(spec)
            day_load[d] += 1

        # --- overflow: consolidate repeats on days already carrying spec ---
        for _ in range(total - n_unique):
            # Prefer days that already have this spec (but not at the cap)
            already = [
                d for d in working_days
                if spec in day_subjects[d] and day_subjects[d].count(spec) < max_same_per_day
            ]
            # If all such days are full, add to any day under the cap
            candidates = already or [
                d for d in working_days if day_subjects[d].count(spec) < max_same_per_day
            ]
            if not candidates:
                candidates = list(working_days)  # safety: over-cap scenarios
            target = min(
                candidates,
                key=lambda d: (
                    -day_subjects[d].count(spec),   # prefer day already holding spec
                    day_load[d],
                    rnd.random(),
                ),
            )
            day_subjects[target].append(spec)
            day_load[target] += 1

    # Flatten day-by-day, class-teacher subjects first within each day,
    # and shuffle the rest for between-attempt variety.
    plan: List[Tuple[int, _SubjectSpec]] = []
    for d in sorted(working_days):
        ct_first = [s for s in day_subjects[d] if s.is_class_teacher_subject]
        others = [s for s in day_subjects[d] if not s.is_class_teacher_subject]
        rnd.shuffle(others)
        for s in ct_first + others:
            plan.append((d, s))
    return plan


# ---------------------------------------------------------------------------
# Phase 2 — Slot validation & placement
# ---------------------------------------------------------------------------

class _SchedulerState:
    """Mutable state threaded through a single attempt."""

    __slots__ = (
        "class_grid",
        "teacher_busy",
        "teacher_day_count",
        "teacher_week_count",
        "subject_day_count",
        "subject_at",
    )

    def __init__(self, cross_teacher_busy: Set[Tuple[str, int, int]]):
        # class-grid: (day, period) → class_subject_id placed for this class
        self.class_grid: Dict[Tuple[int, int], str] = {}
        # teacher-busy: (teacher_id, day, period) — union of cross-class + own
        self.teacher_busy: Set[Tuple[str, int, int]] = set(cross_teacher_busy)
        # counts per teacher
        self.teacher_day_count: Dict[Tuple[str, int], int] = defaultdict(int)
        self.teacher_week_count: Dict[str, int] = defaultdict(int)
        # counts per (day, class_subject_id) for same-subject limits
        self.subject_day_count: Dict[Tuple[int, str], int] = defaultdict(int)
        # for fast consecutive-subject checks
        self.subject_at: Dict[Tuple[int, int], str] = {}


def is_valid_slot(
    *,
    state: _SchedulerState,
    class_subject_id: str,
    teacher_id: str,
    day: int,
    period: int,
    max_per_day_for_subject: int,
    max_consecutive: int,
    workload: Tuple[int, int],
) -> bool:
    """Return ``True`` if placing ``(class_subject, teacher)`` at
    ``(day, period)`` violates no hard constraint.

    Exposed as a helper so tests / repair passes can validate candidate
    swaps without touching the full placement logic.
    """
    if (day, period) in state.class_grid:
        return False
    if (teacher_id, day, period) in state.teacher_busy:
        return False
    if state.subject_day_count[(day, class_subject_id)] >= max_per_day_for_subject:
        return False

    max_day, max_week = workload
    if state.teacher_day_count[(teacher_id, day)] >= max_day:
        return False
    if state.teacher_week_count[teacher_id] >= max_week:
        return False

    # Consecutive-same-subject: walk back up to (max_consecutive) periods.
    streak = 1
    p = period - 1
    while p >= 1 and state.subject_at.get((day, p)) == class_subject_id:
        streak += 1
        if streak > max_consecutive:
            return False
        p -= 1
    # Also walk forward in case placements happened out-of-order (fallback days).
    p = period + 1
    while state.subject_at.get((day, p)) == class_subject_id:
        streak += 1
        if streak > max_consecutive:
            return False
        p += 1
    return True


def _commit_placement(
    state: _SchedulerState,
    class_subject_id: str,
    teacher_id: str,
    day: int,
    period: int,
) -> None:
    state.class_grid[(day, period)] = class_subject_id
    state.teacher_busy.add((teacher_id, day, period))
    state.teacher_day_count[(teacher_id, day)] += 1
    state.teacher_week_count[teacher_id] += 1
    state.subject_day_count[(day, class_subject_id)] += 1
    state.subject_at[(day, period)] = class_subject_id


def _try_place_on_day(
    *,
    spec: _SubjectSpec,
    day: int,
    lesson_periods: List[int],
    state: _SchedulerState,
    workload_map: Dict[str, Tuple[int, int]],
    max_same_per_day: int,
    max_consecutive: int,
    prefer_period_1: bool,
    rnd: random.Random,
) -> Optional[_Placement]:
    """Find the first valid (period, teacher) for ``spec`` on ``day``."""
    # Quick cap-check
    if state.subject_day_count[(day, spec.class_subject_id)] >= max_same_per_day:
        return None

    periods = list(lesson_periods)
    if prefer_period_1 and periods and periods[0] != 1 and 1 in periods:
        periods = [1] + [p for p in periods if p != 1]

    # Candidates: primary first; shuffle only *within* the same rank so
    # primary never loses to an assistant unfairly between attempts.
    by_rank: Dict[int, List[_Candidate]] = defaultdict(list)
    for c in spec.candidates:
        by_rank[c.rank].append(c)
    ranked_candidates: List[_Candidate] = []
    for rk in sorted(by_rank.keys()):
        bucket = list(by_rank[rk])
        rnd.shuffle(bucket)
        ranked_candidates.extend(bucket)

    for period in periods:
        for cand in ranked_candidates:
            workload = workload_map.get(
                cand.teacher_id, (DEFAULT_TEACHER_MAX_DAY, DEFAULT_TEACHER_MAX_WEEK)
            )
            if is_valid_slot(
                state=state,
                class_subject_id=spec.class_subject_id,
                teacher_id=cand.teacher_id,
                day=day,
                period=period,
                max_per_day_for_subject=max_same_per_day,
                max_consecutive=max_consecutive,
                workload=workload,
            ):
                return _Placement(
                    class_subject_id=spec.class_subject_id,
                    subject_name=spec.subject_name,
                    teacher_id=cand.teacher_id,
                    teacher_role=cand.role,
                    day_of_week=day,
                    period_number=period,
                )
    return None


# ---------------------------------------------------------------------------
# Scoring — evaluate one finished attempt
# ---------------------------------------------------------------------------

def _score_attempt(
    placements: Sequence[_Placement],
    unplaced_count: int,
    workload_map: Dict[str, Tuple[int, int]],
) -> int:
    """Higher = better.  Dominated by ``len(placements)``.

    * ``+ SCORE_SLOT_WEIGHT`` per placement
    * ``- PENALTY_UNPLACED`` per unplaced occurrence
    * ``- PENALTY_SUBJECT_CLUSTER`` per repeat of a subject on the same day
    * ``- PENALTY_TEACHER_STREAK`` per extra period in a 3+ teacher streak
    * ``- PENALTY_LOAD_IMBALANCE`` per teacher-day at/near daily cap
    """
    score = len(placements) * SCORE_SLOT_WEIGHT - unplaced_count * PENALTY_UNPLACED

    # Subject clustering
    per_day_subject: Dict[Tuple[int, str], int] = defaultdict(int)
    for p in placements:
        per_day_subject[(p.day_of_week, p.class_subject_id)] += 1
    for count in per_day_subject.values():
        if count > 1:
            score -= (count - 1) * PENALTY_SUBJECT_CLUSTER

    # Teacher back-to-back streaks (3+)
    periods_by_teacher_day: Dict[Tuple[str, int], List[int]] = defaultdict(list)
    for p in placements:
        periods_by_teacher_day[(p.teacher_id, p.day_of_week)].append(p.period_number)
    for _key, periods in periods_by_teacher_day.items():
        periods.sort()
        streak = 1
        for i in range(1, len(periods)):
            if periods[i] == periods[i - 1] + 1:
                streak += 1
            else:
                if streak >= 3:
                    score -= (streak - 2) * PENALTY_TEACHER_STREAK
                streak = 1
        if streak >= 3:
            score -= (streak - 2) * PENALTY_TEACHER_STREAK

    # Load imbalance near daily cap
    day_counts: Dict[Tuple[str, int], int] = defaultdict(int)
    for p in placements:
        day_counts[(p.teacher_id, p.day_of_week)] += 1
    for (tid, _d), count in day_counts.items():
        cap = workload_map.get(tid, (DEFAULT_TEACHER_MAX_DAY, DEFAULT_TEACHER_MAX_WEEK))[0]
        if count >= cap:
            score -= PENALTY_LOAD_IMBALANCE * 2
        elif count == cap - 1:
            score -= PENALTY_LOAD_IMBALANCE
    return score


# ---------------------------------------------------------------------------
# Single attempt — plan + place + score
# ---------------------------------------------------------------------------

def _run_attempt(
    specs: Sequence[_SubjectSpec],
    working_days: List[int],
    lesson_periods: List[int],
    cross_teacher_busy: Set[Tuple[str, int, int]],
    workload_map: Dict[str, Tuple[int, int]],
    *,
    max_consecutive: int,
    max_same_per_day: int,
    rnd: random.Random,
) -> _AttemptResult:
    state = _SchedulerState(cross_teacher_busy)
    result = _AttemptResult()

    day_plan = _plan_days(specs, working_days, max_same_per_day, rnd)

    for day, spec in day_plan:
        placed = _try_place_on_day(
            spec=spec,
            day=day,
            lesson_periods=lesson_periods,
            state=state,
            workload_map=workload_map,
            max_same_per_day=max_same_per_day,
            max_consecutive=max_consecutive,
            prefer_period_1=spec.is_class_teacher_subject,
            rnd=rnd,
        )
        if placed is None:
            # Fallback: try other working days.  Prefer the day with the
            # fewest occurrences of this subject so we don't create a
            # new cluster in the escape route.
            fallback_days = sorted(
                (d for d in working_days if d != day),
                key=lambda d: (
                    state.subject_day_count[(d, spec.class_subject_id)],
                    -len(lesson_periods) + sum(
                        1 for p in lesson_periods if (d, p) in state.class_grid
                    ),  # prefer days with more free slots
                    rnd.random(),
                ),
            )
            for alt_day in fallback_days:
                placed = _try_place_on_day(
                    spec=spec,
                    day=alt_day,
                    lesson_periods=lesson_periods,
                    state=state,
                    workload_map=workload_map,
                    max_same_per_day=max_same_per_day,
                    max_consecutive=max_consecutive,
                    prefer_period_1=spec.is_class_teacher_subject,
                    rnd=rnd,
                )
                if placed is not None:
                    break

        if placed is None:
            result.unplaced.append({
                "class_subject_id": spec.class_subject_id,
                "subject_name": spec.subject_name,
                "planned_day": day,
                "reason": _diagnose_unplaced(spec, state, lesson_periods, workload_map),
            })
            continue

        _commit_placement(
            state,
            placed.class_subject_id,
            placed.teacher_id,
            placed.day_of_week,
            placed.period_number,
        )
        result.placements.append(placed)

    result.score = _score_attempt(result.placements, len(result.unplaced), workload_map)
    return result


def _diagnose_unplaced(
    spec: _SubjectSpec,
    state: _SchedulerState,
    lesson_periods: List[int],
    workload_map: Dict[str, Tuple[int, int]],
) -> str:
    """Best-effort human-readable reason the subject could not be placed.

    Used for debug logs / UI warnings so the admin knows what to fix.
    """
    all_teachers_at_cap = all(
        state.teacher_week_count[c.teacher_id]
        >= workload_map.get(c.teacher_id, (DEFAULT_TEACHER_MAX_DAY, DEFAULT_TEACHER_MAX_WEEK))[1]
        for c in spec.candidates
    )
    if all_teachers_at_cap:
        return "All candidate teachers reached their weekly workload cap"

    # Count remaining free slots across the grid (union of all working-day keys seen)
    busy_days = {d for d, _p in state.class_grid.keys()}
    free_any = 0
    for d in busy_days:
        for p in lesson_periods:
            if (d, p) not in state.class_grid:
                free_any += 1
    if free_any == 0 and state.class_grid:
        return "No free periods remain in the weekly grid"

    # Check if every free slot conflicts with at least one candidate
    return (
        "No feasible slot found — every remaining period conflicts with another class, "
        "exceeds the subject-per-day cap, or would break a constraint"
    )


# ---------------------------------------------------------------------------
# Public entry point — multi-attempt driver
# ---------------------------------------------------------------------------

def generate_timetable(
    tenant_id: str,
    class_id: str,
    *,
    bell_schedule_id: str,
    working_days: List[int],
    class_teacher_user_id: Optional[str] = None,
    exclude_class_id: Optional[str] = None,
    seed: Optional[int] = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    max_consecutive_same_subject: int = DEFAULT_MAX_CONSECUTIVE_SAME_SUBJECT,
    max_same_subject_per_day: int = DEFAULT_MAX_SAME_SUBJECT_PER_DAY,
) -> Dict[str, Any]:
    """Build a feasible weekly timetable (no persistence).

    The caller is responsible for wrapping the returned placements in a
    ``TimetableVersion`` / ``TimetableEntry`` set inside a transaction.

    Returns a dict::

        {
          "success": bool,
          "placements": [
              {class_subject_id, subject_name, teacher_id, teacher_role,
               day_of_week, period_number}, …
          ],
          "unplaced": [{class_subject_id, subject_name, planned_day, reason}, …],
          "warnings": [str, …],
          "quality_score": int,          # higher is better
          "draft_quality": "excellent" | "good" | "fair" | "poor",
          "timetable": {                 # day-grouped view for UIs
              "Mon": [{period, subject, teacher, teacher_id, class_subject_id}, …],
              …
          },
          "debug": [str, …],             # per-attempt diagnostics
        }
    """
    if not bell_schedule_id:
        return _fail("bell_schedule_id is required")
    if not working_days:
        return _fail("working_days must be non-empty (ISO 1=Mon … 7=Sun)")

    specs, warnings = _load_subject_specs(tenant_id, class_id, class_teacher_user_id)
    if not specs:
        return {
            "success": False,
            "error": "No schedulable subjects — add class subjects and assign teachers first",
            "warnings": warnings,
            "placements": [],
            "unplaced": [],
            "quality_score": 0,
            "timetable": {},
            "debug": [],
        }

    lesson_periods = _load_lesson_periods(tenant_id, bell_schedule_id)
    if not lesson_periods:
        return _fail("Bell schedule has no lesson periods configured")

    # Feasibility sanity check — we cannot fit more periods than slots
    total_needed = sum(s.weekly_periods for s in specs)
    total_slots = len(working_days) * len(lesson_periods)
    if total_needed > total_slots:
        return {
            "success": False,
            "error": (
                f"Cannot fit {total_needed} weekly periods into {total_slots} available slots "
                f"({len(working_days)} days × {len(lesson_periods)} lesson periods). "
                "Reduce weekly_periods, add more lesson periods, or add working days."
            ),
            "warnings": warnings,
            "placements": [],
            "unplaced": [],
            "quality_score": 0,
            "timetable": {},
            "debug": [],
        }

    cross_teacher_busy = _load_cross_class_teacher_occupancy(tenant_id, exclude_class_id or class_id)
    workload_map = _load_teacher_workload(tenant_id)

    rng = random.Random(seed)
    best: Optional[_AttemptResult] = None
    debug_logs: List[str] = []

    for attempt_idx in range(max_attempts):
        # Each attempt gets its own Random so reseeding still produces
        # diverse plans while the outer seed fully reproduces the batch.
        inner = random.Random(rng.random())
        result = _run_attempt(
            specs,
            working_days,
            lesson_periods,
            cross_teacher_busy,
            workload_map,
            max_consecutive=max_consecutive_same_subject,
            max_same_per_day=max_same_subject_per_day,
            rnd=inner,
        )
        debug_logs.append(
            f"attempt={attempt_idx + 1} score={result.score} "
            f"placed={len(result.placements)}/{total_needed} "
            f"unplaced={len(result.unplaced)}"
        )

        if best is None or result.score > best.score:
            best = result

        # Early exit on a perfect run
        if best and not best.unplaced:
            # Keep iterating only if we might improve soft-penalty score.
            # An arbitrary small budget is enough for a perfect solution.
            if attempt_idx >= 5:
                break

    assert best is not None
    draft_quality = _classify_quality(best, total_needed)

    return {
        "success": True,
        "placements": [_placement_to_dict(p) for p in best.placements],
        "unplaced": best.unplaced,
        "warnings": warnings,
        "quality_score": best.score,
        "draft_quality": draft_quality,
        "timetable": _group_by_day(best.placements),
        "debug": debug_logs,
    }


def _classify_quality(best: _AttemptResult, total_needed: int) -> str:
    if total_needed == 0:
        return "excellent"
    ratio = len(best.placements) / total_needed
    if ratio >= 1.0 and best.score >= total_needed * SCORE_SLOT_WEIGHT - 10:
        return "excellent"
    if ratio >= 1.0:
        return "good"
    if ratio >= 0.9:
        return "fair"
    return "poor"


def _placement_to_dict(p: _Placement) -> Dict[str, Any]:
    return {
        "class_subject_id": p.class_subject_id,
        "subject_name": p.subject_name,
        "teacher_id": p.teacher_id,
        "teacher_role": p.teacher_role,
        "day_of_week": p.day_of_week,
        "period_number": p.period_number,
    }


def _group_by_day(placements: Sequence[_Placement]) -> Dict[str, List[Dict[str, Any]]]:
    """Return ``{"Mon": [{period, subject, teacher_id}, …], …}`` for UI consumption."""
    grid: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for p in sorted(placements, key=lambda x: (x.day_of_week, x.period_number)):
        label = _DAY_NAMES[p.day_of_week] if 1 <= p.day_of_week < len(_DAY_NAMES) else str(p.day_of_week)
        grid[label].append({
            "period": p.period_number,
            "class_subject_id": p.class_subject_id,
            "subject": p.subject_name,
            "teacher_id": p.teacher_id,
            "teacher_role": p.teacher_role,
        })
    return dict(grid)


def _fail(msg: str) -> Dict[str, Any]:
    return {
        "success": False,
        "error": msg,
        "warnings": [],
        "placements": [],
        "unplaced": [],
        "quality_score": 0,
        "timetable": {},
        "debug": [],
    }


# ---------------------------------------------------------------------------
# Read-side overlay — teacher availability & approved leave
# ---------------------------------------------------------------------------

def overlay_daily_schedule(
    tenant_id: str,
    entries: Sequence[Dict[str, Any]],
    on_date,
) -> List[Dict[str, Any]]:
    """Overlay teacher availability / leave on top of a day's timetable.

    ``entries`` should already be filtered to a single ``day_of_week`` and
    each dict must contain ``teacher_id`` and ``period_number``.  The
    returned list is a shallow copy of each entry augmented with
    ``availability_status`` (``'available'`` | ``'unavailable'`` |
    ``'on_leave'``) and ``substitute_needed`` (bool).

    The weekly generator ignores these fields on purpose — they change
    daily and rebuilding the whole timetable when a teacher calls in sick
    would wipe the class's stable schedule.  This function is the
    read-time equivalent.
    """
    day_of_week = entries[0]["day_of_week"] if entries else None
    teacher_ids = {e["teacher_id"] for e in entries if e.get("teacher_id")}

    # Availability blocks (not available = explicit unavailability)
    avail_blocked: Set[Tuple[str, int]] = set()
    if day_of_week is not None and teacher_ids:
        rows = TeacherAvailability.query.filter(
            TeacherAvailability.tenant_id == tenant_id,
            TeacherAvailability.teacher_id.in_(teacher_ids),
            TeacherAvailability.day_of_week == day_of_week,
            TeacherAvailability.available.is_(False),
        ).all()
        avail_blocked = {(str(r.teacher_id), int(r.period_number)) for r in rows}

    # Approved leaves covering on_date
    on_leave: Set[str] = set()
    if teacher_ids:
        leaves = TeacherLeave.query.filter(
            TeacherLeave.tenant_id == tenant_id,
            TeacherLeave.teacher_id.in_(teacher_ids),
            TeacherLeave.status == TeacherLeave.STATUS_APPROVED,
            TeacherLeave.start_date <= on_date,
            TeacherLeave.end_date >= on_date,
        ).all()
        on_leave = {str(l.teacher_id) for l in leaves}

    out: List[Dict[str, Any]] = []
    for e in entries:
        tid = str(e.get("teacher_id") or "")
        pnum = int(e.get("period_number") or 0)
        enriched = dict(e)
        if tid and tid in on_leave:
            enriched["availability_status"] = "on_leave"
            enriched["substitute_needed"] = True
        elif tid and (tid, pnum) in avail_blocked:
            enriched["availability_status"] = "unavailable"
            enriched["substitute_needed"] = True
        else:
            enriched["availability_status"] = "available"
            enriched["substitute_needed"] = False
        out.append(enriched)
    return out
