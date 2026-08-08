# Where this architecture takes the business, and what it will cost

**Date:** 2026-08-07
**Question:** the compliance report asked whether the implementation matches the
architecture. This asks a different one — whether the architecture matches the
business, and what breaks first as the business grows.
**Evidence:** the schema, the code and the running system. Every number below
was measured, not estimated.

---

# 1. What the documentation does and does not say

## The canon does not know that modules can be switched off

`server/docs/` — the v2 canon — contains **no mention of feature flags,
switchable modules or optional features.** Not one file.

This is not a small omission. Whether a school has Transport is a first-class
architectural property: it decides what every other service must tolerate being
absent. Half a day's work this week went into proving that turning a module off
does not break the ones still on, and the rule that makes that possible —
*side-effect callers check, gated routes refuse, nothing 500s* — exists only in
the code and in `docs-new/`, which is the v1 reference set.

An engineer reading the canon to learn how this system is put together would not
find out that a tenant can be missing half of it.

## There is no commercial domain

Billing appears once in the canon, in passing, inside `domain-interactions.md`.
There is no document describing how the company earns money, what a subscription
is, what happens when a school stops paying, or who owns that.

Every other domain has one — People, Identity, Authorization, Academic. The one
that pays for all of them does not. Section 2 shows what that has cost already.

## The frontend has no architectural home

Design tokens, the typography scale, the content-width rule, what happens when a
parent turns on Larger Text — none of it is in the canon. Some is in
`docs-new/22-mobile-client.md`; the work done this week (`FontScaleCap`,
`ContentMaxWidth`, `Breakpoint`, the spacing guard, the web resolver) is
documented only in commit messages and the code.

Three clients share one design system. That is an architecture, and it is not
written down anywhere that governs.

## What is written well

The ADRs are genuinely good — fourteen of them, each stating a decision and its
reason, and the implementation follows them. `business/product-vision.md` is a
real decision framework rather than a mission statement. The module docs under
`server/docs/modules/` describe behaviour rather than tables.

The problem is not quality. It is that the canon covers the domain model
thoroughly and the *system* — clients, deployment, commercials, module
switchability — barely at all.

---

# 2. What will hurt, in the order it will hurt

## R1 — The company cannot bill anybody

**Severity: highest. This is a business risk, not a technical one.**

`tenants` carries `price_per_student_per_year`, `discount_percentage`,
`discount_start_date`, `discount_end_date`, `billing_cycle` and `trial_ends_at`.

That is a price list. Subscription *scaffolding* exists — a `plans` catalogue,
`tenant_usage`, per-tenant billing fields (migrations 043, 047) — but there is
no tenant invoice table, no record of a payment made *to Nexchool*, no receipt,
no dunning. (The `payments` table records school-side fee collection from
parents, not tenant billing.) Nothing anywhere records that a school has ever
paid for the product.

The panel will tell you a school owes 270 students × ₹0.00. It cannot tell you
whether they paid.

Worse: **`trial_ends_at` is never enforced.** Every one of its ten references is
in `modules/platform/services.py`, reading or writing the field for display. No
code checks it. A trial does not end unless a person notices and changes
`status` by hand.

So today the product can onboard a school, serve it indefinitely, and never
notice it is not a customer. Revenue lives in a spreadsheet somewhere outside
the system, and reconciling it is manual for as long as that stays true.

## R2 — The system has no idea what time it is at the school

> **Closed 2026-08-07, one commit after this review:** migration
> `093_the_school_has_a_clock` adds `tenants.timezone` and converts the naive
> timestamp columns, and `core/school_time.py` (`school_today()`,
> `school_now()`) replaces the bare `date.today()` calls. The analysis below
> is kept as written, for the record.

**Severity: high. A correctness bug now, a hard blocker for expansion.**

There is no configured school timezone anywhere in the codebase.

The API container runs UTC. Twelve places across attendance, schedule and the
dashboard call `date.today()` to decide which school day it is — including the
guard that refuses attendance for a future date.

Demonstrated, not argued:

```
   08:00 IST on 08 Aug  ->  server says 08 Aug   ok
   20:00 IST on 08 Aug  ->  server says 08 Aug   ok
   23:59 IST on 08 Aug  ->  server says 08 Aug   ok
   00:30 IST on 08 Aug  ->  server says 07 Aug   <-- WRONG DAY
   05:00 IST on 08 Aug  ->  server says 07 Aug   <-- WRONG DAY
```

Every day between midnight and 05:29 IST, the server is on yesterday. Hostel
gate passes and the morning bus run both happen inside that window.

The same root cause shows in the schema: **141 of 232 timestamp columns are
`timestamp without time zone`**, against 91 that are not — and
the repo's engineering rules (`.claude/rules/database-conventions.md`, outside
this canon) say *"Timestamps: always `TIMESTAMP WITH TIME ZONE`. No local
times."* The code is split too: 75 calls to the deprecated
`datetime.utcnow()`, which returns a naive value, against 60 timezone-aware
ones.

For a product sold in one country this is a narrow, low-traffic bug. It becomes
unfixable-in-a-hurry the moment a school outside India signs, because by then
every historical timestamp is ambiguous.

## R3 — Examination does not exist, and it is why schools buy this

`business/product-vision.md` lists eighteen modules. Eight exist:

| Built | Missing |
|---|---|
| Academics, Students, People, Attendance, Timetable, Notifications, Fees/Finance, Transport, Hostel | **Examination**, **Admissions**, Homework, Payroll, Library, Inventory, Analytics |

Examination is not one of eighteen equal items. Report cards are the thing a
school principal asks about first, and the thing that makes switching systems
mid-year impossible. Selling to a school that needs marks entry before it exists
means either losing the deal or promising a date.

Admissions is the other notable absence, because ADR-007 exists specifically to
separate admission from academic enrollment — the architecture models a
distinction whose module has not been written.

The good news is real: after this week's work, the two things Examination
attaches to — a class and a teaching assignment — each have exactly one owner,
and *"who taught this subject in November"* can be answered correctly. Before
this milestone it could not. Examination is now a build, not a redesign.

## R4 — Authorization is half migrated

Authority is held by the employment rather than the login, `user_roles` is
dropped, delegation works. That is the irreversible half and it is done.

The vocabulary is not. The live check is still
`has_permission(user, "attendance.manage")` across sixteen files; Business
Actions, Capabilities and Authority Profiles remain documents. Every module
written before that lands accrues call sites in the old language, and
Examination is a large module.

## R5 — Academic has no owner module

The domain is spread across `classes`, `academics`, `grades`, `mediums`,
`academic_programmes` and `subjects` — 39 source files under `modules/academics`
alone. Ownership is documented and invisible in the layout. This milestone found
two duplications hiding in exactly that gap.

## R6 — Two tenant-scoped tables have no `tenant_id`

`notification_recipients` and `hostel_gatepass_audit` are the only tables
holding tenant data without a tenant column. Both are reachable only through a
scoped parent, and every current query filters by `user_id` or the parent id, so
nothing leaks today.

But `with_loader_criteria` — the mechanism the entire product's isolation rests
on — cannot protect a table with no `tenant_id`. These two are safe by
convention, and the convention is not checked anywhere. One query written by
`notification_id` alone is a cross-tenant read.

## R7 — Attendance is the table that will need partitioning

Sessions are one per class per day, which is the cheap grain. Even so:

| Scale | Attendance rows / year |
|---|---|
| One school, 800 students | 160,000 |
| One 15,000-student trust | 3,000,000 |
| 100 schools averaging 1,500 | **30,000,000** |

Postgres is comfortable with that given the right indexes, and the table has
three. There is no partitioning or archival plan, and no need for one yet — but
it is the first table that will demand one, somewhere around the third year of
selling.

## R8 — Two known performance defects, unchanged

From the compliance report, still open: duplicate detection takes **65 seconds**
on migrated data where thousands of parents share one placeholder phone number,
and listing buses costs **84 queries** because an operational warning runs once
per bus. Neither is on a path a school uses per lesson; the first is on the path
every school uses exactly once, on day one, during import.

---

# 3. Where this can go

## What the architecture has already earned

The hard part is done, and it is worth being clear about which part that is.

Multi-tenant, multi-campus, multi-board, multi-medium — with one class's identity
being `(tenant, campus, programme, grade, section, year)` — is the thing that is
expensive to retrofit and cheap to have designed in. It is designed in, and the
15,000-student fixture proves the query shapes hold: students page in 3 queries
and 45ms, teachers in 5 and 35ms, classes in 2 and 68ms.

Every business concept has exactly one owner. Four domain boundaries are
enforced by tests that read imports rather than exercise behaviour. That means
the next module is an extension rather than a negotiation, which is precisely
what `product-vision.md` asks for: *"New modules should extend the platform, not
redesign it."*

That claim is now true. It was not true a week ago.

## What decides the next eighteen months

Three different things are being called "the roadmap" and they have different
shapes:

**Breadth — ten missing modules.** Each is a build on a foundation that holds.
Examination and Admissions are worth more than the other eight combined, because
they are the two a school asks about before signing.

**Depth — the commercial layer.** Onboarding, billing, trial expiry, dunning,
offboarding. None of it exists. This does not block a first customer; it blocks
the fiftieth, because at fifty the manual reconciliation is somebody's full-time
job.

**Reach — geography.** Blocked outright by R2 until timestamps and the school
timezone are dealt with, and the cost of that fix rises with every month of data
written naive.

## The order I would put them in

1. **Timezone and timestamps (R2)** — before more modules write more naive
   timestamps. Every month of delay adds rows that a later migration has to
   guess about.
2. **Authorization vocabulary (R4)** — before Examination, not because it blocks
   it but because Examination is large and would otherwise be written twice.
3. **Examination** — the module that converts pipeline into customers.
4. **The commercial layer (R1)** — before the customer count outgrows a
   spreadsheet. Trial enforcement is a day's work and should not wait for the
   rest.
5. **Academic owner module (R5)** — before Examination adds to a domain nobody
   can find.

R6 is an afternoon: add the column, backfill from the parent, let the existing
mechanism cover it. Worth doing while it is still two tables.

## The risk that is not on any list

The vision says schools should never feel they are adapting to the software, and
the feature-flag work this week moved toward that — seven questions a school
knows the answer to, instead of fourteen internal module names.

The pressure will be in the other direction. Every school will want one thing
its neighbour does not, and the cheap answer is a flag. Fourteen keys became
seven this week by deleting the ones that were never real choices; that number
will creep back if each new customer's exception becomes a switch.

The discipline that keeps it honest is the one already written down: a flag is
something a school genuinely does or does not do. Not a way to say yes.
