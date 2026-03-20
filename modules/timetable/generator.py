"""
Smart Timetable Generator v2  —  Spread-First Balanced Algorithm

WHY THE OLD GREEDY FAILED
  The previous algorithm iterated (day, period) and picked any valid subject.
  Because it always scanned from day 0 and chose from a shuffled pool, subjects
  with higher weekly counts ended up clustering on early days:
      English×3 → Mon P1, Mon P2, Mon P3  ← bad
      instead of  → Mon P1, Wed P2, Fri P3  ← good

NEW ALGORITHM: Two-Phase Spread-First

PHASE 1 — Day Planning  (per attempt, randomised for variety)
  ─────────────────────────────────────────────────────────
  For every unique subject S with N weekly periods:
  a) Spread first occurrences across N distinct days (lowest-load days win).
  b) Extra occurrences (when N > 5) are consolidated on days that already
     have one occurrence of S — this naturally produces double-period blocks
     (subject appears in both morning & afternoon of the same day, which is
     real-world acceptable and explicitly allowed by the user).
  c) Class-teacher subjects are anchored to include Monday as a preference.

  Result: a list of (day, subject_id) pairs, sorted by day,
          class-teacher subjects listed first within each day.

PHASE 2 — Period Filling  (constraint-satisfying)
  ────────────────────────────────────────────────
  For each (day, subject) pair from Phase 1:
  1. Try all available periods on the target day.
     • Period 1 is always tried first for class-teacher subjects.
     • Consecutive-subject constraint is checked against already-placed
       periods on that day (using a placed_grid dict).
  2. If no slot available on the target day → fallback to the least-burdened
     alternate day that still has capacity for this subject.
  3. If still no slot → record as conflict (informative message).

SCORING  (weighted greedy)
  Each attempt is evaluated by a composite score:
    score = slots_filled × SCORE_SLOT_WEIGHT
            − teacher_consecutive_penalty
            − subject_cluster_penalty
            − teacher_overload_penalty
  slots_filled dominates; penalties act as tie-breakers to prefer
  higher-quality distributions when filling counts are equal.
  MAX_ATTEMPTS are run; the highest-scoring result is saved.

HARD CONSTRAINTS (all enforced in Phase 2)
  1. Teacher cannot be double-booked across classes at the same (day, period).
  2. Teacher availability records (TeacherAvailability.available = False).
  3. Teacher approved leave on this week's calendar dates.
  4. Teacher max_periods_per_day / max_periods_per_week (TeacherWorkloadRule).
  5. Max MAX_SAME_SUBJECT_PER_DAY occurrences of the same subject per day.
  6. Max MAX_CONSECUTIVE_SAME_SUBJECT consecutive periods of the same subject.

SOFT PREFERENCES
  • Class-teacher subjects placed in period 1 each day when possible.
  • Subjects spread across as many different days as their weekly count allows.
  • Repeat occurrences grouped on the same day (double/triple periods) rather
    than scattered randomly, making the timetable feel intentional.
"""

import random
import uuid
from collections import Counter, defaultdict
from datetime import date, time, timedelta
from typing import Dict, List, Optional, Set, Tuple

from backend.core.database import db
from backend.core.tenant import get_tenant_id
from backend.modules.classes.models import Class, ClassTeacher, SubjectLoad
from backend.modules.teachers.models import (
    Teacher,
    TeacherAvailability,
    TeacherLeave,
    TeacherSubject,
    TeacherWorkloadRule,
)
from .models import TimetableSlot, TimetableConfig

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

DAYS_PER_WEEK = 5           # Mon–Fri
MAX_ATTEMPTS = 30           # Attempts with different random plans
MAX_SAME_SUBJECT_PER_DAY = 2
MAX_CONSECUTIVE_SAME_SUBJECT = 2

# Scoring weights — slots_filled dominates; penalties are tie-breakers
SCORE_SLOT_WEIGHT = 100
PENALTY_TEACHER_CONSECUTIVE = 3   # per extra period in a 3+ consecutive streak
PENALTY_SUBJECT_CLUSTER = 2       # per repeat-on-same-day occurrence
PENALTY_TEACHER_OVERLOAD = 1      # per teacher-day at or near daily max

