"""The document types a school collects, and who each one is collected from.

The single source for the vocabulary, in the manner of `modules/rbac/catalog.py`:
declared here, seeded into `document_types`, read from the database everywhere
else. Adding a type a school asks for is a line here plus a reseed — not a
migration, and not a code change anywhere that consumes it (ADR-015).

A type declares the contexts it belongs to. A profile offers IDENTITY plus its
own context, so a teacher is not asked for a transfer certificate and a student
is not asked for an appointment letter.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Contexts a document type can belong to.
CONTEXT_IDENTITY = "identity"
CONTEXT_STUDENT = "student"
CONTEXT_STAFF = "staff"

VALID_CONTEXTS = {CONTEXT_IDENTITY, CONTEXT_STUDENT, CONTEXT_STAFF}

# What a profile of each kind may be asked for. Identity papers belong to the
# human and are collected whoever they are, so every profile offers them.
CONTEXTS_FOR_STUDENT = (CONTEXT_IDENTITY, CONTEXT_STUDENT)
CONTEXTS_FOR_STAFF = (CONTEXT_IDENTITY, CONTEXT_STAFF)

# A person is document-complete at this many DISTINCT types. Two photographs of
# one Aadhar are one type and do not satisfy it. A constant rather than tenant
# configuration until a school asks for something else (ADR-015).
MINIMUM_DOCUMENT_TYPES = 2


@dataclass(frozen=True)
class DocumentTypeDefinition:
    code: str
    label: str
    contexts: tuple[str, ...]
    # Display order within a context; lower sorts first.
    sequence: int = 100
    description: str = field(default="")


CATALOG: tuple[DocumentTypeDefinition, ...] = (
    # --- Identity: facts about the human, collected from everyone -----------
    DocumentTypeDefinition(
        "aadhar_card", "Aadhar Card", (CONTEXT_IDENTITY,), 10
    ),
    DocumentTypeDefinition(
        "pan_card", "PAN Card", (CONTEXT_IDENTITY,), 20
    ),
    DocumentTypeDefinition(
        "birth_certificate", "Birth Certificate", (CONTEXT_IDENTITY,), 30
    ),
    DocumentTypeDefinition(
        "passport", "Passport", (CONTEXT_IDENTITY,), 40
    ),
    # --- Student: papers about a studentship --------------------------------
    DocumentTypeDefinition(
        "transfer_certificate", "Transfer Certificate", (CONTEXT_STUDENT,), 10,
        "Issued by the previous school on leaving.",
    ),
    DocumentTypeDefinition(
        "leaving_certificate", "Leaving Certificate", (CONTEXT_STUDENT,), 20,
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
        "employment_contract", "Employment Contract", (CONTEXT_STAFF,), 40,
    ),
    DocumentTypeDefinition(
        "police_verification", "Police Verification", (CONTEXT_STAFF,), 50,
        "Background check, required by several boards for staff working with children.",
    ),
    DocumentTypeDefinition(
        "medical_fitness_certificate", "Medical Fitness Certificate", (CONTEXT_STAFF,), 60,
    ),
    # --- Anything the vocabulary does not name yet --------------------------
    DocumentTypeDefinition(
        "other", "Other", (CONTEXT_IDENTITY, CONTEXT_STUDENT, CONTEXT_STAFF), 999,
    ),
)

CATALOG_BY_CODE: dict[str, DocumentTypeDefinition] = {d.code: d for d in CATALOG}


def codes_for_contexts(contexts: tuple[str, ...]) -> list[str]:
    """Type codes offered to a profile living in these contexts, in display order.

    Grouped by context in the order given, then by sequence — so a picker reads
    "identity papers, then the ones this role is asked for", rather than
    interleaving the two because their sequences happen to collide.
    """
    ranked: list[tuple[int, int, int, str, str]] = []
    for definition in CATALOG:
        position = next(
            (i for i, c in enumerate(contexts) if c in definition.contexts), None
        )
        if position is None:
            continue
        # A type belonging to every context is a catch-all rather than a thing
        # a profile is asked for, so it sorts after every group instead of
        # landing inside whichever one it matched first.
        is_catch_all = int(len(definition.contexts) == len(VALID_CONTEXTS))
        ranked.append(
            (
                is_catch_all,
                position,
                definition.sequence,
                definition.label,
                definition.code,
            )
        )
    return [code for *_, code in sorted(ranked)]


# v1 stored the type on the row as an enum value. Every one of those values is
# still a code here, so the migration maps them straight across; the mapping is
# written down rather than assumed because "other" is the only safe fallback and
# a silent fallback would quietly relabel a real document.
LEGACY_STUDENT_DOCUMENT_TYPES: dict[str, str] = {
    "aadhar_card": "aadhar_card",
    "birth_certificate": "birth_certificate",
    "leaving_certificate": "leaving_certificate",
    "transfer_certificate": "transfer_certificate",
    "passport": "passport",
    "other": "other",
}
