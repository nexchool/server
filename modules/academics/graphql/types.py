"""The structure a school is arranged into.

Campuses and academic years are what every other read hangs off: a class
belongs to a campus and a year, a student is enrolled for a year, a register
is taken on a day inside one. They are small, they change rarely, and almost
every screen needs one or the other.

`Campus` is the word the v2 canon uses for what the tables still call a
school unit — the rename belongs to the model, not to a migration of columns,
so the new surface says it and the storage keeps its name.
"""

from __future__ import annotations

import datetime
from typing import List, Optional

import strawberry


@strawberry.type(
    description=(
        "One site a school teaches at. A trust may run twenty; most schools "
        "have one and never think about it."
    )
)
class Campus:
    id: strawberry.ID
    name: str
    code: str
    status: str = strawberry.field(
        description="Whether the school is still using this campus."
    )
    phone: Optional[str] = None
    address: Optional[str] = None
    dise_no: Optional[str] = None
    index_no: Optional[str] = None
    recognition_no: Optional[str] = None
    gr_number_scheme: Optional[str] = None
    logo_url: Optional[str] = None
    principal_signature_url: Optional[str] = None


@strawberry.type(description="A year the school teaches through.")
class AcademicYear:
    id: strawberry.ID
    name: str
    start_date: Optional[datetime.date] = None
    end_date: Optional[datetime.date] = None
    is_active: bool = strawberry.field(
        default=False,
        description="The year the school is currently working in.",
    )


def _date(value) -> Optional[datetime.date]:
    if not value:
        return None
    if isinstance(value, datetime.date):
        return value
    return datetime.date.fromisoformat(str(value)[:10])


def campus_to_graphql(row: dict) -> Campus:
    return Campus(
        id=strawberry.ID(row["id"]),
        name=row["name"],
        code=row["code"],
        status=row.get("status") or "active",
        phone=row.get("phone"),
        address=row.get("address"),
        dise_no=row.get("dise_no"),
        index_no=row.get("index_no"),
        recognition_no=row.get("recognition_no"),
        gr_number_scheme=row.get("gr_number_scheme"),
        logo_url=row.get("logo_url"),
        principal_signature_url=row.get("principal_signature_url"),
    )


def academic_year_to_graphql(row: dict) -> AcademicYear:
    return AcademicYear(
        id=strawberry.ID(row["id"]),
        name=row["name"],
        start_date=_date(row.get("start_date")),
        end_date=_date(row.get("end_date")),
        is_active=bool(row.get("is_active")),
    )


def campuses_to_graphql(rows) -> List[Campus]:
    return [campus_to_graphql(row) for row in rows]


def academic_years_to_graphql(rows) -> List[AcademicYear]:
    return [academic_year_to_graphql(row) for row in rows]


@strawberry.type(
    description=(
        "A course of education a school offers — a board and a medium taken "
        "together. A trust may run several on one campus, which is why a "
        "class names one rather than the school having a single answer."
    )
)
class Programme:
    id: strawberry.ID
    name: str
    board: str
    code: str
    status: str
    medium: Optional[str] = None
    medium_id: Optional[strawberry.ID] = None


@strawberry.type(
    description=(
        "A year-group a school teaches — Nursery, Std 5, Grade 12. `sequence` "
        "is what orders them, because their names do not: sorted as text, "
        "Std 10 comes before Std 2."
    )
)
class Grade:
    id: strawberry.ID
    name: str
    sequence: int


@strawberry.type(
    description=(
        "A language a school teaches in. Parallel mediums in one grade are "
        "ordinary here, so this is a dimension rather than a setting."
    )
)
class Medium:
    id: strawberry.ID
    name: str
    code: Optional[str] = None
    is_active: bool = True


def programme_to_graphql(row: dict) -> Programme:
    return Programme(
        id=strawberry.ID(row["id"]),
        name=row["name"],
        board=row.get("board") or "",
        code=row.get("code") or "",
        status=row.get("status") or "active",
        medium=row.get("medium"),
        medium_id=(
            strawberry.ID(row["medium_id"]) if row.get("medium_id") else None
        ),
    )


def grade_to_graphql(row: dict) -> Grade:
    return Grade(
        id=strawberry.ID(row["id"]),
        name=row["name"],
        sequence=int(row.get("sequence") or 0),
    )


