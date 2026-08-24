"""Stream catalogue — read and resolve.

Writes are deliberately not here yet: the four common tracks are seeded per
tenant by migration 107 and at tenant creation, and nothing in this phase asks
a school to define a fifth. The catalogue is a table so that it *can* be
extended without a deploy; the screen that extends it arrives with the work
that needs it.
"""

from __future__ import annotations

from typing import List, Optional

from flask import g

from core.database import db
from .models import Stream

# Seeded for every tenant so a school opening Grade 11 finds the common tracks
# already there. Kept in step with migration 107 by
# `tests/test_stream_is_a_domain_entity.py`.
DEFAULT_STREAMS = [
    ("Science", "SCI", 10),
    ("Commerce", "COM", 20),
    ("Arts", "ART", 30),
    ("Vocational", "VOC", 40),
]


def list_streams(tenant_id: Optional[str] = None) -> List[Stream]:
    """Active streams for a tenant, in the order a school reads them."""
    return (
        Stream.query.filter(
            Stream.tenant_id == (tenant_id or g.tenant_id),
            Stream.deleted_at.is_(None),
        )
        .order_by(Stream.sequence, Stream.name)
        .all()
    )


def stream_by_name(name: str, tenant_id: Optional[str] = None) -> Optional[Stream]:
    """Resolve a stream by the name a person typed. Case-insensitive."""
    if not name or not str(name).strip():
        return None
    return (
        Stream.query.filter(
            Stream.tenant_id == (tenant_id or g.tenant_id),
            db.func.lower(Stream.name) == str(name).strip().lower(),
            Stream.deleted_at.is_(None),
        ).first()
    )


def resolve_stream_id(
    value: Optional[str], tenant_id: Optional[str] = None
) -> Optional[str]:
    """Turn whatever a caller supplied into a stream id, or refuse.

    Accepts an id or a name, because the REST payload has always carried the
    name and the shipped clients still send it. An unrecognised name is
    **refused rather than created**: silently minting a catalogue row from a
    typo is how "Sci" and "Science" both come to exist, and a school then has
    two tracks it cannot tell apart.
    """
    if value is None or not str(value).strip():
        return None
    raw = str(value).strip()
    tid = tenant_id or g.tenant_id

    existing = Stream.query.filter(
        Stream.tenant_id == tid, Stream.id == raw, Stream.deleted_at.is_(None)
    ).first()
    if existing:
        return existing.id

    by_name = stream_by_name(raw, tid)
    if by_name:
        return by_name.id

    raise ValueError(
        f"Unknown stream '{raw}'. Add it to the school's streams first."
    )


def seed_default_streams(tenant_id: str) -> int:
    """Give a new tenant the common tracks. Idempotent."""
    created = 0
    for name, code, sequence in DEFAULT_STREAMS:
        if stream_by_name(name, tenant_id):
            continue
        db.session.add(
            Stream(tenant_id=tenant_id, name=name, code=code, sequence=sequence)
        )
        created += 1
    return created
