"""A room cannot hold more beds than its capacity says.

Room capacity is the number of beds the room is built for. Adding a bed past
that number, or shrinking a room's capacity below the beds already standing in
it, both break the promise; the service refuses either. Retired beds (soft
deleted) no longer take a slot.
"""

from __future__ import annotations

import pytest

from core.school_time import utc_now
from modules.hostel.services import FacilityService


def test_a_bed_is_accepted_while_the_room_has_a_free_slot(
    db_session, tenant, room, bed
):
    # room holds 4, one bed stands → three slots free
    FacilityService(db_session).assert_bed_fits_room(tenant_id=tenant.id, room=room)


def test_a_bed_past_the_room_capacity_is_refused(db_session, tenant, room, beds):
    # room holds 4, four beds stand
    with pytest.raises(ValueError, match="4 beds"):
        FacilityService(db_session).assert_bed_fits_room(
            tenant_id=tenant.id, room=room
        )


def test_a_retired_bed_frees_its_slot(db_session, tenant, room, beds):
    FacilityService(db_session).retire_bed(bed=beds[0])
    db_session.flush()

    FacilityService(db_session).assert_bed_fits_room(tenant_id=tenant.id, room=room)


def test_a_room_cannot_shrink_below_the_beds_standing_in_it(
    db_session, tenant, room, beds
):
    service = FacilityService(db_session)
    service.assert_room_capacity_holds_beds(
        tenant_id=tenant.id, room=room, new_capacity=4
    )
    with pytest.raises(ValueError, match="4 beds"):
        service.assert_room_capacity_holds_beds(
            tenant_id=tenant.id, room=room, new_capacity=3
        )
