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
