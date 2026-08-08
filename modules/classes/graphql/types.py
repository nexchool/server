"""What a client sees of a class.

The v2 canon calls this a Section — a grade divided into the groups children
are actually taught in. This schema says `Class` anyway, and deliberately: it
already says class everywhere else, in `Student.currentClass`, in the student
filter's `classId`, in attendance. One concept with two names on one transport
is worse than one concept with the older name, and ADR-012 is the bridge that
lets the docs say Section while the code keeps its word.

The type carries what the screens render — the table, the structured pickers,
the detail page — and not the whole row. `start_date`, `end_date` and
`created_at` are on the table and read by nobody, so they are not here; a
field earns its place when something renders it.
"""

from __future__ import annotations

from typing import List, Optional

import strawberry


@strawberry.type(
    name="Class",
    description=(
        "A group of children taught together for one academic year. Its "
        "identity is the campus, programme, grade, section letter and year "
        "taken together — `name` is only a display label, and may be empty."
    ),
)
class SchoolClass:
    id: strawberry.ID
    name: Optional[str] = None
    section: Optional[str] = None
    stream: Optional[str] = strawberry.field(
        default=None,
        description="Science, Commerce, Arts or Vocational, for grades 11-12.",
    )
    grade_level: Optional[int] = None
    display_name: Optional[str] = strawberry.field(
        default=None,
        description=(
            "What this class is called on screen. `name` is a nullable legacy "
            "label and is empty for every class created through the "
            "structured form — a class is named by its grade — so the rule "
            "for composing it lives here rather than in each client, where "
            "screens had come to be titled \"— A\"."
        ),
    )

    academic_year_id: Optional[strawberry.ID] = None
    academic_year: Optional[str] = strawberry.field(
        default=None, description="The name of the year this class runs in."
    )

    school_unit_id: Optional[strawberry.ID] = None
    school_unit_name: Optional[str] = None
    programme_id: Optional[strawberry.ID] = None
    programme_name: Optional[str] = None
    grade_id: Optional[strawberry.ID] = None
    grade_name: Optional[str] = None
    grade_sequence: Optional[int] = strawberry.field(
        default=None,
        description=(
            "What orders grades, because their names do not: sorted as text, "
            "Std 10 comes before Std 2."
        ),
    )
    medium_id: Optional[strawberry.ID] = None
    medium_name: Optional[str] = None
    department_id: Optional[strawberry.ID] = None
    department_name: Optional[str] = None

    teacher_id: Optional[strawberry.ID] = strawberry.field(
        default=None,
        description="The teacher responsible for this class, if one is named.",
    )
    teacher_name: Optional[str] = None

    student_count: int = 0
    teacher_count: int = strawberry.field(
        default=0,
        description=(
            "Distinct teachers who teach this class. One teacher taking four "
            "of its subjects is one teacher."
        ),
    )
    status: Optional[str] = strawberry.field(
        default=None,
        description=(
            "`active` while the class sits in the school's current academic "
            "year, `archived` once that year has passed. Derived: a class has "
            "no status of its own, only the year it belongs to."
        ),
    )


@strawberry.type(description="A child placed in a class.")
class ClassStudent:
    id: strawberry.ID
    admission_number: str
    full_name: str
    roll_number: Optional[int] = None


@strawberry.type(
    description=(
        "Someone teaching a class. A class teacher is responsible for the "
        "class itself and names no subject; a subject teacher names one."
    )
)
class ClassTeacher:
    teacher_id: strawberry.ID
    teacher_name: Optional[str] = None
    employee_number: Optional[str] = None
    subject_id: Optional[strawberry.ID] = None
    subject_name: Optional[str] = None
    role: Optional[str] = strawberry.field(
        default=None, description="primary or assistant."
    )
    is_class_teacher: bool = False


@strawberry.type(
    name="ClassDetail",
    description=(
        "One class with who is in it. Everything a `Class` has, plus the "
        "children placed in it and everyone teaching it — asked for one class "
        "at a time, because a list of them is a query per row."
    ),
)
class ClassDetail(SchoolClass):
    students: List[ClassStudent] = strawberry.field(default_factory=list)
    teachers: List[ClassTeacher] = strawberry.field(default_factory=list)


