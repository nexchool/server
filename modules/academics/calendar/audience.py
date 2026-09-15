"""Who is asking, and therefore how much of the calendar they get.

One value answers it for every calendar read. The alternative — each read
deciding for itself — is how a teacher came to be able to read the Std 12
board-exam schedule from a Std 8 account.

Narrowing keys on *identity*, not on which permission string the caller holds:
`academic_calendar.read` means "may open the calendar", and being a teacher or
a student is what decides how much of it comes back. A caller who is neither —
the office desk, a view-only sub-admin — keeps the whole view they have on
admin-web today.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Iterable, Optional

from flask import g, has_app_context

# Every audience a school event or holiday can be addressed to. Mirrors
# `models.APPLIES_TO_VALUES`; kept as a frozenset because it is intersected.
ALL_AUDIENCES: FrozenSet[str] = frozenset(
    {"entire_school", "students", "teachers", "staff"}
)

# What a student is entitled to. A staff meeting is not their information.
STUDENT_AUDIENCES: FrozenSet[str] = frozenset({"entire_school", "students"})

# What a row means when it does not say who it is for.
DEFAULT_AUDIENCE = "entire_school"


@dataclass(frozen=True)
class CalendarAudience:
    """How much of the calendar one caller may see."""

    unrestricted: bool
    class_ids: Optional[FrozenSet[str]]
    applies_to: FrozenSet[str]

    def may_see_exam(self, applicable_class_ids: Optional[Iterable[str]]) -> bool:
        """Whether an exam window touches a class of theirs.

        An empty scope means the whole school — that is what the field already
        means when a window is created without naming classes, not a new rule.
        """
        if self.unrestricted:
            return True
        if not applicable_class_ids:
            return True
        return bool(set(applicable_class_ids) & (self.class_ids or frozenset()))

    def may_see_audience(self, applies_to: Optional[str]) -> bool:
        """Whether a holiday or event addressed to `applies_to` is theirs."""
        if self.unrestricted:
            return True
        return (applies_to or DEFAULT_AUDIENCE) in self.applies_to


UNRESTRICTED = CalendarAudience(
    unrestricted=True, class_ids=None, applies_to=ALL_AUDIENCES
)

# Nobody signed in. The permission classes on the resolvers and the auth
# decorators on the routes reject this long before here; answering
# "everything" would make them the only thing standing in the way.
NOBODY = CalendarAudience(
    unrestricted=False, class_ids=frozenset(), applies_to=frozenset()
)


def _caller():
    if not has_app_context():
        return None
    return getattr(g, "current_user", None)


def resolve_calendar_audience(user=None) -> CalendarAudience:
    """The audience of whoever is signed in.

    Tests pass `user` explicitly; request code leaves it out and the caller on
    `g` is used.
    """
    from modules.academics.teaching_assignment import class_ids_taught_by
    from modules.auth.parents import children_of_account
    from modules.rbac.services import has_permission
    from modules.students.services import student_for_user
    from modules.teachers.services import teacher_for_user

    if user is None:
        user = _caller()
    if user is None:
        return NOBODY

    if has_permission(user.id, "academic_calendar.manage") or has_permission(
        user.id, "system.manage"
    ):
        return UNRESTRICTED

    teacher = teacher_for_user(user.id)
    if teacher is not None:
        return CalendarAudience(
            unrestricted=False,
            class_ids=frozenset(class_ids_taught_by(teacher.id)),
            applies_to=ALL_AUDIENCES,
        )

    student = student_for_user(user.id)
    if student is not None:
        return CalendarAudience(
            unrestricted=False,
            class_ids=frozenset({student.class_id} if student.class_id else ()),
            applies_to=STUDENT_AUDIENCES,
        )

    # Separate parent logins (ADR-011). Under shared access the parent signs in
    # as the student and was already answered above.
    children = children_of_account(user)
    if children:
        return CalendarAudience(
            unrestricted=False,
            class_ids=frozenset(
                child.class_id for child in children if child.class_id
            ),
            applies_to=STUDENT_AUDIENCES,
        )

    # Office staff, view-only sub-admins: neither teaching nor studying, so
    # there is no "their students" to narrow to.
    return UNRESTRICTED
