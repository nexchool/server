"""People's documents — the person owner kind, and the types a school collects.

Registers `person` with the document store (`modules/documents`). Everything
about storage, upload, deletion and completeness comes from there; this file
declares only what is specific to people: which papers, for whom, and how many
make a person's file complete (ADR-015).

A document belongs to the human, so the student profile and the teacher profile
read the same set. Someone who is both a parent and a teacher hands over their
Aadhar once.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from modules.documents import OwnerKind, register

OWNER_KIND = "person"

# Contexts within the person kind.
CONTEXT_IDENTITY = "identity"
CONTEXT_STUDENT = "student"
CONTEXT_STAFF = "staff"

# What a profile of each kind is asked for. Identity papers belong to the human
# and are collected whoever they are, so every profile offers them.
CONTEXTS_FOR_STUDENT = (CONTEXT_IDENTITY, CONTEXT_STUDENT)
CONTEXTS_FOR_STAFF = (CONTEXT_IDENTITY, CONTEXT_STAFF)

# A person is document-complete at this many DISTINCT types. Two photographs of
# one Aadhar are one type and do not satisfy it.
MINIMUM_DOCUMENT_TYPES = 2


@dataclass(frozen=True)
class DocumentTypeDefinition:
    code: str
    label: str
    contexts: tuple[str, ...]
    sequence: int = 100
    description: str = field(default="")


CATALOG: tuple[DocumentTypeDefinition, ...] = (
    # --- Identity: facts about the human, collected from everyone -----------
    DocumentTypeDefinition("aadhar_card", "Aadhar Card", (CONTEXT_IDENTITY,), 10),
    DocumentTypeDefinition("pan_card", "PAN Card", (CONTEXT_IDENTITY,), 20),
    DocumentTypeDefinition(
        "birth_certificate", "Birth Certificate", (CONTEXT_IDENTITY,), 30
    ),
    DocumentTypeDefinition("passport", "Passport", (CONTEXT_IDENTITY,), 40),
    # --- Student: papers about a studentship --------------------------------
    DocumentTypeDefinition(
        "transfer_certificate", "Transfer Certificate", (CONTEXT_STUDENT,), 10,
        "Issued by the previous school on leaving.",
    ),
    DocumentTypeDefinition(
        "leaving_certificate", "Leaving Certificate", (CONTEXT_STUDENT,), 20
    ),
    # --- Staff: papers about employment -------------------------------------
    DocumentTypeDefinition(
        "degree_certificate", "Degree Certificate", (CONTEXT_STAFF,), 10,
        "Highest qualification held.",
    ),
    DocumentTypeDefinition(
        "experience_letter", "Experience Letter", (CONTEXT_STAFF,), 20,
        "Issued by a previous employer.",
    ),
    DocumentTypeDefinition(
        "appointment_letter", "Appointment Letter", (CONTEXT_STAFF,), 30,
        "Issued by this school on joining.",
    ),
    DocumentTypeDefinition(
        "employment_contract", "Employment Contract", (CONTEXT_STAFF,), 40
    ),
    DocumentTypeDefinition(
        "police_verification", "Police Verification", (CONTEXT_STAFF,), 50,
        "Background check, required by several boards for staff working with children.",
    ),
    DocumentTypeDefinition(
        "medical_fitness_certificate", "Medical Fitness Certificate",
        (CONTEXT_STAFF,), 60,
    ),
    # --- Anything the vocabulary does not name yet --------------------------
    DocumentTypeDefinition(
        "other", "Other", (CONTEXT_IDENTITY, CONTEXT_STUDENT, CONTEXT_STAFF), 999
    ),
)


def _resolve_tenant(person_id: str) -> str | None:
    """Whose person this is, or None when there is no such person here.

    The store cannot police a polymorphic owner reference, so this is what
    stands between a bad id and a document filed against nothing. The ORM's
    tenant scope means a person in another school reads as absent, which is
    the answer we want.
    """
    from modules.people.models import Person

    person = Person.query.filter(
        Person.id == person_id, Person.deleted_at.is_(None)
    ).first()
    return person.tenant_id if person else None


PERSON_DOCUMENTS = register(
    OwnerKind(
        name=OWNER_KIND,
        label="Person",
        contexts=(CONTEXT_IDENTITY, CONTEXT_STUDENT, CONTEXT_STAFF),
        resolve_tenant=_resolve_tenant,
        minimum_distinct_types=MINIMUM_DOCUMENT_TYPES,
        description="Papers a school holds about a human it knows.",
    )
)