@strawberry.type(
    description=(
        "A page of classes. Paged by offset rather than by cursor: a class "
        "list has no order whose key is both unique and unchanging, and a "
        "cursor over such a key does not fail — it skips rows."
    )
)
class ClassPage:
    nodes: List[SchoolClass]
    has_next_page: bool = strawberry.field(
        description="Whether asking again with a larger `offset` returns more."
    )

    # What produced this page, so a count can repeat the same filters.
    filters: strawberry.Private[dict]

    @strawberry.field(
        description=(
            "How many classes match, ignoring paging. Counted only when "
            "asked — a picker that pages to the end should not pay for one."
        )
    )
    def total_count(self, info: strawberry.Info) -> int:
        from modules.classes.services import classes_matching_count

        return classes_matching_count(**self.filters)


@strawberry.type(
    description=(
        "Totals over the classes matching a filter, computed in one pass "
        "rather than by summing a page."
    )
)
class ClassStats:
    total_classes: int
    total_students: int
    total_teachers: int = strawberry.field(
        description="Distinct teachers across the matching classes."
    )
    average_class_size: float


def class_to_graphql(row) -> SchoolClass:
    """One row of the class list query as a client sees it."""
    cls, student_count, teacher_count, year_is_active = row
    return _class_fields(
        SchoolClass,
        cls,
        student_count=student_count or 0,
        teacher_count=teacher_count or 0,
        status="active" if year_is_active else "archived",
    )


def classes_to_graphql(rows) -> List[SchoolClass]:
    return [class_to_graphql(row) for row in rows]


def class_detail_to_graphql(detail: dict) -> ClassDetail:
    """The class, the children in it and everyone teaching it."""
    students = detail["students"]
    teachers = detail["teachers"]
    node = _class_fields(
        ClassDetail,
        detail["class"],
        student_count=len(students),
        teacher_count=len({held["teacher_id"] for held in teachers}),
        status=detail["status"],
    )
    node.students = [
        ClassStudent(
            id=strawberry.ID(student.id),
            admission_number=student.admission_number,
            full_name=student.person.full_name if student.person else "",
            roll_number=student.roll_number,
        )
        for student in students
    ]
    node.teachers = [
        ClassTeacher(
            teacher_id=strawberry.ID(held["teacher_id"]),
            teacher_name=held["teacher_name"],
            employee_number=held["employee_number"],
            subject_id=(
                strawberry.ID(held["subject_id"]) if held["subject_id"] else None
            ),
            subject_name=held["subject_name"],
            role=held["role"],
            is_class_teacher=held["is_class_teacher"],
        )
        for held in teachers
    ]
    return node


def _class_fields(node_type, cls, *, student_count, teacher_count, status):
    """The fields a class and its detail share, read from the class row.

    One reader for both, so the table and the detail page cannot come to
    disagree about what a class is called.
    """
    teacher = cls.teacher
    employment = teacher.staff if teacher else None
    return node_type(
        id=strawberry.ID(cls.id),
        name=cls.name,
        section=cls.section,
        stream=cls.stream,
        grade_level=cls.grade_level,
        display_name=_display_name(cls),
        academic_year_id=_id(cls.academic_year_id),
        academic_year=(
            cls.academic_year_ref.name if cls.academic_year_ref else None
        ),
        school_unit_id=_id(cls.school_unit_id),
        school_unit_name=cls.school_unit.name if cls.school_unit else None,
        programme_id=_id(cls.programme_id),
        programme_name=cls.programme.name if cls.programme else None,
        grade_id=_id(cls.grade_id),
        grade_name=cls.grade.name if cls.grade else None,
        grade_sequence=cls.grade.sequence if cls.grade else None,
        medium_id=_id(cls.medium_id),
        medium_name=cls.medium.name if cls.medium else None,
        department_id=_id(cls.department_id),
        department_name=cls.department_ref.name if cls.department_ref else None,
        teacher_id=_id(cls.teacher_id),
        teacher_name=(
            employment.person.full_name
            if employment and employment.person
            else None
        ),
        student_count=student_count,
        teacher_count=teacher_count,
        status=status,
    )


def _display_name(cls) -> Optional[str]:
    """What a school calls this class.

    The grade first, because that is what names it; the free-text label only
    where there is no grade, and the legacy standard number only where there
    is neither. The section follows when there is one.
    """
    label = (
        (cls.grade.name if cls.grade else None)
        or cls.name
        or (f"Grade {cls.grade_level}" if cls.grade_level is not None else None)
    )
    parts = [part for part in (label, cls.section) if part]
    return " ".join(parts) or None


def _id(value) -> Optional[strawberry.ID]:
    return strawberry.ID(value) if value else None
