"""What kinds of thing can own documents, and the rules each one carries.

A domain that wants documents registers an owner kind and gets the whole store:
upload, listing, deletion, completeness, tenant-scoped keys. It does not write
storage code, and it does not get its own table.

    register(
        OwnerKind(
            name="exam_paper",
            label="Exam paper",
            contexts=("question_paper", "answer_sheet"),
            resolve_tenant=lambda owner_id: ...,
            max_file_size_bytes=50 * 1024 * 1024,
        )
    )

The owner reference is `(owner_kind, owner_id)` rather than a foreign key per
domain, which is what lets one table serve every domain. The price is that the
database cannot enforce the reference, so the kind supplies `resolve_tenant`:
it answers "does this owner exist, and whose is it" in one call, and the store
refuses to write anything it cannot place in a school.

The other half of that price is cleanup. Nothing cascades on its own, so a
domain deleting an owner calls `delete_all_for` (see `service`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from modules.documents.errors import UnknownOwnerKind

# What most documents a school files are: a scan or a photograph of paper.
DEFAULT_MIME_TYPES = frozenset(
    {"application/pdf", "image/jpeg", "image/jpg", "image/png"}
)
DEFAULT_MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class OwnerKind:
    """A kind of thing that owns documents, and the rules its documents follow."""

    name: str
    label: str
    # Sub-groupings inside this kind, used to decide which types a particular
    # profile or screen offers. A person has identity/student/staff; an exam
    # paper might have question_paper/answer_sheet.
    contexts: tuple[str, ...]
    # owner_id -> tenant_id, or None when the owner does not exist. The store
    # never writes a document it cannot place in a school.
    resolve_tenant: Callable[[str], str | None]
    # How many DISTINCT types make this owner complete. 0 means the kind has no
    # completeness rule and never reports one.
    minimum_distinct_types: int = 0
    allowed_mime_types: frozenset[str] = DEFAULT_MIME_TYPES
    max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES
    description: str = field(default="")


_REGISTRY: dict[str, OwnerKind] = {}


def register(kind: OwnerKind) -> OwnerKind:
    """Register an owner kind. Re-registering the same name replaces it.

    Replacement rather than refusal, because a module can be imported twice
    under test and a registry that raises would make that a failure instead of
    a no-op.
    """
    _REGISTRY[kind.name] = kind
    return kind


def get(name: str) -> OwnerKind:
    kind = _REGISTRY.get(name)
    if kind is None:
        raise UnknownOwnerKind(
            f"No owner kind '{name}' is registered. The domain that owns it is "
            "probably not imported — registration happens on import."
        )
    return kind


def is_registered(name: str) -> bool:
    return name in _REGISTRY


def all_kinds() -> list[OwnerKind]:
    return sorted(_REGISTRY.values(), key=lambda k: k.name)
