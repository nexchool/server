"""GraphQL fields for documents, reached through the profile that shows them.

Documents belong to a person (ADR-015), but authority does not: the question a
guard answers is "may you see this student" or "may you manage this teacher",
which the student and teacher domains already have keys for. So the fields are
named for the profile, guarded by that domain's permissions, and resolve to the
person themselves.

That is also why there is no `document.read` key. Inventing one would mean a
school that can already manage its students has to be granted a second thing
before it can see their papers, and nothing about the school changed.
"""

from __future__ import annotations

from typing import List, Optional

import strawberry

from graphql_api.errors import NotFoundError
from graphql_api.permissions import (
    IsAuthenticated,
    RequiresTenant,
    SetupComplete,
    requires,
    requires_any,
)

from .graphql.types import (
    DocumentSet,
    completeness_to_graphql,
    document_to_graphql,
    type_option_to_graphql,
)

# Reading a student's papers is reading the student. A class teacher who may
# see their own classes may see those students' documents and no others; the
# resolver does that narrowing, not the guard.
STUDENT_READ = ("student.read.all", "student.read.class")
STUDENT_MANAGE = "student.manage"
TEACHER_READ = "teacher.read"
TEACHER_MANAGE = "teacher.manage"


def _student_person_id(student_id: str) -> str:
    from modules.students import services as student_services

    person_id = student_services.person_id_for_student(student_id)
    if not person_id:
        raise NotFoundError("No such student in this school.")
    return person_id


def _teacher_person_id(teacher_id: str) -> str:
    from modules.teachers import services as teacher_services

    person_id = teacher_services.person_id_for_teacher(teacher_id)
    if not person_id:
        raise NotFoundError("No such teacher in this school.")
    return person_id


def _document_set(
    person_id: str, contexts: tuple[str, ...], view_url_base: str
) -> DocumentSet:
    from modules.people.document_catalog import OWNER_KIND
    from . import service

    return DocumentSet(
        documents=[
            document_to_graphql(d, view_url_base)
            for d in service.list_for(OWNER_KIND, person_id)
        ],
        completeness=completeness_to_graphql(
            service.completeness(OWNER_KIND, person_id)
        ),
        available_types=[
            type_option_to_graphql(t)
            for t in service.types_for(OWNER_KIND, contexts)
        ],
    )


def _delete_owned_by(person_id: str, document_id: str) -> bool:
    """Delete only when the document really hangs off this person.

    Checked here rather than trusting the id: a document id is guessable, and
    the guard above only established that the caller may manage *this* profile.
    """
    from modules.people.document_catalog import OWNER_KIND
    from . import service
    from .errors import DocumentNotFound

    try:
        document = service.get(document_id)
    except DocumentNotFound:
        raise NotFoundError("No such document.")
    if document.owner_kind != OWNER_KIND or document.owner_id != person_id:
        raise NotFoundError("No such document on this profile.")
    service.delete(document_id)
    return True


@strawberry.type
class DocumentQuery:
    @strawberry.field(
        permission_classes=[
            IsAuthenticated,
            RequiresTenant,
            requires_any(*STUDENT_READ),
        ],
        description=(
            "A student's documents, what they still may file, and whether the "
            "school has enough of them."
        ),
    )
    def student_documents(self, info: strawberry.Info, student_id: str) -> DocumentSet:
        from modules.people.document_catalog import CONTEXTS_FOR_STUDENT

        return _document_set(
            _student_person_id(student_id),
            CONTEXTS_FOR_STUDENT,
            f"/api/students/{student_id}/documents",
        )

    @strawberry.field(
        permission_classes=[IsAuthenticated, RequiresTenant, requires(TEACHER_READ)],
        description=(
            "A teacher's documents, what they still may file, and whether the "
            "school has enough of them."
        ),
    )
    def teacher_documents(self, info: strawberry.Info, teacher_id: str) -> DocumentSet:
        from modules.people.document_catalog import CONTEXTS_FOR_STAFF

        return _document_set(
            _teacher_person_id(teacher_id),
            CONTEXTS_FOR_STAFF,
            f"/api/teachers/{teacher_id}/documents",
        )


@strawberry.type
class DocumentMutation:
    @strawberry.mutation(
        permission_classes=[
            IsAuthenticated,
            RequiresTenant,
            SetupComplete,
            requires(STUDENT_MANAGE),
        ],
        description="Remove one of a student's documents, and its file.",
    )
    def delete_student_document(
        self, info: strawberry.Info, student_id: str, document_id: str
    ) -> bool:
        return _delete_owned_by(_student_person_id(student_id), document_id)

    @strawberry.mutation(
        permission_classes=[
            IsAuthenticated,
            RequiresTenant,
            SetupComplete,
            requires(TEACHER_MANAGE),
        ],
        description="Remove one of a teacher's documents, and its file.",
    )
    def delete_teacher_document(
        self, info: strawberry.Info, teacher_id: str, document_id: str
    ) -> bool:
        return _delete_owned_by(_teacher_person_id(teacher_id), document_id)
