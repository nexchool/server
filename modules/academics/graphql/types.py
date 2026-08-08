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
