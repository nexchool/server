# Phase G — moving the writes to GraphQL

**Status:** scoped, not started. **Date:** 2026-08-09.

Reads have migrated and writes have not: 40 GraphQL queries against 10
mutations, and 257 REST business writes. Every slice so far moved a read
surface and left that module's writes on REST, so "module X is on GraphQL" has
never been more than half true.

This is the scope for closing that. It is deliberately a plan and not a start —
the sequencing question below changes what the first slice should be, and it is
not mine to answer.

---

## 1. What is actually there

Measured from the route table and both clients' call sites, using the matcher in
`scripts/audit_client_routes.py` (which resolves URL variables and template
literals — a prefix match over-counts badly here).

| | |
|---|---|
| REST write operations | 298 |
| of those, infrastructure (auth, uploads, exports, health, platform) | 41 |
| **business writes** | **257** |
| admin-web write call sites | 174 |
| Expo write call sites | 110 |
| called by **both** clients | 82 |
| **admin-web only — movable without a mobile release** | **92** |

The split by module is the part that matters:

| module | admin-web only | Expo touches |
|---|---|---|
| transport | **25** | 5 |
| hostel | **12** | 6 |
| academics | 9 | 8 |
| school-setup | **9** | 0 |
| students | 7 | 5 |
| subject-contexts | **5** | 0 |
| teachers | 5 | 16 |
| classes | 2 | **31** |
| announcements | 0 | 8 |
| student-leaves | 0 | 6 |

## 2. Two things this changes about the obvious plan

**The modules with the most movable writes have no GraphQL at all.** Transport
(25) and hostel (12) lead the migratable surface and have not a single query or
mutation today. Meanwhile classes — where the reads were migrated first — is
almost entirely Expo-gated on the write side: 31 of its 33 writes are called by
the shipped mobile app. Continuing module-by-module in the order reads were done
would start with the *least* movable work.

**A write is not a row change.** All ten existing mutations are named as acts a
school performs — `withdrawStudent`, `graduateStudent`, `transferStudentOut`,
`mergeSections` — and `graphql-conventions.md` §7 says so explicitly: *"Name
mutations as the school names the act… Not `updateStudentStatus`."* But most of
the 257 REST writes are CRUD: `POST /api/mediums/`, `PATCH
/api/transport/routes/<id>`, `DELETE /api/grades/<id>`.

Porting those one-for-one produces 257 CRUD mutations and abandons the
convention that makes the ten existing ones worth having. Phase G is therefore a
**modelling exercise per module**, not a mechanical port: decide which REST
writes are acts (and get a named mutation), which are genuine record editing
(and get one `update…` mutation with a partial input), and which should not
survive the move at all.

That is also why it cannot be estimated as "257 ÷ slice size". The count is the
surface, not the work.

## 3. The sequencing decision — needs an answer before the first slice

82 writes are called by **both** clients. Moving one to GraphQL leaves two
choices, and they are not equivalent:

**(A) Move the operation and keep the REST route for Expo.** The module finishes
in one pass. But it creates a new dual transport for every one of those 82,
which is exactly what debt 31 already tracks and what the locked decision
forbids — *"one transport per operation… do not leave permanent accidental dual
transports."*

**(B) Move only the 92 admin-web-only writes now; leave the 82 shared ones until
the Expo release.** No new dual transports. Modules end up split — transport
would have 25 writes on GraphQL and 5 on REST — but each *operation* has exactly
one transport, which is what the rule actually says.

**(C) Wait for an Expo release and do whole modules.** Cleanest result, blocked
on a mobile release that also gates debts 25, 31, 2b and 4b.

**Recommended: (B).** It is the only option that honours the locked decision
without waiting, and it front-loads transport, hostel, school-setup and
subject-contexts — 51 movable writes across four modules that have no GraphQL
today, so each is a clean first cut rather than a retrofit.

The cost of (B) is honest and worth stating: for a while, a reviewer opening
`modules/transport` finds writes in two places. The register should carry that
as a known, time-boxed state rather than a surprise.

## 3a. Correction — two of the picks below do not qualify

