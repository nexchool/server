"""A room arrives with its beds, and grows them when its capacity grows.

An allocation needs a bed row; a room used to be created with only a
capacity, and its beds entered afterwards by hand. Hostel A had seven rooms
and 24 places and not one bed to put a student in.
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

import pytest

from modules.hostel.models import HostelBed, HostelRoom
from modules.hostel.services.facility_service import FacilityService


def _beds(db_session, room) -> list[HostelBed]:
    return (
        db_session.query(HostelBed)
        .filter(HostelBed.room_id == room.id, HostelBed.deleted_at.is_(None))
        .order_by(HostelBed.bed_number)
        .all()
    )


def test_a_new_room_gets_one_bed_per_place(db_session, tenant, room):
    # `room` is capacity 4 with no beds (the `beds` fixture is not requested).
    added = FacilityService(db_session).provision_beds(tenant_id=tenant.id, room=room)
    assert added == 4
    beds = _beds(db_session, room)
    assert [b.bed_number for b in beds] == ["1", "2", "3", "4"]
    assert all(b.status == "active" and not b.is_allocated for b in beds)


def test_a_room_already_holding_its_capacity_gets_nothing(db_session, tenant, room, beds):
    assert FacilityService(db_session).provision_beds(tenant_id=tenant.id, room=room) == 0
    assert len(_beds(db_session, room)) == 4


def test_provisioning_twice_adds_nothing_the_second_time(db_session, tenant, room):
    service = FacilityService(db_session)
    service.provision_beds(tenant_id=tenant.id, room=room)
    assert service.provision_beds(tenant_id=tenant.id, room=room) == 0
    assert len(_beds(db_session, room)) == 4


def test_a_bigger_room_grows_its_beds_and_keeps_the_warden_s_names(db_session, tenant, room, beds):
    """`beds` are named A1..A4 by hand. Raising capacity to 6 adds two beds and
    renames nothing."""
    room.capacity = 6
    db_session.flush()
    added = FacilityService(db_session).provision_beds(tenant_id=tenant.id, room=room)
    assert added == 2
    assert [b.bed_number for b in _beds(db_session, room)] == ["1", "2", "A1", "A2", "A3", "A4"]


def test_a_retired_bed_keeps_its_number(db_session, tenant, room):
    """Retiring bed 2 frees a place, not the name — the unique constraint does
    not care about deleted_at, so the replacement is 5, never a second 2."""
    service = FacilityService(db_session)
    service.provision_beds(tenant_id=tenant.id, room=room)
    two = next(b for b in _beds(db_session, room) if b.bed_number == "2")
    service.retire_bed(bed=two)
    db_session.flush()
    assert service.provision_beds(tenant_id=tenant.id, room=room) == 1
    assert [b.bed_number for b in _beds(db_session, room)] == ["1", "3", "4", "5"]


# ---------------------------------------------------------------------------
# The migration that does the same for rooms that already exist
# ---------------------------------------------------------------------------

def _load_migration():
    path = Path(__file__).resolve().parents[1] / "migrations/versions/138_rooms_come_with_their_beds.py"
    spec = importlib.util.spec_from_file_location("migration_138", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_existing_rooms_are_topped_up_by_the_migration(db_session, tenant, hostel, room, beds):
    """One room full (A1..A4), one empty room of 3, one retired room: the
    migration adds exactly the three beds the empty room is missing."""
    empty = HostelRoom(id=f"r-{uuid.uuid4().hex[:12]}", tenant_id=tenant.id, hostel_id=hostel.id,
                       room_number="G002", floor="Ground Floor", capacity=3)
    retired = HostelRoom(id=f"r-{uuid.uuid4().hex[:12]}", tenant_id=tenant.id, hostel_id=hostel.id,
                         room_number="G003", floor="Ground Floor", capacity=2)
    db_session.add_all([empty, retired])
    db_session.flush()
    FacilityService(db_session).retire_room(tenant_id=tenant.id, room=retired)
    db_session.flush()

    added = _load_migration().backfill_beds(db_session.connection())
    db_session.expire_all()

    assert added == 3
    assert [b.bed_number for b in _beds(db_session, empty)] == ["1", "2", "3"]
    assert [b.bed_number for b in _beds(db_session, room)] == ["A1", "A2", "A3", "A4"]
    assert _beds(db_session, retired) == []
    # Running it again changes nothing.
    assert _load_migration().backfill_beds(db_session.connection()) == 0