# Fallback period schedule when no TimetableConfig exists
_DEFAULT_PERIOD_SCHEDULE: List[Tuple[time, time]] = [
    (time(8,  0),  time(8,  50)),
    (time(9,  0),  time(9,  45)),
    (time(9,  50), time(10, 35)),
    (time(10, 40), time(11, 25)),
    (time(11, 30), time(12, 15)),
    (time(12, 20), time(13,  5)),
    (time(13, 10), time(13, 55)),
    (time(14,  0), time(14, 45)),
]

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
             "Saturday", "Sunday"]


# ---------------------------------------------------------------------------
# Schedule helpers
# ---------------------------------------------------------------------------

def _compute_period_schedule(config: Optional[TimetableConfig]) -> Tuple[List[Tuple[time, time]], int]:
    """Compute (start, end) for each period from TimetableConfig."""
    if not config:
        return (_DEFAULT_PERIOD_SCHEDULE, 8)

    breaks_by_period: Dict[int, int] = {}
    for b in config.get_breaks():
        after = b.get("after_period")
        dur = b.get("duration_minutes", 0)
        if after is not None and dur and after >= 1:
            breaks_by_period[after] = dur

    schedule: List[Tuple[time, time]] = []
    start = config.school_start_time
    gap_min = config.gap_between_classes_minutes or 5

    for p in range(1, config.periods_per_day + 1):
        dur_min = (
            config.first_class_duration_minutes
            if p == 1
            else config.general_class_duration_minutes
        )
        total_end_minutes = start.hour * 60 + start.minute + dur_min
        end = time(total_end_minutes // 60, total_end_minutes % 60)
        schedule.append((start, end))

        # Advance start by gap + optional break after this period
        advance = gap_min + breaks_by_period.get(p, 0)
        total_start_minutes = total_end_minutes + advance
        start = time(total_start_minutes // 60, total_start_minutes % 60)

    return (schedule, config.periods_per_day)


def _period_times(period_number: int, schedule: List[Tuple[time, time]]) -> Tuple[time, time]:
    idx = max(0, min(period_number - 1, len(schedule) - 1))
    return schedule[idx]


def _monday_of_week(today: Optional[date] = None) -> date:
    d = today or date.today()
    return d - timedelta(days=d.weekday())


# ---------------------------------------------------------------------------
# Data loader
# ---------------------------------------------------------------------------

class _ConstraintData:
    """Loads and caches all constraint data from the DB before generation."""

    def __init__(self, class_id: str, tenant_id: str, overwrite: bool):
        self.class_id = class_id
        self.tenant_id = tenant_id

        self.cls = Class.query.filter_by(id=class_id, tenant_id=tenant_id).first()

        # Timetable config
        self.config = TimetableConfig.query.filter_by(tenant_id=tenant_id).first()
        self.period_schedule, self.periods_per_day = _compute_period_schedule(self.config)

        # Class-teacher subject IDs for period-1 prioritisation
        self.class_teacher_subject_ids: Set[str] = set()
        if self.cls and self.cls.teacher_id:
            ct_row = ClassTeacher.query.filter_by(
                class_id=class_id, tenant_id=tenant_id, is_class_teacher=True
            ).first()
            if ct_row and ct_row.subject_id:
                self.class_teacher_subject_ids.add(ct_row.subject_id)
            else:
                teacher = Teacher.query.filter_by(
                    tenant_id=tenant_id, user_id=self.cls.teacher_id
                ).first()
                if teacher:
                    for ts in TeacherSubject.query.filter_by(
                        tenant_id=tenant_id, teacher_id=teacher.id
                    ).all():
                        self.class_teacher_subject_ids.add(ts.subject_id)

        # Subject loads → expanded pool
        loads = SubjectLoad.query.filter_by(class_id=class_id, tenant_id=tenant_id).all()
        self.full_subject_pool: List[str] = []
        for load in loads:
            self.full_subject_pool.extend([load.subject_id] * load.weekly_periods)
        self.subject_load_map: Dict[str, int] = {
            load.subject_id: load.weekly_periods for load in loads
        }

        # Teacher expertise per subject (same teacher may cover multiple subjects)
        ts_rows = TeacherSubject.query.filter_by(tenant_id=tenant_id).all()
        self.teachers_by_subject: Dict[str, List[str]] = {}
        for ts in ts_rows:
            self.teachers_by_subject.setdefault(ts.subject_id, []).append(ts.teacher_id)

        # Teacher availability blocks (1-indexed day → 0-indexed)
        avail_rows = TeacherAvailability.query.filter_by(tenant_id=tenant_id).all()
        self.avail_blocked: Set[Tuple[str, int, int]] = set()
        for a in avail_rows:
            if not a.available:
                day0 = a.day_of_week - 1
                if 0 <= day0 < DAYS_PER_WEEK:
                    self.avail_blocked.add((a.teacher_id, day0, a.period_number))

        # Approved leaves this week
        monday = _monday_of_week()
        leave_rows = TeacherLeave.query.filter_by(
            tenant_id=tenant_id, status=TeacherLeave.STATUS_APPROVED
        ).all()
        self.leave_blocked: Set[Tuple[str, int]] = set()
        for leave in leave_rows:
            for day_offset in range(DAYS_PER_WEEK):
                slot_date = monday + timedelta(days=day_offset)
                if leave.start_date <= slot_date <= leave.end_date:
                    self.leave_blocked.add((leave.teacher_id, day_offset))

        # Workload rules (default 6/day, 30/week)
        rule_rows = TeacherWorkloadRule.query.filter_by(tenant_id=tenant_id).all()
        self.workload: Dict[str, Tuple[int, int]] = {
            r.teacher_id: (r.max_periods_per_day, r.max_periods_per_week)
            for r in rule_rows
        }

        # Cross-class teacher occupancy
        other_slots = (
            TimetableSlot.query
            .filter_by(tenant_id=tenant_id)
            .filter(TimetableSlot.class_id != class_id)
            .all()
        )
        self.cross_occupied: Set[Tuple[str, int, int]] = {
            (s.teacher_id, s.day_of_week, s.period_number) for s in other_slots
        }

        # Existing slots for this class
        self.existing_slots = (
            TimetableSlot.query
            .filter_by(tenant_id=tenant_id, class_id=class_id)
            .all()
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_timetable(class_id: str, overwrite_existing: bool) -> Dict:
    """
    Generate and persist a balanced weekly timetable for a class.

    Returns:
        {
            "success": bool,
            "slots_created": int,
            "total_periods_needed": int,
            "conflicts": [{"reason": str, ...}]
        }
    """
    tenant_id = get_tenant_id()
    if not tenant_id:
        return {"success": False, "error": "Tenant context is required"}

    data = _ConstraintData(class_id, tenant_id, overwrite_existing)

    if data.cls is None:
        return {"success": False, "error": "Class not found"}

    if not data.full_subject_pool:
        return {
            "success": False,
            "error": (
                "No subject loads configured for this class. "
                "Go to Class → Subject Weekly Load and add subjects first."
            ),
        }

    subjects_with_teachers = [
        s for s in set(data.full_subject_pool)
        if data.teachers_by_subject.get(s)
    ]
    if not subjects_with_teachers:
        return {
            "success": False,
            "error": (
                "No teachers have been assigned subject expertise for any of this class's subjects. "
                "Go to Teacher → Subjects and assign expertise first."
            ),
        }

    # Handle overwrite vs incremental
    if overwrite_existing:
        TimetableSlot.query.filter_by(tenant_id=tenant_id, class_id=class_id).delete()
        db.session.flush()
        subject_pool = data.full_subject_pool.copy()
        occupied_grid: Set[Tuple[int, int]] = set()
        initial_placements: List[Dict] = []
    else:
        occupied_grid = {
            (s.day_of_week, s.period_number) for s in data.existing_slots
        }
        already_placed = [s.subject_id for s in data.existing_slots]
        subject_pool = data.full_subject_pool.copy()
        for sid in already_placed:
            if sid in subject_pool:
                subject_pool.remove(sid)
        for s in data.existing_slots:
            data.cross_occupied.add((s.teacher_id, s.day_of_week, s.period_number))
        # Pre-populate placed_grid so consecutive checks work across existing slots
        initial_placements = [
            {"day": s.day_of_week, "period": s.period_number, "subject_id": s.subject_id}
            for s in data.existing_slots
        ]

    total_needed = len(subject_pool)
    total_slots = DAYS_PER_WEEK * data.periods_per_day

    if total_needed == 0:
        return {"success": True, "slots_created": 0, "total_periods_needed": 0, "conflicts": []}

    if total_needed > total_slots:
        return {
            "success": False,
            "error": (
                f"Cannot fit {total_needed} periods into {total_slots} available slots "
                f"({DAYS_PER_WEEK} days × {data.periods_per_day} periods/day). "
                "Reduce subject loads or increase periods per day in Timetable Config."
            ),
        }

    # Diagnostic: warn about subjects with no teacher
    subjects_no_teacher = [
        s for s in set(subject_pool)
        if not data.teachers_by_subject.get(s)
    ]

    # Run multiple attempts, keep the best-scoring result.
    # Score = slots_filled * weight - penalties, so higher is better.
    # A perfect score means every slot filled with zero penalties.
    best_result: Optional[Dict] = None
    best_score = -1
    perfect_score = total_needed * SCORE_SLOT_WEIGHT

    for _ in range(MAX_ATTEMPTS):
        result = _greedy_attempt(
            subject_pool=subject_pool,
            occupied_grid=occupied_grid,
            teachers_by_subject=data.teachers_by_subject,
            avail_blocked=data.avail_blocked,
            leave_blocked=data.leave_blocked,
            workload=data.workload,
            cross_occupied=data.cross_occupied,
            periods_per_day=data.periods_per_day,
            period_schedule=data.period_schedule,
            class_teacher_subject_ids=data.class_teacher_subject_ids,
            initial_placements=initial_placements,
        )

        if result["score"] > best_score:
            best_score = result["score"]
            best_result = result

        if best_score >= perfect_score:
            break

    assert best_result is not None

    # Persist best result
    saved_count = 0
    for s in best_result["slots"]:
        slot = TimetableSlot(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            class_id=class_id,
            subject_id=s["subject_id"],
            teacher_id=s["teacher_id"],
            day_of_week=s["day"],
            period_number=s["period"],
            start_time=s["start_time"],
            end_time=s["end_time"],
        )
        db.session.add(slot)
        saved_count += 1

    db.session.commit()

    # Enrich conflicts with subject-no-teacher info
    conflicts = best_result["conflicts"]
    for sid in subjects_no_teacher:
        conflicts.append({
            "subject_id": sid,
            "reason": "No teacher assigned with expertise for this subject (Teacher → Subjects)",
        })

    return {
        "success": True,
        "slots_created": saved_count,
        "total_periods_needed": total_needed,
        "conflicts": conflicts,
    }


# ---------------------------------------------------------------------------
# Phase 1 — Balanced Day Planning
# ---------------------------------------------------------------------------

def _build_balanced_day_plan(
    subject_pool: List[str],
    ct_subjects: Set[str],
) -> List[Tuple[int, str]]:
    """
    Compute a balanced (day, subject_id) assignment list.

    Strategy
    ────────
    For each unique subject S with N weekly periods:

    1. SPREAD first occurrences across N different days (prefer lowest-load days).
       Class-teacher subjects anchor to Monday first.

    2. CONSOLIDATE extra occurrences (N > DAYS_PER_WEEK) onto days already
       carrying one occurrence of S, creating intentional double-periods
       (e.g. Maths appears at period 2 AND period 6 on Wednesday — acceptable
       and common in real schools).

    3. Within each day, list class-teacher subjects first (they get period 1).
       Remaining subjects are shuffled for variety between attempts.

    Returns: sorted list of (day_index, subject_id) by day.
    """
    counts = Counter(subject_pool)

    # Rank: CT subjects first, then higher-count subjects (hardest to spread first)
    ranked_subjects = sorted(
        counts.keys(),
        key=lambda s: (0 if s in ct_subjects else 1, -counts[s], random.random()),
    )

    day_assignments: Dict[int, List[str]] = defaultdict(list)
    day_load = [0] * DAYS_PER_WEEK

    for subject_id in ranked_subjects:
        total = counts[subject_id]
        n_unique = min(total, DAYS_PER_WEEK)

        # --- First occurrences: one per unique day ---
        if subject_id in ct_subjects:
            # CT subjects prefer Mon (day 0) first
            day_order = [0] + [d for d in range(1, DAYS_PER_WEEK)]
        else:
            day_order = list(range(DAYS_PER_WEEK))

        # Sort by current load (ascending), random tie-breaking gives variety
        days_sorted = sorted(day_order, key=lambda d: (day_load[d], random.random()))
        chosen_unique = days_sorted[:n_unique]

        for d in chosen_unique:
            day_assignments[d].append(subject_id)
            day_load[d] += 1

        # --- Extra occurrences: consolidate on existing days ---
        for _ in range(total - n_unique):
            # Prefer days that already have one occurrence of S and are least loaded
            candidates = [
                d for d in range(DAYS_PER_WEEK)
                if day_assignments[d].count(subject_id) < MAX_SAME_SUBJECT_PER_DAY
            ]
            if not candidates:
                candidates = list(range(DAYS_PER_WEEK))  # safety fallback

            best = min(
                candidates,
                key=lambda d: (
                    -day_assignments[d].count(subject_id),  # prefer consolidation
                    day_load[d],
                    random.random(),
                ),
            )
            day_assignments[best].append(subject_id)
            day_load[best] += 1

    # Build output with two-pass ordering per day:
    #   FIRST PASS  — subjects appearing for the first time this day (unique)
    #   SECOND PASS — repeat occurrences (needed when weekly load > days)
    # Within each pass, CT subjects stay first; others are shuffled.
    result: List[Tuple[int, str]] = []
    for day in range(DAYS_PER_WEEK):
        subjects = list(day_assignments[day])
        ct_part = [s for s in subjects if s in ct_subjects]
        other_part = [s for s in subjects if s not in ct_subjects]
        random.shuffle(other_part)
        ordered = ct_part + other_part

        seen: Set[str] = set()
        first_pass: List[Tuple[int, str]] = []
        second_pass: List[Tuple[int, str]] = []
        for s in ordered:
            if s not in seen:
                first_pass.append((day, s))
                seen.add(s)
            else:
                second_pass.append((day, s))

        random.shuffle(second_pass)
        result.extend(first_pass + second_pass)

    return result


# ---------------------------------------------------------------------------
# Phase 2 — Period Filling (per day-subject assignment)
# ---------------------------------------------------------------------------

def _try_place_on_day(
    day: int,
    subject_id: str,
    avail_periods: List[int],           # sorted ascending; DO NOT mutate here
    subject_day_count: Dict[int, Dict[str, int]],
    placed_grid: Dict[Tuple[int, int], str],   # (day, period) → subject_id
    teachers_by_subject: Dict[str, List[str]],
    avail_blocked: Set[Tuple[str, int, int]],
    leave_blocked: Set[Tuple[str, int]],
    workload: Dict[str, Tuple[int, int]],
    cross_occupied: Set[Tuple[str, int, int]],
    this_occupied: Set[Tuple[str, int, int]],
    teacher_day_count: Dict[str, Dict[int, int]],
    teacher_week_count: Dict[str, int],
    schedule: List[Tuple[time, time]],
    prefer_period_1: bool = False,
) -> Optional[Dict]:
    """
    Find the first valid (period, teacher) for subject_id on the given day.
    Returns a slot dict on success, or None if no valid slot exists.
    """
    sdc = subject_day_count[day]

    # Hard cap: cannot exceed MAX_SAME_SUBJECT_PER_DAY occurrences
    if sdc.get(subject_id, 0) >= MAX_SAME_SUBJECT_PER_DAY:
        return None

    candidates = list(teachers_by_subject.get(subject_id, []))
    if not candidates:
        return None
    random.shuffle(candidates)

    # Period ordering: class-teacher subjects try period 1 first
    periods = sorted(avail_periods)
    if prefer_period_1 and 1 in periods:
        periods = [1] + [p for p in periods if p != 1]

    for period in periods:
        # Consecutive constraint: scan what's at periods p-1 and p-2
        if (
            period > 2
            and placed_grid.get((day, period - 1)) == subject_id
            and placed_grid.get((day, period - 2)) == subject_id
        ):
            continue  # Would create 3+ consecutive same-subject periods

        for teacher_id in candidates:
            if (teacher_id, day, period) in avail_blocked:
                continue
            if (teacher_id, day) in leave_blocked:
                continue
            if (teacher_id, day, period) in cross_occupied:
                continue
            if (teacher_id, day, period) in this_occupied:
                continue

            max_day_p, max_week_p = workload.get(teacher_id, (6, 30))
            if teacher_day_count.get(teacher_id, {}).get(day, 0) >= max_day_p:
                continue
            if teacher_week_count.get(teacher_id, 0) >= max_week_p:
                continue

            start_t, end_t = _period_times(period, schedule)
            return {
                "subject_id": subject_id,
                "teacher_id": teacher_id,
                "day": day,
                "period": period,
                "start_time": start_t,
                "end_time": end_t,
            }

    return None


def _record_placement(
    placed: Dict,
    placed_slots: List[Dict],
    avail_periods_per_day: Dict[int, List[int]],
    this_occupied: Set[Tuple[str, int, int]],
    teacher_day_count: Dict[str, Dict[int, int]],
    teacher_week_count: Dict[str, int],
    subject_day_count: Dict[int, Dict[str, int]],
    placed_grid: Dict[Tuple[int, int], str],
) -> None:
    """Update all tracking state after a successful placement."""
    day = placed["day"]
    period = placed["period"]
    teacher_id = placed["teacher_id"]
    subject_id = placed["subject_id"]

    placed_slots.append(placed)
    avail_periods_per_day[day].remove(period)
    this_occupied.add((teacher_id, day, period))

    tdc = teacher_day_count.setdefault(teacher_id, {})
    tdc[day] = tdc.get(day, 0) + 1
    teacher_week_count[teacher_id] = teacher_week_count.get(teacher_id, 0) + 1

    subject_day_count[day][subject_id] = subject_day_count[day].get(subject_id, 0) + 1
    placed_grid[(day, period)] = subject_id


# ---------------------------------------------------------------------------
# Scoring — weighted quality evaluation
# ---------------------------------------------------------------------------

def _compute_score(
    placed_slots: List[Dict],
    teacher_day_count: Dict[str, Dict[int, int]],
    workload: Dict[str, Tuple[int, int]],
) -> int:
    """
    Compute a weighted score for a generation attempt.

    Higher is better.  slots_filled dominates so the engine still
    prioritises filling every slot; penalties differentiate among
    otherwise equally-full results.

    score = slots_filled * SCORE_SLOT_WEIGHT
            - teacher_consecutive_penalty
            - subject_cluster_penalty
            - teacher_overload_penalty
    """
    base = len(placed_slots) * SCORE_SLOT_WEIGHT

    # ── Teacher consecutive penalty ──────────────────────────────────────
    # Penalise long unbroken teaching streaks for a single teacher on one day.
    teacher_consec_penalty = 0
    teacher_day_periods: Dict[Tuple[str, int], List[int]] = defaultdict(list)
    for s in placed_slots:
        teacher_day_periods[(s["teacher_id"], s["day"])].append(s["period"])

    for _key, periods in teacher_day_periods.items():
        periods_sorted = sorted(periods)
        streak = 1
        for i in range(1, len(periods_sorted)):
            if periods_sorted[i] == periods_sorted[i - 1] + 1:
                streak += 1
            else:
                if streak >= 3:
                    teacher_consec_penalty += (streak - 2) * PENALTY_TEACHER_CONSECUTIVE
                streak = 1
        if streak >= 3:
            teacher_consec_penalty += (streak - 2) * PENALTY_TEACHER_CONSECUTIVE

    # ── Subject cluster penalty ──────────────────────────────────────────
    # Penalise the same subject appearing more than once on the same day
    # (unavoidable when weekly_load > days, but should be minimised).
    subject_cluster_penalty = 0
    subject_day_occurrences: Dict[Tuple[str, int], int] = defaultdict(int)
    for s in placed_slots:
        subject_day_occurrences[(s["subject_id"], s["day"])] += 1

    for _key, count in subject_day_occurrences.items():
        if count > 1:
            subject_cluster_penalty += (count - 1) * PENALTY_SUBJECT_CLUSTER

    # ── Teacher overload penalty ─────────────────────────────────────────
    # Mild penalty when a teacher's daily count reaches or nears their max.
    teacher_overload_penalty = 0
    for tid, day_counts in teacher_day_count.items():
        max_daily = workload.get(tid, (6, 30))[0]
        for _day, count in day_counts.items():
            if count >= max_daily:
                teacher_overload_penalty += PENALTY_TEACHER_OVERLOAD * 2
            elif count == max_daily - 1:
                teacher_overload_penalty += PENALTY_TEACHER_OVERLOAD

    return base - teacher_consec_penalty - subject_cluster_penalty - teacher_overload_penalty


# ---------------------------------------------------------------------------
# Single generation attempt
# ---------------------------------------------------------------------------

def _greedy_attempt(
    subject_pool: List[str],
    occupied_grid: Set[Tuple[int, int]],
    teachers_by_subject: Dict[str, List[str]],
    avail_blocked: Set[Tuple[str, int, int]],
    leave_blocked: Set[Tuple[str, int]],
    workload: Dict[str, Tuple[int, int]],
    cross_occupied: Set[Tuple[str, int, int]],
    periods_per_day: int = 8,
    period_schedule: Optional[List[Tuple[time, time]]] = None,
    class_teacher_subject_ids: Optional[Set[str]] = None,
    initial_placements: Optional[List[Dict]] = None,
) -> Dict:
    """
    One Spread-First placement pass.

    Returns: {"slots_placed": int, "slots": [...], "conflicts": [...]}
    """
    schedule = period_schedule or _DEFAULT_PERIOD_SCHEDULE
    ct_subjects = class_teacher_subject_ids or set()

    # Available periods per day (excludes pre-occupied from non-overwrite mode)
    avail_periods_per_day: Dict[int, List[int]] = {
        day: sorted([
            p for p in range(1, periods_per_day + 1)
            if (day, p) not in occupied_grid
        ])
        for day in range(DAYS_PER_WEEK)
    }

    # Tracking structures
    this_occupied: Set[Tuple[str, int, int]] = set()
    teacher_day_count: Dict[str, Dict[int, int]] = {}
    teacher_week_count: Dict[str, int] = {}
    subject_day_count: Dict[int, Dict[str, int]] = {d: {} for d in range(DAYS_PER_WEEK)}

    # placed_grid maps (day, period) → subject_id for consecutive-subject checking
    # Pre-populate with already-existing slots (non-overwrite mode)
    placed_grid: Dict[Tuple[int, int], str] = {}
    for p in (initial_placements or []):
        placed_grid[(p["day"], p["period"])] = p["subject_id"]

    placed_slots: List[Dict] = []
    unplaced: List[str] = []

    # ── Phase 1: Compute balanced day plan ──────────────────────────────────
    day_plan = _build_balanced_day_plan(subject_pool, ct_subjects)

    # ── Phase 2: Place each (day, subject) assignment ───────────────────────
    for (target_day, subject_id) in day_plan:
        prefer_p1 = subject_id in ct_subjects

        # --- Try target day first ---
        placed = None
        if avail_periods_per_day[target_day]:
            placed = _try_place_on_day(
                day=target_day,
                subject_id=subject_id,
                avail_periods=avail_periods_per_day[target_day],
                subject_day_count=subject_day_count,
                placed_grid=placed_grid,
                teachers_by_subject=teachers_by_subject,
                avail_blocked=avail_blocked,
                leave_blocked=leave_blocked,
                workload=workload,
                cross_occupied=cross_occupied,
                this_occupied=this_occupied,
                teacher_day_count=teacher_day_count,
                teacher_week_count=teacher_week_count,
                schedule=schedule,
                prefer_period_1=prefer_p1,
            )

        if placed:
            _record_placement(
                placed, placed_slots, avail_periods_per_day,
                this_occupied, teacher_day_count, teacher_week_count,
                subject_day_count, placed_grid,
            )
            continue

        # --- Fallback: try other days ────────────────────────────────────────
        # Prefer days that:
        #   1. Have few or no occurrences of this subject (maintain spread)
        #   2. Have available periods
        #   3. Have low total load (not overcrowded)
        fallback_days = [
            d for d in range(DAYS_PER_WEEK)
            if d != target_day
            and avail_periods_per_day[d]
            and subject_day_count[d].get(subject_id, 0) < MAX_SAME_SUBJECT_PER_DAY
        ]
        fallback_days.sort(key=lambda d: (
            subject_day_count[d].get(subject_id, 0),   # fewer occurrences = preferred
            -len(avail_periods_per_day[d]),              # more free periods = preferred
            random.random(),
        ))

        placed_on_fallback = False
        for alt_day in fallback_days:
            placed = _try_place_on_day(
                day=alt_day,
                subject_id=subject_id,
                avail_periods=avail_periods_per_day[alt_day],
                subject_day_count=subject_day_count,
                placed_grid=placed_grid,
                teachers_by_subject=teachers_by_subject,
                avail_blocked=avail_blocked,
                leave_blocked=leave_blocked,
                workload=workload,
                cross_occupied=cross_occupied,
                this_occupied=this_occupied,
                teacher_day_count=teacher_day_count,
                teacher_week_count=teacher_week_count,
                schedule=schedule,
                prefer_period_1=(subject_id in ct_subjects),
            )
            if placed:
                _record_placement(
                    placed, placed_slots, avail_periods_per_day,
                    this_occupied, teacher_day_count, teacher_week_count,
                    subject_day_count, placed_grid,
                )
                placed_on_fallback = True
                break

        if not placed_on_fallback:
            unplaced.append(subject_id)

    # Build conflict list from unplaced occurrences
    unplaced_counts = Counter(unplaced)
    conflicts: List[Dict] = []
    for subject_id, count in unplaced_counts.items():
        has_teacher = bool(teachers_by_subject.get(subject_id))
        if has_teacher:
            conflicts.append({
                "subject_id": subject_id,
                "reason": (
                    f"{count} occurrence(s) could not be placed. Possible causes: "
                    "teacher availability/leave blocks all options, workload limit reached, "
                    "or cross-class conflicts. Try reducing weekly periods or checking teacher "
                    "constraints."
                ),
            })
        else:
            conflicts.append({
                "subject_id": subject_id,
                "reason": (
                    "No teacher assigned with expertise for this subject. "
                    "Go to Teacher → Subjects and assign expertise first."
                ),
            })

    score = _compute_score(placed_slots, teacher_day_count, workload)

    return {
        "slots_placed": len(placed_slots),
        "slots": placed_slots,
        "conflicts": conflicts,
        "score": score,
    }
