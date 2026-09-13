# Hostel

A school that boards children has to know, at any hour, where each one is
sleeping tonight and who has walked out of the gate.

---

# The shape of the thing

```
Hostel ──── HostelRoom ──── HostelBed ──── HostelAllocation ──── Student
 capacity     capacity        (one per        (one active per bed,
                              place)          one active per student)

Student ──── HostelGatepass ──── HostelGatepassAudit
                (one in flight at a time)

HostelVisitor ──── HostelVisitorLog
 (one per phone)     (one per visit)
```

Three containers and one occupant. A **hostel** holds a number of places; its
**rooms** divide that number between them; each room holds one **bed** per
place; a **student** sleeps in exactly one bed. Everything else in the module
— gate passes, visitors, the warden's dashboard — is about the student who is
in that bed.

Every table is tenant-scoped (`TenantBaseModel`), and the module is behind the
`hostel` feature flag (`@require_feature("hostel")` on every route), so a
school without boarding never sees it.

---

# Capacity is a budget, paid in two instalments

`hostel.capacity` is the number of places the building holds. `room.capacity`
is the number of places one room holds. The two are reconciled by
**`FacilityService`**, and the rules do not bend:

- **The rooms of a hostel may never add up to more than the hostel holds.**
  A room that would push the sum past the hostel's capacity is refused, and
  a hostel may not be shrunk below what its rooms already promise. A room
  being resized is measured against its neighbours, not against its old self.
- **A room may never contain more beds than its own capacity**, and may not be
  shrunk below the beds standing in it.
- **Retired rooms and beds hand their share back.** Hostels and rooms are
  soft-deleted (`deleted_at`); a bed is retired with `status='removed'` *and*
  `deleted_at`, because two readers disagree about which column means "gone",
  and setting both is what makes it disappear from all of them. Retiring a
  container cascades downward, so a deleted room does not leave beds behind
  that still count.

`capacity` is the number the warden thinks in — "Hostel A holds 24" — and it
is also what the school pays for. It is not a cache of the bed count.

---

# A room arrives with its beds

An allocation points at a bed row (`bed_id` is NOT NULL). Until 2026-09-13 a
room was created with only a capacity and its beds were entered afterwards,
by hand, one at a time — so a hostel of seven rooms and 24 places routinely
had nowhere to put a student, while its room cards read "3 free" and its
listing card read "0 vacant".

**`FacilityService.provision_beds` now brings a room up to its capacity** when
it is created and whenever its capacity is raised. It is idempotent; it
numbers beds `1..n`; and it **skips any number the room already uses** — a
retired bed keeps its number (`uq_hostel_beds_tenant_room_bed_number` does not
care about `deleted_at`), and beds a warden named by hand keep their names.
Migration 138 applied the same top-up to every room that already existed.

Beds can still be added, renamed and retired individually
(`POST/PATCH/DELETE /api/hostel/beds`); provisioning is the default, not the
only way.

---

# What the numbers on a card mean

`GET /api/hostel/reports/occupancy` and the dashboard both report, per hostel:

| | |
|---|---|
| `total_beds` | the sum of its live rooms' `capacity` — the places it promises |
| `active_allocations` | students currently in a bed |
| `vacant_beds` | `total_beds − active_allocations`, never below zero |
| `occupancy_pct` | the two as a percentage; `0.0` for a hostel with no rooms |

`total_beds` is capacity, **not** a count of bed rows. The rooms screen, the
"is this hostel full" check and the capacity budget all reason in capacity;
the report used to count rows instead and disagreed with all three (see the
previous section for the day it showed `0/0` over 24 free beds).

---

# Allocation

`AllocationService` owns the student → bed assignment:

- **One active allocation per bed** — also a partial unique index in the
  database, so two requests racing for the last bed cannot both win.
- **One active allocation per student.**
- **A full hostel refuses one more**, measured directly against
  `hostel.capacity` and the count of active residents — a hostel set up
  before the room and bed budgets existed must still not take a student it
  cannot hold.
- **Checkout** sets `status='completed'`, stamps `check_out_at`, and frees the
  bed. A checked-out student no longer blocks the room's or hostel's deletion.
- **A move is one event, recorded as one.** `POST /allocations/<id>/move`
  closes the allocation being left with `status='moved'` and opens the new one
  at the same instant, in one transaction — so the history of a stay reads as
  a stay, not as a departure and a re-admission. The destination is validated
  as a new allocation would be; a move *between* hostels also checks the
  destination is not full, a move within one does not (the student already
  holds a place). `moved` rows are closed rows: they drop out of every
  active-resident count exactly as `completed` ones do.