def medium_to_graphql(row: dict) -> Medium:
    return Medium(
        id=strawberry.ID(row["id"]),
        name=row["name"],
        code=row.get("code"),
        is_active=bool(row.get("is_active", True)),
    )


def programmes_to_graphql(rows) -> List[Programme]:
    return [programme_to_graphql(row) for row in rows]


def grades_to_graphql(rows) -> List[Grade]:
    return [grade_to_graphql(row) for row in rows]


def mediums_to_graphql(rows) -> List[Medium]:
    return [medium_to_graphql(row) for row in rows]


@strawberry.type(
    description=(
        "Something a school teaches. The catalogue, not a class's timetable — "
        "which subjects a particular class takes is a class-subject."
    )
)
class Subject:
    id: strawberry.ID
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    subject_type: Optional[str] = None
    is_active: bool = True


@strawberry.type(
    description=(
        "One class that takes a subject. `weeklyPeriods` is how much of the "
        "week it is given there, which can differ between two classes of the "
        "same grade."
    )
)
class SubjectClassAssignment:
    class_subject_id: strawberry.ID
    class_id: strawberry.ID
    class_name: Optional[str] = None
    grade_name: Optional[str] = None
    programme_id: Optional[strawberry.ID] = None
    programme_name: Optional[str] = None
    weekly_periods: int = 0
    is_mandatory: bool = True


@strawberry.type(description="A programme a subject is taught under.")
class SubjectProgramme:
    id: strawberry.ID
    name: Optional[str] = None


@strawberry.type(
    name="SubjectCatalogueEntry",
    description=(
        "A subject and where it is actually taught. Everything a `Subject` "
        "has, plus its live class assignments and the programmes those imply "
        "— the catalogue screen's question is not what a school teaches but "
        "who it teaches it to."
    ),
)
class SubjectCatalogueEntry(Subject):
    classes: List[SubjectClassAssignment] = strawberry.field(default_factory=list)
    programmes: List[SubjectProgramme] = strawberry.field(default_factory=list)


@strawberry.type(
    description=(
        "A page of the subject catalogue. Paged by offset, not by cursor: no "
        "order it offers has a key that is both unique and unchanging."
    )
)
class SubjectPage:
    nodes: List[SubjectCatalogueEntry]
    has_next_page: bool = strawberry.field(
        description="Whether asking again with a larger `offset` returns more."
    )

    # What produced this page, so a count can repeat the same filters.
    filters: strawberry.Private[dict]

    @strawberry.field(
        description=(
            "How many subjects match, ignoring paging. Counted only when "
            "asked."
        )
    )
    def total_count(self, info: strawberry.Info) -> int:
        from modules.subjects.services import subjects_matching_count

        return subjects_matching_count(info.context.tenant_id, **self.filters)


def subject_to_graphql(row: dict) -> Subject:
    return Subject(
        id=strawberry.ID(row["id"]),
        name=row["name"],
        code=row.get("code"),
        description=row.get("description"),
        subject_type=row.get("subject_type"),
        is_active=bool(row.get("is_active", True)),
    )


def subjects_to_graphql(rows) -> List[Subject]:
    return [subject_to_graphql(row) for row in rows]


def catalogue_entry_to_graphql(row: dict) -> SubjectCatalogueEntry:
    return SubjectCatalogueEntry(
        id=strawberry.ID(row["id"]),
        name=row["name"],
        code=row.get("code"),
        description=row.get("description"),
        subject_type=row.get("subject_type"),
        is_active=bool(row.get("is_active", True)),
        classes=[
            SubjectClassAssignment(
                class_subject_id=strawberry.ID(held["class_subject_id"]),
                class_id=strawberry.ID(held["class_id"]),
                class_name=held.get("class_name"),
                grade_name=held.get("grade_name"),
                programme_id=(
                    strawberry.ID(held["programme_id"])
                    if held.get("programme_id")
                    else None
                ),
                programme_name=held.get("programme_name"),
                weekly_periods=held.get("weekly_periods") or 0,
                is_mandatory=bool(held.get("is_mandatory", True)),
            )
            for held in row.get("classes", [])
        ],
        programmes=[
            SubjectProgramme(
                id=strawberry.ID(programme["id"]), name=programme.get("name")
            )
            for programme in row.get("programmes", [])
        ],
    )


def catalogue_to_graphql(rows) -> List[SubjectCatalogueEntry]:
    return [catalogue_entry_to_graphql(row) for row in rows]