*Added 2026-08-09, before the first slice, after auditing the two modules §4
proposed starting with.*

**subject-contexts is not a migratable slice.** Its five writes and three reads
have no component consumer in any client. The chain stops one step short of a
screen: `subjectContextsService` → `useSubjectContexts` → nothing.
`useBulkUpsertSubjectContexts` and `useApplySubjectContexts` are exported and
called by no component; the one apparent reference to `useSubjectContexts` is
`CreateSectionModal` importing `useMediums`, which lives in that file by
accident of placement. Expo and panel never touch the routes.

The *domain* is live — `school_setup/promote_service.py` calls `apply_for_grade`
and `seed_service.py` creates `SubjectContext` rows — so this is not dead code.
It is a live domain whose HTTP surface and client code were the **removed
admin-web setup wizard's** interface; `subjectContextsService.ts` was last
touched by that wizard's commit, and onboarding has since moved to the panel.

**school-setup looks the same.** Nine write functions in
`schoolSetupService.ts`, and the only screen that imports the service is
`SetupGate`, which reads status. The wizard those writes belonged to is gone.

**So the 92 figure in §1 is an upper bound.** It counted `apiPost(...)` call
sites inside admin-web service modules, not whether a screen can reach them —
the same error as debt 39's "80 uncalled functions", measured one level away
from the question. Every module in §4 needs a reachability check before it is
scheduled, not after.

Module-level import reachability is too coarse to do this in bulk: a service is
"reached" if any one of its exports is, so `subjectContextsService` looks live
because `useMediums` shares its hook file. It has to be done per operation.

## 4. Proposed order under (B)

Each slice is one module's admin-web-only writes: model the acts, build the
mutations, move admin-web, delete the replaced routes, verify live.

1. ~~subject-contexts~~ and ~~school-setup~~ — **disqualified, see §3a.**
   Neither has a screen that reaches its writes.
2. **the structural masters** — grades, programmes, school-units, departments,
   mediums: four writes each, twenty in total, no Expo, and verified live
   (`/grades`, `/programmes`, `/school-units`, `/departments` are real screens
   whose create and delete hooks are used by components). They share one shape,
   so one pass covers all five and proves the write pattern on the smallest
   surface that a user can actually reach. **This is the corrected first slice.**
3. **transport** (25) — the largest movable block. Split across at least three
   slices (fleet, routes and stops, enrollments).
4. **hostel** (12) — allocations, gatepasses, visitors.
5. **students** (7) and **academics** (9) — both already have GraphQL, so these
   are extensions rather than first cuts.
6. **teachers** (5) — small, but 16 of its writes are Expo's, so expect the
   module to stay visibly split longest.

Roughly a dozen slices the size of the section-merge work done this session.
That is the honest estimate: not a sprint, and not something to start without
the decision in §3.

## 5. Exit criteria for a slice

Borrowed from what the read migration learned, and from what it got wrong:

- Every mutation names its Business Action and carries `IsAuthenticated`,
  `RequiresTenant` and the permission(s) it needs. **A write that does two
  things declares both keys** (`mergeSections` needs `class.manage` *and*
  `student.update`).
- Refusals arrive as codes, not prose — `NOT_FOUND`, `CONFLICT`,
  `VALIDATION_ERROR` — matched on a stable fragment so rewording a message for a
  human cannot reclassify it.
- The replaced REST route is **deleted**, not left. If it cannot be deleted
  because a client still calls it, the slice is not done — register it.
- Before deleting anything, run `scripts/audit_client_routes.py`. Three routes
  were deleted in this project on a false "no consumer" claim, twice.
- admin-web moves in the same slice. A mutation nothing calls is debt 18's shape.
- Verified against the running stack, not only the suite.

## 6. Out of scope

- The 82 shared writes, until the Expo release (see §3).
- Infrastructure writes — uploads, downloads, exports, auth and session,
  device tokens. These stay REST permanently, by the canon.
- New modules. Examination, results, report cards and the rest wait, as the
  roadmap says.
- Rewriting the service layer. Mutations call the same services the routes do;
  a slice that changes behaviour is not a transport migration.