- A container holding people is not deletable: `DELETE` on a hostel, room or
  bed with an active resident returns `409 RoomOccupied` (or its sibling) and
  tells the warden to check them out first.

`GET /api/hostel/students/<id>/allocation` answers "where does this child
sleep" for the student, parent and warden screens.

---

# Gate passes

A gate pass is permission for a boarder to leave, with a stated return. Two
types, `day_out` and `night_out`; one state machine, in `GatepassService`:

```
pending → approved → active → closed
   │          │         │
   └─→ rejected         └─→ overdue ─→ closed   (a late return is still allowed)
```

- **A student has one in-flight pass at a time** (pending, approved or
  active).
- **Every transition writes a `HostelGatepassAudit` row.** The audit trail is
  the record a school may one day have to produce.
- **Three different people act on it**, and three permissions say which:
  `hostel.gatepass.create` (the student or the warden raises it),
  `hostel.gatepass.approve` (the warden decides), and
  `hostel.gatepass.gatekeeper` (the gate marks the student out and back in).
- **Overdue is decided by a clock, not a person.** `hostel.mark_overdue_gatepasses`
  runs every five minutes (`celery_app.py` beat schedule, `tasks/hostel.py`)
  and moves an `active` pass past its expected return plus a 30-minute grace
  period to `overdue`. `GET /api/hostel/gatepasses/overdue` and the dashboard
  list them for the warden.
- **Times are instants.** `departure_datetime` and `expected_return_datetime`
  are `timestamptz`; a stamp sent with no offset is read as the school's
  wall-clock, never as UTC (`_parse_datetime`, tested).
- Parent consent is **informational in v1**: the guard telephones the parent
  before approving, and the row records that it happened
  (`parent_consent_status`, `parent_consent_notified_at`). The module sends no
  SMS or push of its own.

---

# Visitors

`VisitorService`: a **visitor profile is one per `(tenant, phone)`**, and each
check-in/check-out pair is one `HostelVisitorLog`. "Who is inside right now"
is simply the logs with no `check_out_at`. Logs are soft-deleted so the trail
survives; profiles are never deleted automatically.

---

# Who may see what

Permissions live in `modules/hostel/permissions.py` and are seeded from
`scripts/seed_rbac.py`; routes use the constants, never raw strings:

| Area | read | write |
|---|---|---|
| hostels, rooms, beds | `hostel.read` | `hostel.manage` |
| allocations | `hostel.allocations.read` | `hostel.allocations.manage` |
| visitors | `hostel.visitors.read` | `hostel.visitors.manage` |
| gate passes | `hostel.gatepass.read` | `create` / `approve` / `gatekeeper` (above) |
| reports, dashboard | `hostel.reports.read` (dashboard also accepts `hostel.read`) | — |

**Branch scoping goes through the student.** A hostel is a building, not a
campus, but which bed a child sleeps in and whether they have come back are
facts about that child — so every reader that returns a student is filtered
by `core/branch_scope.filter_by_student_ids`: the allocations list, gate
passes (list, detail, overdue), the dashboard's overdue alerts, visitor logs
and "who is inside", and the residents export. A campus-restricted warden sees
their own campus's children. The foundation review (2026-08-05) records this
choice.

---

# Surfaces

`/api/hostel/*` under `hostel_bp`: hostels, rooms, beds (CRUD), allocations
(list, per-student, create, checkout), gate passes (list, get, overdue, create,
approve, reject, checkout, checkin), visitors (search, check in, check out,
logs), `dashboard` (occupancy + overdue + visitors inside) and two reports
(`reports/occupancy`, `reports/residents.csv`).

admin-web renders the listing (`HostelCard`), the rooms grid, the hostel
dashboard, gate-pass creation and the warden's gate view; the mobile app has
the hostel list and detail, room detail, the hostel dashboard, residents, gate
passes (list and detail) and visitors.
**None of them recompute occupancy** —
every card shows the report's numbers as sent, which is why the report's
definition of a bed had to be right.

---

# Declared but unreachable

- Migration 138's downgrade is a no-op: the beds it added are
  indistinguishable from hand-entered ones and may hold students by the time
  anyone downgrades. Recorded as an accepted irreversibility, not an
  oversight.

---

# What the module does not do

- No fee or billing for boarding — a hostel place is not priced here.
- No mess, laundry or attendance-in-hostel.
- No parent notification of its own for gate passes (see above).
- No room preferences, waiting list or automatic bed assignment; the warden
  chooses the bed.
